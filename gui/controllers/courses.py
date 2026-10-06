"""
Controller for Courses (Section 7, Courses row).

Courses are identified by list index, not name: repeated course_id values are
legal and create sections ("CMSC 140.01", "CMSC 140.02"), same as
app/commands/courses.py. An index can go stale when the list changes under an
open page, so update/delete take an optional `expected_course_id`; the views
pass the course_id the page showed (a hidden form field) and a mismatch is
refused instead of editing the wrong section.

Every write builds a CourseConfig, then commits through
gui.controllers.common.apply_config_edit(), so the whole configuration is
revalidated and a failed edit keeps the previous valid configuration
(Sections 10, 11). Problems come back as ControllerError with FieldErrors on
the form fields; nothing here touches HTTP or templates (Section 20).

form_data keys (CourseForm.cleaned_data; plain text is accepted too):

    course_id                str, required
    section_id               str, blank -> auto-numbered by position
    credits                  int >= 1, must match an enabled class pattern
    capacity                 int >= 1
    modality                 "in_person" | "online" | "hybrid" (default in_person)
    room, lab                lists of existing room / lab names
    conflicts                list of other course_ids
    faculty                  list of faculty names; empty -> null, which means
                             "take faculty from faculty course preferences"
    required_room_features   list or "a, b"
    required_lab_features    list or "a, b"
    reserve_room_during_lab  bool (default True)

What this controller adds on top of the library:
  * unknown-name, self-conflict and credit/pattern checks on the right field,
  * online courses drop rooms, labs and features (the library forbids them)
    and say so in a notice, matching the CLI,
  * renaming the last section of a course_id carries the new id into other
    courses' conflicts and faculty course preferences in the same atomic edit
    (otherwise the library rejects every such rename),
  * delete is blocked while the last section of a course_id is still
    referenced (Section 12). Deleting one of several sections is always safe,
    because references point at the course_id, not a section.
"""

from __future__ import annotations

import re

from scheduler.config import CourseConfig, CourseModality, ValidationError

from app.commands.courses import course_display_name, enabled_pattern_credits
from app.crud import ReferenceError_, check_no_references
from gui.controllers.common import apply_config_edit, require_config
from gui.controllers.errors import ControllerError, FieldError, translate_validation_error
from gui.session_store import get_session

COURSE_FIELDS = (
    "course_id",
    "section_id",
    "credits",
    "capacity",
    "modality",
    "room",
    "lab",
    "conflicts",
    "faculty",
    "required_room_features",
    "required_lab_features",
    "reserve_room_during_lab",
)
MODALITIES = tuple(mode.value for mode in CourseModality)
_SPLIT = re.compile(r"[,;\n]")


# ---------------------------------------------------------------------- #
#  Reads
# ---------------------------------------------------------------------- #
def describe_courses(request) -> dict:
    """Everything the Courses list page needs, as plain data.

    {"has_config": False} when nothing is loaded (Section 19 empty state).
    """
    config = get_session(request).config
    if config is None:
        return {"has_config": False}
    seen: dict[str, int] = {}
    rows = []
    for index, course in enumerate(config.config.courses):
        references = _references(config, index)
        rows.append(
            {
                "index": index,
                "display": course_display_name(course, seen),
                "course_id": course.course_id,
                "section_id": course.section_id,
                "credits": course.credits,
                "capacity": course.capacity,
                "modality": _modality(course),
                "rooms": list(course.room),
                "labs": list(course.lab),
                "conflicts": list(course.conflicts),
                "faculty": list(course.faculty) if course.faculty is not None else None,
                # When faculty is null the library picks from these people:
                "derived_faculty": _preferring(config, course.course_id) if course.faculty is None else [],
                "required_room_features": sorted(course.required_room_features),
                "required_lab_features": sorted(course.required_lab_features),
                "reserve_room_during_lab": course.reserve_room_during_lab,
                "referenced_by": references,
                "can_delete": not references,
            }
        )
    return {"has_config": True, "courses": rows}


def get_course(request, course_index: int) -> dict:
    """One course in form_data shape (use as CourseForm `initial`), plus
    `index`, `display`, `referenced_by` and `can_delete`. Passing it back to
    update_course() changes nothing."""
    config = require_config(get_session(request), "editing courses")
    course = _course_at(config, course_index)
    seen: dict[str, int] = {}
    display = ""
    for item in config.config.courses[: course_index + 1]:
        display = course_display_name(item, seen)
    references = _references(config, course_index)
    return {
        "index": course_index,
        "display": display,
        "course_id": course.course_id,
        "section_id": course.section_id or "",
        "credits": course.credits,
        "capacity": course.capacity,
        "modality": _modality(course),
        "room": list(course.room),
        "lab": list(course.lab),
        "conflicts": list(course.conflicts),
        "faculty": list(course.faculty or []),
        "required_room_features": ", ".join(sorted(course.required_room_features)),
        "required_lab_features": ", ".join(sorted(course.required_lab_features)),
        "reserve_room_during_lab": course.reserve_room_during_lab,
        "referenced_by": references,
        "can_delete": not references,
    }


