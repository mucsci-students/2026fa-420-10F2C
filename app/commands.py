# ----------------------------------------------------------------------------------------------------------------------- #
#   app/commands.py                                                                                                       #
#                                                                                                                         #
#   Every function here takes `session` (app/session.py) as its first argument   #
#   instead of doing its own file I/O.                                          #
#                                                                                 #
#   Implemented against the real library and tested -- all built on             #
#   CombinedConfig + edit_mode(), following the same recipe throughout:         #
#   require_config() -> prompt -> construct the library's real model ->         #
#   _apply_edit() + _mutate() closure -> catch ValidationFailure;               #
#   check_no_references() first for any delete_* that can leave a              #
#   dangling reference (room/lab/faculty/course):                              #
#     - Config lifecycle (Req #4): new/load/save/print/validate.                #
#     - Faculty CRUD -- the worked example everything else follows.             #
#     - Course CRUD (Req #5-7), room/lab CRUD including features + optional     #
#       weekday availability windows, timeslot CRUD + global timing options,    #
#       and meeting CRUD.                                                       #
#     - Class pattern CRUD (add/modify/delete_pattern), identified by list      #
#       index rather than a name/id -- see the comment block above              #
#       _list_patterns() for why.                                               #
#     - Global settings: generation limit, optimizer flags.        #
#     - Schedule generation/inspection/export (Req #8-10) -- schedule_ops.py    #
#       does the real work; export_schedule() here bounds-checks --index        #
#       before touching session.schedules so a bad index degrades to a         #
#       printed message instead of killing the session (Req #3).               #
# ----------------------------------------------------------------------------------------------------------------------- #

import re

from app.session import ConfigError
from app.crud import apply_edit, ReferenceError_, ValidationFailure, check_no_references
from app import schedule_ops

from scheduler.config import FacultyConfig, TimeBlock, LabConfig, RoomConfig, ValidationError, OptimizerFlags, ClassPattern, Meeting, CourseConfig

_VALID_DAYS = ("MON", "TUE", "WED", "THU", "FRI")
_VALID_OPTIMIZER_FLAGS = {
    "faculty_course", "faculty_room", "faculty_lab",
    "same_room", "same_lab", "pack_rooms", "pack_labs",
}

# Sentinel for "no current value was passed in" -- used wherever the
# actual current value of an optional field can legitimately be None
# (e.g. course.faculty, room/lab.times, faculty.mandatory_days), so
# that a real None can't be mistaken for "this is an add, not a
# modify." See the modify_*() functions below: each _prompt_*_fields()
# now takes the record being edited and shows/keeps its current values
# on a blank answer instead of silently wiping them (the bug behind
# a modify wiping out a course's rooms/labs/conflicts/faculty because
# the user left those blank expecting them to be left alone).
_UNSET = object()

def _apply_edit(session, config, area, mutate_fn):
    """Thin wrapper around crud.apply_edit that also marks the session
    dirty on success. Every CRUD command below calls this instead of
    apply_edit() directly, so shell.py can warn before exiting, starting
    a new config, or loading over unsaved changes -- one choke point for
    every entity (faculty/course/room/lab/timeslot/pattern/meeting/
    global settings all funnel through here) instead of repeating the
    dirty-flag logic in each command."""
    apply_edit(config, area, mutate_fn)
    session.dirty = True


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

_TIME_RANGE_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$")


def _format_day_blocks(blocks):
    return ", ".join(f"{_field(b, 'start')}-{_field(b, 'end')}" for b in blocks)


def _prompt_faculty_times(current=None):
    """Availability by weekday (Req: 'Times -- default 9-5, specify a
    day'). Per day: blank = keep the current value if editing an
    existing faculty member (else the default 09:00-17:00), 'n/a' =
    unavailable that day, or a custom HH:MM-HH:MM range."""
    print("Availability (Times) -- one entry per weekday: MON, TUE, WED, THU, FRI.")
    if current is not None:
        print("  Leave blank to keep that day's current value")
    else:
        print("  Leave blank for the default 09:00-17:00")
    print("  Type 'n/a' if unavailable that day")
    print("  Or enter a custom range like 09:30-15:00")
    times = {}
    for day in _VALID_DAYS:
        existing_blocks = current.get(day) if current else None
        shown = _format_day_blocks(existing_blocks) if existing_blocks else "unavailable"
        prompt = f"  {day} [{shown}]: " if current is not None else f"  {day}: "
        raw = input(prompt).strip()
        if raw.lower() in ("n/a", "na", "none", "unavailable"):
            continue
        if not raw:
            if current is not None:
                if existing_blocks:
                    times[day] = existing_blocks
                continue
            times[day] = [{"start": "09:00", "end": "17:00"}]
            continue
        if not _TIME_RANGE_RE.match(raw):
            print(f"  '{raw}' isn't a valid HH:MM-HH:MM range -- treating {day} as unavailable.")
            continue
        start, end = raw.split("-")
        times[day] = [{"start": start, "end": end}]
    return times


