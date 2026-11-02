"""
Tests for the Observer pattern in schedule generation (app/generation_job.py).

GenerationJob is the subject. Instead of one callback it notifies any number of observers:

    job = GenerationJob(config, limit_override=5, runner=...)
    job.subscribe(observer)        # before start()
    job.start()

An observer is a GenerationObserver: a base class with two no-op hooks it overrides as it needs,

    on_progress(job, found, limit)   after each schedule the solver finds
    on_finished(job, result)         once, BEFORE the job counts as finished

Two observers ship with it: ProgressTracker (found / limit / percent, which job.snapshot() reports) and, in
the GUI controller, ResultsStore (stores or clears the schedules and releases the session).

What these cover:
  * every observer hears every event, in subscription order, on the worker thread
  * unsubscribing, subscribing twice, subscribing after start, and observers with only one hook
  * on_finished runs before job.finished is true (anyone who sees "finished" can rely on the results)
  * a failing observer never stops the others: a failing on_progress is logged and ignored, a failing
    on_finished makes the job's result RUNTIME_ERROR while the other observers still get the original result
  * ProgressTracker is updated before any other observer is told, and job.snapshot() reads it
  * ResultsStore does what the controller's old callback did for every outcome, and always releases the session
  * the old on_finish= argument still works (it subscribes an observer)
"""

import logging
import threading
from types import SimpleNamespace

import pytest

from app import schedule_ops
from app.generation_job import GenerationJob, GenerationObserver, ProgressTracker
from app.schedule_ops import GenerationOutcome, GenerationResult
from app.session import Session
from gui.controllers import schedule_controller as ctrl
from gui.controllers.schedule_controller import ResultsStore

TIMEOUT = 5.0
EXAMPLE = "app/examples/config_example.json"


def steps_runner(steps=2, outcome=GenerationOutcome.SUCCESS):
    """A solver stand-in: reports `steps` schedules found, then returns `outcome`."""

    def runner(config, limit, flags, on_progress=None, should_cancel=None):
        effective = (
            limit if limit is not None else config.limit
        )  # as the real solver reports it
        for number in range(1, steps + 1):
            if on_progress is not None:
                on_progress(number, effective)
        schedules = ["s"] * steps if outcome == GenerationOutcome.SUCCESS else []
        return GenerationResult(outcome, "done", schedules)

    return runner


def make_job(runner=None, limit=5, **kwargs):
    return GenerationJob(
        SimpleNamespace(limit=limit), None, runner=runner or steps_runner(), **kwargs
    )


def run(job):
    job.start()
    assert job.wait(TIMEOUT)
    return job


class Recorder(GenerationObserver):
    """Writes what it hears to a shared log, so tests can check the order across observers."""

    def __init__(self, name, log):
        self.name, self.log = name, log

    def on_progress(self, job, found, limit):
        self.log.append((self.name, "progress", found, limit))

    def on_finished(self, job, result):
        self.log.append((self.name, "finished", result.outcome))


# ---------------------------------------------------------------------- #
#  Subject: subscribing and notifying
# ---------------------------------------------------------------------- #
def test_every_observer_hears_every_event_in_subscription_order():
    log = []
    job = make_job(steps_runner(2), limit=5)
    job.subscribe(Recorder("a", log))
    job.subscribe(Recorder("b", log))
    run(job)

    assert log == [
        ("a", "progress", 1, 5),
        ("b", "progress", 1, 5),
        ("a", "progress", 2, 5),
        ("b", "progress", 2, 5),
        ("a", "finished", GenerationOutcome.SUCCESS),
        ("b", "finished", GenerationOutcome.SUCCESS),
    ]


def test_observers_are_notified_on_the_worker_thread():
    threads = []

    class Where(GenerationObserver):
        def on_finished(self, job, result):
            threads.append(threading.current_thread().name)

    job = make_job()
    job.subscribe(Where())
    run(job)
    assert threads == ["schedule-generation"]


def test_an_unsubscribed_observer_hears_nothing_more():
    log = []
    kept, dropped = Recorder("kept", log), Recorder("dropped", log)
    job = make_job()
    job.subscribe(kept)
    job.subscribe(dropped)
    job.unsubscribe(dropped)
    run(job)
    assert {entry[0] for entry in log} == {"kept"}


def test_unsubscribing_someone_who_never_subscribed_is_harmless():
    make_job().unsubscribe(Recorder("nobody", []))


def test_subscribing_the_same_observer_twice_notifies_it_once():
    log = []
    observer = Recorder("a", log)
    job = make_job(steps_runner(1))
    job.subscribe(observer)
    job.subscribe(observer)
    run(job)
    assert [entry[1] for entry in log] == ["progress", "finished"]


