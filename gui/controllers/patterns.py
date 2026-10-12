"""
Controller for Class Patterns (Section 7, Class patterns row): credits,
enabled state, optional fixed start time, and the pattern's meetings.

Patterns have no name or id field (see app/commands/patterns.py), so each one is
identified by its position in time_slot_config.classes, same as the CLI.

The page edits a pattern's own fields (credits, start time, enabled). Its
meetings are managed on the Meetings page (gui/controllers/meetings.py); editing
a pattern keeps its meetings exactly as they are (user story 23). A new pattern
needs at least one meeting, so the Add form takes the first one.

What the scheduler library enforces (so we do NOT reimplement it): field types,
time format, and whole-configuration rules such as course/pattern compatibility
(for example, you cannot remove the last pattern a course needs). Every edit goes
through app.crud.apply_edit() via apply_config_edit(), so the complete
CombinedConfig is re-validated and a failed edit leaves the previous valid
configuration untouched (Sections 10 and 11).

What this controller adds because the GUI needs a clear message first:
  * a positive whole-number credits value (user story 22 wording),
  * stale-index guards for pages that are out of date.

Deletion behaviour (Section 12): nothing in the configuration points at a pattern
by name, so there is no reference list to show. If removing a pattern would leave
a course with no usable pattern, the library rejects the change and the user sees
its explanation; the configuration stays as it was.

Functions raise ControllerError for anything the user can fix; they never touch
HttpResponse or templates (Section 20). Write functions return a list of
non-blocking warning strings.

form_data keys (plain Python values; the View's form produces them):
    credits     int
    start_time  str "HH:MM", or None/"" for "no fixed start"   (optional)
    enabled     bool (optional, default True)
  add_pattern also reads the first meeting, prefixed with "meeting_":
    meeting_day, meeting_duration, meeting_lab, meeting_delivery, meeting_start_time
"""

from __future__ import annotations

from scheduler.config import ClassPattern, ValidationError

from gui.controllers.common import apply_config_edit, require_config
from gui.controllers.errors import ControllerError, FieldError, translate_validation_error
from gui.controllers.meetings import (
    build_meeting,
    copy_meetings,
    meeting_row,
    meeting_summary,
)
from gui.controllers.timeslots import _fit_warnings
from gui.session_store import get_session

PATTERN_FIELDS = ("credits", "start_time", "enabled")

CREDITS_MESSAGE = "Credits must be a positive integer."


# ---------------------------------------------------------------------- #
#  Helpers
# ---------------------------------------------------------------------- #
def _require_config(session):
    return require_config(session, "editing class patterns")


def _patterns(config):
    return config.time_slot_config.classes


def _check_index(config, index: int):
    patterns = _patterns(config)
    if not 0 <= index < len(patterns):
        raise ControllerError("That class pattern no longer exists. Refresh the page and try again.")
    return patterns[index]


def _apply(session, config, mutate) -> None:
    apply_config_edit(session, config, "pattern", mutate, form_fields=PATTERN_FIELDS)


def _check_credits(form_data) -> int | None:
    credits = form_data.get("credits")
    if isinstance(credits, bool) or not isinstance(credits, int) or credits <= 0:
        return None
    return credits


def _build_pattern(form_data, meetings) -> ClassPattern:
    """Build a ClassPattern; the library validates the rest of its shape."""
    try:
        return ClassPattern(
            credits=form_data["credits"],
            meetings=meetings,
            start_time=form_data.get("start_time") or None,
            disabled=not form_data.get("enabled", True),
        )
    except ValidationError as error:
        items = translate_validation_error(error, form_fields=("credits", "start_time"))
        raise ControllerError(items) from error


def _day_set(meetings) -> set[str]:
    return {str(getattr(m.day, "value", m.day)) for m in meetings}


def _pattern_row(index: int, pattern) -> dict:
    meetings = [meeting_row(index, i, m) for i, m in enumerate(pattern.meetings)]
    return {
        "index": index,
        "credits": pattern.credits,
        "enabled": not getattr(pattern, "disabled", False),
        "start_time": getattr(pattern, "start_time", None) or "",
        "meetings": meetings,
        "summary": ", ".join(meeting_summary(m) for m in pattern.meetings),
    }


# ---------------------------------------------------------------------- #
#  Reads
# ---------------------------------------------------------------------- #
def describe_patterns(request) -> dict:
    """Everything the Class Patterns page needs, as plain data (no models).

    Returns {"has_config": False} when nothing is loaded so the view can show
    the empty state (Section 19).
    """
    config = get_session(request).config
    if config is None:
        return {"has_config": False}
    return {
        "has_config": True,
        "patterns": [_pattern_row(i, p) for i, p in enumerate(_patterns(config))],
    }


def get_pattern(request, pattern_index: int) -> dict:
    """One pattern as plain data, for the edit and delete pages."""
    config = _require_config(get_session(request))
    pattern = _check_index(config, pattern_index)
    return _pattern_row(pattern_index, pattern)


# ---------------------------------------------------------------------- #
#  Writes -- each returns a list of non-blocking warning strings
# ---------------------------------------------------------------------- #
def add_pattern(request, form_data) -> list[str]:
    """Append a new pattern with one starting meeting."""
    session = get_session(request)
    config = _require_config(session)

    problems: list[FieldError] = []
    if _check_credits(form_data) is None:
        problems.append(FieldError("credits", CREDITS_MESSAGE))
    meeting = None
    try:
        meeting = build_meeting(form_data, prefix="meeting_")
    except ControllerError as error:
        problems.extend(error.errors)
    if problems:
        raise ControllerError(problems)

    pattern = _build_pattern(form_data, [meeting])

    def mutate(draft):
        _patterns(draft).append(pattern)

    _apply(session, config, mutate)
    return _fit_warnings_for(config, pattern)


def update_pattern(request, pattern_index: int, form_data) -> list[str]:
    """Change the pattern's credits, start time and enabled state. Its
    meetings are kept as they are."""
    session = get_session(request)
    config = _require_config(session)
    existing = _check_index(config, pattern_index)
    if _check_credits(form_data) is None:
        raise ControllerError([FieldError("credits", CREDITS_MESSAGE)])

    updated = _build_pattern(form_data, copy_meetings(existing))

    def mutate(draft):
        _patterns(draft)[pattern_index] = updated

    _apply(session, config, mutate)
    return _fit_warnings_for(config, updated)


def delete_pattern(request, pattern_index: int) -> list[str]:
    """Remove the pattern at pattern_index (the page asks for confirmation
    first). The library rejects the change if it would leave the configuration
    invalid, e.g. a course left with no usable pattern."""
    session = get_session(request)
    config = _require_config(session)
    _check_index(config, pattern_index)

    def mutate(draft):
        del _patterns(draft)[pattern_index]

    _apply(session, config, mutate)
    return []


def _fit_warnings_for(config, pattern) -> list[str]:
    """Time-block fit warnings for every weekday the pattern has a meeting on."""
    if getattr(pattern, "disabled", False):
        return []
    warnings: list[str] = []
    for day in sorted(_day_set(pattern.meetings)):
        warnings += [w for w in _fit_warnings(config, day) if w not in warnings]
    return warnings