def _prompt_weighted_preferences(label, valid_names, ask_weight=True, max_weight=10, current=None):
    """Repeatedly asks for a name (and, unless ask_weight is False, a
    weight) until the user enters a blank name. Used for course/room/lab
    preferences.
    CONFIRMED (via a real validation error against the installed
    library) that a preference must name something that already
    exists in the config -- courses/rooms/labs that don't exist yet
    get rejected at save time with an 'unknown_faculty_*_preference'
    error. This contradicts the written Sprint 1 wording ('a course
    preference need not exist yet') -- worth confirming with whoever
    wrote that spec. Shows the valid options and re-prompts
    immediately on an unrecognized name, instead of silently
    collecting a name that will only fail much later when the whole
    record is saved.
    ask_weight=False skips the weight prompt entirely and stores the
    default weight (5) for every name -- used for room preferences,
    where a per-room weight was judged redundant with course weighting.
    max_weight caps the accepted range (course preferences use 5
    instead of the general 0-10).

    current: the faculty member's existing {label}_preferences dict,
    when editing. If given, it's shown up front and kept unchanged
    unless the user explicitly asks to redo it -- otherwise leaving
    this blank (to mean 'no change') would instead erase every
    preference of this kind."""
    if current is not None:
        shown = ", ".join(f"{n} ({w})" for n, w in current.items()) if current else "(none)"
        print(f"  Current {label} preferences: {shown}")
        keep = input(f"  Keep these {label} preferences as-is? (Y/n): ").strip().lower()
        if keep not in ("n", "no"):
            return dict(current)

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





def _prompt_mandatory_days(times, current=_UNSET):
    """Which weekdays this faculty member MUST be scheduled on (Req #5:
    the Faculty row explicitly lists 'mandatory days' as required
    editable data). Previously missing entirely -- _format_faculty()
    displayed f.mandatory_days but nothing ever prompted for it, so
    every faculty member got the model's default regardless of intent.

    CONFIRMED against the scheduler library's own example.json
    (github.com/mucsci/Scheduler, matches the course-constraint-scheduler
    version pinned in pyproject.toml): mandatory_days is an OPTIONAL
    list of the same day-code strings used in `times`
    (e.g. ["MON", "WED", "FRI"]) -- several faculty entries in that
    example have no mandatory_days key at all, and it's fine to omit it.

    Restricted here to days the faculty is actually available on: every
    faculty entry with mandatory_days in the confirmed example data also
    has a non-empty `times` block for each of those days, and a
    mandatory day with no available time would be rejected by edit_mode()
    anyway -- this just surfaces that as an immediate, specific message.

    Returns None (omit the field, let the library default apply) if the
    user leaves this blank.

    current: the faculty member's existing mandatory_days (a list, or
    None) when editing. If given (current is not _UNSET), a blank
    answer keeps it instead of clearing it.
    """
    available_days = [d for d in _VALID_DAYS if times.get(d)]
    if not available_days:
        print("  No available days set -- skipping mandatory days.")
        return None if current is _UNSET else current

    print(f"  Mandatory days (must be scheduled every term) -- choose from: {', '.join(available_days)}")
    if current is not _UNSET:
        shown = ", ".join(current) if current else "(none)"
        print(f"  Current: {shown}")
        print("  Comma-separated to replace, or blank to keep as-is:")
    else:
        print("  Comma-separated, or blank for none:")
    raw = input("  > ").strip()
    if not raw:
        return current if current is not _UNSET else None

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


def _prompt_faculty_fields(config, existing=None):
    """Same interactive prompts as the old facultyComm.py -- reuse that
    UX, just stop building a plain dict for a hand-rolled validator and
    build kwargs for the library's real Faculty model instead.

    existing: the FacultyConfig being edited, or None when adding a new
    one. When given, every field is shown with its current value and a
    blank answer keeps it -- previously modify_faculty() called this
    with no way to keep anything, so leaving any field blank silently
    reset it (times to unavailable, preferences to none, etc.)."""
    if existing is not None:
        print(f"Enter the faculty's name [{existing.name}] (blank to keep):")
    else:
        print("Enter the faculty's name:")
    name = input().strip() or (existing.name if existing is not None else "")

    if existing is not None:
        print(f"  Current credit range: {existing.minimum_credits}-{existing.maximum_credits}, "
              f"unique course limit: {existing.unique_course_limit}")
        print('  Change to full-time or adjunct defaults? (Enter "full", "adjunct", or '
              'blank to keep the current numbers as-is):')
        kind = input().lower().replace(" ", "")
        if kind == "adjunct":
            max_credits, min_credits, unique_course_limit = 4, 0, 1
        elif kind == "full":
            max_credits, min_credits, unique_course_limit = 12, 0, 2
        else:
            max_credits = existing.maximum_credits
            min_credits = existing.minimum_credits
            unique_course_limit = existing.unique_course_limit
    else:
        print('Are they full-time or adjunct? (Enter "full" or "adjunct") (Default: full)')
        kind = input().lower().replace(" ", "")
        if kind == "adjunct":
            max_credits, min_credits, unique_course_limit = 4, 0, 1
        else:
            max_credits, min_credits, unique_course_limit = 12, 0, 2

    times = _prompt_faculty_times(current=(existing.times if existing is not None else None))
    mandatory_days = _prompt_mandatory_days(
        times, current=(existing.mandatory_days if existing is not None else _UNSET))

    course_ids = {c.course_id for c in config.config.courses}
    room_names = {r.name for r in config.config.rooms}
    lab_names = {l.name for l in config.config.labs}

    print("Preferences:")
    course_preferences = _prompt_weighted_preferences(
        "course", course_ids, max_weight=5,
        current=(existing.course_preferences if existing is not None else None))
    room_preferences = _prompt_weighted_preferences(
        "room", room_names, ask_weight=False,
        current=(existing.room_preferences if existing is not None else None))
    lab_preferences = _prompt_weighted_preferences(
        "lab", lab_names, current=(existing.lab_preferences if existing is not None else None))

    fields = {
        "name": name,
        "maximum_credits": max_credits,
        "minimum_credits": min_credits,
        "unique_course_limit": unique_course_limit,
        "times": times,
        "course_preferences": course_preferences,
        "room_preferences": room_preferences,
        "lab_preferences": lab_preferences,
    }
    if mandatory_days is not None:
        fields["mandatory_days"] = mandatory_days
    return fields


