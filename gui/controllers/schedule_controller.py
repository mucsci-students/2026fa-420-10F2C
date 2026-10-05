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
    export_schedules    -> done (Section 18): JSON or CSV, one schedule or all;
                           returns an ExportFile for the view

Like every controller, these raise ControllerError for anything the user
can fix and never build HTTP responses (Section 20).
"""

from __future__ import annotations

from dataclasses import dataclass

from app import schedule_io
from app.schedule_io import Assignment
from gui.controllers.errors import ControllerError, FieldError
from gui.controllers.uploads import read_upload
from gui.session_store import get_session

IMPORT_FIELD = "schedule_file"
NO_SCHEDULES_MESSAGE = "There are no schedules yet. Generate schedules or load a schedule file first."
JSON_CONTENT_TYPE = "application/json; charset=utf-8"
CSV_CONTENT_TYPE = "text/csv; charset=utf-8"


@dataclass(frozen=True)
class ExportFile:
    """A file ready to download: the view passes these to download_response()."""

    filename: str
    content: str
    content_type: str
    schedule_count: int


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


def export_schedule_json(request, index: int | None = None) -> ExportFile:
    """Section 18: one schedule (0-based `index`) or, with index=None, every
    schedule, in the documented JSON format that load_schedule_json reads
    back. Raises ControllerError when there is nothing to export or the
    index doesn't exist. Nothing in the session changes.

    File names: schedule-<n>.json (n as shown to the user, 1-based) or
    schedules-all-<count>.json.
    """
    schedules, stem = _schedules_to_export(request, index)
    return ExportFile(
        filename=f"{stem}.json",
        content=schedule_io.schedules_to_json(schedules),
        content_type=JSON_CONTENT_TYPE,
        schedule_count=len(schedules),
    )


def export_schedule_csv(request, index: int | None = None) -> ExportFile:
    """Section 18 / Sprint 1: the same choice as export_schedule_json, as
    CSV (one row per meeting, columns in schedule_io.CSV_COLUMNS). The
    `schedule` column keeps the number shown in the viewer, so exporting
    schedule 3 alone writes 3, not 1. CSV is for spreadsheets; it can't be
    loaded back into the viewer (use JSON for that).

    File names: schedule-<n>.csv or schedules-all-<count>.csv.
    """
    schedules, stem = _schedules_to_export(request, index)
    first_number = 1 if index is None else index + 1
    return ExportFile(
        filename=f"{stem}.csv",
        content=schedule_io.schedules_to_csv(schedules, first_number=first_number),
        content_type=CSV_CONTENT_TYPE,
        schedule_count=len(schedules),
    )


EXPORTERS = {"json": export_schedule_json, "csv": export_schedule_csv}


def export_schedules(request, index: int | None, file_format: str) -> ExportFile:
    """Export in `file_format` ("json" or "csv"); index=None means every schedule."""
    try:
        exporter = EXPORTERS[file_format]
    except KeyError:
        raise ControllerError(f"Unknown export format '{file_format}'. Choose JSON or CSV.") from None
    return exporter(request, index)


def _schedules_to_export(request, index: int | None) -> tuple[list[list[Assignment]], str]:
    """The schedules to write and the file name without its extension."""
    if index is None:
        schedules = get_schedules(request)
        return schedules, f"schedules-all-{len(schedules)}"
    return [get_schedule(request, index)], f"schedule-{index + 1}"
