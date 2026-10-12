"""Time-slot CRUD and global timing commands."""

from scheduler.config import TimeBlock, ValidationError

from app.crud import ValidationFailure

from .common import VALID_DAYS, apply_session_edit


def prompt_time_block():
    """Prompt for and validate one time block."""
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
    except ValidationError as error:
        print(f"Invalid time block: {error}")
        return None


def blocks_overlap(first, second):
    """Return whether two time blocks overlap."""
    return first.start < second.end and second.start < first.end


def add_timeslot(session):
    """Prompt for and add a global time slot."""
    config = session.require_config()
    print(f"Which day? ({'/'.join(VALID_DAYS)})")
    day = input().strip().upper()
    if day not in VALID_DAYS:
        print(f"'{day}' is not a valid day.")
        return
    new_block = prompt_time_block()
    if new_block is None:
        return

    existing = config.time_slot_config.times.get(day, [])
    conflict = next((block for block in existing if blocks_overlap(block, new_block)), None)
    if conflict:
        print(f"Time Conflict: overlaps existing block {conflict.start}-{conflict.end}")
        return

    def mutate(draft):
        draft.time_slot_config.times.setdefault(day, []).append(new_block)

    try:
        apply_session_edit(session, config, "timeslot", mutate)
        print("Time Slot Added Successfully")
    except ValidationFailure as error:
        print(f"Could not add time slot: {error}")


def modify_timeslot(session):
    """Prompt for and update an existing global time slot."""
    config = session.require_config()
    print(f"Which day is the time slot on? ({'/'.join(VALID_DAYS)})")
    day = input().strip().upper()
    blocks = config.time_slot_config.times.get(day, [])
    if not blocks:
        print(f"No time slots defined for {day}.")
        return
    for index, block in enumerate(blocks):
        print(f"  [{index}] {block.start}-{block.end} (spacing {block.spacing}m)")
    print("Which one do you want to change? (index)")
    try:
        index = int(input().strip())
        blocks[index]
    except (ValueError, IndexError):
        print("Not a valid selection.")
        return

    print("Enter the new time slot:")
    new_block = prompt_time_block()
    if new_block is None:
        return
    conflict = next(
        (block for other_index, block in enumerate(blocks) if other_index != index and blocks_overlap(block, new_block)),
        None,
    )
    if conflict:
        print(f"Time Conflict: overlaps existing block {conflict.start}-{conflict.end}")
        return

    def mutate(draft):
        draft.time_slot_config.times[day][index] = new_block

    try:
        apply_session_edit(session, config, "timeslot", mutate)
        print("Time Changed Successfully")
    except ValidationFailure as error:
        print(f"Could not save changes, previous version kept: {error}")


def delete_timeslot(session):
    """Delete a selected global time slot."""
    config = session.require_config()
    print(f"Which day is the time slot on? ({'/'.join(VALID_DAYS)})")
    day = input().strip().upper()
    blocks = config.time_slot_config.times.get(day, [])
    if not blocks:
        print(f"No time slots defined for {day}.")
        return
    if len(blocks) == 1:
        print(f"Can't delete the only time block on {day} -- every weekday needs at least one.")
        return
    for index, block in enumerate(blocks):
        print(f"  [{index}] {block.start}-{block.end} (spacing {block.spacing}m)")
    print("Which one do you want to delete? (index)")
    try:
        index = int(input().strip())
        blocks[index]
    except (ValueError, IndexError):
        print("Not a valid selection.")
        return
    print("Are you sure? Type confirm or cancel")
    if input().strip().lower() != "confirm":
        print("Cancelled.")
        return

    def mutate(draft):
        del draft.time_slot_config.times[day][index]

    try:
        apply_session_edit(session, config, "timeslot", mutate)
        print("Time slot deleted.")
    except ValidationFailure as error:
        print(f"Could not delete: {error}")


def modify_timing_options(session):
    """Update global maximum-gap and minimum-overlap settings."""
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

    def mutate(draft):
        if new_gap is not None:
            draft.time_slot_config.max_time_gap = new_gap
        if new_overlap is not None:
            draft.time_slot_config.min_time_overlap = new_overlap

    try:
        apply_session_edit(session, config, "timeslot", mutate)
        print("Timing options updated.")
    except ValidationFailure as error:
        print(f"Could not update timing options: {error}")