"""
app/generation_job.py -- one schedule-generation run in a background thread.

Model layer (Section 20): no Django, no HTML. It runs the scheduler library
through app.schedule_ops.generate_schedules() on a worker thread and tells
whoever is interested what happens. This is the Observer pattern:

    GenerationJob          the subject: runs the solver and notifies, nothing else
    GenerationObserver     the observer: a base class with two no-op hooks,
                             on_progress(job, found, limit)  after each schedule found
                             on_finished(job, result)        once, when the run ends
    ProgressTracker        an observer: found / limit / percent (job.snapshot() reads it)
    ResultsStore           an observer in gui/controllers/schedule_controller.py:
                           stores the results and releases the session

    job = GenerationJob(config, limit_override=5, optimizer_overrides=None)
    job.subscribe(ResultsStore(session))     # before start()
    job.start()
    job.snapshot()   # {"state": "running", "found": 2, "limit": 5, "percent": 40, ...}
    job.cancel()     # takes effect between schedules (see below)
    job.wait(5.0)    # True once finished
    job.result       # GenerationResult, or None while running

Design notes
  * The job works on a deep copy of the configuration, so edits made in
    another tab while it runs cannot change a run that already started.
  * Progress is "schedules found / limit". The solver yields one schedule at
    a time, so the bar moves when a schedule is found; the first schedule is
    often the slowest. With no limit there is no total, so percent is None
    and the page shows an indeterminate bar.
  * Cancel is cooperative: the Z3 call that is searching for the next
    schedule cannot be interrupted, so cancellation is noticed as soon as
    that call returns. A cancelled run stores nothing.
  * Observers are told on the worker thread, in subscription order. Every job
    subscribes its ProgressTracker first, so it is up to date before any other
    observer hears about a schedule. Observers subscribe before start().
  * on_finished runs BEFORE the job is marked finished, so anyone who sees
    "finished" can rely on the results having been stored.
  * A failing observer never stops the others. A failing on_progress is logged
    and ignored. A failing on_finished makes the job's result a runtime error
    (e.g. storing the results failed) while the other observers still receive
    the original result.
  * The old on_finish=function argument still works: it subscribes an observer
    that calls the function.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from copy import deepcopy

from app import schedule_ops
from app.schedule_ops import GenerationOutcome, GenerationResult

logger = logging.getLogger("app.generation_job")

STATE_RUNNING = "running"
STATE_FINISHED = "finished"


# ---------------------------------------------------------------------- #
#  Observers
# ---------------------------------------------------------------------- #
class GenerationObserver:
    """Hears about a generation run. Override only the hooks you need."""

    def on_progress(self, job: GenerationJob, found: int, limit) -> None:
        """A schedule was found: `found` so far, out of `limit` (None if unknown)."""

    def on_finished(self, job: GenerationJob, result: GenerationResult) -> None:
        """The run ended (whatever the outcome). The job is not yet marked finished."""


def _valid_limit(limit) -> int | None:
    return (
        limit
        if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0
        else None
    )


class ProgressTracker(GenerationObserver):
    """The progress display's state: how many schedules were found, and out of how many."""

    def __init__(self, limit=None) -> None:
        self._lock = threading.Lock()
        self._found = 0
        self._limit = _valid_limit(limit)

    @property
    def found(self) -> int:
        with self._lock:
            return self._found

    @property
    def limit(self) -> int | None:
        with self._lock:
            return self._limit

    @property
    def percent(self) -> int | None:
        """Whole percent done, never above 100; None when there is no limit to measure against."""
        with self._lock:
            found, limit = self._found, self._limit
        return None if limit is None else min(100, int(found * 100 / limit))

    def on_progress(self, job, found: int, limit) -> None:
        with self._lock:
            self._found = found
            if _valid_limit(limit) is not None:
                self._limit = limit


class _FinishCallback(GenerationObserver):
    """Adapts the old on_finish=function argument to an observer."""

    def __init__(self, callback: Callable[[GenerationJob, GenerationResult], None]):
        self._callback = callback

    def on_finished(self, job, result) -> None:
        self._callback(job, result)