def test_subscribing_after_start_is_refused():
    gate = threading.Event()

    def blocking(config, limit, flags, on_progress=None, should_cancel=None):
        gate.wait(TIMEOUT)
        return GenerationResult(GenerationOutcome.SUCCESS, "ok", [])

    job = make_job(blocking)
    job.start()
    try:
        with pytest.raises(RuntimeError):
            job.subscribe(Recorder("late", []))
    finally:
        gate.set()
        assert job.wait(TIMEOUT)


def test_an_observer_with_only_one_hook_is_enough():
    seen = []

    class OnlyFinished(GenerationObserver):
        def on_finished(self, job, result):
            seen.append(result.outcome)

    class OnlyProgress(GenerationObserver):
        def on_progress(self, job, found, limit):
            seen.append(found)

    job = make_job(steps_runner(1))
    job.subscribe(OnlyFinished())
    job.subscribe(OnlyProgress())
    run(job)
    assert sorted(seen, key=str) == [1, GenerationOutcome.SUCCESS]


def test_the_base_observer_ignores_everything():
    observer, job = GenerationObserver(), make_job()
    observer.on_progress(job, 1, 2)
    observer.on_finished(job, GenerationResult(GenerationOutcome.SUCCESS, "", []))


def test_the_job_lists_its_observers():
    observer = Recorder("a", [])
    job = make_job()
    job.subscribe(observer)
    assert observer in job.observers
    assert isinstance(job.observers, tuple)


def test_on_finished_runs_before_the_job_counts_as_finished():
    seen = []

    class Watcher(GenerationObserver):
        def on_finished(self, job, result):
            seen.append((job.finished, job.result))

    job = make_job()
    job.subscribe(Watcher())
    run(job)
    assert seen == [(False, None)]
    assert job.finished and job.result is not None


# ---------------------------------------------------------------------- #
#  A failing observer never stops the others
# ---------------------------------------------------------------------- #
class Exploding(GenerationObserver):
    def __init__(self, on="progress"):
        self.on = on

    def on_progress(self, job, found, limit):
        if self.on == "progress":
            raise ValueError("progress observer broke")

    def on_finished(self, job, result):
        if self.on == "finished":
            raise ValueError("store broke")


def test_a_failing_on_progress_is_logged_and_ignored(caplog):
    log = []
    job = make_job(steps_runner(2))
    job.subscribe(Exploding("progress"))
    job.subscribe(Recorder("after", log))
    with caplog.at_level(logging.WARNING, logger="app.generation_job"):
        run(job)

    assert [entry for entry in log if entry[1] == "progress"] == [
        ("after", "progress", 1, 5),
        ("after", "progress", 2, 5),
    ]
    assert job.result.outcome == GenerationOutcome.SUCCESS  # the run itself was fine
    assert any(
        "progress observer broke" in record.getMessage() for record in caplog.records
    )


def test_a_failing_on_finished_becomes_a_runtime_error_but_the_others_still_hear_the_result():
    log = []
    job = make_job()
    job.subscribe(Recorder("before", log))
    job.subscribe(Exploding("finished"))
    job.subscribe(Recorder("after", log))
    run(job)

    assert job.result.outcome == GenerationOutcome.RUNTIME_ERROR
    assert "store broke" in job.result.message
    finished = [entry for entry in log if entry[1] == "finished"]
    assert finished == [
        ("before", "finished", GenerationOutcome.SUCCESS),
        ("after", "finished", GenerationOutcome.SUCCESS),  # the ORIGINAL result
    ]
    assert job.finished  # and the job still ends


def test_a_crashing_solver_still_notifies_observers_with_the_error():
    def crashing(*args, **kwargs):
        raise RuntimeError("boom")

    log = []
    job = make_job(crashing)
    job.subscribe(Recorder("a", log))
    run(job)
    assert log == [("a", "finished", GenerationOutcome.RUNTIME_ERROR)]
    assert "boom" in job.result.message


# ---------------------------------------------------------------------- #
#  ProgressTracker: the progress display
# ---------------------------------------------------------------------- #
def test_every_job_has_a_progress_tracker_that_is_told_first():
    seen = []

    class Peek(GenerationObserver):
        def on_progress(self, job, found, limit):
            seen.append((found, job.progress.found))

    job = make_job(steps_runner(2))
    job.subscribe(Peek())
    assert (
        isinstance(job.progress, ProgressTracker) and job.observers[0] is job.progress
    )
    run(job)
    assert seen == [(1, 1), (2, 2)]  # already up to date when the others hear about it


def test_the_tracker_reports_found_limit_and_percent():
    tracker = ProgressTracker(limit=4)
    assert (tracker.found, tracker.limit, tracker.percent) == (0, 4, 0)
    tracker.on_progress(None, 1, 4)
    assert (tracker.found, tracker.limit, tracker.percent) == (1, 4, 25)
    tracker.on_progress(None, 9, 4)
    assert tracker.percent == 100  # never above 100


def test_the_tracker_has_no_percent_without_a_limit():
    tracker = ProgressTracker(limit=None)
    tracker.on_progress(None, 3, None)
    assert (tracker.found, tracker.limit, tracker.percent) == (3, None, None)


