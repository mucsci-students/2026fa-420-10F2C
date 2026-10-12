"""
Small constants shared by GUI forms, controllers, and views.

Kept free of Django and scheduler imports so any layer can use them.
"""

# Weekday codes are the scheduler library's own ("MON".."FRI"); the dict keeps
# them in display order (Python dicts preserve insertion order).
DAY_NAMES = {
    "MON": "Monday",
    "TUE": "Tuesday",
    "WED": "Wednesday",
    "THU": "Thursday",
    "FRI": "Friday",
}

# Schedule Viewer filter (Sections 16.1-16.2): ?view=courses (default), rooms, or faculty.
VIEW_COURSES = "courses"
VIEW_ROOMS = "rooms"
VIEW_FACULTY = "faculty"

# Filter option values mapped to their menu labels, in display order.
VIEW_OPTIONS = {VIEW_COURSES: "Courses", VIEW_ROOMS: "Rooms", VIEW_FACULTY: "Faculty"}

# Block text for a meeting that has no room or lab (e.g. an online section).
NO_LOCATION_LABEL = "No room assigned"

# Block text for a meeting whose course has no faculty member assigned.
NO_FACULTY_LABEL = "No faculty assigned"

# Plain-language descriptions of the scheduler library's optimizer flags
# (user story 53: hovering over or focusing an option such as "pack_rooms"
# shows what it does). Worded from the library's own OptimizerFlags
# docstrings in scheduler/config.py. Shown as a tooltip and as a short line
# under each checkbox in Global Settings and the Schedule Generator.
OPTIMIZER_FLAG_HELP = {
    "faculty_course": "Try to give each faculty member the courses they prefer, using their course preferences.",
    "faculty_room": "Try to put each faculty member in the rooms they prefer, using their room preferences.",
    "faculty_lab": "Try to put each faculty member in the labs they prefer, using their lab preferences.",
    "same_room": "Try to keep courses taught by the same faculty member in the same room.",
    "same_lab": "Try to keep lab courses taught by the same faculty member in the same lab.",
    "pack_rooms": "Try to use rooms back to back: when meetings are next to each other in time, prefer putting different courses in the same room.",
    "pack_labs": "Try to use labs back to back: prefer putting different courses in the same lab at neighboring lab times.",
}

OPTIMIZER_FLAGS_INTRO = (
    "Optimizer flags are preferences, not hard rules: a schedule is still valid without them. "
    "Each one you turn on can make generation take longer. Hover over or focus a flag to see what it does."
)
