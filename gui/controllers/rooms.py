"""
Controller for Rooms (Section 7, Rooms row).

Same shape as gui/controllers/faculty.py: build a RoomConfig from
validated form data, apply_edit() it via app.crud, and check_no_references
against courses that list this room before deleting (Section 12).
"""

from gui.session_store import get_session


def add_room(request, form_data):
    """TODO: build a RoomConfig from validated form_data and apply_edit()
    it onto the session's config."""
    raise NotImplementedError


def update_room(request, room_name, form_data):
    """TODO: same as add_room, but replaces an existing record."""
    raise NotImplementedError


def delete_room(request, room_name):
    """TODO (Section 12): check_no_references() against courses that list
    this room before deleting."""
    raise NotImplementedError