@pytest.mark.parametrize("limit", [0, -1, True, "5"])
def test_the_tracker_ignores_a_limit_that_is_not_a_positive_number(limit):
    tracker = ProgressTracker(limit=limit)
    assert tracker.limit is None and tracker.percent is None


def test_the_tracker_learns_the_limit_the_solver_reports():
    tracker = ProgressTracker(limit=None)
    tracker.on_progress(None, 1, 7)
    assert tracker.limit == 7 and tracker.percent == 14


def test_the_snapshot_reads_the_tracker():
    gate = threading.Event()

    def blocking(config, limit, flags, on_progress=None, should_cancel=None):
        assert on_progress is not None
        on_progress(1, limit)
        gate.wait(TIMEOUT)
        return GenerationResult(GenerationOutcome.SUCCESS, "ok", ["a"])

    job = GenerationJob(SimpleNamespace(limit=10), 4, runner=blocking)
    job.start()
    try:
        deadline = threading.Event()
        for _ in range(200):
            if job.snapshot()["found"] == 1:
                break
            deadline.wait(0.01)
        snap = job.snapshot()
        assert (snap["state"], snap["found"], snap["limit"], snap["percent"]) == (
            "running",
            1,
            4,
            25,
        )
        assert job.progress.found == 1
    finally:
        gate.set()
        assert job.wait(TIMEOUT)
    assert job.snapshot()["percent"] == 100  # a successful run ends at 100


# ---------------------------------------------------------------------- #
#  The old callback still works
# ---------------------------------------------------------------------- #
def test_on_finish_is_kept_as_a_thin_wrapper_that_subscribes_an_observer():
    calls = []
    log = []
    job = make_job(on_finish=lambda j, result: calls.append((j is job, result.outcome)))
    job.subscribe(Recorder("a", log))
    run(job)
    assert calls == [(True, GenerationOutcome.SUCCESS)]
    assert ("a", "finished", GenerationOutcome.SUCCESS) in log


def test_a_failing_on_finish_callback_is_still_a_runtime_error():
    def broken(job, result):
        raise RuntimeError("storing failed")

    job = make_job(on_finish=broken)
    run(job)
    assert job.result.outcome == GenerationOutcome.RUNTIME_ERROR
    assert "storing failed" in job.result.message


# ---------------------------------------------------------------------- #
#  ResultsStore: the controller's observer
# ---------------------------------------------------------------------- #
@pytest.fixture
def session(monkeypatch):
    fresh = Session()
    fresh.load(EXAMPLE)
    monkeypatch.setattr(ctrl, "get_session", lambda request: fresh)
    fresh.generating = True  # a run is under way, as start_generation sets it
    return fresh


def finish_with(session, outcome, schedules=()):
    ResultsStore(session).on_finished(
        None, GenerationResult(outcome, "m", list(schedules))
    )


def test_a_successful_run_stores_the_schedules_and_releases_the_session(session):
    finish_with(session, GenerationOutcome.SUCCESS, ["a", "b"])
    assert session.schedules == ["a", "b"] and session.generating is False


def test_no_feasible_schedule_clears_the_old_schedules(session):
    session.set_schedules(["old"])
    finish_with(session, GenerationOutcome.NO_FEASIBLE_SCHEDULE)
    assert session.schedules == [] and session.generating is False


@pytest.mark.parametrize(
    "outcome",
    [
        GenerationOutcome.CANCELLED,
        GenerationOutcome.INVALID_CONFIG,
        GenerationOutcome.RUNTIME_ERROR,
    ],
)
def test_other_outcomes_keep_the_previous_schedules_but_still_release_the_session(
    session, outcome
):
    session.set_schedules(["old"])
    finish_with(session, outcome)
    assert session.schedules == ["old"] and session.generating is False


def test_the_session_is_released_even_when_storing_fails(session, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("cannot store")

    monkeypatch.setattr(ctrl, "_set_schedules", broken)
    with pytest.raises(RuntimeError):
        finish_with(session, GenerationOutcome.SUCCESS, ["a"])
    assert session.generating is False


def test_start_generation_subscribes_a_results_store_and_the_tracker(
    session, monkeypatch
):
    gate = threading.Event()

    def blocking(config, limit, flags, on_progress=None, should_cancel=None):
        gate.wait(TIMEOUT)
        return GenerationResult(GenerationOutcome.SUCCESS, "ok", ["a", "b"])

    monkeypatch.setattr(schedule_ops, "generate_schedules", blocking)
    session.generating = False
    ctrl.start_generation(None, limit_override=3)
    job = session.generation_job
    try:
        kinds = [type(observer) for observer in job.observers]
        assert kinds == [ProgressTracker, ResultsStore]
    finally:
        gate.set()
        assert job.wait(TIMEOUT)
    assert session.schedules == ["a", "b"] and session.generating is False
