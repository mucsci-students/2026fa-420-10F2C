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
    exports             -> get_schedule / get_schedules + app.schedule_io writers
    load_schedule_json  -> done (Section 17)
    export_schedules    -> done (Section 18): JSON or CSV, one schedule or all;
                           returns an ExportFile for the view

Like every controller, these raise ControllerError for anything the user
can fix and never build HTTP responses (Section 20).
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass

from app import schedule_io, schedule_ops
from app.generation_job import STATE_FINISHED, GenerationJob
from app.schedule_io import Assignment
from app.commands.common import VALID_OPTIMIZER_FLAGS
from gui.controllers.common import require_config
from gui.controllers.errors import ControllerError, FieldError
from gui.controllers.uploads import read_upload
from gui.session_store import get_session

IMPORT_FIELD = "schedule_file"
NO_SCHEDULES_MESSAGE = (
    "There are no schedules yet. Generate schedules or load a schedule file first."
)
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
    return [
        _as_records(schedule, number)
        for number, schedule in enumerate(schedules, start=1)
    ]


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


def replace_schedules(
    request, schedules: list, version=None, tracked: bool = True
) -> None:
    """Store a new set of results (generated, loaded, or [] to clear).

    The one place session.schedules is written, so anything that should
    happen whenever results change can be added here.
    """
    _set_schedules(get_session(request), schedules, version, tracked)


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
    """Generate schedules from the session's configuration (Sections 13-14).

    limit_override applies to THIS RUN ONLY; the saved config is never changed.
    Returns the schedule_ops.GenerationResult so the view can show which of
    the outcomes happened. Raises ControllerError for a bad override, a
    missing configuration, or an overlapping run.
    """
    session = get_session(request)
    config = require_config(session, "generating schedules")

    optimizer_overrides = _validated_overrides(limit_override, optimizer_overrides)

    # Remember which version of the configuration these schedules come from, so
    # the pages can say when the configuration has changed since (stale notice).
    started_from = session.history.version
    with generation_in_progress(request):
        result = schedule_ops.generate_schedules(
            config, limit_override, optimizer_overrides
        )

    if result.outcome == schedule_ops.GenerationOutcome.SUCCESS:
        replace_schedules(request, result.schedules, started_from)
    elif result.outcome == schedule_ops.GenerationOutcome.NO_FEASIBLE_SCHEDULE:
        replace_schedules(request, [])  # same as the CLI: don't leave stale results
    return result


# ---------------------------------------------------------------------- #
#  Schedule Viewer (James)
# ---------------------------------------------------------------------- #
def clear_schedules(request) -> int:
    """Section 15 / user stories 32, 54: remove every available schedule
    (generated or loaded) and return how many were removed. The view asks
    for confirmation first. Raises ControllerError when there is nothing to
    clear. The configuration is not touched.
    """
    count = schedule_count(request)
    if count == 0:
        raise ControllerError(NO_SCHEDULES_MESSAGE)
    replace_schedules(request, [])
    return count


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
        items = [
            FieldError(
                IMPORT_FIELD, f"{error.message} Your current schedules were kept."
            )
        ]
        items += [FieldError(IMPORT_FIELD, problem) for problem in error.problems]
        raise ControllerError(items) from error

    replace_schedules(
        request, schedules, tracked=False
    )  # an imported file: origin unknown
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
        raise ControllerError(
            f"Unknown export format '{file_format}'. Choose JSON or CSV."
        ) from None
    return exporter(request, index)


def _schedules_to_export(
    request, index: int | None
) -> tuple[list[list[Assignment]], str]:
    """The schedules to write and the file name without its extension."""
    if index is None:
        schedules = get_schedules(request)
        return schedules, f"schedules-all-{len(schedules)}"
    return [get_schedule(request, index)], f"schedule-{index + 1}"


_GENERATION_LOCK = threading.Lock()  # the dev server is threaded
BUSY_MESSAGE = (
    "A schedule generation is already running. Wait for it to finish, then try again."
)


@contextmanager
def generation_in_progress(request):
    """Mark this session as generating; refuse an overlapping request.

    generate() should run its solver call inside this block, so a double
    click or a second tab can't start two runs (Section 13).
    """
    session = get_session(request)
    with _GENERATION_LOCK:
        if session.generating:
            raise ControllerError(BUSY_MESSAGE)
        session.generating = True
    try:
        yield
    finally:
        session.generating = False  # cleared on success, failure, or crash


def is_generating(request) -> bool:
    return get_session(request).generating


