"""
Controller for Meetings (Section 7, Meetings row): day, duration, lab
designation, delivery mode, optional start time. A meeting always belongs
to a class pattern, identified by (pattern_index, meeting_index) -- same
shape as app/commands/meetings.py.
"""

from gui.session_store import get_session


def add_meeting(request, pattern_index, form_data):
    """TODO: build a Meeting from validated form_data and append it to
    the pattern at pattern_index."""
    raise NotImplementedError


def update_meeting(request, pattern_index, meeting_index, form_data):
    """TODO: same as add_meeting, but replaces the meeting at
    (pattern_index, meeting_index)."""
    raise NotImplementedError


def delete_meeting(request, pattern_index, meeting_index):
    """TODO: remove the meeting at (pattern_index, meeting_index). A
    pattern needs at least one meeting -- block the delete if it's the
    last one on that pattern."""
    raise NotImplementedError
