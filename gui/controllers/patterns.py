"""
Controller for Class Patterns (Section 7, Class patterns row): credits,
enabled state, start times. Identified by list index (no name/id field on
a pattern -- see app/commands/patterns.py's comment on this). Same
apply_edit() shape as gui/controllers/faculty.py.
"""

from gui.session_store import get_session


def add_pattern(request, form_data):
    """TODO: build a ClassPattern from validated form_data (must include
    at least one meeting) and apply_edit() it onto the session's config."""
    raise NotImplementedError


def update_pattern(request, pattern_index, form_data):
    """TODO: same as add_pattern, but replaces the pattern at pattern_index."""
    raise NotImplementedError


def delete_pattern(request, pattern_index):
    """TODO: remove the pattern at pattern_index."""
    raise NotImplementedError
