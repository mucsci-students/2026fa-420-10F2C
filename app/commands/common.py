"""Shared helpers used by command-domain modules."""

from __future__ import annotations

import re
from typing import Callable

from app.crud import apply_edit


VALID_DAYS = ("MON", "TUE", "WED", "THU", "FRI")
VALID_OPTIMIZER_FLAGS = {
    "faculty_course", "faculty_room", "faculty_lab",
    "same_room", "same_lab", "pack_rooms", "pack_labs",
}
TIME_RANGE_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$")
DAY_LABELS = {"MON": "Mon", "TUE": "Tue", "WED": "Wed", "THU": "Thu", "FRI": "Fri"}


def apply_session_edit(session, config, area, mutate_fn: Callable[[object], None]):
    """Apply an atomic config edit and mark the active session dirty."""
    apply_edit(config, area, mutate_fn)
    session.dirty = True


def field_value(obj, key):
    """Read a field from either a mapping or a Pydantic model."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def prompt_supplied_features(label):
    """Collect the features supplied by a room or lab."""
    raw = input(f"  Features this {label} provides (comma-separated, blank for none): ").strip()
    return sorted({part.strip() for part in raw.split(",") if part.strip()}) if raw else []


def prompt_resource_availability(label):
    """Collect optional weekday availability windows for a room or lab."""
    restrict = input(
        f"  Restrict this {label}'s availability? (y/n, default n = available any time): "
    ).strip().lower() in ("y", "yes")
    if not restrict:
        return None

    print(f"  Enter availability for this {label}, one entry per weekday: MON, TUE, WED, THU, FRI.")
    print("  Leave blank if unavailable that day, or enter a range like 09:00-17:00")
    times = {}
    for day in VALID_DAYS:
        raw = input(f"  {day}: ").strip()
        if not raw:
            continue
        if not TIME_RANGE_RE.match(raw):
            print(f"  '{raw}' isn't a valid HH:MM-HH:MM range -- treating {day} as unavailable.")
            continue
        start, end = raw.split("-")
        times[day] = [{"start": start, "end": end}]
    return times or None