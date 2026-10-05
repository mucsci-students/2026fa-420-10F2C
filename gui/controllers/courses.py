"""Controller for the Course Configuration Editor pages.

Courses are identified by list index because a course ID may have multiple
sections. This module is the MVC boundary between CourseForm and CourseConfig:
it converts form values into scheduler models, protects references, and makes
all changes through apply_config_edit() so a failed validation never mutates
the active configuration.
"""

from __future__ import annotations

from collections.abc import Mapping

from scheduler.config import CourseConfig, ValidationError

from app.crud import ReferenceError_, check_no_references
from gui.controllers.common import apply_config_edit, require_config
from gui.controllers.errors import ControllerError, FieldError, translate_validation_error
from gui.session_store import get_session

COURSE_FIELDS = (
    "course_id",
    "section_id",
    "credits",
    "capacity",
    "room",
    "lab",
    "conflicts",
    "faculty",
    "modality",
    "required_room_features",
    "required_lab_features",
    "reserve_room_during_lab",
)
COURSE_MODALITIES = {"in_person", "online", "hybrid"}


# ---------------------------------------------------------------------- #
#  Helpers
# ---------------------------------------------------------------------- #
def _find_course(config, course_index):
    """Return the indexed course or report a stale or malformed browser URL."""
    courses = config.config.courses
    if isinstance(course_index, bool) or not isinstance(course_index, int) or not 0 <= course_index < len(courses):
        raise ControllerError("This course no longer exists. Refresh the page and try again.")
    return courses[course_index]


def _known_names(config) -> dict[str, set[str]]:
    """Return the names valid for cross-record CourseConfig fields."""
    return {
        "course": {course.course_id for course in config.config.courses},
        "room": {room.name for room in config.config.rooms},
        "lab": {lab.name for lab in config.config.labs},
        "faculty": {person.name for person in config.config.faculty},
    }


def _references(config, course_id, *, ignore_index=None) -> list[str]:
    """List records that would point to a missing final course ID.

    Conflicts and faculty preferences target a base course ID, not a particular
    section. A rename or deletion therefore only needs this check when it
    removes the last section with that ID.
    """
    found: list[str] = []
    for index, course in enumerate(config.config.courses):
        if index != ignore_index and course_id in (course.conflicts or []):
            label = f"course '{course.course_id}' (conflict)"
            if label not in found:
                found.append(label)
    for person in config.config.faculty:
        if course_id in (person.course_preferences or {}):
            found.append(f"faculty '{person.name}' (course preference)")
    return found


def _is_last_section(config, course_id, *, ignore_index) -> bool:
    """Return whether excluding one row leaves no section for this course ID."""
    return not any(
        course.course_id == course_id
        for index, course in enumerate(config.config.courses)
        if index != ignore_index
    )


def _parse_names(raw, field, label, allowed_names, errors, *, none_when_empty=False):
    """Validate a form list against current resource names.

    Forms submit lists, but the controller also guards direct callers so
    malformed input cannot silently become a character-by-character string.
    """
    if raw is None:
        return None if none_when_empty else []
    if not isinstance(raw, (list, tuple, set)):
        errors.append(FieldError(field, f"{label} must be a list of names."))
        return None if none_when_empty else []

    names = []
    for name in raw:
        if not isinstance(name, str) or not name.strip():
            errors.append(FieldError(field, f"Each {label.lower()} must be a non-blank name."))
            continue
        normalized = name.strip()
        if normalized not in allowed_names:
            errors.append(FieldError(field, f"'{normalized}' is not a current {label.lower()}."))
            continue
        if normalized in names:
            errors.append(FieldError(field, f"'{normalized}' is listed more than once."))
            continue
        names.append(normalized)
    return (names or None) if none_when_empty else names


