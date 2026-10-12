"""Commands for generating, viewing, clearing, and exporting schedules."""

from app import schedule_ops


def generate_schedule(session, limit_override=None):
    """Generate schedules using the active configuration."""
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
    else:
        print(f"Unexpected error during generation: {result.message}")


def schedule_summary(session):
    """Display a summary of all generated schedules."""
    if not session.schedules:
        print("No generated schedules in this session. Run 'schedule generate' first.")
        return
    for index, schedule in enumerate(session.schedules):
        print(f"--- Schedule {index} ({len(schedule)} course assignments) ---")


def view_schedule(session, index):
    """Display one generated schedule by index."""
    if not session.schedules:
        print("No generated schedules in this session.")
        return
    if not 0 <= index < len(session.schedules):
        print(f"No schedule at index {index}. Valid range: 0-{len(session.schedules) - 1}.")
        return
    print(schedule_ops.summarize_schedule(session.schedules[index]))


def clear_schedules(session):
    """Remove all generated schedules from the session."""
    session.schedules = []
    print("Cleared generated schedules.")


def export_schedule(session, fmt, path, index=None, overwrite=False):
    """Export one or all generated schedules to a file."""
    if not session.schedules:
        print("No generated schedules to export. Run 'schedule generate' first.")
        return
    if index is not None:
        if not 0 <= index < len(session.schedules):
            print(f"No schedule at index {index}. Valid range: 0-{len(session.schedules) - 1}.")
            return
        payload = [session.schedules[index]]
    else:
        payload = session.schedules
    try:
        target = schedule_ops.export_schedule(payload, fmt, path, overwrite=overwrite)
        print(f"Exported to '{target}'.")
    except FileExistsError as error:
        print(f"{error} (pass --overwrite to replace it).")
    except ValueError as error:
        print(f"Export failed: {error}")
    except OSError as error:
        print(f"Export failed: could not write to that location ({error}).")