def form_choices(request, course_index: int | None = None) -> dict:
    """Choices for CourseForm's pickers, as keyword arguments for it.

    `course_index` is the section being edited, so its own course_id is not
    offered as a conflict (unless another section shares it, which the
    controller still rejects as a self-conflict).
    """
    config = require_config(get_session(request), "editing courses")
    entities = config.config
    return {
        "credit_choices": enabled_pattern_credits(config),
        "room_names": sorted(room.name for room in entities.rooms),
        "lab_names": sorted(lab.name for lab in entities.labs),
        "faculty_names": sorted(person.name for person in entities.faculty),
        "course_ids": sorted(
            {course.course_id for position, course in enumerate(entities.courses) if position != course_index}
        ),
    }


# ---------------------------------------------------------------------- #
#  Writes -- each returns a list of non-blocking notice strings
# ---------------------------------------------------------------------- #
def add_course(request, form_data) -> list[str]:
    session = get_session(request)
    config = require_config(session, "adding a course")
    fields, notices = _fields_from_form(config, form_data)
    new_course = _build(fields)

    def mutate(draft):
        draft.config.courses.append(new_course)

    apply_config_edit(session, config, "course", mutate, form_fields=COURSE_FIELDS)
    return notices


def update_course(request, course_index: int, form_data, expected_course_id: str | None = None) -> list[str]:
    """Replace the section at `course_index`, keeping its place in the list."""
    session = get_session(request)
    config = require_config(session, "editing courses")
    old_id = _course_at(config, course_index, expected_course_id).course_id
    fields, notices = _fields_from_form(config, form_data, editing_index=course_index)
    updated = _build(fields)
    new_id = updated.course_id
    cascade = new_id != old_id and _is_last_section(config, course_index)
    if cascade:
        notices += _rename_notices(config, course_index, old_id, new_id)  # counted before the edit

    def mutate(draft):
        draft.config.courses[course_index] = updated
        if cascade:
            _rename_references(draft, course_index, old_id, new_id)

    apply_config_edit(session, config, "course", mutate, form_fields=COURSE_FIELDS)
    return notices


def delete_course(request, course_index: int, expected_course_id: str | None = None) -> list[str]:
    """Delete one section. Blocked, with the reasons listed, when it is the
    last section of its course_id and something still refers to that id."""
    session = get_session(request)
    config = require_config(session, "deleting a course")
    course = _course_at(config, course_index, expected_course_id)
    try:
        check_no_references(course.course_id, _references(config, course_index))
    except ReferenceError_ as error:
        raise ControllerError(f"{error}. Remove those references first.") from error

    def mutate(draft):
        del draft.config.courses[course_index]

    apply_config_edit(session, config, "course", mutate, form_fields=COURSE_FIELDS)
    return []


# ---------------------------------------------------------------------- #
#  Helpers
# ---------------------------------------------------------------------- #
def _build(fields: dict) -> CourseConfig:
    """The library checks the record on its own here (blank ids, online
    courses with rooms, features without rooms, duplicate names)."""
    try:
        return CourseConfig(**fields)
    except ValidationError as error:
        raise ControllerError(translate_validation_error(error, COURSE_FIELDS)) from error


def _course_at(config, index: int, expected_course_id: str | None = None):
    courses = config.config.courses
    if not isinstance(index, int) or not 0 <= index < len(courses):
        raise ControllerError("That course no longer exists. Refresh the page and try again.")
    course = courses[index]
    if expected_course_id is not None and course.course_id != expected_course_id:
        raise ControllerError(
            "The course list changed since this page was opened. Refresh the page and try again."
        )
    return course


def _modality(course) -> str:
    return getattr(course.modality, "value", str(course.modality))


def _preferring(config, course_id: str) -> list[str]:
    return [person.name for person in config.config.faculty if course_id in person.course_preferences]


def _is_last_section(config, index: int) -> bool:
    course_id = config.config.courses[index].course_id
    return not any(
        other.course_id == course_id
        for position, other in enumerate(config.config.courses)
        if position != index
    )


def _references(config, index: int) -> list[str]:
    """What still points at this section's course_id, if it is the last one."""
    if not _is_last_section(config, index):
        return []
    course_id = config.config.courses[index].course_id
    seen: dict[str, int] = {}
    references = []
    for position, other in enumerate(config.config.courses):
        display = course_display_name(other, seen)
        if position != index and course_id in other.conflicts:
            references.append(f"course {display} (conflicts)")
    references += [
        f"faculty {person.name} (course preference)"
        for person in config.config.faculty
        if course_id in person.course_preferences
    ]
    return references


def _rename_references(draft, index: int, old_id: str, new_id: str) -> None:
    """Inside the edit: point conflicts and faculty preferences at new_id."""
    for position, other in enumerate(draft.config.courses):
        if position == index or old_id not in other.conflicts:
            continue
        renamed = [new_id if item == old_id else item for item in other.conflicts]
        # Drop a would-be self-conflict and any duplicate the rename created.
        other.conflicts = [item for item in dict.fromkeys(renamed) if item != other.course_id]
    for person in draft.config.faculty:
        prefs = person.course_preferences
        if old_id in prefs:
            weight = prefs.pop(old_id)
            prefs[new_id] = max(weight, prefs.get(new_id, weight))


