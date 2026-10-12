"""
Controller for Time Slots (Section 7, Time slots row): weekday time blocks
and the global timing options (max_time_gap, min_time_overlap).

A time block means: starting at `start`, a class may begin every `spacing`
minutes, and its meeting must finish by `end` (the library's generator
requires start + duration <= end). Blocks are identified by (day, index),
same as app/commands/timeslots.py.

What the scheduler library enforces (so we do NOT reimplement it): end after
start, 24-hour HH:MM format, spacing > 0, and at least one block per weekday.
What it does NOT enforce, and this controller therefore does (verified
against the library, see the Sprint 2 planning notes):
  * overlapping blocks on one day (touching blocks are fine),
  * keeping a day's blocks sorted by time,
  * guarding stale indexes from an out-of-date page.

Every edit goes through app.crud.apply_edit() via apply_session_edit(), so
the complete CombinedConfig is re-validated and a failed edit leaves the
previous valid configuration untouched (Sections 10 and 11).

Functions raise ControllerError for anything the user can fix; they never
touch HttpResponse or templates (Section 20).
"""

from __future__ import annotations

from scheduler.config import TimeBlock, ValidationError

from app.commands.common import VALID_DAYS
from app.commands.timeslots import blocks_overlap
from gui.constants import DAY_NAMES
from gui.controllers.common import apply_config_edit, require_config
from gui.controllers.errors import ControllerError, translate_validation_error
from gui.session_store import get_session

TIME_FIELDS = ("start", "end", "spacing")
OPTION_FIELDS = ("max_time_gap", "min_time_overlap")


# ---------------------------------------------------------------------- #
#  Helpers
# ---------------------------------------------------------------------- #
def _minutes(hhmm: str) -> int:
    """'HH:MM' -> minutes since midnight."""
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _sort_key(block):
    return (block.start, block.end)


def _require_config(session):
    return require_config(session, "editing time slots")


def _check_day(day: str) -> str:
    if day not in VALID_DAYS:
        raise ControllerError(f"'{day}' is not a valid day. Choose one of: {', '.join(VALID_DAYS)}.")
    return day


def _check_index(blocks, day: str, index: int) -> None:
    if not 0 <= index < len(blocks):
        raise ControllerError(
            f"That time block no longer exists on {day}. Refresh the page and try again."
        )


def _build_block(form_data) -> TimeBlock:
    """Build a TimeBlock; the library validates format, order, and spacing."""
    try:
        return TimeBlock(
            start=form_data.get("start"),
            end=form_data.get("end"),
            spacing=form_data.get("spacing"),
        )
    except ValidationError as error:
        raise ControllerError(translate_validation_error(error, form_fields=TIME_FIELDS)) from error


def _check_overlap(blocks, new_block, ignore_index: int | None = None) -> None:
    """The library accepts overlapping blocks (and would generate duplicate
    slots from them), so reject them here. Wording matches user story 19/20."""
    for position, existing in enumerate(blocks):
        if position != ignore_index and blocks_overlap(existing, new_block):
            raise ControllerError(
                f"Time Conflict: overlaps existing block {existing.start}-{existing.end}"
            )


def _apply(session, config, mutate) -> None:
    apply_config_edit(session, config, "timeslot", mutate, form_fields=TIME_FIELDS + OPTION_FIELDS)


def _day_of(meeting) -> str:
    value = getattr(meeting, "day", None)
    return str(getattr(value, "value", value))


def _fit_warnings(config, day: str) -> list[str]:
    """Non-blocking notice after an edit that can remove capacity.

    The library accepts a time-slot change even when an enabled class pattern
    has a meeting on `day` longer than every remaining block -- the schedule
    just becomes infeasible at generation time. Only clear-cut cases are
    reported (duration longer than the longest block); meetings with a fixed
    start_time are skipped because how the library treats them is unverified.
    """
    blocks = config.time_slot_config.times.get(day, [])
    longest = max((_minutes(b.end) - _minutes(b.start) for b in blocks), default=0)
    too_long: set[int] = set()
    for pattern in config.time_slot_config.classes:
        if getattr(pattern, "disabled", False):
            continue
        for meeting in pattern.meetings:
            if _day_of(meeting) != day or getattr(meeting, "start_time", None):
                continue
            duration = getattr(meeting, "duration", None)
            if duration is not None and duration > longest:
                too_long.add(duration)
    if not too_long:
        return []
    durations = ", ".join(str(value) for value in sorted(too_long))
    return [
        f"{day}: enabled class patterns have meetings of {durations} minutes that do not fit "
        f"in any {day} time block. The change is valid, but schedules that need those "
        f"meetings may not be feasible."
    ]


