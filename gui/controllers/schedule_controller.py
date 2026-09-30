"""
Controller for Schedule Generator + Schedule Viewer actions (Sections 13-18).

Shared helpers (use these instead of touching session.schedules directly):

    schedule_count(request)            -> int
    get_schedules(request)             -> list[list[Assignment]]   (every schedule)
    get_schedule(request, index)       -> list[Assignment]         (one, 0-based)
    replace_schedules(request, items)  -> None                     (store new results)

An Assignment (app/schedule_io.py) is one course section's placement:
course, faculty, room, lab, and meetings (day, start, end, duration, lab).
get_schedule/get_schedules return the same records whether a schedule was
generated (the library's CourseInstance objects) or loaded from a file, so
the viewer tables and exports never need to know which.

Who uses what:
    generate()          -> replace_schedules(request, result.schedules)
    clear_schedules()   -> replace_schedules(request, [])
    view_schedule()     -> get_schedule(request, index), then group by room/faculty
    exports             -> get_schedule / get_schedules + app.schedule_io writers
    load_schedule_json  -> done (Section 17)

Like every controller, these raise ControllerError for anything the user
can fix and never build HTTP responses (Section 20).
"""

from __future__ import annotations

from app import schedule_io
from app.schedule_io import Assignment
from gui.controllers.errors import ControllerError, FieldError
from gui.controllers.uploads import read_upload
from gui.session_store import get_session

IMPORT_FIELD = "schedule_file"
NO_SCHEDULES_MESSAGE = "There are no schedules yet. Generate schedules or load a schedule file first."


# ---------------------------------------------------------------------- #
#  Shared reads / writes
# ---------------------------------------------------------------------- #
def schedule_count(request) -> int:
    """How many schedules (generated or loaded) are available right now."""
    return len(get_session(request).schedules)


def get_schedules(request) -> list[list[Assignment]]:
    """Every available schedule as Assignment records."""
    schedules = get_session(request).schedules
    if not schedules:
        raise ControllerError(NO_SCHEDULES_MESSAGE)
    return [_as_records(schedule, number) for number, schedule in enumerate(schedules, start=1)]


def get_schedule(request, index: int) -> list[Assignment]:
    """One schedule (0-based `index`) as Assignment records."""
    schedules = get_session(request).schedules
    if not schedules:
        raise ControllerError(NO_SCHEDULES_MESSAGE)
    if not 0 <= index < len(schedules):
        raise ControllerError(
            f"Schedule {index + 1} doesn't exist. There are {len(schedules)} schedule(s)."
        )
    return _as_records(schedules[index], index + 1)


def replace_schedules(request, schedules: list) -> None:
    """Store a new set of results (generated, loaded, or [] to clear).

    The one place session.schedules is written, so anything that should
    happen whenever results change can be added here.
    """
    get_session(request).schedules = list(schedules)


def _as_records(schedule, number: int) -> list[Assignment]:
    try:
        return schedule_io.to_assignments(schedule)
    except schedule_io.ScheduleFileError as error:
        raise ControllerError(
            [FieldError(None, f"Schedule {number} could not be read: {error.message}")]
            + [FieldError(None, problem) for problem in error.problems]
        ) from error


# ---------------------------------------------------------------------- #
#  Schedule Generator (Henry)
# ---------------------------------------------------------------------- #
def generate(request, limit_override=None, optimizer_overrides=None):
    """TODO (Section 13-14): call app.schedule_ops.generate_schedules()
    with the session's valid config, applying limit_override/optimizer_overrides
    for THIS RUN ONLY -- must not mutate the saved config's own settings.
    Must distinguish success / no-feasible-schedule / invalid-config /
    invalid-override / runtime-error outcomes for the view to display.
    Store successful results with replace_schedules(request, result.schedules)."""
    raise NotImplementedError


# ---------------------------------------------------------------------- #
#  Schedule Viewer (James)
# ---------------------------------------------------------------------- #
def clear_schedules(request):
    """TODO (Section 15): replace_schedules(request, [])."""
    raise NotImplementedError


def view_schedule(request, index):
    """TODO (Section 15-16): start from get_schedule(request, index) and
    return the rows grouped by room/lab and by faculty for the templates."""
    raise NotImplementedError


# ---------------------------------------------------------------------- #
#  Schedule files (Samsong)
# ---------------------------------------------------------------------- #
def load_schedule_json(request, uploaded_file) -> int:
    """Section 17: load schedules from an uploaded JSON file.

    The whole file is read (read_upload) and validated (app.schedule_io)
    before anything changes; only then does it replace the current
    schedules. On any problem this raises ControllerError attached to the
    file field, and the schedules already loaded stay exactly as they were.

    Returns the number of schedules loaded.
    """
    raw = read_upload(uploaded_file, IMPORT_FIELD)
    try:
        schedules = schedule_io.parse_schedule_file(raw)
    except schedule_io.ScheduleFileError as error:
        items = [FieldError(IMPORT_FIELD, f"{error.message} Your current schedules were kept.")]
        items += [FieldError(IMPORT_FIELD, problem) for problem in error.problems]
        raise ControllerError(items) from error

    replace_schedules(request, schedules)
    return len(schedules)


def export_schedule_json(request, index=None):
    """TODO (Section 18): get_schedule(request, index) or get_schedules(request),
    then app.schedule_io.schedules_to_json(...)."""
    raise NotImplementedError


def export_schedule_csv(request, index=None):
    """TODO (Section 18): same as export_schedule_json with
    app.schedule_io.schedules_to_csv(...) (Sprint 1 CSV export)."""
    raise NotImplementedError
