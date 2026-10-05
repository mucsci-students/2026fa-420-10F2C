"""
Controller for Labs (Section 7, Labs row): name, capacity, features, and
optional weekday availability.

Labs work like rooms (see gui/controllers/rooms.py) but are referenced from
different places: a course lists labs in its `lab` list, and faculty
`lab_preferences` are keyed by lab name. Labs are identified by name (names are
unique), same as app/commands/labs.py.

Every edit goes through app.crud.apply_edit() via apply_session_edit(), so the
complete CombinedConfig is re-validated and a failed edit leaves the previous
valid configuration untouched (Sections 10 and 11).

What the scheduler library enforces (so we do NOT reimplement it): field types,
time-range format, and whole-config rules such as lab references and
capacity/feature compatibility with courses. What this controller adds so the
GUI can show clear field-level messages:
  * a non-blank, unique name,
  * a positive whole-number capacity,
    * reference checks (Section 12) before a lab is deleted or directly renamed.
        Deletion remains blocked; a reviewed rename confirmation updates blocking
        course and faculty references atomically after the user confirms.

Functions raise ControllerError for anything the user can fix; they never touch
HttpResponse or templates (Section 20).

form_data keys (plain Python values; the View's form produces them):
    name      str
    capacity  int
    features  iterable of str, or a comma-separated str   (optional)
    times     None/empty for "available any time", or
              {"MON": [{"start": "09:00", "end": "17:00"}], ...}   (optional)
"""

from __future__ import annotations

from scheduler.config import LabConfig, ValidationError

from app.commands.common import VALID_DAYS, apply_session_edit, field_value
from app.crud import ReferenceError_, ValidationFailure, check_no_references
from app.session import ConfigError
from gui.constants import DAY_NAMES
from gui.controllers.errors import (
    ControllerError,
    FieldError,
    to_controller_error,
    translate_validation_error,
)
from gui.session_store import get_session

LAB_FIELDS = ("name", "capacity", "features", "times")


# ---------------------------------------------------------------------- #
#  Helpers
# ---------------------------------------------------------------------- #
def _require_config(session):
    try:
        return session.require_config()
    except ConfigError as error:
        raise ControllerError(
            "No configuration is loaded. Create or load one before editing labs."
        ) from error


def _find_lab(config, name):
    lab = next((lab for lab in config.config.labs if lab.name == name), None)
    if lab is None:
        raise ControllerError(f"Lab '{name}' no longer exists. Refresh the page and try again.")
    return lab


def _references(config, name) -> list[str]:
    """Human-readable list of records that still point at lab `name`."""
    found: list[str] = []
    for course in config.config.courses:
        if name in (getattr(course, "lab", None) or []):
            label = f"course '{course.course_id}'"
            if label not in found:
                found.append(label)
    for person in config.config.faculty:
        if name in (getattr(person, "lab_preferences", None) or {}):
            found.append(f"faculty '{person.name}' (lab preference)")
    return found


def _parse_features(raw) -> list[str]:
    if raw is None:
        return []
    parts = raw.split(",") if isinstance(raw, str) else list(raw)
    return sorted({str(part).strip() for part in parts if str(part).strip()})


def _parse_times(raw, errors: list[FieldError]):
    """Return {day: [{"start","end"}, ...]} or None for unrestricted."""
    if not raw:
        return None
    if not isinstance(raw, dict):
        errors.append(FieldError("times", "Availability must be a set of weekday time ranges."))
        return None
    times = {}
    for day, blocks in raw.items():
        if day not in VALID_DAYS:
            errors.append(
                FieldError("times", f"'{day}' is not a valid day. Choose from: {', '.join(VALID_DAYS)}.")
            )
            continue
        if not blocks:
            continue
        times[day] = [{"start": field_value(b, "start"), "end": field_value(b, "end")} for b in blocks]
    return times or None


def _lab_fields(form_data) -> dict:
    """Shape-check form_data and return kwargs for LabConfig.

    Only obvious shape problems are caught here (blank name, capacity not a
    positive whole number, unknown weekday); everything else is the library's
    job. All problems are reported together.
    """
    errors: list[FieldError] = []

    name = (form_data.get("name") or "").strip()
    if not name:
        errors.append(FieldError("name", "Lab name cannot be blank."))

    capacity = form_data.get("capacity")
    if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0:
        errors.append(FieldError("capacity", "Capacity must be a positive whole number."))

    features = _parse_features(form_data.get("features"))
    times = _parse_times(form_data.get("times"), errors)

    if errors:
        raise ControllerError(errors)

    fields = {"name": name, "capacity": capacity, "features": features}
    if times is not None:
        fields["times"] = times
    return fields


def _build_lab(fields) -> LabConfig:
    try:
        return LabConfig(**fields)
    except ValidationError as error:
        raise ControllerError(translate_validation_error(error, form_fields=LAB_FIELDS)) from error


def _prepared_update(config, lab_name, form_data) -> tuple[dict, LabConfig]:
    """Validate one LabConfig replacement before an edit is committed."""
    _find_lab(config, lab_name)
    fields = _lab_fields(form_data)
    if fields["name"] != lab_name and any(lab.name == fields["name"] for lab in config.config.labs):
        raise ControllerError([FieldError("name", f"A lab named '{fields['name']}' already exists.")])
    return fields, _build_lab(fields)


def _apply(session, config, mutate) -> None:
    try:
        apply_session_edit(session, config, "lab", mutate)
    except ValidationFailure as error:
        raise to_controller_error(error, form_fields=LAB_FIELDS) from error