def add_faculty(session):
    config = session.require_config()
    fields = _prompt_faculty_fields(config)
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
        _apply_edit(session, config, "faculty", _mutate)
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

    # Collect edited fields the same way add_faculty does, but seeded
    # with the existing record so a blank answer keeps that field
    # instead of wiping it (mirrors the old modify_faculty's "pull the
    # record out, ask what to change" flow -- the seeding is the part
    # that was missing before).
    updated_fields = _prompt_faculty_fields(config, existing=existing)

    def _mutate(cfg):
        faculty_list = cfg.config.faculty
        faculty_list.remove(existing)
        faculty_list.append(FacultyConfig(**updated_fields))

    try:
        _apply_edit(session, config, "faculty", _mutate)
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
    referencing_courses = [c.course_id for c in config.config.courses if name in (getattr(c, "faculty", None) or [])]
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
        _apply_edit(session, config, "faculty", _mutate)
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
#  Course CRUD (Req #5, #6, #7).
#  - Repeated course_id values are legal (they create sections), so
#    modify/delete pick by list index like patterns do, not by name.
#  - modify assigns in place: section numbers come from list position,
#    so remove+append would renumber other sections of the same id.
#  - delete only checks references when removing the LAST section of a
#    course_id -- conflicts/preferences point at the id, not a section.
# =========================================================================== #

def _enabled_pattern_credits(config):
    """Credit values that have at least one enabled class pattern."""
    return sorted({p.credits for p in config.time_slot_config.classes if not p.disabled})
 
 
def _course_display_name(course, seen_counts):
    """'CS 101.A' or 'CS 101.01' -- matches the library's own section naming."""
    count = seen_counts.get(course.course_id, 0) + 1
    seen_counts[course.course_id] = count
    return f"{course.course_id}.{course.section_id or f'{count:02d}'}"
 
 
def _format_course(index, course, display):
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
 
 
def _list_courses(config):
    courses = config.config.courses
    if not courses:
        print("(no courses defined)")
        return courses
    seen = {}
    for i, c in enumerate(courses):
        print(_format_course(i, c, _course_display_name(c, seen)))
    return courses
 
 
def _prompt_course_index(count):
    raw = input("Enter the course's index: ").strip()
    if not raw.isdigit():
        print("Please enter a valid integer index.")
        return None
    idx = int(raw)
    if not (0 <= idx < count):
        print(f"No course at index {idx}. Valid range: 0-{count - 1}.")
        return None
    return idx
 
 
def _prompt_name_list(label, valid_names, current=_UNSET):
    """Collects names from `valid_names` until a blank line.

    current: the record's existing list for this field when editing
    (may itself be None -- e.g. a course's candidate faculty when it's
    meant to be derived from preferences). If given, it's shown up
    front and kept as-is unless the user explicitly asks to redo it --
    otherwise a blank first answer would wipe the list rather than
    leave it alone."""
    if current is not _UNSET:
        shown = ", ".join(sorted(current)) if current else "(none)"
        print(f"  Current {label}s: {shown}")
        keep = input(f"  Keep these {label}s as-is? (Y/n): ").strip().lower()
        if keep not in ("n", "no"):
            return list(current) if current is not None else None

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
 
 
def _prompt_feature_set(label, current=_UNSET):
    """current: the existing required-feature set for this field when
    editing. If given, shown up front and kept on a blank answer
    instead of being cleared to no requirements."""
    if current is not _UNSET:
        shown = ", ".join(sorted(current)) if current else "(none)"
        raw = input(f"  Required {label} features [{shown}] "
                    f"(blank = keep, or enter a new comma-separated list): ").strip()
        if not raw:
            return set(current) if current else set()
        return {part.strip() for part in raw.split(",") if part.strip()}
    raw = input(f"  Required {label} features (comma-separated, blank for none): ").strip()
    return {part.strip() for part in raw.split(",") if part.strip()} if raw else set()
 
 
def _prompt_positive_int(prompt_text, label, current=_UNSET):
    """current: the field's existing value when editing. If given, a
    blank answer keeps it instead of looping forever demanding a
    number (there's nothing to type to 'keep the current value'
    otherwise)."""
    while True:
        raw = input(prompt_text).strip()
        if not raw and current is not _UNSET:
            return current
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
        print(f"{label} must be a positive whole number!")
 
 