# ---------------------------------------------------------------------- #
#  Background generation with live progress (Sections 13 and 19)
#
#  generate() above runs the solver inside the request and is what the form
#  uses without JavaScript. These functions run the same generation on a
#  background thread (app.generation_job.GenerationJob) so the page can show
#  a progress bar and a Cancel button:
#
#      start_generation(request, limit, flags) -> status dict (the run starts)
#      generation_status(request)               -> status dict, or {"state": "idle"}
#      cancel_generation(request)               -> status dict
#      collect_generation_result(request)       -> GenerationResult, once
#      describe_outcome(result)                 -> (level, user-facing text)
#
#  Overrides apply to this run only; the saved configuration is never changed.
# ---------------------------------------------------------------------- #
def _validated_overrides(limit_override, optimizer_overrides):
    """Check a run's one-off overrides; return the flag list (or None)."""
    if limit_override is not None:
        if (
            isinstance(limit_override, bool)
            or not isinstance(limit_override, int)
            or limit_override <= 0
        ):
            raise ControllerError(
                [
                    FieldError(
                        "limit", "Generation limit must be a positive whole number."
                    )
                ]
            )

    if optimizer_overrides is not None:
        optimizer_overrides = list(optimizer_overrides)
        unknown = [
            flag for flag in optimizer_overrides if flag not in VALID_OPTIMIZER_FLAGS
        ]
        if unknown:
            raise ControllerError(
                [
                    FieldError(
                        "optimizer_flags", f"'{flag}' is not a valid optimizer flag."
                    )
                    for flag in unknown
                ]
            )
    return optimizer_overrides


def _set_schedules(session, schedules, version=None, tracked=True) -> None:
    """The one place session.schedules is written (see replace_schedules).
    `version` is the configuration version they were generated from (default:
    the configuration as it is now); `tracked=False` is for schedules of unknown
    origin (an imported file), which are never flagged as out of date."""
    session.set_schedules(list(schedules), version, tracked)


def _finish_generation(session, job, result, started_from=None) -> None:
    """Runs on the worker thread when a background run ends: store the
    results exactly as generate() does, then release the session."""
    try:
        if result.outcome == schedule_ops.GenerationOutcome.SUCCESS:
            _set_schedules(session, result.schedules, started_from)
        elif result.outcome == schedule_ops.GenerationOutcome.NO_FEASIBLE_SCHEDULE:
            _set_schedules(session, [])  # don't leave stale results, same as generate()
        # invalid configuration, runtime error and cancel keep the previous results
    finally:
        with _GENERATION_LOCK:
            session.generating = False


def start_generation(request, limit_override=None, optimizer_overrides=None) -> dict:
    """Start a background generation and return its first status.

    Raises ControllerError for a missing configuration, a bad override, or a
    run that is already going (BUSY_MESSAGE).
    """
    session = get_session(request)
    config = require_config(session, "generating schedules")
    optimizer_overrides = _validated_overrides(limit_override, optimizer_overrides)
    started_from = session.history.version

    with _GENERATION_LOCK:
        if session.generating:
            raise ControllerError(BUSY_MESSAGE)
        session.generating = True
        job = GenerationJob(
            config,
            limit_override,
            optimizer_overrides,
            on_finish=lambda finished_job, result: _finish_generation(
                session, finished_job, result, started_from
            ),
        )
        session.generation_job = job
    try:
        job.start()
    except Exception:
        with _GENERATION_LOCK:
            session.generating = False
            session.generation_job = None
        raise
    return job.snapshot()


def _current_job(request):
    return getattr(get_session(request), "generation_job", None)


def generation_job_active(request) -> bool:
    """True while a background run exists or its outcome is still unreported."""
    return _current_job(request) is not None


def generation_status(request) -> dict:
    """The current run's progress, or {"state": "idle"} when there is none."""
    job = _current_job(request)
    if job is None:
        return {"state": "idle"}
    return job.snapshot()


def cancel_generation(request) -> dict:
    """Ask the running generation to stop. Raises ControllerError if none is running."""
    job = _current_job(request)
    if job is None or job.finished:
        raise ControllerError("No schedule generation is running right now.")
    job.cancel()
    return job.snapshot()


def collect_generation_result(request):
    """Return the finished run's GenerationResult once, then forget the run.

    Returns None while the run is still going, or when there is nothing (left)
    to report. The view calls this to turn the outcome into a message.
    """
    session = get_session(request)
    with _GENERATION_LOCK:
        job = getattr(session, "generation_job", None)
        if job is None or not job.finished:
            return None
        session.generation_job = None
        return job.result


def describe_outcome(result) -> tuple[str, str]:
    """(level, text) for a GenerationResult; level is success, warning or error."""
    outcome = schedule_ops.GenerationOutcome
    if result.outcome == outcome.SUCCESS:
        return "success", result.message
    if result.outcome == outcome.NO_FEASIBLE_SCHEDULE:
        return (
            "warning",
            "No feasible schedule was found. Check the configuration and try again.",
        )
    if result.outcome == outcome.CANCELLED:
        return "warning", result.message
    if result.outcome == outcome.INVALID_CONFIG:
        return "error", f"The configuration is invalid: {result.message}"
    return "error", f"Schedule generation failed unexpectedly: {result.message}"
