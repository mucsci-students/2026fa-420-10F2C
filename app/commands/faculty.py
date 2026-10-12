"""Faculty CRUD commands."""

from scheduler.config import FacultyConfig

from app.crud import ReferenceError_, ValidationFailure, check_no_references

from .common import DAY_LABELS, TIME_RANGE_RE, VALID_DAYS, apply_session_edit, field_value


def prompt_faculty_times():
    """Collect faculty availability by weekday."""
    print("Availability (Times) -- one entry per weekday: MON, TUE, WED, THU, FRI.")
    print("  Leave blank for the default 09:00-17:00")
    print("  Type 'n/a' if unavailable that day")
    print("  Or enter a custom range like 09:30-15:00")
    times = {}
    for day in VALID_DAYS:
        raw = input(f"  {day}: ").strip()
        if raw.lower() in ("n/a", "na", "none", "unavailable"):
            continue
        if not raw:
            times[day] = [{"start": "09:00", "end": "17:00"}]
            continue
        if not TIME_RANGE_RE.match(raw):
            print(f"  '{raw}' isn't a valid HH:MM-HH:MM range -- treating {day} as unavailable.")
            continue
        start, end = raw.split("-")
        times[day] = [{"start": start, "end": end}]
    return times


def prompt_weighted_preferences(label, valid_names, ask_weight=True, max_weight=10):
    """Collect valid weighted course, room, or lab preferences."""
    prefs = {}
    if valid_names:
        print(f"  Existing {label}s: {', '.join(sorted(valid_names))}")
    else:
        print(f"  (no {label}s defined yet -- add one first if you want a {label} preference)")
    print(f"  Add {label} preferences (blank name to stop):")
    while True:
        name = input(f"  {label.capitalize()} name: ").strip()
        if not name:
            break
        if valid_names and name not in valid_names:
            print(f"  '{name}' isn't a known {label} -- pick from: {', '.join(sorted(valid_names))}")
            continue
        if not ask_weight:
            prefs[name] = 5
            continue
        weight_raw = input(f"  Weight (0-{max_weight}, default 5): ").strip()
        if weight_raw.isdigit() and 0 <= int(weight_raw) <= max_weight:
            weight = int(weight_raw)
        else:
            print(f"  '{weight_raw}' isn't 0-{max_weight} -- using the default weight of 5.")
            weight = 5
        prefs[name] = weight
    return prefs


def prompt_mandatory_days(times):
    """Collect a faculty member's optional mandatory teaching days."""
    available_days = [day for day in VALID_DAYS if times.get(day)]
    if not available_days:
        print("  No available days set -- skipping mandatory days.")
        return None

    print(f"  Mandatory days (must be scheduled every term) -- choose from: {', '.join(available_days)}")
    print("  Comma-separated, or blank for none:")
    raw = input("  > ").strip()
    if not raw:
        return None

    days = []
    for token in raw.split(","):
        day = token.strip().upper()
        if not day:
            continue
        if day not in available_days:
            print(f"  Skipping '{day}' -- not one of this faculty member's available days.")
            continue
        if day not in days:
            days.append(day)
    return days or None


def prompt_maximum_days(mandatory_days):
    """Collect an optional weekly teaching-day limit.

    A faculty member cannot have a maximum below the number of days they
    explicitly require, so raise a smaller supplied limit to that minimum.
    """
    raw = input("  Maximum teaching days per week (blank for no limit): ").strip()
    if not raw or not raw.isdigit() or int(raw) <= 0:
        return None

    maximum_days = int(raw)
    mandatory_count = len(mandatory_days or [])
    return max(maximum_days, mandatory_count)


def prompt_faculty_fields(config):
    """Collect fields for a faculty record."""
    print("Enter the faculty's name:")
    name = input().strip()

    print('Are they full-time or adjunct? (Enter "full" or "adjunct") (Default: full)')
    kind = input().lower().replace(" ", "")
    if kind == "adjunct":
        max_credits, unique_course_limit = 4, 1
    else:
        max_credits, unique_course_limit = 12, 2

    times = prompt_faculty_times()
    mandatory_days = prompt_mandatory_days(times)
    maximum_days = prompt_maximum_days(mandatory_days)
    course_ids = {course.course_id for course in config.config.courses}
    room_names = {room.name for room in config.config.rooms}
    lab_names = {lab.name for lab in config.config.labs}

    print("Preferences:")
    course_preferences = prompt_weighted_preferences("course", course_ids)
    room_preferences = prompt_weighted_preferences("room", room_names)
    lab_preferences = prompt_weighted_preferences("lab", lab_names)

    fields = {
        "name": name,
        "maximum_credits": max_credits,
        "minimum_credits": 0,
        "unique_course_limit": unique_course_limit,
        "times": times,
        "course_preferences": course_preferences,
        "room_preferences": room_preferences,
        "lab_preferences": lab_preferences,
    }
    if mandatory_days is not None:
        fields["mandatory_days"] = mandatory_days
    if maximum_days is not None:
        fields["maximum_days"] = maximum_days
    return fields


