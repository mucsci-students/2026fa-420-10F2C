"""
Controller for Rooms (Section 7, Rooms row): name, capacity, features, and
optional weekday availability.

Rooms are identified by name (names are unique), same as app/commands/rooms.py.
Every edit goes through app.crud.apply_edit() via apply_session_edit(), so the
complete CombinedConfig is re-validated and a failed edit leaves the previous
valid configuration untouched (Sections 10 and 11).

What the scheduler library enforces (so we do NOT reimplement it): field types,
time-range format, and whole-config rules such as room references and
capacity/feature compatibility with courses. What this controller adds because
the GUI needs a clear, field-level message before (or instead of) the library's
whole-config error:
  * a non-blank, unique name,
  * a positive whole-number capacity,
    * reference checks (Section 12) before a room is deleted or directly renamed.
        Courses list rooms by name, and faculty room_preferences are keyed by room
        name. Deletion remains blocked; the reviewed rename-confirmation operation
        updates those references atomically after user confirmation.

Functions raise ControllerError for anything the user can fix; they never touch
HttpResponse or templates (Section 20).

form_data keys (all plain Python values; the View's form produces them):
    name      str
    capacity  int
    features  iterable of str, or a comma-separated str   (optional)
    times     None/empty for "available any time", or
              {"MON": [{"start": "09:00", "end": "17:00"}], ...}   (optional)
"""

from __future__ import annotations

from scheduler.config import RoomConfig, ValidationError

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

ROOM_FIELDS = ("name", "capacity", "features", "times")


# ---------------------------------------------------------------------- #
#  Helpers
# ---------------------------------------------------------------------- #
def _require_config(session):
    try:
        return session.require_config()
    except ConfigError as error:
        raise ControllerError(
            "No configuration is loaded. Create or load one before editing rooms."
        ) from error


def _find_room(config, name):
    room = next((room for room in config.config.rooms if room.name == name), None)
    if room is None:
        raise ControllerError(f"Room '{name}' no longer exists. Refresh the page and try again.")
    return room


def _references(config, name) -> list[str]:
    """Human-readable list of records that still point at room `name`."""
    found: list[str] = []
    for course in config.config.courses:
        if name in (getattr(course, "room", None) or []):
            label = f"course '{course.course_id}'"
            if label not in found:
                found.append(label)
    for person in config.config.faculty:
        if name in (getattr(person, "room_preferences", None) or {}):
            found.append(f"faculty '{person.name}' (room preference)")
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


def _room_fields(form_data) -> dict:
    """Shape-check form_data and return kwargs for RoomConfig.

    Only obvious shape problems are caught here (blank name, capacity not a
    positive whole number, unknown weekday); everything else is the library's
    job. All problems are reported together.
    """
    errors: list[FieldError] = []

    name = (form_data.get("name") or "").strip()
    if not name:
        errors.append(FieldError("name", "Room name cannot be blank."))

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


def _build_room(fields) -> RoomConfig:
    try:
        return RoomConfig(**fields)
    except ValidationError as error:
        raise ControllerError(translate_validation_error(error, form_fields=ROOM_FIELDS)) from error


def _prepared_update(config, room_name, form_data) -> tuple[dict, RoomConfig]:
    """Validate one RoomConfig replacement before an edit is committed."""
    _find_room(config, room_name)
    fields = _room_fields(form_data)
    if fields["name"] != room_name and any(room.name == fields["name"] for room in config.config.rooms):
        raise ControllerError([FieldError("name", f"A room named '{fields['name']}' already exists.")])
    return fields, _build_room(fields)


def _apply(session, config, mutate) -> None:
    try:
        apply_session_edit(session, config, "room", mutate)
    except ValidationFailure as error:
        raise to_controller_error(error, form_fields=ROOM_FIELDS) from error


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
def describe_rooms(request) -> dict:
    """Everything the Rooms page needs, as plain data (no models).

    Returns {"has_config": False} when nothing is loaded so the view can show
    the empty state (Section 19).
    """
    config = get_session(request).config
    if config is None:
        return {"has_config": False}

    rooms = []
    for room in config.config.rooms:
        references = _references(config, room.name)
        rooms.append(
            {
                "name": room.name,
                "capacity": room.capacity,
                "features": sorted(room.features or []),
                "availability": _availability(room.times),
                "unrestricted": not room.times,
                "referenced_by": references,
                "can_delete": not references,
            }
        )
    return {"has_config": True, "rooms": rooms}