def _prompt_course_fields(config, existing=None):
    """existing: the CourseConfig being edited, or None when adding a
    new one. When given, every field below is shown with its current
    value and a blank answer keeps it, instead of forcing the whole
    record to be retyped from scratch (which is what let a course's
    course_id accidentally get typo'd, and its rooms/labs/conflicts/
    faculty candidates get silently wiped to empty, in real use)."""
    scheduler_config = config.config

    if existing is not None:
        print(f"Course ID [{existing.course_id}] (blank to keep):")
        course_id = input().strip() or existing.course_id
    else:
        while True:
            course_id = input("Course ID (e.g. 'CS 101'): ").strip()
            if course_id:
                break
            print("Course ID cannot be blank.")

    if existing is not None:
        shown = existing.section_id if existing.section_id is not None else "(auto-numbered)"
        section_raw = input(f"Section ID [{shown}] (blank to keep, '-' to clear): ").strip()
        if not section_raw:
            section_id = existing.section_id
        elif section_raw == "-":
            section_id = None
        else:
            section_id = section_raw
    else:
        section_id = input("Section ID (blank = auto-number by input order): ").strip() or None

    available = _enabled_pattern_credits(config)
    if available:
        print(f"  Credit values with an enabled class pattern: {', '.join(str(c) for c in available)}")
    else:
        print("  (warning: no enabled class patterns exist -- any course will be rejected)")
    if existing is not None:
        credits = _prompt_positive_int(f"Credits [{existing.credits}] (blank to keep): ",
                                        "Credits", current=existing.credits)
    else:
        credits = _prompt_positive_int("Credits: ", "Credits")
    if available and credits not in available:
        print(f"  Note: no enabled pattern has {credits} credits, so this will be rejected "
              f"until you add one (Class Meeting Patterns -> Add).")

    if existing is not None:
        capacity = _prompt_positive_int(
            f"Expected enrollment (capacity) [{existing.capacity}] (blank to keep): ",
            "Capacity", current=existing.capacity)
    else:
        capacity = _prompt_positive_int("Expected enrollment (capacity): ", "Capacity")

    while True:
        if existing is not None:
            modality = input(f"Modality (in_person/online/hybrid) [{existing.modality}] "
                              f"(blank to keep): ").strip().lower() or existing.modality
        else:
            modality = (input("Modality (in_person/online/hybrid, default in_person): ").strip().lower()
                        or "in_person")
        if modality in ("in_person", "online", "hybrid"):
            break
        print("  Modality must be one of: in_person, online, hybrid.")

    rooms, labs = [], []
    required_room_features, required_lab_features = set(), set()
    reserve_room_during_lab = existing.reserve_room_during_lab if existing is not None else True

    # Online courses may not carry rooms, labs, or room features, so don't ask.
    if modality == "online":
        print("  (online course -- skipping rooms, labs, and feature requirements)")
    else:
        print("Candidate rooms (blank list is valid only for patterns that occupy no room):")
        rooms = _prompt_name_list("room", [r.name for r in scheduler_config.rooms],
                                   current=(existing.room if existing is not None else _UNSET))
        if rooms:
            required_room_features = _prompt_feature_set(
                "room", current=(existing.required_room_features if existing is not None else _UNSET))

        print("Candidate labs (leave empty if this course has no lab meeting):")
        labs = _prompt_name_list("lab", [lab.name for lab in scheduler_config.labs],
                                  current=(existing.lab if existing is not None else _UNSET))
        if labs:
            required_lab_features = _prompt_feature_set(
                "lab", current=(existing.required_lab_features if existing is not None else _UNSET))
            reserve_default = "y" if reserve_room_during_lab else "n"
            answer = input(f"  Should the lab meeting also occupy the lecture room? "
                            f"(y/n, default {reserve_default}): ")
            answer = answer.strip().lower()
            if answer:
                reserve_room_during_lab = answer not in ("n", "no")

    print("Conflicting courses (sections of these can never overlap):")
    conflicts = _prompt_name_list(
        "conflict course",
        sorted({c.course_id for c in scheduler_config.courses if c.course_id != course_id}),
        current=(existing.conflicts if existing is not None else _UNSET),
    )

    print("Faculty candidates (leave empty to derive them from faculty course preferences):")
    faculty = _prompt_name_list("faculty", [f.name for f in scheduler_config.faculty],
                                 current=(existing.faculty if existing is not None else _UNSET))

    return {
        "course_id": course_id,
        "section_id": section_id,
        "credits": credits,
        "capacity": capacity,
        "room": rooms,
        "lab": labs,
        "conflicts": conflicts,
        "faculty": faculty or None,  # [] is rejected; None = derive from preferences
        "modality": modality,
        "required_room_features": required_room_features,
        "required_lab_features": required_lab_features,
        "reserve_room_during_lab": reserve_room_during_lab,
    }
 
 
def add_course(session):
    config = session.require_config()
    fields = _prompt_course_fields(config)
 
    try:
        new_course = CourseConfig(**fields)
    except ValidationError as e:
        print(f"Could not add course: {e}")
        return
 
    def _mutate(cfg):
        cfg.config.courses.append(new_course)
 
    try:
        _apply_edit(session, config, "course", _mutate)
        print("Course added.")
    except ValidationFailure as e:
        print(f"Could not add course: {e}")
 
 
