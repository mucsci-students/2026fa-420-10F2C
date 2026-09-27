"""
Controller for Faculty (Section 7, Faculty row).

Get this browser's Session via gui.session_store.get_session(request),
build a FacultyConfig from validated form data, and call
app.crud.apply_edit(...) -- exactly what app/commands/faculty.py already
does for the CLI, just fed from a Django Form instead of input(). Delete
must call app.crud.check_no_references(...) first (Section 12) against
courses that list this faculty member, and surface any ReferenceError_ to
the user instead of silently failing.

Worked example -- copy this file's shape for the other entity areas.
"""

from gui.session_store import get_session


def add_faculty(request, form_data):
    """TODO: build a FacultyConfig from validated form_data and
    apply_edit() it onto the session's config."""
    raise NotImplementedError


def update_faculty(request, faculty_name, form_data):
    """TODO: same as add_faculty, but replaces an existing record."""
    raise NotImplementedError


def delete_faculty(request, faculty_name):
    """TODO (Section 12): check_no_references() against courses that list
    this faculty member before deleting; surface blocking references to
    the user."""
    raise NotImplementedError
