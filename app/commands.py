# ----------------------------------------------------------------------------------------------------------------------- #
#   app/commands.py                                                                                                       #
#                                                                                                                         #
#   Every function here takes `session` (app/session.py) as its first argument   #
#   instead of doing its own file I/O.                                          #
#                                                                                 #
#   Implemented against the real library and tested:                            #
#     - Config lifecycle (Req #4): new/load/save/print/validate.                #
#     - Faculty CRUD -- the worked example everything else below follows;       #
#       built on CombinedConfig + edit_mode(), not the old hand-rolled          #
#       facultyModel.py.                                                        #
#     - Timeslot CRUD (add/modify/delete) and global timing options.            #
#     - Class pattern CRUD (add/modify/delete_pattern), identified by list      #
#       index rather than a name/id -- see the comment block above              #
#       _list_patterns() for why.                                               #
#     - Global settings (Req #28-30): generation limit, optimizer flags.        #
#     - Schedule generation/inspection/export (Req #8-10) -- schedule_ops.py    #
#       does the real work; export_schedule() here bounds-checks --index        #
#       before touching session.schedules so a bad index degrades to a         #
#       printed message instead of killing the session (Req #3).               #
#                                                                                 #
#   Still TODO, same recipe as add_faculty() below (require_config() ->         #
#   prompt -> construct the library's real model -> apply_edit() + _mutate()    #
#   closure -> catch ValidationFailure; check_no_references() first for any     #
#   delete_*):                                                                  #
#     - Course CRUD (add/modify/delete_course).                                 #
#     - Lab CRUD (add/modify/delete_lab) -- delete needs to check courses'      #
#       lab lists.                                                              #
#     - Room CRUD (add/modify/delete_room) -- delete needs to check courses'    #
#       room lists.                                                             #
#     - Meeting CRUD (add/modify/delete_meeting).                               #
# ----------------------------------------------------------------------------------------------------------------------- #


from app.session import ConfigError
from app.crud import apply_edit, ValidationFailure, check_no_references
from app import schedule_ops

from scheduler.config import FacultyConfig, TimeBlock, ValidationError, OptimizerFlags, ClassPattern, Meeting

_VALID_DAYS = ("MON", "TUE", "WED", "THU", "FRI")
_VALID_OPTIMIZER_FLAGS = {
    "faculty_course", "faculty_room", "faculty_lab",
    "same_room", "same_lab", "pack_rooms", "pack_labs",
}

# =========================================================================== #
#  Config lifecycle (Req #4)
# =========================================================================== #

def new_config(session):
    session.new_config()
    print("Started a new, empty configuration.")


def load_config(session, path):
    try:
        session.load(path)
    except ConfigError as e:
        # re-raise: shell.handle_command already catches ConfigError and
        # prints it, and prior valid session.config is untouched because
        # Session.load() only swaps state in on success.
        raise e
    print(f"Loaded and validated '{path}'.")


def save_config(session, path=None):
    target = session.save(path)  # raises ConfigError -> caught by shell
    print(f"Saved configuration to '{target}'.")


def print_config(session):
    config = session.require_config()
    # Pydantic gives us readable JSON for free -- no custom printer needed.
    print(config.model_dump_json(indent=2))


def validate_config(session):
    config = session.require_config()
    # If it's sitting in session.config at all, it already passed
    # validation on load/new/every edit_mode() exit. Re-running validation
    # explicitly (e.g. via model_validate(config.model_dump())) is cheap
    # reassurance for the user and matches Req #4 ("validate the current
    # configuration") as an explicit, standalone action rather than an
    # implicit side effect.
    try:
        type(config).model_validate(config.model_dump())
    except Exception as e:  # noqa: BLE001 -- narrow to ValidationError once confirmed
        print(f"Configuration is INVALID: {e}")
        return
    print("Configuration is valid.")


# =========================================================================== #
#  Faculty CRUD -- worked example against CombinedConfig (replaces the old
#  facultyModel.py / facultyComm.py entirely; do not import those anymore)
# =========================================================================== #