def modify_course(session):
    config = session.require_config()
    courses = _list_courses(config)
    if not courses:
        return
 
    index = _prompt_course_index(len(courses))
    if index is None:
        return
 
    fields = _prompt_course_fields(config, existing=courses[index])
 
    try:
        updated_course = CourseConfig(**fields)
    except ValidationError as e:
        print(f"Could not save changes, previous version kept: {e}")
        return
 
    def _mutate(cfg):
        cfg.config.courses[index] = updated_course
 
    try:
        _apply_edit(session, config, "course", _mutate)
        print("Course updated.")
    except ValidationFailure as e:
        print(f"Could not save changes, previous version kept: {e}")
 
 
def delete_course(session):
    config = session.require_config()
    courses = _list_courses(config)
    if not courses:
        return
 
    index = _prompt_course_index(len(courses))
    if index is None:
        return
 
    existing = courses[index]
    course_id = existing.course_id
 
    last_section = not any(c.course_id == course_id for i, c in enumerate(courses) if i != index)
    if last_section:
        referenced_by = [
            f"course '{c.course_id}' (conflicts)"
            for i, c in enumerate(courses)
            if i != index and course_id in c.conflicts
        ]
        referenced_by += [
            f"faculty '{f.name}' (course preference)"
            for f in config.config.faculty
            if course_id in f.course_preferences
        ]
        try:
            check_no_references(course_id, referenced_by)
        except ReferenceError_ as e:
            print(f"{e} -- remove those references first.")
            return
 
    print("Are you sure you want to delete this course? This cannot be undone. (y/n)")
    if input().strip().lower() not in ("y", "yes"):
        print("Removal cancelled")
        return
 
    def _mutate(cfg):
        del cfg.config.courses[index]
 
    try:
        _apply_edit(session, config, "course", _mutate)
        print("Course removed.")
    except ValidationFailure as e:
        print(f"Could not remove course: {e}")
 
 
def view_course(session):
    config = session.require_config()
    if not config.config.courses:
        print("(no courses defined)")
        return
    seen = {}
    for i, c in enumerate(config.config.courses):
        if i > 0:
            print()
        print(_format_course(i, c, _course_display_name(c, seen)))

def _prompt_lab_fields(existing=None):
    """existing: the LabConfig being edited, or None when adding. When
    given, name/capacity/features/availability are all shown with
    their current values and a blank answer keeps them."""
    if existing is not None:
        name = input(f"Enter the lab's name [{existing.name}] (blank to keep): ").strip() or existing.name
        capacity = _prompt_positive_int(
            f"Enter the lab's max student capacity [{existing.capacity}] (blank to keep): ",
            "Lab capacity", current=existing.capacity)
        features = _prompt_supplied_features("lab", current=existing.features)
        times = _prompt_resource_availability("lab", current=existing.times)
    else:
        while True:
            name = input("Enter the lab's name: ").strip()
            if name:
                break
            print("Lab name cannot be blank.")

        while True:
            capacity_input = input("Enter the lab's max student capacity: ").strip()
            try:
                capacity = int(capacity_input)
                if capacity > 0:
                    break
            except ValueError:
                pass
            print("Lab capacity must be a positive whole number!")

        features = _prompt_supplied_features("lab")
        times = _prompt_resource_availability("lab")

    fields = {
        "name": name,
        "capacity": capacity,
        "features": features,
    }
    if times is not None:
        fields["times"] = times
    return fields


def add_lab(session):
    config = session.require_config()
    fields = _prompt_lab_fields()

    if any(lab.name == fields["name"] for lab in config.config.labs):
        print("Lab is already in the system!")
        return

    new_lab = LabConfig(**fields)

    def _mutate(cfg):
        cfg.config.labs.append(new_lab)

    try:
        _apply_edit(session, config, "lab", _mutate)
        print("Lab added.")
    except ValidationFailure as e:
        print(f"Could not add lab: {e}")


def modify_lab(session):
    config = session.require_config()
    target_name = input("What is the name of the lab you would like to edit? ").strip()
    existing = next(
        (lab for lab in config.config.labs if lab.name == target_name),
        None,
    )

    if existing is None:
        print("Lab does not exist!")
        return

    fields = _prompt_lab_fields(existing=existing)

    if fields["name"] != target_name and any(
        lab.name == fields["name"] for lab in config.config.labs):
        print("Lab name is already in the system!")
        return

    updated_lab = LabConfig(**fields)

    def _mutate(cfg):
        lab_list = cfg.config.labs
        lab_list.remove(existing)
        lab_list.append(updated_lab)

    try:
        _apply_edit(session, config, "lab", _mutate)
        print("Lab updated.")
    except ValidationFailure as e:
        print(f"Could not save changes, previous version kept: {e}")


def delete_lab(session):
    config = session.require_config()

    name = input("What is the name of the lab you want to remove? ")

    existing = next(
        (lab for lab in config.config.labs if lab.name == name),
        None,
    )
    if existing is None:
        print("Lab does not exist!")
        return
    referencing_courses = [
        course.course_id
        for course in config.config.courses
        if name in course.lab
    ]

    try:
        check_no_references(name, referencing_courses)
    except ReferenceError_ as e:
        print(f"{e} -- remove this lab from those courses first")
        return

    print("Are you sure you want to delete this lab? This cannot be undone (y/n)")
    if input().lower().strip() not in ("yes", "y"):
        print("Removal cancelled")
        return

    def _mutate(cfg):
        cfg.config.labs.remove(existing)

    try:
        _apply_edit(session, config, "lab", _mutate)
        print("Lab removed.")
    except ValidationFailure as e:
        print(f"Could not remove lab: {e}")

