"""Class-pattern CRUD commands."""

from scheduler.config import ClassPattern

from app.crud import ValidationFailure

from .common import DAY_LABELS, apply_session_edit
from .meetings import prompt_meeting


def prompt_pattern_fields():
    """Prompt for a full class pattern and its initial meetings."""
    print("Credits for this pattern:")
    credits_raw = input().strip()
    credits = int(credits_raw) if credits_raw.isdigit() else 0
    meetings = []
    print("Now enter the meetings for this pattern (at least one required).")
    while True:
        meetings.append(prompt_meeting())
        print("Add another meeting? (y/n, default n)")
        if input().strip().lower() not in ("y", "yes"):
            break
    print("Fixed start time for this pattern, e.g. 16:00 (blank = none):")
    start_time = input().strip() or None
    print("Should this pattern start disabled? (y/n, default n)")
    disabled = input().strip().lower() in ("y", "yes")
    return {"credits": credits, "meetings": meetings, "start_time": start_time, "disabled": disabled}


def format_pattern(index, pattern):
    """Format an indexed class pattern for terminal display."""
    meeting_bits = ", ".join(
        f"{DAY_LABELS.get(meeting.day, meeting.day)} {meeting.duration}min" + (" (lab)" if getattr(meeting, "lab", False) else "")
        for meeting in pattern.meetings
    )
    extras = []
    if getattr(pattern, "start_time", None):
        extras.append(f"starts at {pattern.start_time}")
    if getattr(pattern, "disabled", False):
        extras.append("disabled")
    extra_str = f"  ({'; '.join(extras)})" if extras else ""
    return f"[{index}] {pattern.credits} credits: {meeting_bits}{extra_str}"


def list_patterns(config):
    """Display every class pattern and return the ordered list."""
    patterns = config.time_slot_config.classes
    if not patterns:
        print("(no class patterns defined)")
        return patterns
    for index, pattern in enumerate(patterns):
        print(format_pattern(index, pattern))
    return patterns


def prompt_pattern_index(count):
    """Prompt for and validate a class-pattern index."""
    raw = input("Enter the pattern's index: ").strip()
    if not raw.isdigit():
        print("Please enter a valid integer index.")
        return None
    index = int(raw)
    if not 0 <= index < count:
        print(f"No pattern at index {index}. Valid range: 0-{count - 1}.")
        return None
    return index


def add_pattern(session):
    """Prompt for and add a class pattern."""
    config = session.require_config()
    fields = prompt_pattern_fields()
    if fields["credits"] <= 0:
        print("Credits must be a positive integer.")
        return
    if not fields["meetings"]:
        print("A pattern needs at least one meeting.")
        return
    new_pattern = ClassPattern(**fields)

    def mutate(draft):
        draft.time_slot_config.classes.append(new_pattern)

    try:
        apply_session_edit(session, config, "pattern", mutate)
        print("Class pattern added.")
    except ValidationFailure as error:
        print(f"Could not add pattern: {error}")


def modify_pattern(session):
    """Prompt for and update an existing class pattern."""
    config = session.require_config()
    patterns = list_patterns(config)
    if not patterns:
        return
    print("Which pattern would you like to edit?")
    index = prompt_pattern_index(len(patterns))
    if index is None:
        return
    updated_fields = prompt_pattern_fields()
    if updated_fields["credits"] <= 0:
        print("Credits must be a positive integer.")
        return
    if not updated_fields["meetings"]:
        print("A pattern needs at least one meeting.")
        return
    updated_pattern = ClassPattern(**updated_fields)

    def mutate(draft):
        draft.time_slot_config.classes[index] = updated_pattern

    try:
        apply_session_edit(session, config, "pattern", mutate)
        print("Class pattern updated.")
    except ValidationFailure as error:
        print(f"Could not save changes, previous version kept: {error}")


def delete_pattern(session):
    """Delete a selected class pattern after confirmation."""
    config = session.require_config()
    patterns = list_patterns(config)
    if not patterns:
        return
    print("Which pattern would you like to delete?")
    index = prompt_pattern_index(len(patterns))
    if index is None:
        return
    print("Are you sure you want to delete this pattern? This cannot be undone. (y/n)")
    if input().lower().strip() not in ("y", "yes"):
        print("Removal cancelled")
        return

    def mutate(draft):
        del draft.time_slot_config.classes[index]

    try:
        apply_session_edit(session, config, "pattern", mutate)
        print("Class pattern removed.")
    except ValidationFailure as error:
        print(f"Could not remove pattern: {error}")