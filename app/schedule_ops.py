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

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from scheduler import Scheduler
from scheduler.config import OptimizerFlags
from scheduler.writers import CSVWriter, JSONWriter

from app import lock_solver
from app.locks import find_conflicts

DEFAULT_EXPORT_DIR = Path.cwd() / "exports"


class GenerationOutcome:
    """Distinguishes the four cases Req #8 explicitly calls out, instead of
    letting the shell guess from a generic exception."""

    SUCCESS = "success"
    NO_FEASIBLE_SCHEDULE = "no_feasible_schedule"
    INVALID_CONFIG = "invalid_config"
    RUNTIME_ERROR = "runtime_error"
    CANCELLED = "cancelled"  # the user stopped a run in progress; nothing is stored
    # Locked sections cannot all be kept (a clash between locks, a lock that no
    # longer fits the configuration, or no schedule that keeps them all).
    # Nothing is stored and earlier schedules are left alone.
    LOCK_CONFLICT = "lock_conflict"


@dataclass
class GenerationResult:
    outcome: str
    message: str
    schedules: list  # list of (list of CourseInstance); empty unless outcome == SUCCESS
    # The locked sections this run kept in place (SUCCESS only; empty when nothing was locked).
    kept: tuple[str, ...] = ()


def generate_schedules(
    config,
    limit_override: int | None = None,
    optimizer_overrides=None,
    on_progress=None,
    should_cancel=None,
    locks=None,
) -> GenerationResult:
    """Runs the scheduler's public API and reports one of the four outcomes
    Req #8 requires. Does not mutate session state -- the caller (a
    commands.py function) decides whether/how to store the result, e.g.
    `session.schedules = result.schedules`."""

    # Locked sections (a list of Assignment records, see app/locks.py). Clashes
    # between locks need no solver, so they are caught first.
    lock_list = list(locks) if locks else []
    conflicts = find_conflicts(lock_list)
    if conflicts:
        return GenerationResult(
            GenerationOutcome.LOCK_CONFLICT,
            " ".join(conflict.message for conflict in conflicts)
            + " Unlock one of them and try again. Nothing was generated; "
            "your schedules and configuration are unchanged.",
            [],
        )

    # "Require a valid complete configuration" -- if construction itself is
    # what validates completeness, this try/except covers it. If not, add
    # an explicit completeness check here once you've confirmed the
    # library's behavior (see module docstring).
    run_config = config
    if optimizer_overrides is not None:
        run_config = deepcopy(config)
        run_config.optimizer_flags = [
            OptimizerFlags(flag) for flag in optimizer_overrides
        ]

    try:
        engine = Scheduler(run_config)
    except Exception as e:  # noqa: BLE001 -- narrow once the real exception type is known
        return GenerationResult(GenerationOutcome.INVALID_CONFIG, str(e), [])

    # Turn the locks into extra rules for the solver (app/lock_solver.py).
    if lock_list:
        try:
            plan = lock_solver.plan_locks(engine, lock_list)
            if plan.problems:
                return GenerationResult(
                    GenerationOutcome.LOCK_CONFLICT,
                    " ".join(plan.problems)
                    + " Unlock those sections and try again. Nothing was "
                    "generated; your schedules and configuration are unchanged.",
                    [],
                )
            lock_solver.apply_plan(engine, plan)
        except Exception as e:  # noqa: BLE001 -- the library's private parts changed
            return GenerationResult(
                GenerationOutcome.RUNTIME_ERROR,
                f"Could not apply the locked sections: {e}",
                [],
            )

    limit = (
        limit_override
        if limit_override is not None
        else getattr(run_config, "limit", None)
    )

    # The solver yields one schedule at a time, so progress is simply "schedules
    # found so far" out of `limit`. Both hooks are optional:
    #   on_progress(found, limit)  called after every schedule that is found
    #   should_cancel()            polled between schedules; True stops the run
    # A Z3 call that is already searching cannot be interrupted, so a cancel is
    # noticed when the schedule being searched for comes back.
    schedules: list = []

    def cancelled() -> GenerationResult:
        return GenerationResult(
            GenerationOutcome.CANCELLED,
            f"Generation was cancelled after {len(schedules)} schedule(s) were found. "
            "Nothing was saved; your previous schedules are unchanged.",
            [],
        )

    try:
        if should_cancel is not None and should_cancel():
            return cancelled()
        for schedule in engine.get_models():
            schedules.append(schedule)
            if on_progress is not None:
                on_progress(len(schedules), limit)
            if limit and len(schedules) >= limit:
                break
            if should_cancel is not None and should_cancel():
                return cancelled()
    except Exception as e:  # noqa: BLE001 -- the Z3 layer; treat as unexpected runtime error
        return GenerationResult(GenerationOutcome.RUNTIME_ERROR, str(e), [])

    if not schedules:
        if lock_list:
            return GenerationResult(
                GenerationOutcome.LOCK_CONFLICT, _locks_cannot_hold(lock_list), []
            )
        return GenerationResult(
            GenerationOutcome.NO_FEASIBLE_SCHEDULE,
            "The solver found no schedule satisfying every hard constraint.",
            [],
        )

    message = f"Generated {len(schedules)} schedule(s)."
    if lock_list:
        # Safety net: the rules should make this impossible, but never hand
        # back a schedule that does not keep a lock.
        try:
            for schedule in schedules:
                broken = lock_solver.unkept_locks(schedule, lock_list)
                if broken:
                    names = ", ".join(f'"{name}"' for name in broken)
                    return GenerationResult(
                        GenerationOutcome.RUNTIME_ERROR,
                        f"A generated schedule did not keep the lock on {names}. "
                        "Nothing was saved.",
                        [],
                    )
        except Exception as e:  # noqa: BLE001 -- unreadable schedule: do not trust it
            return GenerationResult(
                GenerationOutcome.RUNTIME_ERROR,
                f"Could not check the locked sections: {e}",
                [],
            )
        message += f" Kept {len(lock_list)} locked section(s) in place."

    return GenerationResult(
        GenerationOutcome.SUCCESS,
        message,
        schedules,
        tuple(lock.course for lock in lock_list),
    )


def _locks_cannot_hold(lock_list) -> str:
    """The message for 'the solver found nothing, and there are locks'."""
    names = [lock.course for lock in lock_list]
    shown = ", ".join(f'"{name}"' for name in names[:6])
    if len(names) > 6:
        shown += f" and {len(names) - 6} more"
    return (
        f"No schedule can keep all {len(names)} locked section(s) in place "
        f"({shown}). Unlock one or more of them and try again. Nothing was "
        "generated; your schedules and configuration are unchanged."
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


def export_schedule(
    schedules: list, fmt: str, out_path: str | None, overwrite: bool = False
) -> Path:
    if fmt not in ("json", "csv"):
        raise ValueError(f"Unknown export format: {fmt!r} (expected 'json' or 'csv')")

    target = (
        Path(out_path)
        if out_path and out_path.strip()
        else DEFAULT_EXPORT_DIR / f"schedule.{fmt}"
    )

    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() and not overwrite:
        raise FileExistsError(
            f"'{target}' already exists. Re-run with overwrite confirmed to replace it."
        )

    writer_cls = JSONWriter if fmt == "json" else CSVWriter
    with writer_cls(str(target)) as writer:
        for schedule in schedules:
            writer.add_schedule(schedule)

    return target.resolve()
