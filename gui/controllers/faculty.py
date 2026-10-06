"""Faculty controller for the Configuration Editor.

This module is the MVC boundary between Django's FacultyForm and the
scheduler's FacultyConfig model. It keeps HTTP/template work in the views,
uses ControllerError for user-correctable failures, and commits only through
apply_config_edit(), which validates the complete configuration atomically.
"""

from __future__ import annotations

from collections.abc import Mapping

from scheduler.config import FacultyConfig, ValidationError

from app.commands.common import VALID_DAYS, field_value
from app.crud import ReferenceError_, check_no_references
from gui.controllers.common import apply_config_edit, require_config
from gui.controllers.errors import ControllerError, FieldError, translate_validation_error
from gui.session_store import get_session

MAX_WEEKDAYS = len(VALID_DAYS)
MAX_PREFERENCE_WEIGHT = 10
FACULTY_FIELDS = (
    "name",
    "minimum_credits",
    "maximum_credits",
    "unique_course_limit",
    "maximum_days",
    "times",
    "mandatory_days",
)


# ---------------------------------------------------------------------- #
#  Helpers
# ---------------------------------------------------------------------- #
def _find_faculty(config, name):
    """Return a named faculty member or explain that the browser is stale."""
    faculty = next((person for person in config.config.faculty if person.name == name), None)
    if faculty is None:
        raise ControllerError(f"Faculty member '{name}' no longer exists. Refresh the page and try again.")
    return faculty


def _references(config, name) -> list[str]:
    """List courses that explicitly assign this faculty member.

    Faculty preferences do not reference other faculty records, so courses are
    the only records that can make a faculty rename or delete unsafe.
    """
    found: list[str] = []
    for course in config.config.courses:
        if name in (getattr(course, "faculty", None) or []):
            label = f"course '{course.course_id}'"
            if label not in found:
                found.append(label)
    return found


def _valid_preferences(config) -> dict[str, set[str]]:
    """Return the current resource names that may receive a preference."""
    return {
        "course": {course.course_id for course in config.config.courses},
        "room": {room.name for room in config.config.rooms},
        "lab": {lab.name for lab in config.config.labs},
    }


def form_choices(request) -> dict[str, list[str]]:
    """Return dynamic FacultyForm choices without exposing scheduler models.

    Views call this every time they build a form so a failed POST and an edit
    GET use the resources in the current configuration.
    """
    config = get_session(request).config
    if config is None:
        return {"course_names": [], "room_names": [], "lab_names": []}
    choices = _valid_preferences(config)
    return {
        "course_names": sorted(choices["course"]),
        "room_names": sorted(choices["room"]),
        "lab_names": sorted(choices["lab"]),
    }


def _parse_times(raw, errors: list[FieldError]) -> dict:
    """Keep the weekday mapping expected by FacultyConfig.

    The form has already checked the input text. These guards make direct
    controller callers safe as well and let the scheduler validate individual
    TimeRange values such as end-after-start.
    """
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        errors.append(FieldError("times", "Availability must be weekday time ranges."))
        return {}

    times = {}
    for day, blocks in raw.items():
        if day not in VALID_DAYS:
            errors.append(FieldError("times", f"'{day}' is not a valid weekday."))
            continue
        if not isinstance(blocks, list):
            errors.append(FieldError("times", f"Availability for {day} must be a list of time ranges."))
            continue
        times[day] = blocks
    return times


def _parse_mandatory_days(raw, times: Mapping, errors: list[FieldError]) -> list[str]:
    """Validate day selections that depend on the availability mapping."""
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple, set)):
        errors.append(FieldError("mandatory_days", "Mandatory days must be a list of weekdays."))
        return []

    days = list(raw)
    if len(set(days)) != len(days):
        errors.append(FieldError("mandatory_days", "Choose each mandatory day only once."))
    for day in days:
        if day not in VALID_DAYS:
            errors.append(FieldError("mandatory_days", f"'{day}' is not a valid weekday."))
        elif not times.get(day):
            errors.append(
                FieldError("mandatory_days", f"{day} must have availability before it can be mandatory.")
            )
    return days


def _parse_preferences(raw, kind: str, allowed_names: set[str], errors: list[FieldError]) -> dict[str, int]:
    """Validate one name-to-weight preference map from FacultyForm.clean()."""
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        errors.append(FieldError(None, f"{kind.capitalize()} preferences must map names to weights."))
        return {}

    preferences = {}
    for name, weight in raw.items():
        if name not in allowed_names:
            errors.append(FieldError(None, f"'{name}' is not a current {kind}."))
            continue
        if isinstance(weight, bool) or not isinstance(weight, int) or not 0 <= weight <= MAX_PREFERENCE_WEIGHT:
            errors.append(
                FieldError(None, f"Preference for '{name}' must be a whole number from 0 to {MAX_PREFERENCE_WEIGHT}.")
            )
            continue
        preferences[name] = weight
    return preferences


