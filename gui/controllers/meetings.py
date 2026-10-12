"""
Controller for Meetings (Section 7, Meetings row): day, duration, lab
designation, delivery mode, and an optional fixed start time.

A meeting always belongs to a class pattern, so it is identified by
(pattern_index, meeting_index) -- the same shape as app/commands/meetings.py.
Patterns have no name or id, only a position in time_slot_config.classes.

What the scheduler library enforces (so we do NOT reimplement it): field types,
allowed day / delivery values, time format, and every whole-configuration rule
that involves meetings (the edit is re-validated through app.crud.apply_edit()
via apply_config_edit(), so a failed edit leaves the previous valid
configuration untouched -- Sections 10 and 11).

What this controller adds because the GUI needs a clear message first:
  * a positive whole-number duration and a real weekday,
  * stale-index guards for pages that are out of date,
  * "a pattern keeps at least one meeting" -- deleting the last one is blocked
    with the user-story wording (story 27); delete the pattern instead,
  * a non-blocking warning when a meeting is longer than every time block on its
    day (the library accepts it; the schedule just becomes infeasible).

Functions raise ControllerError for anything the user can fix; they never touch
HttpResponse or templates (Section 20). The write functions return a list of
non-blocking warning strings, like gui/controllers/timeslots.py.

form_data keys (plain Python values; the View's form produces them):
    day         str   "MON".."FRI"
    duration    int   minutes
    lab         bool  (optional, default False)
    delivery    str   "in_person" / "online" / "hybrid" (optional, default in_person)
    start_time  str   "HH:MM", or None/"" for "no fixed start"  (optional)
"""

from __future__ import annotations

import copy

from scheduler.config import Meeting, ValidationError

from app.commands.common import VALID_DAYS
from gui.constants import DAY_NAMES
from gui.controllers.common import apply_config_edit, require_config
from gui.controllers.errors import ControllerError, FieldError, translate_validation_error
from gui.controllers.timeslots import _fit_warnings
from gui.session_store import get_session

MEETING_FIELDS = ("day", "duration", "lab", "delivery", "start_time")
DELIVERY_MODES = ("in_person", "online", "hybrid")
DELIVERY_LABELS = {"in_person": "In person", "online": "Online", "hybrid": "Hybrid"}

LAST_MEETING_MESSAGE = (
    "Can't delete the only meeting on this pattern -- delete the pattern instead if you don't need it."
)


# ---------------------------------------------------------------------- #
#  Helpers (also used by gui/controllers/patterns.py)
# ---------------------------------------------------------------------- #
def _require_config(session):
    return require_config(session, "editing meetings")


def _value(item):
    """An enum member's plain value, or the thing itself."""
    return str(getattr(item, "value", item))


def _patterns(config):
    return config.time_slot_config.classes


def _check_pattern_index(config, pattern_index: int):
    patterns = _patterns(config)
    if not 0 <= pattern_index < len(patterns):
        raise ControllerError("That class pattern no longer exists. Refresh the page and try again.")
    return patterns[pattern_index]


def _check_meeting_index(pattern, meeting_index: int) -> None:
    if not 0 <= meeting_index < len(pattern.meetings):
        raise ControllerError("That meeting no longer exists. Refresh the page and try again.")


def _apply(session, config, mutate) -> None:
    apply_config_edit(session, config, "meeting", mutate, form_fields=MEETING_FIELDS)


def meeting_summary(meeting) -> str:
    """One line, e.g. "MON 50 min" / "TUE 110 min, lab, starts at 09:00"."""
    parts = [f"{_value(meeting.day)} {meeting.duration} min"]
    if getattr(meeting, "lab", False):
        parts.append("lab")
    if getattr(meeting, "start_time", None):
        parts.append(f"starts at {meeting.start_time}")
    return ", ".join(parts)


def pattern_summary(index: int, pattern) -> str:
    """e.g. "Pattern 0: 3 credits (MON 50 min, WED 50 min)" -- used in dropdowns."""
    meetings = ", ".join(meeting_summary(m) for m in pattern.meetings)
    return f"Pattern {index}: {pattern.credits} credits ({meetings})"


def meeting_row(pattern_index: int, meeting_index: int, meeting) -> dict:
    """One meeting as plain data for templates and edit forms (no models)."""
    day = _value(meeting.day)
    delivery = _value(getattr(meeting, "delivery", "in_person") or "in_person")
    return {
        "pattern_index": pattern_index,
        "index": meeting_index,
        "day": day,
        "day_name": DAY_NAMES.get(day, day),
        "duration": meeting.duration,
        "lab": bool(getattr(meeting, "lab", False)),
        "delivery": delivery,
        "delivery_label": DELIVERY_LABELS.get(delivery, delivery),
        "start_time": getattr(meeting, "start_time", None) or "",
        "summary": meeting_summary(meeting),
    }