def _parse_features(raw, field, errors) -> list[str]:
    """Normalize comma-separated feature tags without accepting malformed values."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        values = raw.split(",")
    elif isinstance(raw, (list, tuple, set)):
        values = raw
    else:
        errors.append(FieldError(field, "Features must be a comma-separated list."))
        return []
    if any(not isinstance(value, str) for value in values):
        errors.append(FieldError(field, "Each feature must be text."))
        return []
    return sorted({value.strip() for value in values if value.strip()})


def _course_fields(form_data, config) -> dict:
    """Shape-check form data and return keyword arguments for CourseConfig.

    Local errors are shown against their form fields. Scheduler-specific and
    whole-configuration rules remain in CourseConfig and edit_mode(), which
    preserve atomicity for a failed add or update.
    """
    errors: list[FieldError] = []
    course_id = (form_data.get("course_id") or "").strip()
    if not course_id:
        errors.append(FieldError("course_id", "Course ID cannot be blank."))

    raw_section_id = form_data.get("section_id")
    if raw_section_id is not None and not isinstance(raw_section_id, str):
        errors.append(FieldError("section_id", "Section ID must be text."))
        section_id = None
    else:
        section_id = raw_section_id.strip() if raw_section_id else None

    numeric_values = {"credits": form_data.get("credits"), "capacity": form_data.get("capacity")}
    for field, value in numeric_values.items():
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            errors.append(FieldError(field, "Enter a positive whole number."))

    modality = form_data.get("modality")
    if modality not in COURSE_MODALITIES:
        errors.append(FieldError("modality", "Choose in person, online, or hybrid."))

    available = _known_names(config)
    rooms = _parse_names(form_data.get("room"), "room", "room", available["room"], errors)
    labs = _parse_names(form_data.get("lab"), "lab", "lab", available["lab"], errors)
    conflicts = _parse_names(
        form_data.get("conflicts"), "conflicts", "conflicting course", available["course"], errors
    )
    faculty = _parse_names(
        form_data.get("faculty"), "faculty", "faculty member", available["faculty"], errors, none_when_empty=True
    )
    room_features = _parse_features(form_data.get("required_room_features"), "required_room_features", errors)
    lab_features = _parse_features(form_data.get("required_lab_features"), "required_lab_features", errors)

    # A null faculty list asks CombinedConfig to derive candidates from faculty
    # preferences. Report the missing source at the form field instead of
    # waiting for complete-config validation to return a generic error.
    if faculty is None and course_id and not any(
        course_id in (person.course_preferences or {}) for person in config.config.faculty
    ):
        errors.append(
            FieldError(
                "faculty",
                "Choose at least one faculty member or add a faculty course preference for this course ID.",
            )
        )

    reserve_room_during_lab = form_data.get("reserve_room_during_lab")
    if not isinstance(reserve_room_during_lab, bool):
        errors.append(FieldError("reserve_room_during_lab", "Choose whether to reserve the lecture room during labs."))

    if course_id and course_id in conflicts:
        errors.append(FieldError("conflicts", "A course cannot conflict with itself."))
    if modality == "online":
        if rooms:
            errors.append(FieldError("room", "Online courses cannot have candidate rooms."))
        if labs:
            errors.append(FieldError("lab", "Online courses cannot have candidate labs."))
        if room_features:
            errors.append(FieldError("required_room_features", "Online courses cannot require room features."))
        if lab_features:
            errors.append(FieldError("required_lab_features", "Online courses cannot require lab features."))

    if errors:
        raise ControllerError(errors)

    return {
        "course_id": course_id,
        "section_id": section_id,
        "credits": numeric_values["credits"],
        "capacity": numeric_values["capacity"],
        "room": rooms,
        "lab": labs,
        "conflicts": conflicts,
        "faculty": faculty,
        "modality": modality,
        "required_room_features": room_features,
        "required_lab_features": lab_features,
        "reserve_room_during_lab": reserve_room_during_lab,
    }


def _build_course(fields) -> CourseConfig:
    """Build CourseConfig and translate scheduler validation for the form."""
    try:
        return CourseConfig(**fields)
    except ValidationError as error:
        raise ControllerError(translate_validation_error(error, form_fields=COURSE_FIELDS)) from error


def _course_label(config, course_index) -> str:
    """Create a stable human label for an indexed section on GUI pages."""
    course = config.config.courses[course_index]
    if course.section_id:
        return f"{course.course_id}.{course.section_id}"
    number = sum(1 for item in config.config.courses[: course_index + 1] if item.course_id == course.course_id)
    return f"{course.course_id}.{number:02d}"


def _associated_faculty(config, course) -> list[str]:
    """Return the faculty members available to teach one course section.

    A CourseConfig may explicitly name faculty or leave its faculty field null.
    In the latter case, the scheduler associates members through their course
    preferences, so the list page shows those names instead of exposing that
    implementation detail to users.
    """
    if course.faculty is not None:
        return list(course.faculty)
    return [
        person.name
        for person in config.config.faculty
        if course.course_id in (person.course_preferences or {})
    ]


def _course_data(config, course_index) -> dict:
    """Convert one scheduler model into template-safe Course page data."""
    course = _find_course(config, course_index)
    is_last_section = _is_last_section(config, course.course_id, ignore_index=course_index)
    references = _references(config, course.course_id, ignore_index=course_index) if is_last_section else []
    return {
        "index": course_index,
        "label": _course_label(config, course_index),
        "course_id": course.course_id,
        "section_id": course.section_id or "",
        "credits": course.credits,
        "capacity": course.capacity,
        "room": list(course.room or []),
        "lab": list(course.lab or []),
        "conflicts": list(course.conflicts or []),
        "faculty": _associated_faculty(config, course),
        "modality": course.modality,
        "required_room_features": sorted(course.required_room_features or []),
        "required_lab_features": sorted(course.required_lab_features or []),
        "reserve_room_during_lab": course.reserve_room_during_lab,
        "referenced_by": references,
        "can_delete": not references,
    }


def form_choices(request, course_index=None) -> dict[str, list[str]]:
    """Return CourseForm choices without exposing scheduler models to views."""
    config = get_session(request).config
    if config is None:
        return {"course_names": [], "room_names": [], "lab_names": [], "faculty_names": []}
    names = _known_names(config)
    if course_index is not None:
        current = _find_course(config, course_index)
        names["course"].discard(current.course_id)
    return {
        "course_names": sorted(names["course"]),
        "room_names": sorted(names["room"]),
        "lab_names": sorted(names["lab"]),
        "faculty_names": sorted(names["faculty"]),
    }


# ---------------------------------------------------------------------- #
#  Reads
# ---------------------------------------------------------------------- #
def describe_courses(request) -> dict:
    """Return the Course list page data or the no-configuration state."""
    config = get_session(request).config
    if config is None:
        return {"has_config": False}
    return {"has_config": True, "courses": [_course_data(config, index) for index in range(len(config.config.courses))]}


def get_course(request, course_index) -> dict:
    """Return one indexed course for its edit or delete page."""
    config = require_config(get_session(request), "editing courses")
    return _course_data(config, course_index)


# ---------------------------------------------------------------------- #
#  Writes
# ---------------------------------------------------------------------- #
def add_course(request, form_data) -> None:
    """Append one CourseConfig through complete-configuration validation."""
    session = get_session(request)
    config = require_config(session, "adding courses")
    new_course = _build_course(_course_fields(form_data, config))

    def mutate(draft):
        draft.config.courses.append(new_course)

    apply_config_edit(session, config, "course", mutate, form_fields=COURSE_FIELDS)


def update_course(request, course_index, form_data) -> None:
    """Replace one section and protect references if its final ID changes."""
    session = get_session(request)
    config = require_config(session, "editing courses")
    original = _find_course(config, course_index)
    fields = _course_fields(form_data, config)

    if original.course_id != fields["course_id"] and _is_last_section(
        config, original.course_id, ignore_index=course_index
    ):
        try:
            check_no_references(original.course_id, _references(config, original.course_id, ignore_index=course_index))
        except ReferenceError_ as error:
            raise ControllerError(
                f"{error}. Remove those references before changing the final '{original.course_id}' section."
            ) from error
    updated = _build_course(fields)

    def mutate(draft):
        draft.config.courses[course_index] = updated

    apply_config_edit(session, config, "course", mutate, form_fields=COURSE_FIELDS)


def delete_course(request, course_index) -> None:
    """Delete one section after protecting references to its final course ID."""
    session = get_session(request)
    config = require_config(session, "deleting courses")
    course = _find_course(config, course_index)
    if _is_last_section(config, course.course_id, ignore_index=course_index):
        try:
            check_no_references(course.course_id, _references(config, course.course_id, ignore_index=course_index))
        except ReferenceError_ as error:
            raise ControllerError(f"{error}. Remove those references first.") from error

    def mutate(draft):
        del draft.config.courses[course_index]

    apply_config_edit(session, config, "course", mutate, form_fields=COURSE_FIELDS)