# ---------------------------------------------------------------------- #
#  The subject
# ---------------------------------------------------------------------- #
class GenerationJob:
    def __init__(
        self,
        config,
        limit_override: int | None = None,
        optimizer_overrides=None,
        *,
        on_finish: Callable[[GenerationJob, GenerationResult], None] | None = None,
        runner: Callable | None = None,
    ) -> None:
        self._config = deepcopy(config)
        self._limit_override = limit_override
        self._optimizer_overrides = (
            list(optimizer_overrides) if optimizer_overrides is not None else None
        )
        self._runner = (
            runner  # None -> schedule_ops.generate_schedules, looked up at run time
        )

        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._done = threading.Event()
        self._thread: threading.Thread | None = None

        self._tracker = ProgressTracker(
            limit_override
            if limit_override is not None
            else getattr(config, "limit", None)
        )
        self._observers: list[GenerationObserver] = [self._tracker]
        if on_finish is not None:
            self.subscribe(_FinishCallback(on_finish))

        self._started_at: float | None = None
        self._finished_at: float | None = None
        self._result: GenerationResult | None = None

    # ------------------------------------------------------------------ #
    #  Observers
    # ------------------------------------------------------------------ #
    def subscribe(self, observer: GenerationObserver) -> None:
        """Be told about this run. Only before start(), so no event can be missed."""
        with self._lock:
            if self._thread is not None:
                raise RuntimeError("Observers must subscribe before the job starts.")
            if observer not in self._observers:
                self._observers.append(observer)

    def unsubscribe(self, observer: GenerationObserver) -> None:
        with self._lock:
            if observer in self._observers:
                self._observers.remove(observer)

    @property
    def observers(self) -> tuple[GenerationObserver, ...]:
        with self._lock:
            return tuple(self._observers)

    @property
    def progress(self) -> ProgressTracker:
        return self._tracker

    # ------------------------------------------------------------------ #
    #  Control
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                raise RuntimeError("This generation job was already started.")
            self._started_at = time.monotonic()
            # daemon: a stuck solver must not keep the server from shutting down
            self._thread = threading.Thread(
                target=self._run, name="schedule-generation", daemon=True
            )
        self._thread.start()

    def cancel(self) -> None:
        """Ask the run to stop. A no-op once the job has finished."""
        self._cancel.set()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the job finishes; True if it did, False on timeout."""
        return self._done.wait(timeout)

    # ------------------------------------------------------------------ #
    #  State
    # ------------------------------------------------------------------ #
    @property
    def finished(self) -> bool:
        return self._done.is_set()

    @property
    def cancel_requested(self) -> bool:
        return self._cancel.is_set()

    @property
    def result(self) -> GenerationResult | None:
        with self._lock:
            return self._result

    def snapshot(self) -> dict:
        """A JSON-friendly picture of the job right now."""
        finished = self.finished
        found, limit, percent = (
            self._tracker.found,
            self._tracker.limit,
            self._tracker.percent,
        )
        with self._lock:
            result = self._result
            now = time.monotonic()
            started = self._started_at if self._started_at is not None else now
            ended = self._finished_at if self._finished_at is not None else now

        if (
            finished
            and result is not None
            and result.outcome == GenerationOutcome.SUCCESS
        ):
            percent = 100

        return {
            "state": STATE_FINISHED if finished else STATE_RUNNING,
            "found": found,
            "limit": limit,
            "percent": percent,
            "elapsed": round(max(0.0, ended - started), 1),
            "cancel_requested": self.cancel_requested,
            "outcome": result.outcome if finished and result is not None else None,
            "message": result.message if finished and result is not None else "",
        }

    # ------------------------------------------------------------------ #
    #  Worker thread
    # ------------------------------------------------------------------ #
    def _notify_progress(self, found: int, limit) -> None:
        for observer in self.observers:
            try:
                observer.on_progress(self, found, limit)
            except Exception as exc:  # noqa: BLE001 -- a broken observer must not stop the run
                logger.warning(
                    "Generation observer %s failed on progress: %s",
                    type(observer).__name__,
                    exc,
                )

    def _notify_finished(self, result: GenerationResult) -> GenerationResult:
        """Tell every observer the result. If any fails (e.g. storing the results failed), the job's
        result becomes a runtime error; the others still hear the original result."""
        failure: Exception | None = None
        for observer in self.observers:
            try:
                observer.on_finished(self, result)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Generation observer %s failed on finish: %s",
                    type(observer).__name__,
                    exc,
                )
                failure = failure or exc
        if failure is None:
            return result
        return GenerationResult(GenerationOutcome.RUNTIME_ERROR, str(failure), [])

    def _run(self) -> None:
        runner = self._runner or schedule_ops.generate_schedules
        try:
            result = runner(
                self._config,
                self._limit_override,
                self._optimizer_overrides,
                on_progress=self._notify_progress,
                should_cancel=self._cancel.is_set,
            )
        except Exception as exc:  # noqa: BLE001 -- never let the worker die silently
            result = GenerationResult(GenerationOutcome.RUNTIME_ERROR, str(exc), [])

        try:
            result = self._notify_finished(result)
        finally:
            with self._lock:
                self._result = result
                self._finished_at = time.monotonic()
            self._done.set()