def _rename_notices(config, index: int, old_id: str, new_id: str) -> list[str]:
    conflicts = sum(
        1
        for position, course in enumerate(config.config.courses)
        if position != index and old_id in course.conflicts
    )
    prefs = sum(1 for person in config.config.faculty if old_id in person.course_preferences)
    parts = []
    if conflicts:
        parts.append(f"{conflicts} course conflict list{'s' if conflicts != 1 else ''}")
    if prefs:
        parts.append(f"{prefs} faculty course preference{'s' if prefs != 1 else ''}")
    if not parts:
        return []
    return [f"Renamed '{old_id}' to '{new_id}' in {' and '.join(parts)}."]


def _split(value) -> list[str]:
    """'a, b; c' / ['a', ' b '] -> ['a', 'b', 'c'] (blanks dropped)."""
    if value is None:
        return []
    parts = _SPLIT.split(value) if isinstance(value, str) else [str(item) for item in value]
    return [part.strip() for part in parts if part and part.strip()]


def _names(value, field: str, known, label: str, errors: list[FieldError]) -> list[str]:
    """Existing names, order kept, duplicates dropped; unknown ones reported."""
    names = list(dict.fromkeys(_split(value)))
    known = set(known)
    unknown = [name for name in names if name not in known]
    if unknown:
        choices = ", ".join(sorted(known)) or f"none defined yet -- add a {label} first"
        errors.append(FieldError(field, f"Unknown {label}: {', '.join(unknown)}. Choose from: {choices}."))
        return []
    return names


def _whole_number(value, field: str, label: str, errors: list[FieldError]) -> int | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        errors.append(FieldError(field, f"{label} is required."))
        return None
    try:
        number = value if isinstance(value, int) and not isinstance(value, bool) else int(str(value).strip())
    except ValueError:
        errors.append(FieldError(field, f"{label} must be a whole number."))
        return None
    if number < 1:
        errors.append(FieldError(field, f"{label} must be at least 1."))
        return None
    return number


def _flag(value, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def _fields_from_form(config, form_data, editing_index: int | None = None) -> tuple[dict, list[str]]:
    """form_data -> (CourseConfig keyword arguments, notices). Collects every
    field's problems before raising, so the user sees them all at once."""
    errors: list[FieldError] = []
    notices: list[str] = []
    entities = config.config

    course_id = str(form_data.get("course_id") or "").strip()
    if not course_id:
        errors.append(FieldError("course_id", "Course ID is required."))
    section_id = str(form_data.get("section_id") or "").strip() or None

    credits = _whole_number(form_data.get("credits"), "credits", "Credits", errors)
    capacity = _whole_number(form_data.get("capacity"), "capacity", "Capacity", errors)
    if credits is not None:
        available = enabled_pattern_credits(config)
        if credits not in available:
            offer = (
                f"Enabled patterns have: {', '.join(str(value) for value in available)}."
                if available
                else "There are no enabled class patterns."
            )
            errors.append(
                FieldError("credits", f"No enabled class pattern has {credits} credits. {offer} Add or enable a pattern first.")
            )

    modality = str(form_data.get("modality") or "in_person").strip().lower()
    if modality not in MODALITIES:
        errors.append(FieldError("modality", f"Modality must be one of: {', '.join(MODALITIES)}."))

    rooms = _names(form_data.get("room"), "room", (r.name for r in entities.rooms), "room", errors)
    labs = _names(form_data.get("lab"), "lab", (l.name for l in entities.labs), "lab", errors)
    faculty = _names(form_data.get("faculty"), "faculty", (f.name for f in entities.faculty), "faculty member", errors)
    other_ids = {
        course.course_id for position, course in enumerate(entities.courses) if position != editing_index
    }
    conflicts = _names(form_data.get("conflicts"), "conflicts", other_ids | {course_id}, "course", errors)
    if course_id and course_id in conflicts:
        errors.append(FieldError("conflicts", "A course can't conflict with itself."))
    room_features = set(_split(form_data.get("required_room_features")))
    lab_features = set(_split(form_data.get("required_lab_features")))
    reserve = _flag(form_data.get("reserve_room_during_lab"), default=True)

    if errors:
        raise ControllerError(errors)

    if modality == "online":
        dropped = [
            label
            for label, value in (
                ("rooms", rooms),
                ("labs", labs),
                ("required room features", room_features),
                ("required lab features", lab_features),
            )
            if value
        ]
        if dropped:
            notices.append(f"Online courses don't use physical space, so {', '.join(dropped)} were cleared.")
        rooms, labs, room_features, lab_features = [], [], set(), set()

    return (
        {
            "course_id": course_id,
            "section_id": section_id,
            "credits": credits,
            "capacity": capacity,
            "modality": modality,
            "room": rooms,
            "lab": labs,
            "conflicts": conflicts,
            "faculty": faculty or None,
            "required_room_features": room_features,
            "required_lab_features": lab_features,
            "reserve_room_during_lab": reserve,
        },
        notices,
    )
