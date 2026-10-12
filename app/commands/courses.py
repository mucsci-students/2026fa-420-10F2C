"""Course CRUD commands."""

from scheduler.config import CourseConfig, ValidationError

from app.crud import ReferenceError_, ValidationFailure, check_no_references

from .common import apply_session_edit


def enabled_pattern_credits(config):
    """Return credit values with at least one enabled class pattern."""
    return sorted({pattern.credits for pattern in config.time_slot_config.classes if not pattern.disabled})


def course_display_name(course, seen_counts):
    """Return the scheduler's display name for a course section."""
    count = seen_counts.get(course.course_id, 0) + 1
    seen_counts[course.course_id] = count
    return f"{course.course_id}.{course.section_id or f'{count:02d}'}"


def format_course(index, course, display):
    """Format an indexed course record for terminal display."""
    bits = [f"[{index}] {display}  --  {course.credits} credits, capacity {course.capacity}"]
    bits.append(f"      Modality: {course.modality}")
    if course.room:
        bits.append(f"      Rooms: {', '.join(course.room)}")
    if course.required_room_features:
        bits.append(f"      Required room features: {', '.join(sorted(course.required_room_features))}")
    if course.lab:
        bits.append(f"      Labs: {', '.join(course.lab)}")
        bits.append(f"      Reserves room during lab: {'yes' if course.reserve_room_during_lab else 'no'}")
    if course.required_lab_features:
        bits.append(f"      Required lab features: {', '.join(sorted(course.required_lab_features))}")
    if course.conflicts:
        bits.append(f"      Conflicts: {', '.join(course.conflicts)}")
    if course.faculty is None:
        bits.append("      Faculty: (derived from faculty course preferences)")
    else:
        bits.append(f"      Faculty: {', '.join(course.faculty)}")
    return "\n".join(bits)


def list_courses(config):
    """Display all courses and return the ordered course list."""
    courses = config.config.courses
    if not courses:
        print("(no courses defined)")
        return courses
    seen = {}
    for index, course in enumerate(courses):
        print(format_course(index, course, course_display_name(course, seen)))
    return courses


def prompt_course_index(count):
    """Prompt for and validate a course-list index."""
    raw = input("Enter the course's index: ").strip()
    if not raw.isdigit():
        print("Please enter a valid integer index.")
        return None
    index = int(raw)
    if not 0 <= index < count:
        print(f"No course at index {index}. Valid range: 0-{count - 1}.")
        return None
    return index


def prompt_name_list(label, valid_names):
    """Collect names from a known set until the user enters a blank line."""
    if valid_names:
        print(f"  Existing {label}s: {', '.join(sorted(valid_names))}")
    else:
        print(f"  (no {label}s defined yet)")
    print(f"  Add {label}s one at a time (blank to stop):")

    chosen = []
    while True:
        name = input(f"  {label.capitalize()}: ").strip()
        if not name:
            break
        if valid_names and name not in valid_names:
            print(f"  '{name}' isn't a known {label} -- pick from: {', '.join(sorted(valid_names))}")
            continue
        if name in chosen:
            print(f"  '{name}' is already on the list.")
            continue
        chosen.append(name)
    return chosen


def prompt_feature_set(label):
    """Prompt for a comma-separated set of required features."""
    raw = input(f"  Required {label} features (comma-separated, blank for none): ").strip()
    return {part.strip() for part in raw.split(",") if part.strip()} if raw else set()


def prompt_positive_int(prompt_text, label):
    """Prompt until the user supplies a positive integer."""
    while True:
        raw = input(prompt_text).strip()
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
        print(f"{label} must be a positive whole number!")