def _format_lab(index, lab):
    lines = [f"[{index}] {lab.name} -- capacity {lab.capacity}"]
    if lab.features:
        lines.append(f"      Features: {', '.join(sorted(lab.features))}")
    if lab.times:
        lines.append("      Availability:")
        for day in _VALID_DAYS:
            blocks = _field(lab.times, day)
            if not blocks:
                continue
            ranges = ", ".join(f"{_field(b, 'start')}-{_field(b, 'end')}" for b in blocks)
            lines.append(f"        {_DAY_LABELS[day]}  {ranges}")
    else:
        lines.append("      Availability: unrestricted")
    return "\n".join(lines)


def view_lab(session):
    config = session.require_config()
    if not config.config.labs:
        print("(no labs defined)")
        return
    for i, l in enumerate(config.config.labs):
        if i > 0:
            print()
        print(_format_lab(i, l))

def _prompt_supplied_features(label, current=_UNSET):
    """Features/equipment tags this room or lab itself SUPPLIES
    (RoomConfig.features / LabConfig.features -- confirmed via
    model_json_schema(): list[str], unique). Distinct from
    _prompt_feature_set(), which collects a COURSE's *required*
    features -- this collects what the resource itself provides.

    current: the existing features list when editing. If given, shown
    up front and kept on a blank answer instead of being cleared."""
    if current is not _UNSET:
        shown = ", ".join(sorted(current)) if current else "(none)"
        raw = input(f"  Features this {label} provides [{shown}] "
                    f"(blank = keep, or enter a new comma-separated list): ").strip()
        if not raw:
            return sorted(current) if current else []
        return sorted({part.strip() for part in raw.split(",") if part.strip()})
    raw = input(f"  Features this {label} provides (comma-separated, blank for none): ").strip()
    return sorted({part.strip() for part in raw.split(",") if part.strip()}) if raw else []


def _prompt_resource_availability(label, current=_UNSET):
    """Optional weekday availability windows for a room/lab
    (RoomConfig.times / LabConfig.times -- confirmed via
    model_json_schema(): optional dict[Day, list[TimeRange]],
    default null = unrestricted).

    ASSUMPTION, not yet confirmed the way Faculty.times' semantics
    were: a weekday left out of the mapping means the resource is
    NOT available that day, mirroring Faculty.times on the same
    TimeRange shape. Re-check against a real validation/schedule
    result before trusting this if a generated schedule looks wrong
    for a restricted room/lab.

    current: the existing `times` value (a dict, or None if
    unrestricted) when editing. If given, it's shown and kept unless
    the user explicitly asks to change it -- editing used to re-ask
    this from scratch every time, silently un-restricting a room/lab
    whenever the answer was left at the default 'n'.
    """
    if current is not _UNSET:
        if current:
            lines = []
            for day in _VALID_DAYS:
                blocks = _field(current, day)
                if blocks:
                    lines.append(f"{day} {_format_day_blocks(blocks)}")
            shown = "; ".join(lines) if lines else "unrestricted"
        else:
            shown = "unrestricted"
        print(f"  Current availability: {shown}")
        change = input(f"  Change this {label}'s availability? (y/N): ").strip().lower()
        if change not in ("y", "yes"):
            return current

    restrict = input(
        f"  Restrict this {label}'s availability? (y/n, default n = available any time): "
    ).strip().lower() in ("y", "yes")
    if not restrict:
        return None

    print(f"  Enter availability for this {label}, one entry per weekday: MON, TUE, WED, THU, FRI.")
    print("  Leave blank if unavailable that day, or enter a range like 09:00-17:00")
    times = {}
    for day in _VALID_DAYS:
        raw = input(f"  {day}: ").strip()
        if not raw:
            continue
        if not _TIME_RANGE_RE.match(raw):
            print(f"  '{raw}' isn't a valid HH:MM-HH:MM range -- treating {day} as unavailable.")
            continue
        start, end = raw.split("-")
        times[day] = [{"start": start, "end": end}]
    return times or None


def _prompt_room_fields(existing=None):
    """existing: the RoomConfig being edited, or None when adding. When
    given, name/capacity/features/availability are all shown with
    their current values and a blank answer keeps them."""
    if existing is not None:
        name = input(f"Enter the room's name [{existing.name}] (blank to keep): ").strip() or existing.name
        capacity = _prompt_positive_int(
            f"Enter the room's max student capacity [{existing.capacity}] (blank to keep): ",
            "Room capacity", current=existing.capacity)
        features = _prompt_supplied_features("room", current=existing.features)
        times = _prompt_resource_availability("room", current=existing.times)
    else:
        while True:
            name = input("Enter the room's name: ").strip()
            if name:
                break
            print("Room name cannot be blank.")

        while True:
            capacity_input = input("Enter the room's max student capacity: ").strip()
            try:
                capacity = int(capacity_input)
                if capacity > 0:
                    break
            except ValueError:
                pass
            print("Room capacity must be a positive whole number!")

        features = _prompt_supplied_features("room")
        times = _prompt_resource_availability("room")

    fields = {
        "name": name,
        "capacity": capacity,
        "features": features,
    }
    if times is not None:
        fields["times"] = times
    return fields


