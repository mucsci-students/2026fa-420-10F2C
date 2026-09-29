"""
Controller for Time Slots (Section 7, Time slots row): weekday time
blocks and the global timing options (max_time_gap, min_time_overlap).
Same apply_edit() shape as gui/controllers/faculty.py; identified by
(day, index) rather than a name, same as app/commands/timeslots.py.
"""

from gui.session_store import get_session


def add_timeslot(request, day, form_data):
    """TODO: build a TimeBlock from validated form_data, check it doesn't
    overlap an existing block on that day, and apply_edit() it in."""
    raise NotImplementedError


def update_timeslot(request, day, index, form_data):
    """TODO: same as add_timeslot, but replaces the block at (day, index)."""
    raise NotImplementedError


def delete_timeslot(request, day, index):
    """TODO: remove the block at (day, index). A day needs at least one
    time block -- block the delete if it's the last one on that day."""
    raise NotImplementedError


def update_timing_options(request, form_data):
    """TODO: update TimeSlotConfig.max_time_gap / min_time_overlap
    (Section 7's "global timing options")."""
    raise NotImplementedError
