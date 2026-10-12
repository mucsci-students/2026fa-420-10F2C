"""Room CRUD commands."""

from app.crud import ReferenceError_, ValidationFailure, check_no_references
from scheduler.config import RoomConfig

from .common import DAY_LABELS, VALID_DAYS, apply_session_edit, field_value, prompt_resource_availability, prompt_supplied_features


def prompt_room_fields():
    """Collect and validate fields for a room record."""
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

    features = prompt_supplied_features("room")
    times = prompt_resource_availability("room")
    fields = {"name": name, "capacity": capacity, "features": features}
    if times is not None:
        fields["times"] = times
    return fields


def add_room(session):
    """Prompt for and add a room record."""
    config = session.require_config()
    fields = prompt_room_fields()
    if any(room.name == fields["name"] for room in config.config.rooms):
        print("Room is already in the system!")
        return

    new_room = RoomConfig(**fields)

    def mutate(draft):
        draft.config.rooms.append(new_room)

    try:
        apply_session_edit(session, config, "room", mutate)
        print("Room added.")
    except ValidationFailure as error:
        print(f"Could not add room: {error}")


def modify_room(session):
    """Prompt for and update an existing room record."""
    config = session.require_config()
    target_name = input("What is the name of the room you would like to edit? ").strip()
    existing = next((room for room in config.config.rooms if room.name == target_name), None)
    if existing is None:
        print("Room does not exist!")
        return

    fields = prompt_room_fields()
    if fields["name"] != target_name and any(room.name == fields["name"] for room in config.config.rooms):
        print("Room name is already in the system!")
        return

    updated_room = RoomConfig(**fields)

    def mutate(draft):
        room_list = draft.config.rooms
        room_list.remove(existing)
        room_list.append(updated_room)

    try:
        apply_session_edit(session, config, "room", mutate)
        print("Room updated.")
    except ValidationFailure as error:
        print(f"Could not save changes, previous version kept: {error}")


def delete_room(session):
    """Delete an unreferenced room after confirmation."""
    config = session.require_config()
    name = input("What is the name of the room you want to remove? ").strip()
    existing = next((room for room in config.config.rooms if room.name == name), None)
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
    except ReferenceError_ as error:
        print(f"{error} -- remove this room from those courses first.")
        return

    print("Are you sure you want to delete this room? This cannot be undone. (y/n)")
    if input().strip().lower() not in ("y", "yes"):
        print("Removal cancelled")
        return

    def mutate(draft):
        draft.config.rooms.remove(existing)

    try:
        apply_session_edit(session, config, "room", mutate)
        print("Room removed.")
    except ValidationFailure as error:
        print(f"Could not remove room: {error}")


def format_room(index, room):
    """Format an indexed room record for terminal display."""
    lines = [f"[{index}] {room.name} -- capacity {room.capacity}"]
    if room.features:
        lines.append(f"      Features: {', '.join(sorted(room.features))}")
    if room.times:
        lines.append("      Availability:")
        for day in VALID_DAYS:
            blocks = field_value(room.times, day)
            if not blocks:
                continue
            ranges = ", ".join(f"{field_value(block, 'start')}-{field_value(block, 'end')}" for block in blocks)
            lines.append(f"        {DAY_LABELS[day]}  {ranges}")
    else:
        lines.append("      Availability: unrestricted")
    return "\n".join(lines)


def view_room(session):
    """Display all room records in the active configuration."""
    config = session.require_config()
    if not config.config.rooms:
        print("(no rooms defined)")
        return
    for index, room in enumerate(config.config.rooms):
        if index > 0:
            print()
        print(format_room(index, room))