def _faculty_fields(form_data, config) -> dict:
    """Shape-check browser data and return FacultyConfig keyword arguments.

    Cross-record and scheduler-specific validation remains with FacultyConfig
    and CombinedConfig.edit_mode(); this method only reports clear local form
    problems before an atomic edit is attempted.
    """
    errors: list[FieldError] = []
    name = (form_data.get("name") or "").strip()
    if not name:
        errors.append(FieldError("name", "Faculty name cannot be blank."))

    numeric_fields = {
        "minimum_credits": form_data.get("minimum_credits"),
        "maximum_credits": form_data.get("maximum_credits"),
        "unique_course_limit": form_data.get("unique_course_limit"),
        "maximum_days": form_data.get("maximum_days"),
    }
    for field, value in numeric_fields.items():
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append(FieldError(field, "Enter a whole number."))

    minimum_credits = numeric_fields["minimum_credits"]
    maximum_credits = numeric_fields["maximum_credits"]
    unique_course_limit = numeric_fields["unique_course_limit"]
    maximum_days = numeric_fields["maximum_days"]
    if isinstance(minimum_credits, int) and not isinstance(minimum_credits, bool) and minimum_credits < 0:
        errors.append(FieldError("minimum_credits", "Minimum credits cannot be negative."))
    if isinstance(maximum_credits, int) and not isinstance(maximum_credits, bool) and maximum_credits < 0:
        errors.append(FieldError("maximum_credits", "Maximum credits cannot be negative."))
    if (
        isinstance(minimum_credits, int)
        and not isinstance(minimum_credits, bool)
        and isinstance(maximum_credits, int)
        and not isinstance(maximum_credits, bool)
        and minimum_credits > maximum_credits
    ):
        errors.append(FieldError("maximum_credits", "Maximum credits must be at least minimum credits."))
    if isinstance(unique_course_limit, int) and not isinstance(unique_course_limit, bool) and unique_course_limit <= 0:
        errors.append(FieldError("unique_course_limit", "Unique course limit must be at least 1."))
    if (
        isinstance(maximum_days, int)
        and not isinstance(maximum_days, bool)
        and not 0 <= maximum_days <= MAX_WEEKDAYS
    ):
        errors.append(FieldError("maximum_days", f"Maximum teaching days must be from 0 to {MAX_WEEKDAYS}."))

    times = _parse_times(form_data.get("times"), errors)
    mandatory_days = _parse_mandatory_days(form_data.get("mandatory_days"), times, errors)
    if isinstance(maximum_days, int) and not isinstance(maximum_days, bool) and maximum_days < len(mandatory_days):
        errors.append(
            FieldError("maximum_days", "Maximum teaching days cannot be below the number of mandatory days.")
        )

    allowed = _valid_preferences(config)
    course_preferences = _parse_preferences(form_data.get("course_preferences"), "course", allowed["course"], errors)
    room_preferences = _parse_preferences(form_data.get("room_preferences"), "room", allowed["room"], errors)
    lab_preferences = _parse_preferences(form_data.get("lab_preferences"), "lab", allowed["lab"], errors)

    if errors:
        raise ControllerError(errors)

    return {
        "name": name,
        "minimum_credits": minimum_credits,
        "maximum_credits": maximum_credits,
        "unique_course_limit": unique_course_limit,
        "maximum_days": maximum_days,
        "times": times,
        "mandatory_days": mandatory_days,
        "course_preferences": course_preferences,
        "room_preferences": room_preferences,
        "lab_preferences": lab_preferences,
    }


def _build_faculty(fields) -> FacultyConfig:
    """Construct the scheduler model and attach model errors to the form."""
    try:
        return FacultyConfig(**fields)
    except ValidationError as error:
        raise ControllerError(translate_validation_error(error, form_fields=FACULTY_FIELDS)) from error


def _prepared_update(config, faculty_name, form_data) -> tuple[dict, FacultyConfig]:
    """Validate one proposed faculty replacement before any edit is committed.

    Both a normal edit and a confirmed propagated rename use this preparation
    step, so duplicate-name and FacultyConfig validation rules are identical.
    """
    _find_faculty(config, faculty_name)
    fields = _faculty_fields(form_data, config)
    new_name = fields["name"]
    if new_name != faculty_name and any(person.name == new_name for person in config.config.faculty):
        raise ControllerError([FieldError("name", f"A faculty member named '{new_name}' already exists.")])
    return fields, _build_faculty(fields)


def _times_for_form(times) -> dict:
    """Serialize Pydantic TimeRange instances into Form initial values."""
    values = {}
    for day in VALID_DAYS:
        blocks = field_value(times, day)
        if blocks:
            values[day] = [
                {"start": field_value(block, "start"), "end": field_value(block, "end")}
                for block in blocks
            ]
    return values


def _availability(times) -> list[dict]:
    """Create template-friendly availability rows in weekday order."""
    rows = []
    for day in VALID_DAYS:
        blocks = field_value(times, day)
        if not blocks:
            continue
        ranges = ", ".join(f"{field_value(block, 'start')}-{field_value(block, 'end')}" for block in blocks)
        rows.append({"day": day, "ranges": ranges})
    return rows


