#!/usr/bin/env bash
# Run from the repo root. Splits gui/controllers/crud_controller.py into
# one file per entity area, mirroring app/commands/'s existing split
# (rooms.py, labs.py, courses.py, faculty.py, timeslots.py, patterns.py,
# meetings.py, settings.py) so the controller layer never becomes a
# second 2,000-line monolith.
set -euo pipefail

if [ ! -d gui/controllers ]; then
  echo "Run this from the repo root (gui/controllers/ must exist here)." >&2
  exit 1
fi

SHARED_HEADER='"""
Controller for %s (Section 7: %s).

Get this browser'"'"'s Session via gui.session_store.get_session(request),
build the library'"'"'s real Pydantic model from validated form data, and
call app.crud.apply_edit(...) -- exactly what app/commands/%s.py already
does for the CLI, just fed from a Django Form instead of input(). Delete
functions must call app.crud.check_no_references(...) first (Section 12)
and surface any ReferenceError_ to the user instead of silently failing.
"""

from gui.session_store import get_session
'

cat > gui/controllers/faculty.py << 'EOF'
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
EOF

cat > gui/controllers/rooms.py << 'EOF'
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
EOF

cat > gui/controllers/labs.py << 'EOF'
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
EOF

cat > gui/controllers/courses.py << 'EOF'
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
EOF

cat > gui/controllers/timeslots.py << 'EOF'
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
EOF

cat > gui/controllers/patterns.py << 'EOF'
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
EOF

cat > gui/controllers/meetings.py << 'EOF'
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
EOF

cat > gui/controllers/settings.py << 'EOF'
"""
Controller for Global Settings (Section 7, Global settings row):
generation limit and optimizer flags. These are the SAVED configuration
values -- distinct from the Schedule Generator's one-run-only overrides,
which live in gui/controllers/schedule_controller.py (Section 14).
"""

from gui.session_store import get_session


def set_generation_limit(request, value):
    """TODO: validate value is a positive integer and apply_edit() it
    onto config.limit."""
    raise NotImplementedError


def enable_optimizer_flag(request, flag):
    """TODO: validate flag is a supported OptimizerFlags value and
    apply_edit() it onto config.optimizer_flags."""
    raise NotImplementedError


def disable_optimizer_flag(request, flag):
    """TODO: remove flag from config.optimizer_flags via apply_edit()."""
    raise NotImplementedError
EOF

rm -f gui/controllers/crud_controller.py

echo "crud_controller.py split into per-entity controller files."