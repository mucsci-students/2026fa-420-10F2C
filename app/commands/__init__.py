"""Public command API assembled from focused command-domain modules.

The shell continues to import ``app.commands`` exactly as it did when commands
lived in one file. The small wrappers below also preserve the test seam that
lets callers replace prompt helpers or scheduler model classes on this module.
"""

from . import courses, faculty, labs, meetings, patterns, rooms, schedules, settings, timeslots
from .common import DAY_LABELS as _DAY_LABELS
from .common import TIME_RANGE_RE as _TIME_RANGE_RE
from .common import VALID_DAYS as _VALID_DAYS
from .common import VALID_OPTIMIZER_FLAGS as _VALID_OPTIMIZER_FLAGS
from .common import apply_session_edit as _apply_edit
from .common import field_value as _field
from .configuration import load_config, new_config, print_config, save_config, validate_config

FacultyConfig = faculty.FacultyConfig
CourseConfig = courses.CourseConfig
LabConfig = labs.LabConfig
RoomConfig = rooms.RoomConfig
TimeBlock = timeslots.TimeBlock
ClassPattern = patterns.ClassPattern
Meeting = meetings.Meeting
OptimizerFlags = settings.OptimizerFlags
ValidationError = meetings.ValidationError

_prompt_faculty_times = faculty.prompt_faculty_times
_prompt_weighted_preferences = faculty.prompt_weighted_preferences
_prompt_mandatory_days = faculty.prompt_mandatory_days
_prompt_maximum_days = faculty.prompt_maximum_days
_prompt_faculty_fields = faculty.prompt_faculty_fields
_format_faculty = faculty.format_faculty

_enabled_pattern_credits = courses.enabled_pattern_credits
_course_display_name = courses.course_display_name
_format_course = courses.format_course
_list_courses = courses.list_courses
_prompt_course_index = courses.prompt_course_index
_prompt_name_list = courses.prompt_name_list
_prompt_feature_set = courses.prompt_feature_set
_prompt_positive_int = courses.prompt_positive_int
_prompt_course_fields = courses.prompt_course_fields

_prompt_lab_fields = labs.prompt_lab_fields
_format_lab = labs.format_lab
_prompt_supplied_features = labs.prompt_supplied_features
_prompt_resource_availability = labs.prompt_resource_availability

_prompt_room_fields = rooms.prompt_room_fields
_format_room = rooms.format_room

_prompt_time_block = timeslots.prompt_time_block
_blocks_overlap = timeslots.blocks_overlap

_prompt_meeting = meetings.prompt_meeting
_list_meetings = meetings.list_meetings
_prompt_meeting_index = meetings.prompt_meeting_index
_choose_pattern_and_meeting = meetings.choose_pattern_and_meeting

_prompt_pattern_fields = patterns.prompt_pattern_fields
_format_pattern = patterns.format_pattern
_list_patterns = patterns.list_patterns
_prompt_pattern_index = patterns.prompt_pattern_index


def _sync_faculty_dependencies():
    faculty.FacultyConfig = FacultyConfig


def _sync_course_dependencies():
    courses.CourseConfig = CourseConfig
    courses.prompt_course_fields = _prompt_course_fields


def _sync_lab_dependencies():
    labs.LabConfig = LabConfig
    labs.prompt_lab_fields = _prompt_lab_fields


def _sync_room_dependencies():
    rooms.RoomConfig = RoomConfig
    rooms.prompt_room_fields = _prompt_room_fields


def _sync_timeslot_dependencies():
    timeslots.TimeBlock = TimeBlock


def _sync_meeting_dependencies():
    meetings.Meeting = Meeting


def _sync_pattern_dependencies():
    patterns.ClassPattern = ClassPattern
    meetings.Meeting = Meeting


def add_faculty(session):
    _sync_faculty_dependencies()
    return faculty.add_faculty(session)


def modify_faculty(session):
    _sync_faculty_dependencies()
    return faculty.modify_faculty(session)


def delete_faculty(session):
    _sync_faculty_dependencies()
    return faculty.delete_faculty(session)


def view_faculty(session):
    return faculty.view_faculty(session)


def add_course(session):
    _sync_course_dependencies()
    return courses.add_course(session)


def modify_course(session):
    _sync_course_dependencies()
    return courses.modify_course(session)


def delete_course(session):
    return courses.delete_course(session)


def view_course(session):
    return courses.view_course(session)


def add_lab(session):
    _sync_lab_dependencies()
    return labs.add_lab(session)


def modify_lab(session):
    _sync_lab_dependencies()
    return labs.modify_lab(session)


def delete_lab(session):
    return labs.delete_lab(session)


def view_lab(session):
    return labs.view_lab(session)


def add_room(session):
    _sync_room_dependencies()
    return rooms.add_room(session)


def modify_room(session):
    _sync_room_dependencies()
    return rooms.modify_room(session)


def delete_room(session):
    return rooms.delete_room(session)


def view_room(session):
    return rooms.view_room(session)


def add_timeslot(session):
    _sync_timeslot_dependencies()
    return timeslots.add_timeslot(session)


def modify_timeslot(session):
    _sync_timeslot_dependencies()
    return timeslots.modify_timeslot(session)


def delete_timeslot(session):
    return timeslots.delete_timeslot(session)


def modify_timing_options(session):
    return timeslots.modify_timing_options(session)


def add_pattern(session):
    _sync_pattern_dependencies()
    return patterns.add_pattern(session)


def modify_pattern(session):
    _sync_pattern_dependencies()
    return patterns.modify_pattern(session)


def delete_pattern(session):
    return patterns.delete_pattern(session)


def add_meeting(session):
    _sync_meeting_dependencies()
    return meetings.add_meeting(session)


def modify_meeting(session):
    _sync_meeting_dependencies()
    return meetings.modify_meeting(session)


def delete_meeting(session):
    return meetings.delete_meeting(session)


def set_generation_limit(session, value):
    return settings.set_generation_limit(session, value)


def reset_generation_limit(session):
    return settings.reset_generation_limit(session)


def enable_optimizer_flag(session, flag):
    settings.OptimizerFlags = OptimizerFlags
    return settings.enable_optimizer_flag(session, flag)


def disable_optimizer_flag(session, flag):
    return settings.disable_optimizer_flag(session, flag)


def generate_schedule(session, limit_override=None):
    return schedules.generate_schedule(session, limit_override)


def schedule_summary(session):
    return schedules.schedule_summary(session)


def view_schedule(session, index):
    return schedules.view_schedule(session, index)


def clear_schedules(session):
    return schedules.clear_schedules(session)


def export_schedule(session, fmt, path, index=None, overwrite=False):
    return schedules.export_schedule(session, fmt, path, index, overwrite)


__all__ = [
    "add_course", "add_faculty", "add_lab", "add_meeting", "add_pattern",
    "add_room", "add_timeslot", "clear_schedules", "delete_course",
    "delete_faculty", "delete_lab", "delete_meeting", "delete_pattern",
    "delete_room", "delete_timeslot", "disable_optimizer_flag",
    "enable_optimizer_flag", "export_schedule", "generate_schedule",
    "load_config", "modify_course", "modify_faculty", "modify_lab",
    "modify_meeting", "modify_pattern", "modify_room", "modify_timeslot",
    "modify_timing_options", "new_config", "print_config",
    "reset_generation_limit", "save_config", "schedule_summary",
    "set_generation_limit", "validate_config", "view_course", "view_faculty",
    "view_lab", "view_room", "view_schedule",
]