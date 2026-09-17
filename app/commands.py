# ----------------------------------------------------------------------------------------------------------------------- #
#   app/commands.py                                                                                                       #
#                                                                                                                         #
#   Every function here now takes `session` (app/session.py) as its first        #
#   argument instead of doing its own file I/O. Config lifecycle and schedule    #
#   commands are implemented against the real library. Faculty is rewritten as   #
#   the worked CRUD example, built on CombinedConfig + edit_mode() instead of     #
#   the old hand-rolled facultyModel.py. The other entity types are left as      #
#   clearly-marked TODOs following the exact same pattern -- see the comment     #
#   block above add_course() for the recipe.                                     #
#                                                                                 #
#   CONFIRM (see session.py / crud.py / schedule_ops.py docstrings for the       #
#   full list): the exact Pydantic class name for a faculty record inside        #
#   scheduler.config (guessed as `Faculty` below -- check with                   #
#   `python -c "import scheduler.config as c; print([n for n in dir(c) if not   #
#   n.startswith('_')])"` once the library is installed, and fix the single      #
#   import line marked below if the name differs).                              #
# ----------------------------------------------------------------------------------------------------------------------- #

from app.session import ConfigError
from app.crud import apply_edit, ValidationFailure, check_no_references
from app import schedule_ops

# ---- CONFIRM this import: the nested faculty model's real name/location. ----
from scheduler.config import FacultyConfig

# ---- CONFIRM these too: class-pattern CRUD below (add/modify/delete_pattern)
# needs the model class(es) for one entry of time_slot_config.classes and its
# nested meetings. Guessed as ClassConfig / MeetingConfig by analogy with
# FacultyConfig above (JSON key "classes" -> "ClassConfig", singular of the
# nested "meetings" list -> "MeetingConfig") -- NOT verified against
# scheduler.config's real exports. Check with:
#   uv run python -c "import scheduler.config as c; print([n for n in dir(c) if not n.startswith('_')])"
# and fix these two names (and cfg.time_slot_config.classes below, if the
# attribute itself is named differently than the JSON key) once confirmed.
from scheduler.config import ClassConfig, MeetingConfig

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


def view_faculty(session):
    config = session.require_config()
    if not config.config.faculty:
        print("(no faculty defined)")
        return
    for f in config.config.faculty:
        print(f.model_dump_json(indent=2))


# =========================================================================== #
#  TODO: course / lab / room / timeslot / pattern / meeting CRUD
#
#  Follow the exact recipe used above for faculty:
#    1. session.require_config() to get the live CombinedConfig.
#    2. Prompt for fields; construct the library's real nested model
#       (Course / Room / Lab / TimeSlot / ClassPattern / Meeting -- confirm
#       exact names in scheduler.config, same as Faculty above).
#    3. Build a small _mutate(cfg) closure that appends/replaces/removes
#       from the right list on cfg.config (or cfg.time_slot_config for
#       timeslots/patterns/meetings, per the JSON shape in the Sprint 1
#       doc).
#    4. Wrap it in apply_edit(config, "<area>", _mutate) and catch
#       ValidationFailure.
#    5. For delete_*, scan for references first (check_no_references) --
#       e.g. deleting a room needs to check courses' room lists and any
#       class patterns/meetings pinned to it.
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


def add_timeslot(session):
    print("TODO")

def modify_timeslot(session):
    print("TODO")

def delete_timeslot(session):
    print("TODO")


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
    """One {day, duration, lab} entry, per the meetings shape confirmed
    in config_example.json's time_slot_config.classes."""
    print("  Day (MON/TUE/WED/THU/FRI):")
    day = input("  > ").strip().upper()

    print("  Duration in minutes:")
    duration_raw = input("  > ").strip()
    duration = int(duration_raw) if duration_raw.isdigit() else 0

    print("  Is this meeting a lab session? (y/n, default n)")
    lab = input("  > ").strip().lower() in ("y", "yes")

    return MeetingConfig(day=day, duration=duration, lab=lab)


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

    new_pattern = ClassConfig(**fields)

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

    updated_pattern = ClassConfig(**updated_fields)

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


def add_meeting(session):
    print("TODO")

def modify_meeting(session):
    print("TODO")

def delete_meeting(session):
    print("TODO")


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

    payload = session.schedules[index] if index is not None else session.schedules
    try:
        target = schedule_ops.export_schedule(payload, fmt, path, overwrite=overwrite)
        print(f"Exported to '{target}'.")
    except FileExistsError as e:
        print(f"{e} (pass --overwrite to replace it).")
    except NotImplementedError as e:
        print(f"Not wired up yet: {e}")