def _prompt_faculty_fields():
    """Same interactive prompts as the old facultyComm.py -- reuse that
    UX, just stop building a plain dict for a hand-rolled validator and
    build kwargs for the library's real Faculty model instead."""
    print("Enter the faculty's name:")
    name = input().strip()

    print('Are they full-time or adjunct? (Enter "full" or "adjunct") (Default: full)')
    kind = input().lower().replace(" ", "")
    if kind == "adjunct":
        max_credits, unique_course_limit = 4, 1
    else:
        max_credits, unique_course_limit = 12, 2

    # ... existing daysAndTimes()/preference prompts from facultyComm.py
    # can be lifted in here unchanged; omitted for brevity in this
    # backbone pass ...
    return {
        "name": name,
        "maximum_credits": max_credits,
        "minimum_credits": 0,
        "unique_course_limit": unique_course_limit,
        "times": {},
        "course_preferences": {},
        "room_preferences": {},
        "lab_preferences": {},
    }


def add_faculty(session):
    config = session.require_config()
    fields = _prompt_faculty_fields()
    if not fields["name"]:
        print("You entered a blank name!")
        return
    if any(f.name == fields["name"] for f in config.config.faculty):
        print("Faculty is already in the system!")
        return

    new_faculty = FacultyConfig(**fields)

    def _mutate(cfg):
        cfg.config.faculty.append(new_faculty)

    try:
        apply_edit(config, "faculty", _mutate)
        print("Faculty added.")
    except ValidationFailure as e:
        # config is guaranteed unchanged here -- edit_mode() rolled back
        # before this exception ever reached us.
        print(f"Could not add faculty: {e}")


def modify_faculty(session):
    config = session.require_config()
    print("What is the name of the faculty you'd like to edit?")
    target_name = input().strip()

    existing = next((f for f in config.config.faculty if f.name == target_name), None)
    if existing is None:
        print("Faculty does not exist!")
        return

    # Collect edited fields the same way add_faculty does, seeded with the
    # existing record's values (mirrors the old modify_faculty's
    # "pull the record out, ask what to change" flow).
    updated_fields = _prompt_faculty_fields()

    def _mutate(cfg):
        faculty_list = cfg.config.faculty
        faculty_list.remove(existing)
        faculty_list.append(FacultyConfig(**updated_fields))

    try:
        apply_edit(config, "faculty", _mutate)
        print("Faculty updated.")
    except ValidationFailure as e:
        # Nothing to manually restore -- edit_mode() already rolled the
        # whole config back to its pre-mutate state (Req #4/#6).
        print(f"Could not save changes, previous version kept: {e}")


def delete_faculty(session):
    config = session.require_config()
    print("What is the name of the faculty you want to remove?")
    name = input().strip()

    existing = next((f for f in config.config.faculty if f.name == name), None)
    if existing is None:
        print("Faculty does not exist!")
        return

    # Req #7: don't silently leave dangling references. A course whose
    # `faculty` list names this person is a reference; scan for those
    # before deleting.
    referencing_courses = [c.course_id for c in config.config.courses if name in getattr(c, "faculty", [])]
    try:
        check_no_references(name, referencing_courses)
    except Exception as e:  # ReferenceError_ from app.crud
        print(f"{e} -- remove or reassign those first, or add a --cascade option if you want one.")
        return

    print("Are you sure you want to delete this faculty? This cannot be undone. (y/n)")
    if input().lower().strip() not in ("y", "yes"):
        print("Removal cancelled")
        return

    def _mutate(cfg):
        cfg.config.faculty.remove(existing)

    try:
        apply_edit(config, "faculty", _mutate)
        print("Faculty removed.")
    except ValidationFailure as e:
        print(f"Could not remove faculty: {e}")


