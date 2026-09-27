"""
Controller for Labs (Section 7, Labs row).

Same shape as gui/controllers/faculty.py: build a LabConfig from
validated form data, apply_edit() it via app.crud, and check_no_references
against courses that list this lab before deleting (Section 12).
"""

from gui.session_store import get_session


def add_lab(request, form_data):
    """TODO: build a LabConfig from validated form_data and apply_edit()
    it onto the session's config."""
    raise NotImplementedError


def update_lab(request, lab_name, form_data):
    """TODO: same as add_lab, but replaces an existing record."""
    raise NotImplementedError


def delete_lab(request, lab_name):
    """TODO (Section 12): check_no_references() against courses that list
    this lab before deleting."""
    raise NotImplementedError