def add_room(session):
    config = session.require_config()
    fields = _prompt_room_fields()

    if any(room.name == fields["name"] for room in config.config.rooms):
        print("Room is already in the system!")
        return

    new_room = RoomConfig(**fields)

    def _mutate(cfg):
        cfg.config.rooms.append(new_room)

    try:
        _apply_edit(session, config, "room", _mutate)
        print("Room added.")
    except ValidationFailure as e:
        print(f"Could not add room: {e}")

def modify_room(session):
    config = session.require_config()
    target_name = input("What is the name of the room you would like to edit? ").strip()
    existing = next(
        (room for room in config.config.rooms if room.name == target_name),
        None,
    )

    if existing is None:
        print("Room does not exist!")
        return

    fields = _prompt_room_fields(existing=existing)
    if fields["name"] != target_name and any(
        room.name == fields["name"] for room in config.config.rooms
    ):
        print("Room name is already in the system!")
        return

    updated_room = RoomConfig(**fields)

    def _mutate(cfg):
        room_list = cfg.config.rooms
        room_list.remove(existing)
        room_list.append(updated_room)

    try:
        _apply_edit(session, config, "room", _mutate)
        print("Room updated.")
    except ValidationFailure as e:
        print(f"Could not save changes, previous version kept: {e}")


def delete_room(session):
    config = session.require_config()
    name = input("What is the name of the room you want to remove? ").strip()

    existing = next(
        (room for room in config.config.rooms if room.name == name),
        None,
    )
    if existing is None:
        print("Room does not exist!")
        return

    referencing_courses = [
        course.course_id
        for course in config.config.courses
        if name in (getattr(course, "room", None) or [])
    ]
    try:
        check_no_references(name, referencing_courses)
    except ReferenceError_ as e:
        print(f"{e} -- remove this room from those courses first.")
        return

    print("Are you sure you want to delete this room? This cannot be undone. (y/n)")
    if input().strip().lower() not in ("y", "yes"):
        print("Removal cancelled")
        return

    def _mutate(cfg):
        cfg.config.rooms.remove(existing)

    try:
        _apply_edit(session, config, "room", _mutate)
        print("Room removed.")
    except ValidationFailure as e:
        print(f"Could not remove room: {e}")

def _format_room(index, room):
    lines = [f"[{index}] {room.name} -- capacity {room.capacity}"]
    if room.features:
        lines.append(f"      Features: {', '.join(sorted(room.features))}")
    if room.times:
        lines.append("      Availability:")
        for day in _VALID_DAYS:
            blocks = _field(room.times, day)
            if not blocks:
                continue
            ranges = ", ".join(f"{_field(b, 'start')}-{_field(b, 'end')}" for b in blocks)
            lines.append(f"        {_DAY_LABELS[day]}  {ranges}")
    else:
        lines.append("      Availability: unrestricted")
    return "\n".join(lines)


def view_room(session):
    config = session.require_config()
    if not config.config.rooms:
        print("(no rooms defined)")
        return
    for i, r in enumerate(config.config.rooms):
        if i > 0:
            print()
        print(_format_room(i, r))

def _prompt_time_block(existing=None):
    """existing: the TimeBlock being edited, or None when adding a new
    one. When given, each field is shown with its current value and a
    blank answer keeps it -- modify_timeslot used to re-ask all three
    from scratch with no indication of the block being changed."""
    if existing is not None:
        start = input(f"Start time (HH:MM) [{existing.start}] (blank to keep): ").strip() or existing.start
        end = input(f"End time (HH:MM) [{existing.end}] (blank to keep): ").strip() or existing.end
        spacing_raw = input(
            f"Spacing between slots, in minutes [{existing.spacing}] (blank to keep): "
        ).strip()
        spacing = existing.spacing if not spacing_raw else spacing_raw
    else:
        print("Start time (HH:MM)?")
        start = input().strip()
        print("End time (HH:MM)?")
        end = input().strip()
        print("Spacing between slots, in minutes?")
        spacing_raw = input().strip()
        spacing = spacing_raw

    try:
        spacing = int(spacing)
    except ValueError:
        print(f"'{spacing}' is not a valid number of minutes.")
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
        _apply_edit(session, config, "timeslot", _mutate)
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
    new_block = _prompt_time_block(existing=blocks[idx])
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
        _apply_edit(session, config, "timeslot", _mutate)
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
        _apply_edit(session, config, "timeslot", _mutate)
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
        _apply_edit(session, config, "timeslot", _mutate)
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

