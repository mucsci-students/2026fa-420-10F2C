# Faculty records are plain dicts (matches config["config"]["faculty"] in
# the JSON exactly). The Faculty class below is NOT meant to be
# instantiated -- it's just a namespace of @staticmethods, so calls look
# like Faculty.facCheck(faculty_list, name), matching the calling style
# already used elsewhere on the team. Every method's first argument is
# the plain list of faculty dicts, passed in like a normal argument.
#
# Two differences from a similar model you may have seen:
#   - facCheck/removeFaculty use an EXACT name match, not a substring
#     match. A substring match would block adding "Bob" just because
#     "Bobby" already exists, or delete the wrong person by accident.
#   - Every add/modify goes through validate_faculty(), which enforces
#     the real scheduler rules (days must be MON-FRI, preference weights
#     0-10, unique_course_limit >= 1, min <= max credits, "HH:MM-HH:MM"
#     time format). Cross-record checks (does this course/room/lab
#     actually exist) are deliberately NOT done here -- that's checked
#     later when the full config is loaded by the scheduler package,
#     since a preference is allowed to reference a course that doesn't
#     exist yet.

import re

VALID_DAYS = ["MON", "TUE", "WED", "THU", "FRI"]
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")  # matches "HH:MM" in 24h format


class FacultyValidationError(Exception):
    """Raised when a faculty record fails validation."""


def _valid_time_range(t):
    """True if t looks like "09:00-17:00" with start before end."""
    if not isinstance(t, str) or "-" not in t:
        return False
    start, _, end = t.partition("-")
    return bool(TIME_RE.match(start) and TIME_RE.match(end)) and start < end


def validate_faculty(record):
    """Checks one faculty dict against the rules above. Raises
    FacultyValidationError on the first problem found; otherwise returns
    the record unchanged."""

    if not record.get("name") or not str(record["name"]).strip():
        raise FacultyValidationError("Faculty name must not be blank")

    max_c = record.get("maximum_credits")
    min_c = record.get("minimum_credits")
    if not isinstance(max_c, int) or max_c < 0:
        raise FacultyValidationError("maximum_credits must be a non-negative integer")
    if not isinstance(min_c, int) or min_c < 0:
        raise FacultyValidationError("minimum_credits must be a non-negative integer")
    if min_c > max_c:
        raise FacultyValidationError(
            f"minimum_credits ({min_c}) cannot be greater than maximum_credits ({max_c})"
        )

    limit = record.get("unique_course_limit")
    if not isinstance(limit, int) or limit < 1:
        raise FacultyValidationError("unique_course_limit must be a positive integer (>= 1)")

    # times: {"MON": ["09:00-17:00"], ...} -- a day left out means unavailable
    times = record.get("times") or {}
    for day, ranges in times.items():
        if day not in VALID_DAYS:
            raise FacultyValidationError(f"'{day}' is not a valid day (must be one of {VALID_DAYS})")
        for r in ranges:
            if not _valid_time_range(r):
                raise FacultyValidationError(f"'{r}' is not a valid time range for {day} (expected HH:MM-HH:MM)")

    # course/room/lab preferences: {"CMSC 420": 5, ...}, weight 0-10
    for pref_name in ("course_preferences", "room_preferences", "lab_preferences"):
        prefs = record.get(pref_name) or {}
        for key, weight in prefs.items():
            if not isinstance(weight, int) or not (0 <= weight <= 10):
                raise FacultyValidationError(f"Preference weight for '{key}' in {pref_name} must be 0-10")

    return record


class Faculty:
    """Namespace of staticmethods that operate on a plain list of faculty
    dicts. Never instantiate this -- call methods directly on the class,
    e.g. Faculty.facCheck(faculty_list, name)."""

    @staticmethod
    def facCheck(faculty_list, name):
        """True if a faculty member with this EXACT name already exists."""
        return any(f.get("name") == name for f in faculty_list)

    @staticmethod
    def getFaculty(faculty_list, name):
        """Returns the matching faculty dict, or None if not found."""
        return next((f for f in faculty_list if f.get("name") == name), None)

    @staticmethod
    def addFaculty(faculty_list, new_faculty):
        """Validates, then appends new_faculty to faculty_list in place.
        Raises before appending if the record is invalid."""
        validate_faculty(new_faculty)
        faculty_list.append(new_faculty)
        return new_faculty

    @staticmethod
    def removeFaculty(faculty_list, faculty_name):
        """Removes and returns the faculty member with this exact name,
        or returns None if no match was found."""
        record = Faculty.getFaculty(faculty_list, faculty_name)
        if record is not None:
            faculty_list.remove(record)
        return record

    @staticmethod
    def viewFaculty(faculty_list):
        """Prints every faculty member in a readable format."""
        if not faculty_list:
            print("(no faculty defined)")
            return

        for f in faculty_list:
            print(f"Faculty: {f.get('name')}")
            print(f"  Credits: {f.get('minimum_credits')}-{f.get('maximum_credits')}")
            print(f"  Unique course limit: {f.get('unique_course_limit')}")
            print("  Availability:")
            for day in VALID_DAYS:  # fixed order so it always prints MON->FRI
                if day in f.get("times", {}):
                    print(f"    {day}: {', '.join(f['times'][day])}")
            for label, key in (
                ("Course preferences", "course_preferences"),
                ("Room preferences", "room_preferences"),
                ("Lab preferences", "lab_preferences"),
            ):
                prefs = f.get(key) or {}
                if prefs:
                    print(f"  {label}:")
                    for k, w in prefs.items():
                        print(f"    {k}: {w}")
            print()