def get_room(request, room_name) -> dict:
    """One room as plain data, for the edit and delete pages."""
    config = _require_config(get_session(request))
    room = _find_room(config, room_name)
    references = _references(config, room_name)
    return {
        "name": room.name,
        "capacity": room.capacity,
        "features": sorted(room.features or []),
        "times": {
            day: [{"start": field_value(b, "start"), "end": field_value(b, "end")} for b in blocks]
            for day in VALID_DAYS
            if (blocks := field_value(room.times, day))
        }
        if room.times
        else {},
        "availability": _availability(room.times),
        "referenced_by": references,
        "can_delete": not references,
    }


def rename_impact(request, room_name, form_data) -> dict:
    """Describe records that a proposed room rename would update."""
    config = _require_config(get_session(request))
    fields, _ = _prepared_update(config, room_name, form_data)
    references = _references(config, room_name) if fields["name"] != room_name else []
    return {"new_name": fields["name"], "references": references}


# ---------------------------------------------------------------------- #
#  Writes
# ---------------------------------------------------------------------- #
def add_room(request, form_data) -> None:
    """Add a room. Rejects a blank/duplicate name and any whole-config failure."""
    session = get_session(request)
    config = _require_config(session)
    fields = _room_fields(form_data)
    if any(room.name == fields["name"] for room in config.config.rooms):
        raise ControllerError([FieldError("name", f"A room named '{fields['name']}' already exists.")])
    new_room = _build_room(fields)

    def mutate(draft):
        draft.config.rooms.append(new_room)

    _apply(session, config, mutate)


def update_room(request, room_name, form_data) -> None:
    """Replace the room called `room_name`, keeping its position in the list.

    Direct renaming is allowed only to an unused name and only while nothing
    references the old name. Referenced names use the separate confirmed
    propagation operation below (Section 12).
    """
    session = get_session(request)
    config = _require_config(session)
    fields, updated = _prepared_update(config, room_name, form_data)
    new_name = fields["name"]

    if new_name != room_name:
        references = _references(config, room_name)
        if references:
            raise ControllerError(
                [
                    FieldError(
                        "name",
                        f"Can't rename '{room_name}': still referenced by {', '.join(references)}. "
                        "Remove those references first.",
                    )
                ]
            )
    def mutate(draft):
        rooms = draft.config.rooms
        position = next(i for i, room in enumerate(rooms) if room.name == room_name)
        rooms[position] = updated

    _apply(session, config, mutate)


def rename_room_and_update_references(request, room_name, form_data) -> None:
    """Atomically rename a room and all course/faculty name references.

    The caller must show rename_impact() and obtain confirmation first. The
    draft replaces the room itself, each candidate-room list entry, and each
    matching faculty preference key before the complete configuration is
    validated as one change.
    """
    session = get_session(request)
    config = _require_config(session)
    fields, updated = _prepared_update(config, room_name, form_data)
    new_name = fields["name"]
    if new_name == room_name:
        raise ControllerError([FieldError("name", "Enter a different room name before confirming a rename.")])

    def mutate(draft):
        rooms = draft.config.rooms
        position = next(index for index, room in enumerate(rooms) if room.name == room_name)
        rooms[position] = updated

        for course in draft.config.courses:
            if room_name in (course.room or []):
                course.room = [new_name if name == room_name else name for name in course.room]
        for person in draft.config.faculty:
            preferences = dict(person.room_preferences or {})
            if room_name in preferences:
                preferences[new_name] = preferences.pop(room_name)
                person.room_preferences = preferences

    _apply(session, config, mutate)


def delete_room(request, room_name) -> None:
    """Delete a room unless a course or faculty member still references it."""
    session = get_session(request)
    config = _require_config(session)
    _find_room(config, room_name)
    try:
        check_no_references(room_name, _references(config, room_name))
    except ReferenceError_ as error:
        raise ControllerError(
            f"{error}. Remove this room from those records first."
        ) from error

    def mutate(draft):
        rooms = draft.config.rooms
        del rooms[next(i for i, room in enumerate(rooms) if room.name == room_name)]

    _apply(session, config, mutate)