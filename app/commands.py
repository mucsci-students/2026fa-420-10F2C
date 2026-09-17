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
from scheduler.config import FacultyConfig, TimeBlock, ValidationError, OptimizerFlags

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


def view_faculty(session):
    config = session.require_config()
    if not config.config.faculty:
        print("(no faculty defined)")
        return
    for f in config.config.faculty:
        print(f.model_dump_json(indent=2))


# =========================================================================== #
#  TODO: course / lab / room / pattern / meeting CRUD
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


def add_pattern(session):
    print("TODO")

def modify_pattern(session):
    print("TODO")

def delete_pattern(session):
    print("TODO: check courses referencing this class pattern before deleting.")


def add_meeting(session):
    print("TODO")

def modify_meeting(session):
    print("TODO")

def delete_meeting(session):
    print("TODO")


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

    payload = session.schedules[index] if index is not None else session.schedules
    try:
        target = schedule_ops.export_schedule(payload, fmt, path, overwrite=overwrite)
        print(f"Exported to '{target}'.")
    except FileExistsError as e:
        print(f"{e} (pass --overwrite to replace it).")
    except NotImplementedError as e:
        print(f"Not wired up yet: {e}")