def build_meeting(form_data, prefix: str = "") -> Meeting:
    """Build a Meeting from form data; raise ControllerError on a problem.

    `prefix` lets a form that holds a meeting alongside other fields (the Add
    Class Pattern form uses "meeting_") reuse this: values are read from
    prefix+name and any error is attached to the prefixed form field.
    """

    def read(name):
        return form_data.get(prefix + name)

    errors: list[FieldError] = []
    day = str(read("day") or "").strip().upper()
    if day not in VALID_DAYS:
        errors.append(
            FieldError(prefix + "day", f"Choose a weekday: {', '.join(VALID_DAYS)}.")
        )
    duration = read("duration")
    if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
        errors.append(FieldError(prefix + "duration", "Duration must be a positive whole number of minutes."))
    if errors:
        raise ControllerError(errors)

    try:
        return Meeting(
            day=day,
            duration=duration,
            lab=bool(read("lab")),
            delivery=read("delivery") or "in_person",
            start_time=read("start_time") or None,
        )
    except ValidationError as error:
        items = translate_validation_error(error, form_fields=MEETING_FIELDS)
        raise ControllerError(
            [FieldError(prefix + item.field if item.field else None, item.message) for item in items]
        ) from error


# ---------------------------------------------------------------------- #
#  Reads
# ---------------------------------------------------------------------- #
def describe_meetings(request) -> dict:
    """Everything the Meetings page needs, as plain data.

    Returns {"has_config": False} when nothing is loaded so the view can show
    the empty state (Section 19).
    """
    config = get_session(request).config
    if config is None:
        return {"has_config": False}

    patterns = []
    for pattern_index, pattern in enumerate(_patterns(config)):
        rows = [meeting_row(pattern_index, i, m) for i, m in enumerate(pattern.meetings)]
        patterns.append(
            {
                "index": pattern_index,
                "credits": pattern.credits,
                "enabled": not getattr(pattern, "disabled", False),
                "label": pattern_summary(pattern_index, pattern),
                "meetings": rows,
                "only_meeting": len(rows) == 1,
            }
        )
    return {
        "has_config": True,
        "patterns": patterns,
        "pattern_choices": [(item["index"], item["label"]) for item in patterns],
    }


def get_meeting(request, pattern_index: int, meeting_index: int) -> dict:
    """One meeting as plain data, for the edit and delete pages."""
    config = _require_config(get_session(request))
    pattern = _check_pattern_index(config, pattern_index)
    _check_meeting_index(pattern, meeting_index)
    row = meeting_row(pattern_index, meeting_index, pattern.meetings[meeting_index])
    row["pattern_credits"] = pattern.credits
    row["is_only_meeting"] = len(pattern.meetings) == 1
    return row


# ---------------------------------------------------------------------- #
#  Writes -- each returns a list of non-blocking warning strings
# ---------------------------------------------------------------------- #
def add_meeting(request, pattern_index: int, form_data) -> list[str]:
    """Append a meeting to the pattern at pattern_index."""
    session = get_session(request)
    config = _require_config(session)
    _check_pattern_index(config, pattern_index)
    meeting = build_meeting(form_data)

    def mutate(draft):
        _patterns(draft)[pattern_index].meetings.append(meeting)

    _apply(session, config, mutate)
    return _fit_warnings(config, _value(meeting.day))


def update_meeting(request, pattern_index: int, meeting_index: int, form_data) -> list[str]:
    """Replace the meeting at (pattern_index, meeting_index)."""
    session = get_session(request)
    config = _require_config(session)
    pattern = _check_pattern_index(config, pattern_index)
    _check_meeting_index(pattern, meeting_index)
    old_day = _value(pattern.meetings[meeting_index].day)
    meeting = build_meeting(form_data)

    def mutate(draft):
        _patterns(draft)[pattern_index].meetings[meeting_index] = meeting

    _apply(session, config, mutate)
    new_day = _value(meeting.day)
    warnings = _fit_warnings(config, new_day)
    if old_day != new_day:
        warnings += [w for w in _fit_warnings(config, old_day) if w not in warnings]
    return warnings


def delete_meeting(request, pattern_index: int, meeting_index: int) -> list[str]:
    """Remove the meeting at (pattern_index, meeting_index). A pattern keeps at
    least one meeting (the library requires it too; we check first so the
    message is the clear one from user story 27)."""
    session = get_session(request)
    config = _require_config(session)
    pattern = _check_pattern_index(config, pattern_index)
    _check_meeting_index(pattern, meeting_index)
    if len(pattern.meetings) == 1:
        raise ControllerError(LAST_MEETING_MESSAGE)

    def mutate(draft):
        del _patterns(draft)[pattern_index].meetings[meeting_index]

    _apply(session, config, mutate)
    return []


# Kept so gui/controllers/patterns.py can copy a pattern's meetings without
# sharing objects with the live configuration.
def copy_meetings(pattern) -> list:
    return copy.deepcopy(list(pattern.meetings))
