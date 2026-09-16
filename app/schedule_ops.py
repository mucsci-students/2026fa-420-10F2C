# ----------------------------------------------------------------------------------------------------------------------- #
#   app/schedule_ops.py                                                                                                   #
#                                                                                                                         #
#   Backbone piece #3: schedule generation (Req #8), inspection (Req #9), and    #
#   export (Req #10) currently don't exist at all -- every schedule_* function    #
#   in commands.py is a print("implement...") stub.                              #
#                                                                                                                         #
#   Per the library's Python API docs:                                          #
#       from scheduler import Scheduler, load_config_from_file                    #
#       scheduler = Scheduler(config)                                            #
#       for s in scheduler.get_models():   # generator                          #
#           for course_instance in s:      # s is a list[CourseInstance]         #
#               ...                                                             #
#                                                                                 #
#   CONFIRM before trusting this as-is (all guesses below are grounded in the    #
#   library's documented project structure -- src/scheduler/writers/{csv,json}   #
#   _writer.py -- but I could not import the package here to check exact         #
#   class/function names and constructor signatures):                            #
#     - Exact export from scheduler.writers (a class you instantiate as a        #
#       context manager per "CSV output with context manager support", or a      #
#       plain write_json(path, schedules)/write_csv(path, schedules) function).  #
#     - Whether Scheduler(config) validates completeness itself, or whether      #
#       "require a valid complete configuration" (Req #8) means WE should call   #
#       something like config.model_validate() / a completeness check before     #
#       constructing Scheduler. Check the constructor's docstring once           #
#       installed: `uv run python -c "import scheduler; help(scheduler.Scheduler)"`
#     - The generation-limit field's exact name on CombinedConfig (assumed        #
#       `config.limit` based on the REST /submit example body in the Sprint 1    #
#       slides: {"config": {...}, "time_slot_config": {...}, "limit": 10,        #
#       "optimizer_flags": [...]}).                                              #
# ----------------------------------------------------------------------------------------------------------------------- #

from __future__ import annotations

from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Optional

from scheduler import Scheduler


class GenerationOutcome:
    """Distinguishes the four cases Req #8 explicitly calls out, instead of
    letting the shell guess from a generic exception."""
    SUCCESS = "success"
    NO_FEASIBLE_SCHEDULE = "no_feasible_schedule"
    INVALID_CONFIG = "invalid_config"
    RUNTIME_ERROR = "runtime_error"


@dataclass
class GenerationResult:
    outcome: str
    message: str
    schedules: list  # list of (list of CourseInstance); empty unless outcome == SUCCESS


def generate_schedules(config, limit_override: Optional[int] = None) -> GenerationResult:
    """Runs the scheduler's public API and reports one of the four outcomes
    Req #8 requires. Does not mutate session state -- the caller (a
    commands.py function) decides whether/how to store the result, e.g.
    `session.schedules = result.schedules`."""

    # "Require a valid complete configuration" -- if construction itself is
    # what validates completeness, this try/except covers it. If not, add
    # an explicit completeness check here once you've confirmed the
    # library's behavior (see module docstring).
    try:
        engine = Scheduler(config)
    except Exception as e:  # noqa: BLE001 -- narrow once the real exception type is known
        return GenerationResult(GenerationOutcome.INVALID_CONFIG, str(e), [])

    limit = limit_override if limit_override is not None else getattr(config, "limit", None)

    try:
        models = engine.get_models()
        schedules = list(islice(models, limit)) if limit else list(models)
    except Exception as e:  # noqa: BLE001 -- the Z3 layer; treat as unexpected runtime error
        return GenerationResult(GenerationOutcome.RUNTIME_ERROR, str(e), [])

    if not schedules:
        return GenerationResult(
            GenerationOutcome.NO_FEASIBLE_SCHEDULE,
            "The solver found no schedule satisfying every hard constraint.",
            [],
        )

    return GenerationResult(
        GenerationOutcome.SUCCESS,
        f"Generated {len(schedules)} schedule(s).",
        schedules,
    )


def summarize_schedule(schedule) -> str:
    """One line per course assignment: course id, faculty, room/lab,
    meeting times -- enough for a user to understand the schedule at a
    glance (Req #9). Relies on `CourseInstance.as_csv()`, which the
    library's README uses directly for this exact purpose."""
    lines = []
    for course_instance in schedule:
        lines.append(course_instance.as_csv())
    return "\n".join(lines)


def export_schedule(schedule_or_schedules, fmt: str, out_path: str, overwrite: bool = False) -> Path:
    """Writes one schedule or the whole generated set to JSON or CSV
    (Req #10). Refuses to clobber an existing file unless overwrite=True --
    that's this app's documented overwrite-protection approach; adjust the
    behavior/docstring together if you choose a different one (e.g.
    prompting for confirmation in the shell instead of a flag here).
    """
    if fmt not in ("json", "csv"):
        raise ValueError(f"Unknown export format: {fmt!r} (expected 'json' or 'csv')")

    target = Path(out_path)
    if target.exists() and not overwrite:
        raise FileExistsError(f"'{target}' already exists. Re-run with overwrite confirmed to replace it.")

    # ---- CONFIRM: replace this block with the library's real writer API.
    # Guessed shape, based on "context manager support" in the README's
    # project-structure listing:
    #
    #   from scheduler.writers.json_writer import JsonWriter
    #   from scheduler.writers.csv_writer import CsvWriter
    #   writer_cls = JsonWriter if fmt == "json" else CsvWriter
    #   with writer_cls(target) as writer:
    #       writer.write(schedule_or_schedules)
    #
    # or, if writers/__init__.py exports plain functions instead:
    #
    #   from scheduler.writers import write_json, write_csv
    #   (write_json if fmt == "json" else write_csv)(target, schedule_or_schedules)
    #
    # Until confirmed, raise loudly instead of silently writing a
    # hand-rolled (and therefore non-compliant, per Req #10) format:
    raise NotImplementedError(
        "Wire this to scheduler.writers' real JSON/CSV writer classes once "
        "confirmed -- see the CONFIRM block in schedule_ops.export_schedule()."
    )