def add_faculty(session):
    """Prompt for and add a faculty record."""
    config = session.require_config()
    fields = prompt_faculty_fields(config)
    if not fields["name"]:
        print("You entered a blank name!")
        return
    if any(faculty.name == fields["name"] for faculty in config.config.faculty):
        print("Faculty is already in the system!")
        return

    new_faculty = FacultyConfig(**fields)

    def mutate(draft):
        draft.config.faculty.append(new_faculty)

    try:
        apply_session_edit(session, config, "faculty", mutate)
        print("Faculty added.")
    except ValidationFailure as error:
        print(f"Could not add faculty: {error}")


def modify_faculty(session):
    """Prompt for and update an existing faculty record."""
    config = session.require_config()
    print("What is the name of the faculty you'd like to edit?")
    target_name = input().strip()
    existing = next((faculty for faculty in config.config.faculty if faculty.name == target_name), None)
    if existing is None:
        print("Faculty does not exist!")
        return

    updated_fields = prompt_faculty_fields(config)

    def mutate(draft):
        faculty_list = draft.config.faculty
        faculty_list.remove(existing)
        faculty_list.append(FacultyConfig(**updated_fields))

    try:
        apply_session_edit(session, config, "faculty", mutate)
        print("Faculty updated.")
    except ValidationFailure as error:
        print(f"Could not save changes, previous version kept: {error}")


def delete_faculty(session):
    """Delete an unreferenced faculty record after confirmation."""
    config = session.require_config()
    print("What is the name of the faculty you want to remove?")
    name = input().strip()
    existing = next((faculty for faculty in config.config.faculty if faculty.name == name), None)
    if existing is None:
        print("Faculty does not exist!")
        return

    referencing_courses = [
        course.course_id
        for course in config.config.courses
        if name in (getattr(course, "faculty", None) or [])
    ]
    try:
        check_no_references(name, referencing_courses)
    except ReferenceError_ as error:
        print(f"{error} -- remove or reassign those first, or add a --cascade option if you want one.")
        return

    print("Are you sure you want to delete this faculty? This cannot be undone. (y/n)")
    if input().lower().strip() not in ("y", "yes"):
        print("Removal cancelled")
        return

    def mutate(draft):
        draft.config.faculty.remove(existing)

    try:
        apply_session_edit(session, config, "faculty", mutate)
        print("Faculty removed.")
    except ValidationFailure as error:
        print(f"Could not remove faculty: {error}")


def format_faculty(faculty):
    """Format a faculty record for terminal display."""
    kind = "Adjunct" if faculty.unique_course_limit <= 1 else "Full-Time"
    header = f"{faculty.name} \u2014 {kind}"
    lines = [header, "-" * len(header)]
    lines.append(
        f"  Credits: {faculty.minimum_credits}-{faculty.maximum_credits}"
        f"   Unique courses: {faculty.unique_course_limit}"
        f"   Max days/week: {faculty.maximum_days}"
    )
    if faculty.mandatory_days:
        lines.append(f"  Mandatory days: {', '.join(faculty.mandatory_days)}")

    availability_lines = []
    for day in VALID_DAYS:
        blocks = field_value(faculty.times, day)
        if not blocks:
            continue
        ranges = ", ".join(f"{field_value(block, 'start')}-{field_value(block, 'end')}" for block in blocks)
        availability_lines.append(f"    {DAY_LABELS[day]}  {ranges}")
    lines.append("  Availability:")
    lines.extend(availability_lines if availability_lines else ["    (none set)"])

    for label, preferences in (
        ("Course preferences", faculty.course_preferences),
        ("Room preferences", faculty.room_preferences),
        ("Lab preferences", faculty.lab_preferences),
    ):
        if preferences:
            formatted = ", ".join(f"{name} ({weight})" for name, weight in preferences.items())
            lines.append(f"  {label}: {formatted}")
    return "\n".join(lines)


def view_faculty(session):
    """Display all faculty records in the active configuration."""
    config = session.require_config()
    if not config.config.faculty:
        print("(no faculty defined)")
        return
    for index, faculty in enumerate(config.config.faculty):
        if index > 0:
            print()
        print(format_faculty(faculty))