def _prompt_meeting(existing=None):
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
    ValidationError propagate uncaught and crash the app.

    existing: the Meeting being edited, or None when adding a new one.
    When given, every field is shown with its current value and a
    blank answer keeps it -- modify_meeting used to re-collect an
    entirely new Meeting from scratch with nothing shown of the one
    being replaced."""
    while True:
        if existing is not None:
            print(f"  Day (MON/TUE/WED/THU/FRI) [{existing.day}] (blank to keep):")
            day = input("  > ").strip().upper() or existing.day

            print(f"  Duration in minutes [{existing.duration}] (blank to keep):")
            duration_raw = input("  > ").strip()
            duration = int(duration_raw) if duration_raw.isdigit() else existing.duration

            print(f"  Is this meeting a lab session? (y/n) [{'y' if existing.lab else 'n'}] (blank to keep):")
            lab_raw = input("  > ").strip().lower()
            lab = (lab_raw in ("y", "yes")) if lab_raw else existing.lab

            print(f"  Delivery mode (in_person/online/hybrid) [{existing.delivery}] (blank to keep):")
            delivery = input("  > ").strip().lower() or existing.delivery

            shown_start = existing.start_time if existing.start_time else "(none)"
            print(f"  Fixed start time for this meeting, e.g. 09:00 [{shown_start}] "
                  f"(blank to keep, '-' to clear):")
            start_raw = input("  > ").strip()
            if not start_raw:
                start_time = existing.start_time
            elif start_raw == "-":
                start_time = None
            else:
                start_time = start_raw
        else:
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


def _prompt_pattern_fields(existing=None):
    """Prompts for one class-pattern record: credits, and the two
    optional fields (start_time, disabled) seen on some entries in
    config_example.json.

    existing: the ClassPattern being edited, or None when adding a new
    one. When given, credits/start_time/disabled are shown with their
    current values and a blank answer keeps them. Meetings are NOT
    re-collected here even when editing -- they have their own
    dedicated Add/Modify/Delete under the Meeting menu, so modifying a
    pattern's credits/timing no longer risks silently discarding and
    having to blindly retype every one of its meetings."""
    if existing is not None:
        print(f"Credits for this pattern [{existing.credits}] (blank to keep):")
        credits_raw = input().strip()
        credits = int(credits_raw) if credits_raw.isdigit() else existing.credits

        meetings = list(existing.meetings)
        print(f"  (keeping this pattern's {len(meetings)} existing meeting(s) unchanged -- "
              f"edit those via Configuration -> Meetings)")

        shown_start = existing.start_time if existing.start_time else "(none)"
        print(f"Fixed start time for this pattern, e.g. 16:00 [{shown_start}] "
              f"(blank to keep, '-' to clear):")
        start_raw = input().strip()
        if not start_raw:
            start_time = existing.start_time
        elif start_raw == "-":
            start_time = None
        else:
            start_time = start_raw

        print(f"Should this pattern start disabled? (y/n) [{'y' if existing.disabled else 'n'}] "
              f"(blank to keep):")
        disabled_raw = input().strip().lower()
        disabled = (disabled_raw in ("y", "yes")) if disabled_raw else existing.disabled
    else:
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
        f"{_DAY_LABELS.get(m.day, m.day)} {m.duration}min" + (" (lab)" if getattr(m, "lab", False) else "")
        for m in pattern.meetings
    )
    extras = []
    if getattr(pattern, "start_time", None):
        extras.append(f"starts at {pattern.start_time}")
    if getattr(pattern, "disabled", False):
        extras.append("disabled")
    extra_str = f"  ({'; '.join(extras)})" if extras else ""
    return f"[{index}] {pattern.credits} credits: {meeting_bits}{extra_str}"


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
        _apply_edit(session, config, "pattern", _mutate)
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

    updated_fields = _prompt_pattern_fields(existing=patterns[idx])
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
        _apply_edit(session, config, "pattern", _mutate)
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
        _apply_edit(session, config, "pattern", _mutate)
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
        day = _DAY_LABELS.get(m.day, m.day)
        lab_str = " (lab session)" if getattr(m, "lab", False) else ""
        extras = []
        if getattr(m, "delivery", None):
            extras.append(f"delivery: {m.delivery}")
        if getattr(m, "start_time", None):
            extras.append(f"starts at {m.start_time}")
        extra_str = f"  ({'; '.join(extras)})" if extras else ""
        print(f"  [{i}] {day}, {m.duration} min{lab_str}{extra_str}")
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
        _apply_edit(session, config, "meeting", _mutate)
        print("Meeting added.")
    except ValidationFailure as e:
        print(f"Could not add meeting: {e}")


def modify_meeting(session):
    config = session.require_config()
    choice = _choose_pattern_and_meeting(config)
    if choice is None:
        return
    p_idx, m_idx = choice

    existing_meeting = config.time_slot_config.classes[p_idx].meetings[m_idx]
    updated_meeting = _prompt_meeting(existing=existing_meeting)

    def _mutate(cfg):
        cfg.time_slot_config.classes[p_idx].meetings[m_idx] = updated_meeting

    try:
        _apply_edit(session, config, "meeting", _mutate)
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
        _apply_edit(session, config, "meeting", _mutate)
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
        _apply_edit(session, config, "global_settings", _mutate)
        print(f"Generation limit set to {value}.")
    except ValidationFailure as e:
        print(f"Could not set limit: {e}")


def reset_generation_limit(session):
    config = session.require_config()

    def _mutate(cfg):
        cfg.limit = 10  # confirmed library default

    try:
        _apply_edit(session, config, "global_settings", _mutate)
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
        _apply_edit(session, config, "global_settings", _mutate)
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
        _apply_edit(session, config, "global_settings", _mutate)
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
    except OSError as e:
        print(f"Export failed: could not write to that location ({e}).")