def _axis_bounds(blocks) -> tuple[int, int]:
    """Whole-hour start/end (in minutes) for the overview grid."""
    if not blocks:
        return 8 * 60, 17 * 60
    low = min(_minutes(b.start) for b in blocks) // 60 * 60
    high = -(-max(_minutes(b.end) for b in blocks) // 60) * 60
    return low, max(high, low + 60)


# ---------------------------------------------------------------------- #
#  Reads
# ---------------------------------------------------------------------- #
def describe_timeslots(request) -> dict:
    """Everything the Time Slots page needs, as plain data (no models).

    Returns {"has_config": False} when nothing is loaded so the view can
    show the empty state (Section 19). Numbers used for CSS positions are
    pre-formatted strings so template localization cannot change them.
    """
    session = get_session(request)
    config = session.config
    if config is None:
        return {"has_config": False}

    settings = config.time_slot_config
    all_blocks = [block for day in VALID_DAYS for block in settings.times.get(day, [])]
    axis_start, axis_end = _axis_bounds(all_blocks)
    span = axis_end - axis_start

    days = []
    for day in VALID_DAYS:
        blocks = settings.times.get(day, [])
        rows = []
        for index, block in enumerate(blocks):
            start, end = _minutes(block.start), _minutes(block.end)
            tick = block.spacing / (end - start) * 100 if end > start else 0
            rows.append(
                {
                    "index": index,
                    "start": block.start,
                    "end": block.end,
                    "spacing": block.spacing,
                    "top": f"{(start - axis_start) / span * 100:.2f}",
                    "height": f"{(end - start) / span * 100:.2f}",
                    # Tick marks every `spacing` minutes; skip when they'd be
                    # a solid smear (<1.5%) or the spacing spans the block.
                    "tick": f"{tick:.3f}" if 1.5 <= tick < 100 else "",
                }
            )
        days.append(
            {
                "day": day,
                "name": DAY_NAMES[day],
                "blocks": rows,
                "only_block": len(rows) == 1,
            }
        )

    hours = [
        {"label": f"{minute // 60:02d}:00", "top": f"{(minute - axis_start) / span * 100:.2f}"}
        for minute in range(axis_start, axis_end + 1, 60)
    ]
    return {
        "has_config": True,
        "days": days,
        "hours": hours,
        "hour_pct": f"{60 / span * 100:.3f}",
        "max_time_gap": settings.max_time_gap,
        "min_time_overlap": settings.min_time_overlap,
    }


def get_timeslot(request, day, index) -> dict:
    """One block as plain data, for the edit and delete pages."""
    config = _require_config(get_session(request))
    day = _check_day(day)
    blocks = config.time_slot_config.times.get(day, [])
    _check_index(blocks, day, index)
    block = blocks[index]
    return {
        "day": day,
        "index": index,
        "start": block.start,
        "end": block.end,
        "spacing": block.spacing,
        "is_only_block": len(blocks) == 1,
    }


# ---------------------------------------------------------------------- #
#  Writes -- each returns a list of non-blocking warning strings
# ---------------------------------------------------------------------- #
def add_timeslot(request, day, form_data) -> list[str]:
    """Add a block to `day`, keeping the day's blocks in time order.

    form_data needs "start" and "end" ("HH:MM") and "spacing" (int minutes).
    Adding capacity cannot make anything newly unschedulable, so no warnings.
    """
    session = get_session(request)
    config = _require_config(session)
    day = _check_day(day)
    block = _build_block(form_data)
    _check_overlap(config.time_slot_config.times.get(day, []), block)

    def mutate(draft):
        blocks = draft.time_slot_config.times.setdefault(day, [])
        blocks.append(block)
        blocks.sort(key=_sort_key)

    _apply(session, config, mutate)
    return []


def update_timeslot(request, day, index, form_data) -> list[str]:
    """Replace the block at (day, index) with the values in form_data."""
    session = get_session(request)
    config = _require_config(session)
    day = _check_day(day)
    blocks = config.time_slot_config.times.get(day, [])
    _check_index(blocks, day, index)
    block = _build_block(form_data)
    _check_overlap(blocks, block, ignore_index=index)

    def mutate(draft):
        draft_blocks = draft.time_slot_config.times[day]
        draft_blocks[index] = block
        draft_blocks.sort(key=_sort_key)

    _apply(session, config, mutate)
    return _fit_warnings(config, day)


def delete_timeslot(request, day, index) -> list[str]:
    """Remove the block at (day, index). A weekday must keep at least one
    block (the library enforces it too; we check first for a clear message)."""
    session = get_session(request)
    config = _require_config(session)
    day = _check_day(day)
    blocks = config.time_slot_config.times.get(day, [])
    _check_index(blocks, day, index)
    if len(blocks) == 1:
        raise ControllerError(
            f"Can't delete the only time block on {day} -- every weekday needs at least one."
        )

    def mutate(draft):
        del draft.time_slot_config.times[day][index]

    _apply(session, config, mutate)
    return _fit_warnings(config, day)


def update_timing_options(request, form_data) -> None:
    """Update the global max_time_gap / min_time_overlap (minutes).

    Only keys present (and not None) in form_data are changed.
    """
    session = get_session(request)
    config = _require_config(session)
    values = {name: form_data[name] for name in OPTION_FIELDS if form_data.get(name) is not None}

    def mutate(draft):
        for name, value in values.items():
            setattr(draft.time_slot_config, name, value)

    _apply(session, config, mutate)