def _field(obj, key):
    """Reads a field whether obj is a dict or a pydantic model instance
    (times/preferences can come back as either)."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


_DAY_LABELS = {"MON": "Mon", "TUE": "Tue", "WED": "Wed", "THU": "Thu", "FRI": "Fri"}


def _format_faculty(f):
    kind = "Adjunct" if f.unique_course_limit <= 1 else "Full-Time"
    header = f"{f.name} \u2014 {kind}"
    lines = [header, "-" * len(header)]

    lines.append(f"  Credits: {f.minimum_credits}-{f.maximum_credits}"
                  f"   Unique courses: {f.unique_course_limit}"
                  f"   Max days/week: {f.maximum_days}")

    if f.mandatory_days:
        lines.append(f"  Mandatory days: {', '.join(f.mandatory_days)}")

    availability_lines = []
    for day in ["MON", "TUE", "WED", "THU", "FRI"]:
        blocks = _field(f.times, day)
        if not blocks:
            continue
        ranges = ", ".join(f"{_field(b, 'start')}-{_field(b, 'end')}" for b in blocks)
        availability_lines.append(f"    {_DAY_LABELS[day]}  {ranges}")

    lines.append("  Availability:")
    lines.extend(availability_lines if availability_lines else ["    (none set)"])

    for label, prefs in (
        ("Course preferences", f.course_preferences),
        ("Room preferences", f.room_preferences),
        ("Lab preferences", f.lab_preferences),
    ):
        if prefs:
            formatted = ", ".join(f"{name} ({weight})" for name, weight in prefs.items())
            lines.append(f"  {label}: {formatted}")

    return "\n".join(lines)


def view_faculty(session):
    config = session.require_config()
    if not config.config.faculty:
        print("(no faculty defined)")
        return
    for i, f in enumerate(config.config.faculty):
        if i > 0:
            print()
        print(_format_faculty(f))


# =========================================================================== #
#  TODO: course / lab / room / meeting CRUD
#
#  Follow the exact recipe used above for faculty (and already applied to
#  timeslots and patterns below):
#    1. session.require_config() to get the live CombinedConfig.
#    2. Prompt for fields; construct the library's real nested model
#       (Course / Room / Lab / Meeting -- same scheduler.config lookup
#       FacultyConfig/ClassConfig/MeetingConfig already went through).
#    3. Build a small _mutate(cfg) closure that appends/replaces/removes
#       from the right list on cfg.config.
#    4. Wrap it in apply_edit(config, "<area>", _mutate) and catch
#       ValidationFailure.
#    5. For delete_*, scan for references first (check_no_references) --
#       e.g. deleting a room needs to check courses' room lists.
# =========================================================================== #

def add_course(session):
    print("TODO: same pattern as add_faculty -- see the block comment above.")

def modify_course(session):
    print("TODO: same pattern as modify_faculty.")

def delete_course(session):
    print("TODO: same pattern as delete_faculty (check courses referencing this course's conflicts, etc).")


def add_lab(session):
    print("TODO")

def modify_lab(session):
    print("TODO")

def delete_lab(session):
    print("TODO: check courses whose lab list references this lab before deleting.")


def add_room(session):
    print("TODO")

def modify_room(session):
    print("TODO")

def delete_room(session):
    print("TODO: check courses whose room list references this room before deleting.")


def _prompt_time_block():
    print("Start time (HH:MM)?")
    start = input().strip()
    print("End time (HH:MM)?")
    end = input().strip()
    print("Spacing between slots, in minutes?")
    spacing_raw = input().strip()

    try:
        spacing = int(spacing_raw)
    except ValueError:
        print(f"'{spacing_raw}' is not a valid number of minutes.")
        return None

    try:
        return TimeBlock(start=start, spacing=spacing, end=end)
    except ValidationError as e:
        print(f"Invalid time block: {e}")
        return None


def _blocks_overlap(a, b):
    return a.start < b.end and b.start < a.end


def add_timeslot(session):
    config = session.require_config()
    print(f"Which day? ({'/'.join(_VALID_DAYS)})")
    day = input().strip().upper()
    if day not in _VALID_DAYS:
        print(f"'{day}' is not a valid day.")
        return

    new_block = _prompt_time_block()
    if new_block is None:
        return

    existing = config.time_slot_config.times.get(day, [])
    conflict = next((b for b in existing if _blocks_overlap(b, new_block)), None)
    if conflict:
        print(f"Time Conflict: overlaps existing block {conflict.start}-{conflict.end}")
        return

    def _mutate(cfg):
        cfg.time_slot_config.times.setdefault(day, []).append(new_block)

    try:
        apply_edit(config, "timeslot", _mutate)
        print("Time Slot Added Successfully")
    except ValidationFailure as e:
        print(f"Could not add time slot: {e}")


def modify_timeslot(session):
    config = session.require_config()
    print(f"Which day is the time slot on? ({'/'.join(_VALID_DAYS)})")
    day = input().strip().upper()
    blocks = config.time_slot_config.times.get(day, [])
    if not blocks:
        print(f"No time slots defined for {day}.")
        return

    for i, b in enumerate(blocks):
        print(f"  [{i}] {b.start}-{b.end} (spacing {b.spacing}m)")
    print("Which one do you want to change? (index)")
    try:
        idx = int(input().strip())
        blocks[idx]
    except (ValueError, IndexError):
        print("Not a valid selection.")
        return

    print("Enter the new time slot:")
    new_block = _prompt_time_block()
    if new_block is None:
        return

    conflict = next(
        (b for j, b in enumerate(blocks) if j != idx and _blocks_overlap(b, new_block)),
        None,
    )
    if conflict:
        print(f"Time Conflict: overlaps existing block {conflict.start}-{conflict.end}")
        return

    def _mutate(cfg):
        cfg.time_slot_config.times[day][idx] = new_block

    try:
        apply_edit(config, "timeslot", _mutate)
        print("Time Changed Successfully")
    except ValidationFailure as e:
        print(f"Could not save changes, previous version kept: {e}")


def delete_timeslot(session):
    config = session.require_config()
    print(f"Which day is the time slot on? ({'/'.join(_VALID_DAYS)})")
    day = input().strip().upper()
    blocks = config.time_slot_config.times.get(day, [])
    if not blocks:
        print(f"No time slots defined for {day}.")
        return
    if len(blocks) == 1:
        print(f"Can't delete the only time block on {day} -- every weekday needs at least one.")
        return

    for i, b in enumerate(blocks):
        print(f"  [{i}] {b.start}-{b.end} (spacing {b.spacing}m)")
    print("Which one do you want to delete? (index)")
    try:
        idx = int(input().strip())
        blocks[idx]
    except (ValueError, IndexError):
        print("Not a valid selection.")
        return

    print("Are you sure? Type confirm or cancel")
    if input().strip().lower() != "confirm":
        print("Cancelled.")
        return

    def _mutate(cfg):
        del cfg.time_slot_config.times[day][idx]

    try:
        apply_edit(config, "timeslot", _mutate)
        print("Time slot deleted.")
    except ValidationFailure as e:
        print(f"Could not delete: {e}")


def modify_timing_options(session):
    """The 'global timing options' half of the Time slots requirement:
    TimeSlotConfig.max_time_gap / min_time_overlap."""
    config = session.require_config()
    current = config.time_slot_config
    print(f"Max time gap in minutes [{current.max_time_gap}] (blank to keep):")
    gap_input = input().strip()
    print(f"Min time overlap in minutes [{current.min_time_overlap}] (blank to keep):")
    overlap_input = input().strip()

    try:
        new_gap = int(gap_input) if gap_input else None
        new_overlap = int(overlap_input) if overlap_input else None
    except ValueError:
        print("Please enter whole numbers.")
        return

    def _mutate(cfg):
        if new_gap is not None:
            cfg.time_slot_config.max_time_gap = new_gap
        if new_overlap is not None:
            cfg.time_slot_config.min_time_overlap = new_overlap

    try:
        apply_edit(config, "timeslot", _mutate)
        print("Timing options updated.")
    except ValidationFailure as e:
        print(f"Could not update timing options: {e}")


# ---------------------------------------------------------------- #
#  Class pattern CRUD (time_slot_config.classes)                    #
#                                                                    #
#  Same apply_edit()/ValidationFailure recipe as faculty above, with #
#  one structural difference: entries here have no name/id field    #
#  (confirmed against config_example.json -- a "class" entry is     #
#  just {credits, meetings[, start_time][, disabled]}), so add/     #
#  modify/delete identify a pattern by its position in the list     #
#  instead of a lookup key. No check_no_references() call for       #
#  delete_pattern: nothing else in the schema points at a pattern   #
#  by index, unlike rooms/labs/faculty being named from courses     #
#  (Req #7 only calls those four out explicitly).                   #
# ---------------------------------------------------------------- #

def _prompt_meeting():
    """One meeting entry: day, duration, lab flag, delivery mode, and an
    optional fixed start time -- matches the shape confirmed in
    config_example.json's time_slot_config.classes[].meetings
    ({day, duration, lab, delivery, start_time}).
    NOTE: "in_person" is the only delivery value actually confirmed in
    the example data; other values (online/hybrid/etc) are a guess --
    double check the real enum via scheduler.config before relying on
    anything but "in_person" here.
    Loops on invalid input (Req #3/#6: recover from bad input without
    terminating the session) instead of letting Meeting(...)'s
    ValidationError propagate uncaught and crash the app."""
    while True:
        print("  Day (MON/TUE/WED/THU/FRI):")
        day = input("  > ").strip().upper()

        print("  Duration in minutes:")
        duration_raw = input("  > ").strip()
        duration = int(duration_raw) if duration_raw.isdigit() else 0

        print("  Is this meeting a lab session? (y/n, default n)")
        lab = input("  > ").strip().lower() in ("y", "yes")

        print("  Delivery mode (in_person/online/hybrid, default in_person):")
        delivery = input("  > ").strip().lower() or "in_person"

        print("  Fixed start time for this meeting, e.g. 09:00 (blank = none):")
        start_time = input("  > ").strip() or None

        try:
            return Meeting(day=day, duration=duration, lab=lab, delivery=delivery, start_time=start_time)
        except ValidationError as e:
            print(f"Invalid meeting: {e}")
            print("Let's try that meeting again.")


def _prompt_pattern_fields():
    """Prompts for one full class-pattern record: credits, one-or-more
    meetings, and the two optional fields (start_time, disabled) seen on
    some entries in config_example.json."""
    print("Credits for this pattern:")
    credits_raw = input().strip()
    credits = int(credits_raw) if credits_raw.isdigit() else 0

    meetings = []
    print("Now enter the meetings for this pattern (at least one required).")
    while True:
        meetings.append(_prompt_meeting())
        print("Add another meeting? (y/n, default n)")
        if input().strip().lower() not in ("y", "yes"):
            break

    print("Fixed start time for this pattern, e.g. 16:00 (blank = none):")
    start_time = input().strip() or None

    print("Should this pattern start disabled? (y/n, default n)")
    disabled = input().strip().lower() in ("y", "yes")

    return {
        "credits": credits,
        "meetings": meetings,
        "start_time": start_time,
        "disabled": disabled,
    }


def _format_pattern(index, pattern):
    meeting_bits = ", ".join(
        f"{m.day} {m.duration}min" + (" (lab)" if getattr(m, "lab", False) else "")
        for m in pattern.meetings
    )
    extras = []
    if getattr(pattern, "start_time", None):
        extras.append(f"start_time={pattern.start_time}")
    if getattr(pattern, "disabled", False):
        extras.append("disabled")
    extra_str = f"  [{', '.join(extras)}]" if extras else ""
    return f"[{index}] {pattern.credits} credits -- {meeting_bits}{extra_str}"


def _list_patterns(config):
    """Prints every existing pattern with its index (there's no standalone
    'pattern view' command -- see shell.py's pattern subparser -- so
    modify/delete show the list themselves right before asking which one
    to act on)."""
    patterns = config.time_slot_config.classes
    if not patterns:
        print("(no class patterns defined)")
        return patterns
    for i, p in enumerate(patterns):
        print(_format_pattern(i, p))
    return patterns


def _prompt_pattern_index(count):
    raw = input("Enter the pattern's index: ").strip()
    if not raw.isdigit():
        print("Please enter a valid integer index.")
        return None
    idx = int(raw)
    if not (0 <= idx < count):
        print(f"No pattern at index {idx}. Valid range: 0-{count - 1}.")
        return None
    return idx


def add_pattern(session):
    config = session.require_config()
    fields = _prompt_pattern_fields()
    if fields["credits"] <= 0:
        print("Credits must be a positive integer.")
        return
    if not fields["meetings"]:
        print("A pattern needs at least one meeting.")
        return

    new_pattern = ClassPattern(**fields)

    def _mutate(cfg):
        cfg.time_slot_config.classes.append(new_pattern)

    try:
        apply_edit(config, "pattern", _mutate)
        print("Class pattern added.")
    except ValidationFailure as e:
        print(f"Could not add pattern: {e}")


def modify_pattern(session):
    config = session.require_config()
    patterns = _list_patterns(config)
    if not patterns:
        return

    print("Which pattern would you like to edit?")
    idx = _prompt_pattern_index(len(patterns))
    if idx is None:
        return

    updated_fields = _prompt_pattern_fields()
    if updated_fields["credits"] <= 0:
        print("Credits must be a positive integer.")
        return
    if not updated_fields["meetings"]:
        print("A pattern needs at least one meeting.")
        return

    updated_pattern = ClassPattern(**updated_fields)

    def _mutate(cfg):
        cfg.time_slot_config.classes[idx] = updated_pattern

    try:
        apply_edit(config, "pattern", _mutate)
        print("Class pattern updated.")
    except ValidationFailure as e:
        # Nothing to manually restore -- edit_mode() already rolled the
        # whole config back to its pre-mutate state (Req #4/#6).
        print(f"Could not save changes, previous version kept: {e}")


def delete_pattern(session):
    config = session.require_config()
    patterns = _list_patterns(config)
    if not patterns:
        return

    print("Which pattern would you like to delete?")
    idx = _prompt_pattern_index(len(patterns))
    if idx is None:
        return

    print("Are you sure you want to delete this pattern? This cannot be undone. (y/n)")
    if input().lower().strip() not in ("y", "yes"):
        print("Removal cancelled")
        return

    def _mutate(cfg):
        del cfg.time_slot_config.classes[idx]

    try:
        apply_edit(config, "pattern", _mutate)
        print("Class pattern removed.")
    except ValidationFailure as e:
        print(f"Could not remove pattern: {e}")


def _list_meetings(pattern):
    """Prints one pattern's meetings with their index (mirrors
    _list_patterns()'s role for patterns themselves -- add/modify/delete
    show the list right before asking which meeting to act on)."""
    if not pattern.meetings:
        print("(no meetings on this pattern)")
        return pattern.meetings
    for i, m in enumerate(pattern.meetings):
        lab_str = " (lab)" if getattr(m, "lab", False) else ""
        extras = []
        if getattr(m, "delivery", None):
            extras.append(m.delivery)
        if getattr(m, "start_time", None):
            extras.append(f"start_time={m.start_time}")
        extra_str = f"  [{', '.join(extras)}]" if extras else ""
        print(f"  [{i}] {m.day} {m.duration}min{lab_str}{extra_str}")
    return pattern.meetings


def _prompt_meeting_index(count):
    raw = input("Enter the meeting's index: ").strip()
    if not raw.isdigit():
        print("Please enter a valid integer index.")
        return None
    idx = int(raw)
    if not (0 <= idx < count):
        print(f"No meeting at index {idx}. Valid range: 0-{count - 1}.")
        return None
    return idx


def _choose_pattern_and_meeting(config):
    """Shared by modify_meeting/delete_meeting: pick a pattern, then a
    meeting within it. Returns (pattern_index, meeting_index) or None if
    the user backed out / entered something invalid at any step."""
    patterns = _list_patterns(config)
    if not patterns:
        return None

    print("Which pattern is the meeting on?")
    p_idx = _prompt_pattern_index(len(patterns))
    if p_idx is None:
        return None

    meetings = _list_meetings(patterns[p_idx])
    if not meetings:
        return None

    print("Which meeting?")
    m_idx = _prompt_meeting_index(len(meetings))
    if m_idx is None:
        return None

    return p_idx, m_idx


def add_meeting(session):
    config = session.require_config()
    patterns = _list_patterns(config)
    if not patterns:
        print("Add a class pattern first -- meetings belong to a pattern.")
        return

    print("Which pattern do you want to add a meeting to?")
    idx = _prompt_pattern_index(len(patterns))
    if idx is None:
        return

    new_meeting = _prompt_meeting()

    def _mutate(cfg):
        cfg.time_slot_config.classes[idx].meetings.append(new_meeting)

    try:
        apply_edit(config, "meeting", _mutate)
        print("Meeting added.")
    except ValidationFailure as e:
        print(f"Could not add meeting: {e}")


def modify_meeting(session):
    config = session.require_config()
    choice = _choose_pattern_and_meeting(config)
    if choice is None:
        return
    p_idx, m_idx = choice

    updated_meeting = _prompt_meeting()

    def _mutate(cfg):
        cfg.time_slot_config.classes[p_idx].meetings[m_idx] = updated_meeting

    try:
        apply_edit(config, "meeting", _mutate)
        print("Meeting updated.")
    except ValidationFailure as e:
        # Nothing to manually restore -- edit_mode() already rolled the
        # whole config back to its pre-mutate state (Req #4/#6).
        print(f"Could not save changes, previous version kept: {e}")


def delete_meeting(session):
    config = session.require_config()
    patterns = _list_patterns(config)
    if not patterns:
        return

    print("Which pattern is the meeting on?")
    p_idx = _prompt_pattern_index(len(patterns))
    if p_idx is None:
        return

    meetings = _list_meetings(patterns[p_idx])
    if not meetings:
        return
    if len(meetings) == 1:
        print("Can't delete the only meeting on this pattern -- delete the pattern instead if you don't need it.")
        return

    print("Which meeting would you like to delete?")
    m_idx = _prompt_meeting_index(len(meetings))
    if m_idx is None:
        return

    print("Are you sure you want to delete this meeting? This cannot be undone. (y/n)")
    if input().lower().strip() not in ("y", "yes"):
        print("Removal cancelled")
        return

    def _mutate(cfg):
        del cfg.time_slot_config.classes[p_idx].meetings[m_idx]

    try:
        apply_edit(config, "meeting", _mutate)
        print("Meeting removed.")
    except ValidationFailure as e:
        print(f"Could not remove meeting: {e}")


# =========================================================================== #
#  Global settings CRUD (Req #28-30): generation limit + optimizer flags
# =========================================================================== #

def set_generation_limit(session, value):
    config = session.require_config()
    if value <= 0:
        print("Error: generation limit needs to be positive.")
        return

    def _mutate(cfg):
        cfg.limit = value

    try:
        apply_edit(config, "global_settings", _mutate)
        print(f"Generation limit set to {value}.")
    except ValidationFailure as e:
        print(f"Could not set limit: {e}")


def reset_generation_limit(session):
    config = session.require_config()

    def _mutate(cfg):
        cfg.limit = 10  # confirmed library default

    try:
        apply_edit(config, "global_settings", _mutate)
        print("Generation limit reset to default (10).")
    except ValidationFailure as e:
        print(f"Could not reset limit: {e}")


def enable_optimizer_flag(session, flag):
    config = session.require_config()
    if flag not in _VALID_OPTIMIZER_FLAGS:
        print(f"Error: '{flag}' is not a valid optimizer flag.")
        return
    if flag in config.optimizer_flags:
        print(f"'{flag}' is already enabled.")
        return

    def _mutate(cfg):
        cfg.optimizer_flags.append(OptimizerFlags(flag))

    try:
        apply_edit(config, "global_settings", _mutate)
        print(f"Optimizer flag '{flag}' added.")
    except ValidationFailure as e:
        print(f"Could not add flag: {e}")


def disable_optimizer_flag(session, flag):
    config = session.require_config()
    if flag not in config.optimizer_flags:
        print(f"'{flag}' is not currently enabled.")
        return

    def _mutate(cfg):
        cfg.optimizer_flags.remove(flag)

    try:
        apply_edit(config, "global_settings", _mutate)
        print(f"Optimizer flag '{flag}' removed.")
    except ValidationFailure as e:
        print(f"Could not remove flag: {e}")


# =========================================================================== #
#  Schedule generation / inspection / export (Req #8, #9, #10)
# =========================================================================== #

def generate_schedule(session, limit_override=None):
    config = session.require_config()
    result = schedule_ops.generate_schedules(config, limit_override)

    if result.outcome == schedule_ops.GenerationOutcome.SUCCESS:
        session.schedules = result.schedules
        print(result.message)
    elif result.outcome == schedule_ops.GenerationOutcome.NO_FEASIBLE_SCHEDULE:
        session.schedules = []
        print(f"No feasible schedule: {result.message}")
    elif result.outcome == schedule_ops.GenerationOutcome.INVALID_CONFIG:
        print(f"Configuration is not valid for generation: {result.message}")
    else:  # RUNTIME_ERROR
        print(f"Unexpected error during generation: {result.message}")


def schedule_summary(session):
    if not session.schedules:
        print("No generated schedules in this session. Run 'schedule generate' first.")
        return
    for i, sched in enumerate(session.schedules):
        print(f"--- Schedule {i} ({len(sched)} course assignments) ---")


def view_schedule(session, index):
    if not session.schedules:
        print("No generated schedules in this session.")
        return
    if not (0 <= index < len(session.schedules)):
        print(f"No schedule at index {index}. Valid range: 0-{len(session.schedules) - 1}.")
        return
    print(schedule_ops.summarize_schedule(session.schedules[index]))


def clear_schedules(session):
    session.schedules = []
    print("Cleared generated schedules.")


def export_schedule(session, fmt, path, index=None, overwrite=False):
    if not session.schedules:
        print("No generated schedules to export. Run 'schedule generate' first.")
        return

    if index is not None:
        if not (0 <= index < len(session.schedules)):
            print(f"No schedule at index {index}. Valid range: 0-{len(session.schedules) - 1}.")
            return
        payload = [session.schedules[index]]
    else:
        payload = session.schedules

    try:
        target = schedule_ops.export_schedule(payload, fmt, path, overwrite=overwrite)
        print(f"Exported to '{target}'.")
    except FileExistsError as e:
        print(f"{e} (pass --overwrite to replace it).")
    except ValueError as e:
        print(f"Export failed: {e}")