def prompt_course_fields(config):
    """Collect and validate fields for a course record."""
    scheduler_config = config.config
    while True:
        course_id = input("Course ID (e.g. 'CS 101'): ").strip()
        if course_id:
            break
        print("Course ID cannot be blank.")

    section_id = input("Section ID (blank = auto-number by input order): ").strip() or None
    available = enabled_pattern_credits(config)
    if available:
        print(f"  Credit values with an enabled class pattern: {', '.join(str(credit) for credit in available)}")
    else:
        print("  (warning: no enabled class patterns exist -- any course will be rejected)")
    credits = prompt_positive_int("Credits: ", "Credits")
    if available and credits not in available:
        print(f"  Note: no enabled pattern has {credits} credits, so this will be rejected until you add one (Class Meeting Patterns -> Add).")
    capacity = prompt_positive_int("Expected enrollment (capacity): ", "Capacity")

    while True:
        modality = input("Modality (in_person/online/hybrid, default in_person): ").strip().lower() or "in_person"
        if modality in ("in_person", "online", "hybrid"):
            break
        print("  Modality must be one of: in_person, online, hybrid.")

    rooms, labs = [], []
    required_room_features, required_lab_features = set(), set()
    reserve_room_during_lab = True
    if modality == "online":
        print("  (online course -- skipping rooms, labs, and feature requirements)")
    else:
        print("Candidate rooms (blank list is valid only for patterns that occupy no room):")
        rooms = prompt_name_list("room", [room.name for room in scheduler_config.rooms])
        if rooms:
            required_room_features = prompt_feature_set("room")
        print("Candidate labs (leave empty if this course has no lab meeting):")
        labs = prompt_name_list("lab", [lab.name for lab in scheduler_config.labs])
        if labs:
            required_lab_features = prompt_feature_set("lab")
            answer = input("  Should the lab meeting also occupy the lecture room? (y/n, default y): ")
            reserve_room_during_lab = answer.strip().lower() not in ("n", "no")

    print("Conflicting courses (sections of these can never overlap):")
    conflicts = prompt_name_list(
        "conflict course",
        sorted({course.course_id for course in scheduler_config.courses if course.course_id != course_id}),
    )
    print("Faculty candidates (leave empty to derive them from faculty course preferences):")
    faculty = prompt_name_list("faculty", [person.name for person in scheduler_config.faculty])
    return {
        "course_id": course_id,
        "section_id": section_id,
        "credits": credits,
        "capacity": capacity,
        "room": rooms,
        "lab": labs,
        "conflicts": conflicts,
        "faculty": faculty or None,
        "modality": modality,
        "required_room_features": required_room_features,
        "required_lab_features": required_lab_features,
        "reserve_room_during_lab": reserve_room_during_lab,
    }


def add_course(session):
    """Prompt for and add a course record."""
    config = session.require_config()
    fields = prompt_course_fields(config)
    try:
        new_course = CourseConfig(**fields)
    except ValidationError as error:
        print(f"Could not add course: {error}")
        return

    def mutate(draft):
        draft.config.courses.append(new_course)

    try:
        apply_session_edit(session, config, "course", mutate)
        print("Course added.")
    except ValidationFailure as error:
        print(f"Could not add course: {error}")


def modify_course(session):
    """Prompt for and update an existing course record."""
    config = session.require_config()
    courses = list_courses(config)
    if not courses:
        return
    index = prompt_course_index(len(courses))
    if index is None:
        return
    fields = prompt_course_fields(config)
    try:
        updated_course = CourseConfig(**fields)
    except ValidationError as error:
        print(f"Could not save changes, previous version kept: {error}")
        return

    def mutate(draft):
        draft.config.courses[index] = updated_course

    try:
        apply_session_edit(session, config, "course", mutate)
        print("Course updated.")
    except ValidationFailure as error:
        print(f"Could not save changes, previous version kept: {error}")


def delete_course(session):
    """Delete an unreferenced course after confirmation."""
    config = session.require_config()
    courses = list_courses(config)
    if not courses:
        return
    index = prompt_course_index(len(courses))
    if index is None:
        return

    existing = courses[index]
    course_id = existing.course_id
    last_section = not any(course.course_id == course_id for item_index, course in enumerate(courses) if item_index != index)
    if last_section:
        referenced_by = [
            f"course '{course.course_id}' (conflicts)"
            for item_index, course in enumerate(courses)
            if item_index != index and course_id in course.conflicts
        ]
        referenced_by += [
            f"faculty '{faculty.name}' (course preference)"
            for faculty in config.config.faculty
            if course_id in faculty.course_preferences
        ]
        try:
            check_no_references(course_id, referenced_by)
        except ReferenceError_ as error:
            print(f"{error} -- remove those references first.")
            return

    print("Are you sure you want to delete this course? This cannot be undone. (y/n)")
    if input().strip().lower() not in ("y", "yes"):
        print("Removal cancelled")
        return

    def mutate(draft):
        del draft.config.courses[index]

    try:
        apply_session_edit(session, config, "course", mutate)
        print("Course removed.")
    except ValidationFailure as error:
        print(f"Could not remove course: {error}")


def view_course(session):
    """Display all course records in the active configuration."""
    config = session.require_config()
    if not config.config.courses:
        print("(no courses defined)")
        return
    seen = {}
    for index, course in enumerate(config.config.courses):
        if index > 0:
            print()
        print(format_course(index, course, course_display_name(course, seen)))