"""
app/generation_job.py -- one schedule-generation run in a background thread.

Model layer (Section 20): no Django, no HTML. It runs the scheduler library
through app.schedule_ops.generate_schedules() on a worker thread and keeps
the state a progress bar needs: how many schedules were found, the limit,
how long it has been running, whether a cancel was requested, and the final
GenerationResult.

    job = GenerationJob(config, limit_override=5, optimizer_overrides=None,
                        on_finish=store_results)
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
  * on_finish(job, result) runs on the worker thread BEFORE the job is marked
    finished, so anyone who sees "finished" can rely on the results having
    been stored.
"""

from __future__ import annotations

import threading
import time
from copy import deepcopy
from typing import Callable, Optional

from app import schedule_ops
from app.schedule_ops import GenerationOutcome, GenerationResult

STATE_RUNNING = "running"
STATE_FINISHED = "finished"


class GenerationJob:
    def __init__(
        self,
        config,
        limit_override: Optional[int] = None,
        optimizer_overrides=None,
        *,
        on_finish: Optional[Callable[["GenerationJob", GenerationResult], None]] = None,
        runner: Optional[Callable] = None,
    ) -> None:
        self._config = deepcopy(config)
        self._limit_override = limit_override
        self._optimizer_overrides = (
            list(optimizer_overrides) if optimizer_overrides is not None else None
        )
        self._on_finish = on_finish
        self._runner = (
            runner  # None -> schedule_ops.generate_schedules, looked up at run time
        )

        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._done = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._found = 0
        self._limit = (
            limit_override
            if limit_override is not None
            else getattr(config, "limit", None)
        )
        self._started_at: Optional[float] = None
        self._finished_at: Optional[float] = None
        self._result: Optional[GenerationResult] = None

    # ------------------------------------------------------------------ #
    #  Control
    # ------------------------------------------------------------------ #
    def start(self) -> None:
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

    def wait(self, timeout: Optional[float] = None) -> bool:
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
    def result(self) -> Optional[GenerationResult]:
        with self._lock:
            return self._result

    def snapshot(self) -> dict:
        """A JSON-friendly picture of the job right now."""
        finished = self.finished
        with self._lock:
            found, limit, result = self._found, self._limit, self._result
            now = time.monotonic()
            started = self._started_at if self._started_at is not None else now
            ended = self._finished_at if self._finished_at is not None else now

        percent = None
        if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0:
            percent = min(100, int(found * 100 / limit))
        if (
            finished
            and result is not None
            and result.outcome == GenerationOutcome.SUCCESS
        ):
            percent = 100

        return {
            "state": STATE_FINISHED if finished else STATE_RUNNING,
            "found": found,
            "limit": limit if isinstance(limit, int) and limit > 0 else None,
            "percent": percent,
            "elapsed": round(max(0.0, ended - started), 1),
            "cancel_requested": self.cancel_requested,
            "outcome": result.outcome if finished and result is not None else None,
            "message": result.message if finished and result is not None else "",
        }

    # ------------------------------------------------------------------ #
    #  Worker thread
    # ------------------------------------------------------------------ #
    def _record_progress(self, found: int, limit) -> None:
        with self._lock:
            self._found = found
            if limit:
                self._limit = limit

    def _run(self) -> None:
        runner = self._runner or schedule_ops.generate_schedules
        try:
            result = runner(
                self._config,
                self._limit_override,
                self._optimizer_overrides,
                on_progress=self._record_progress,
                should_cancel=self._cancel.is_set,
            )
        except Exception as exc:  # noqa: BLE001 -- never let the worker die silently
            result = GenerationResult(GenerationOutcome.RUNTIME_ERROR, str(exc), [])

        try:
            if self._on_finish is not None:
                self._on_finish(self, result)
        except Exception as exc:  # noqa: BLE001 -- e.g. storing the results failed
            result = GenerationResult(GenerationOutcome.RUNTIME_ERROR, str(exc), [])
        finally:
            with self._lock:
                self._result = result
                self._finished_at = time.monotonic()
            self._done.set()
