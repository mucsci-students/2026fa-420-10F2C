"""Shared helpers used by command-domain modules."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from app.crud import apply_edit

VALID_DAYS = ("MON", "TUE", "WED", "THU", "FRI")
VALID_OPTIMIZER_FLAGS = {
    "faculty_course",
    "faculty_room",
    "faculty_lab",
    "same_room",
    "same_lab",
    "pack_rooms",
    "pack_labs",
}
TIME_RANGE_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$")
DAY_LABELS = {"MON": "Mon", "TUE": "Tue", "WED": "Wed", "THU": "Thu", "FRI": "Fri"}


def apply_session_edit(
    session, config, area, mutate_fn: Callable[[Any], None], label=None
):
    """Apply an atomic config edit, mark the active session dirty, and remember how to undo it.

    Memento pattern (app/memento.py): the history, as caretaker, has the configuration save
    mementos BEFORE the edit; they are only kept if the edit succeeds, and only for the parts
    of the configuration that really changed, so a rejected edit leaves nothing to undo.
    `label` names the change for the Undo button; without one the change is described in
    words (or a generic "Edit <area>").

    An edit that changed nothing (a form submitted with no change) adds nothing to the history
    and does not mark the configuration as having unsaved changes.
    """
    history = getattr(session, "history", None)
    before = history.capture(config) if history is not None else None
    dirty_before = session.dirty
    apply_edit(config, area, mutate_fn)
    changed = True
    if history is not None:
        changed = (
            history.record(label, before, dirty_before, after=config, area=area)
            is not None
        )
    if changed:
        session.dirty = True


def field_value(obj, key):
    """Read a field from either a mapping or a Pydantic model."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def prompt_supplied_features(label):
    """Collect the features supplied by a room or lab."""
    raw = input(
        f"  Features this {label} provides (comma-separated, blank for none): "
    ).strip()
    return (
        sorted({part.strip() for part in raw.split(",") if part.strip()}) if raw else []
    )


def prompt_resource_availability(label):
    """Collect optional weekday availability windows for a room or lab."""
    restrict = input(
        f"  Restrict this {label}'s availability? (y/n, default n = available any time): "
    ).strip().lower() in ("y", "yes")
    if not restrict:
        return None

    print(
        f"  Enter availability for this {label}, one entry per weekday: MON, TUE, WED, THU, FRI."
    )
    print("  Leave blank if unavailable that day, or enter a range like 09:00-17:00")
    times = {}
    for day in VALID_DAYS:
        raw = input(f"  {day}: ").strip()
        if not raw:
            continue
        if not TIME_RANGE_RE.match(raw):
            print(
                f"  '{raw}' isn't a valid HH:MM-HH:MM range -- treating {day} as unavailable."
            )
            continue
        start, end = raw.split("-")
        times[day] = [{"start": start, "end": end}]
    return times or None