def _availability(times) -> list[dict]:
    """Per-day availability rows in weekday order; [] means unrestricted."""
    if not times:
        return []
    rows = []
    for day in VALID_DAYS:
        blocks = field_value(times, day)
        if not blocks:
            continue
        ranges = ", ".join(f"{field_value(b, 'start')}-{field_value(b, 'end')}" for b in blocks)
        rows.append({"day": day, "name": DAY_NAMES[day], "ranges": ranges})
    return rows


# ---------------------------------------------------------------------- #
#  Reads
# ---------------------------------------------------------------------- #
def describe_labs(request) -> dict:
    """Everything the Labs page needs, as plain data (no models).

    Returns {"has_config": False} when nothing is loaded so the view can show
    the empty state (Section 19).
    """
    config = get_session(request).config
    if config is None:
        return {"has_config": False}

    labs = []
    for lab in config.config.labs:
        references = _references(config, lab.name)
        labs.append(
            {
                "name": lab.name,
                "capacity": lab.capacity,
                "features": sorted(lab.features or []),
                "availability": _availability(lab.times),
                "unrestricted": not lab.times,
                "referenced_by": references,
                "can_delete": not references,
            }
        )
    return {"has_config": True, "labs": labs}


def get_lab(request, lab_name) -> dict:
    """One lab as plain data, for the edit and delete pages."""
    config = _require_config(get_session(request))
    lab = _find_lab(config, lab_name)
    references = _references(config, lab_name)
    times = {}
    if lab.times:
        for day in VALID_DAYS:
            blocks = field_value(lab.times, day)
            if blocks:
                times[day] = [
                    {"start": field_value(b, "start"), "end": field_value(b, "end")} for b in blocks
                ]
    return {
        "name": lab.name,
        "capacity": lab.capacity,
        "features": sorted(lab.features or []),
        "times": times,
        "availability": _availability(lab.times),
        "referenced_by": references,
        "can_delete": not references,
    }


def rename_impact(request, lab_name, form_data) -> dict:
    """Describe records that a proposed lab rename would update."""
    config = _require_config(get_session(request))
    fields, _ = _prepared_update(config, lab_name, form_data)
    references = _references(config, lab_name) if fields["name"] != lab_name else []
    return {"new_name": fields["name"], "references": references}


# ---------------------------------------------------------------------- #
#  Writes
# ---------------------------------------------------------------------- #
def add_lab(request, form_data) -> None:
    """Add a lab. Rejects a blank/duplicate name and any whole-config failure."""
    session = get_session(request)
    config = _require_config(session)
    fields = _lab_fields(form_data)
    if any(lab.name == fields["name"] for lab in config.config.labs):
        raise ControllerError([FieldError("name", f"A lab named '{fields['name']}' already exists.")])
    new_lab = _build_lab(fields)

    def mutate(draft):
        draft.config.labs.append(new_lab)

    _apply(session, config, mutate)


def update_lab(request, lab_name, form_data) -> None:
    """Replace the lab called `lab_name`, keeping its position in the list.

    Direct renaming is allowed only to an unused name and only while nothing
    references the old name. Referenced names use the separate confirmed
    propagation operation below (Section 12).
    """
    session = get_session(request)
    config = _require_config(session)
    fields, updated = _prepared_update(config, lab_name, form_data)
    new_name = fields["name"]

    if new_name != lab_name:
        references = _references(config, lab_name)
        if references:
            raise ControllerError(
                [
                    FieldError(
                        "name",
                        f"Can't rename '{lab_name}': still referenced by {', '.join(references)}. "
                        "Remove those references first.",
                    )
                ]
            )
    def mutate(draft):
        labs = draft.config.labs
        position = next(i for i, lab in enumerate(labs) if lab.name == lab_name)
        labs[position] = updated

    _apply(session, config, mutate)


def rename_lab_and_update_references(request, lab_name, form_data) -> None:
    """Atomically rename a lab and all course/faculty name references.

    The caller must show rename_impact() and obtain confirmation first. The
    draft updates the lab, each candidate-lab list, and every matching faculty
    lab-preference key before complete-config validation commits it.
    """
    session = get_session(request)
    config = _require_config(session)
    fields, updated = _prepared_update(config, lab_name, form_data)
    new_name = fields["name"]
    if new_name == lab_name:
        raise ControllerError([FieldError("name", "Enter a different lab name before confirming a rename.")])

    def mutate(draft):
        labs = draft.config.labs
        position = next(index for index, lab in enumerate(labs) if lab.name == lab_name)
        labs[position] = updated

        for course in draft.config.courses:
            if lab_name in (course.lab or []):
                course.lab = [new_name if name == lab_name else name for name in course.lab]
        for person in draft.config.faculty:
            preferences = dict(person.lab_preferences or {})
            if lab_name in preferences:
                preferences[new_name] = preferences.pop(lab_name)
                person.lab_preferences = preferences

    _apply(session, config, mutate)


def delete_lab(request, lab_name) -> None:
    """Delete a lab unless a course or faculty member still references it."""
    session = get_session(request)
    config = _require_config(session)
    _find_lab(config, lab_name)
    try:
        check_no_references(lab_name, _references(config, lab_name))
    except ReferenceError_ as error:
        raise ControllerError(f"{error}. Remove this lab from those records first.") from error

    def mutate(draft):
        labs = draft.config.labs
        del labs[next(i for i, lab in enumerate(labs) if lab.name == lab_name)]

    _apply(session, config, mutate)