"""Lab CRUD commands."""

from app.crud import ReferenceError_, ValidationFailure, check_no_references
from scheduler.config import LabConfig

from .common import apply_session_edit, field_value, prompt_resource_availability, prompt_supplied_features


def prompt_lab_fields():
    """Collect and validate fields for a lab record."""
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

    features = prompt_supplied_features("lab")
    times = prompt_resource_availability("lab")
    fields = {"name": name, "capacity": capacity, "features": features}
    if times is not None:
        fields["times"] = times
    return fields


def add_lab(session):
    """Prompt for and add a lab record."""
    config = session.require_config()
    fields = prompt_lab_fields()
    if any(lab.name == fields["name"] for lab in config.config.labs):
        print("Lab is already in the system!")
        return

    new_lab = LabConfig(**fields)

    def mutate(draft):
        draft.config.labs.append(new_lab)

    try:
        apply_session_edit(session, config, "lab", mutate)
        print("Lab added.")
    except ValidationFailure as error:
        print(f"Could not add lab: {error}")


def modify_lab(session):
    """Prompt for and update an existing lab record."""
    config = session.require_config()
    target_name = input("What is the name of the lab you would like to edit? ").strip()
    existing = next((lab for lab in config.config.labs if lab.name == target_name), None)
    if existing is None:
        print("Lab does not exist!")
        return

    fields = prompt_lab_fields()
    if fields["name"] != target_name and any(lab.name == fields["name"] for lab in config.config.labs):
        print("Lab name is already in the system!")
        return

    updated_lab = LabConfig(**fields)

    def mutate(draft):
        lab_list = draft.config.labs
        lab_list.remove(existing)
        lab_list.append(updated_lab)

    try:
        apply_session_edit(session, config, "lab", mutate)
        print("Lab updated.")
    except ValidationFailure as error:
        print(f"Could not save changes, previous version kept: {error}")


def delete_lab(session):
    """Delete an unreferenced lab after confirmation."""
    config = session.require_config()
    name = input("What is the name of the lab you want to remove? ")
    existing = next((lab for lab in config.config.labs if lab.name == name), None)
    if existing is None:
        print("Lab does not exist!")
        return

    referencing_courses = [course.course_id for course in config.config.courses if name in course.lab]
    try:
        check_no_references(name, referencing_courses)
    except ReferenceError_ as error:
        print(f"{error} -- remove this lab from those courses first")
        return

    print("Are you sure you want to delete this lab? This cannot be undone (y/n)")
    if input().lower().strip() not in ("yes", "y"):
        print("Removal cancelled")
        return

    def mutate(draft):
        draft.config.labs.remove(existing)

    try:
        apply_session_edit(session, config, "lab", mutate)
        print("Lab removed.")
    except ValidationFailure as error:
        print(f"Could not remove lab: {error}")


def format_lab(index, lab):
    """Format an indexed lab record for terminal display."""
    lines = [f"[{index}] {lab.name} -- capacity {lab.capacity}"]
    if lab.features:
        lines.append(f"      Features: {', '.join(sorted(lab.features))}")
    if lab.times:
        lines.append("      Availability:")
        from .common import DAY_LABELS, VALID_DAYS
        for day in VALID_DAYS:
            blocks = field_value(lab.times, day)
            if not blocks:
                continue
            ranges = ", ".join(f"{field_value(block, 'start')}-{field_value(block, 'end')}" for block in blocks)
            lines.append(f"        {DAY_LABELS[day]}  {ranges}")
    else:
        lines.append("      Availability: unrestricted")
    return "\n".join(lines)


def view_lab(session):
    """Display all lab records in the active configuration."""
    config = session.require_config()
    if not config.config.labs:
        print("(no labs defined)")
        return
    for index, lab in enumerate(config.config.labs):
        if index > 0:
            print()
        print(format_lab(index, lab))