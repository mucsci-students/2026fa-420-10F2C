"""Commands for meetings nested inside class patterns."""

from scheduler.config import Meeting, ValidationError

from app.crud import ValidationFailure

from .common import DAY_LABELS, apply_session_edit


def prompt_meeting():
    """Prompt for and return one validated Meeting instance."""
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
        except ValidationError as error:
            print(f"Invalid meeting: {error}")
            print("Let's try that meeting again.")


def list_meetings(pattern):
    """Print a pattern's meetings with their indexes."""
    if not pattern.meetings:
        print("(no meetings on this pattern)")
        return pattern.meetings
    for index, meeting in enumerate(pattern.meetings):
        day = DAY_LABELS.get(meeting.day, meeting.day)
        lab_str = " (lab session)" if getattr(meeting, "lab", False) else ""
        extras = []
        if getattr(meeting, "delivery", None):
            extras.append(f"delivery: {meeting.delivery}")
        if getattr(meeting, "start_time", None):
            extras.append(f"starts at {meeting.start_time}")
        extra_str = f"  ({'; '.join(extras)})" if extras else ""
        print(f"  [{index}] {day}, {meeting.duration} min{lab_str}{extra_str}")
    return pattern.meetings


def prompt_meeting_index(count):
    """Prompt for and validate a meeting index."""
    raw = input("Enter the meeting's index: ").strip()
    if not raw.isdigit():
        print("Please enter a valid integer index.")
        return None
    index = int(raw)
    if not 0 <= index < count:
        print(f"No meeting at index {index}. Valid range: 0-{count - 1}.")
        return None
    return index


def choose_pattern_and_meeting(config):
    """Choose a pattern, then one meeting belonging to that pattern."""
    from .patterns import list_patterns, prompt_pattern_index

    patterns = list_patterns(config)
    if not patterns:
        return None
    print("Which pattern is the meeting on?")
    pattern_index = prompt_pattern_index(len(patterns))
    if pattern_index is None:
        return None
    meetings = list_meetings(patterns[pattern_index])
    if not meetings:
        return None
    print("Which meeting?")
    meeting_index = prompt_meeting_index(len(meetings))
    if meeting_index is None:
        return None
    return pattern_index, meeting_index


def add_meeting(session):
    """Add one meeting to a selected class pattern."""
    from .patterns import list_patterns, prompt_pattern_index

    config = session.require_config()
    patterns = list_patterns(config)
    if not patterns:
        print("Add a class pattern first -- meetings belong to a pattern.")
        return
    print("Which pattern do you want to add a meeting to?")
    index = prompt_pattern_index(len(patterns))
    if index is None:
        return
    new_meeting = prompt_meeting()

    def mutate(draft):
        draft.time_slot_config.classes[index].meetings.append(new_meeting)

    try:
        apply_session_edit(session, config, "meeting", mutate)
        print("Meeting added.")
    except ValidationFailure as error:
        print(f"Could not add meeting: {error}")


def modify_meeting(session):
    """Update a meeting in a selected class pattern."""
    config = session.require_config()
    choice = choose_pattern_and_meeting(config)
    if choice is None:
        return
    pattern_index, meeting_index = choice
    updated_meeting = prompt_meeting()

    def mutate(draft):
        draft.time_slot_config.classes[pattern_index].meetings[meeting_index] = updated_meeting

    try:
        apply_session_edit(session, config, "meeting", mutate)
        print("Meeting updated.")
    except ValidationFailure as error:
        print(f"Could not save changes, previous version kept: {error}")


def delete_meeting(session):
    """Delete a meeting while preserving a non-empty class pattern."""
    from .patterns import list_patterns, prompt_pattern_index

    config = session.require_config()
    patterns = list_patterns(config)
    if not patterns:
        return
    print("Which pattern is the meeting on?")
    pattern_index = prompt_pattern_index(len(patterns))
    if pattern_index is None:
        return
    meetings = list_meetings(patterns[pattern_index])
    if not meetings:
        return
    if len(meetings) == 1:
        print("Can't delete the only meeting on this pattern -- delete the pattern instead if you don't need it.")
        return
    print("Which meeting would you like to delete?")
    meeting_index = prompt_meeting_index(len(meetings))
    if meeting_index is None:
        return
    print("Are you sure you want to delete this meeting? This cannot be undone. (y/n)")
    if input().lower().strip() not in ("y", "yes"):
        print("Removal cancelled")
        return

    def mutate(draft):
        del draft.time_slot_config.classes[pattern_index].meetings[meeting_index]

    try:
        apply_session_edit(session, config, "meeting", mutate)
        print("Meeting removed.")
    except ValidationFailure as error:
        print(f"Could not remove meeting: {error}")