def _preferences(faculty) -> list[dict]:
    """Create consistently ordered display groups for all preference maps."""
    groups = []
    for label, values in (
        ("Course", faculty.course_preferences),
        ("Room", faculty.room_preferences),
        ("Lab", faculty.lab_preferences),
    ):
        entries = [{"name": name, "weight": weight} for name, weight in sorted((values or {}).items())]
        groups.append({"label": label, "entries": entries})
    return groups


def _faculty_data(config, faculty) -> dict:
    """Map a scheduler faculty model to data that templates can render."""
    references = _references(config, faculty.name)
    return {
        "name": faculty.name,
        "minimum_credits": faculty.minimum_credits,
        "maximum_credits": faculty.maximum_credits,
        "unique_course_limit": faculty.unique_course_limit,
        "maximum_days": faculty.maximum_days,
        "mandatory_days": list(faculty.mandatory_days or []),
        "times": _times_for_form(faculty.times),
        "availability": _availability(faculty.times),
        "preferences": _preferences(faculty),
        "course_preferences": dict(faculty.course_preferences or {}),
        "room_preferences": dict(faculty.room_preferences or {}),
        "lab_preferences": dict(faculty.lab_preferences or {}),
        "referenced_by": references,
        "can_delete": not references,
    }


# ---------------------------------------------------------------------- #
#  Reads
# ---------------------------------------------------------------------- #
def describe_faculty(request) -> dict:
    """Return the Faculty page's table data or its empty configuration state."""
    config = get_session(request).config
    if config is None:
        return {"has_config": False}
    return {"has_config": True, "faculty": [_faculty_data(config, person) for person in config.config.faculty]}


def get_faculty(request, faculty_name) -> dict:
    """Return one faculty record for its edit or delete page."""
    session = get_session(request)
    config = require_config(session, "editing faculty")
    return _faculty_data(config, _find_faculty(config, faculty_name))


# ---------------------------------------------------------------------- #
#  Writes
# ---------------------------------------------------------------------- #
def add_faculty(request, form_data) -> None:
    """Add a unique faculty record through complete-config validation."""
    session = get_session(request)
    config = require_config(session, "adding faculty")
    fields = _faculty_fields(form_data, config)
    if any(person.name == fields["name"] for person in config.config.faculty):
        raise ControllerError([FieldError("name", f"A faculty member named '{fields['name']}' already exists.")])
    new_faculty = _build_faculty(fields)

    def mutate(draft):
        draft.config.faculty.append(new_faculty)

    apply_config_edit(session, config, "faculty", mutate, form_fields=FACULTY_FIELDS)


def update_faculty(request, faculty_name, form_data) -> list[str]:
    """Replace a faculty record and update explicit course assignments.

    A faculty name is data inside course assignment lists. Updating both in
    one draft keeps the configuration valid and gives the edit form the same
    direct-update behavior used by Courses.
    """
    session = get_session(request)
    config = require_config(session, "editing faculty")
    fields, updated = _prepared_update(config, faculty_name, form_data)
    new_name = fields["name"]
    notices = _rename_notices(config, faculty_name, new_name)

    def mutate(draft):
        people = draft.config.faculty
        position = next(index for index, person in enumerate(people) if person.name == faculty_name)
        people[position] = updated
        if new_name != faculty_name:
            # Explicit course assignments store a faculty name instead of an
            # object reference. Derived staffing (None) remains unchanged.
            for course in draft.config.courses:
                if faculty_name in (course.faculty or []):
                    course.faculty = [new_name if name == faculty_name else name for name in course.faculty]

    apply_config_edit(session, config, "faculty", mutate, form_fields=FACULTY_FIELDS)
    return notices


def _rename_notices(config, old_name: str, new_name: str) -> list[str]:
    """Describe assignments changed by a direct faculty-name update."""
    if old_name == new_name:
        return []
    assignments = sum(old_name in (course.faculty or []) for course in config.config.courses)
    if not assignments:
        return []
    noun = "assignment" if assignments == 1 else "assignments"
    return [f"Renamed '{old_name}' to '{new_name}' in {assignments} course faculty {noun}."]


def delete_faculty(request, faculty_name) -> None:
    """Delete faculty only after confirming no course still assigns them."""
    session = get_session(request)
    config = require_config(session, "deleting faculty")
    _find_faculty(config, faculty_name)
    try:
        check_no_references(faculty_name, _references(config, faculty_name))
    except ReferenceError_ as error:
        raise ControllerError(f"{error}. Remove this faculty member from those courses first.") from error

    def mutate(draft):
        people = draft.config.faculty
        del people[next(index for index, person in enumerate(people) if person.name == faculty_name)]

    apply_config_edit(session, config, "faculty", mutate, form_fields=FACULTY_FIELDS)
