"""
Controller for Courses (Section 7, Courses row).

Courses are identified by list index, not name (repeated course_id values
are legal -- they create sections; see app/commands/courses.py's own
comment on this). Same apply_edit()/check_no_references() shape as
gui/controllers/faculty.py.
"""

from gui.session_store import get_session


def add_course(request, form_data):
    """TODO: build a CourseConfig from validated form_data and
    apply_edit() it onto the session's config."""
    raise NotImplementedError


def update_course(request, course_index, form_data):
    """TODO: same as add_course, but replaces the record at course_index."""
    raise NotImplementedError


def delete_course(request, course_index):
    """TODO (Section 12): only the last section of a course_id needs a
    reference check (conflicts / faculty course_preferences point at the
    id, not a specific section) -- see app/commands/courses.py's
    delete_course for the exact logic to reuse."""
    raise NotImplementedError
