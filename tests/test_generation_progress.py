"""
Tests for the live generation progress bar (Sections 13, 14, 19, 23.3, 23.6).

None of these run the real Z3 solver: schedule_ops.Scheduler or
schedule_ops.generate_schedules is replaced with a stub, so they are fast and
deterministic. Threads are always released/joined before a test ends.
"""

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import schedule_ops
from app.generation_job import GenerationJob
from app.schedule_ops import GenerationOutcome, GenerationResult
from app.session import Session
from gui.controllers import schedule_controller as ctrl
from gui.controllers.errors import ControllerError

EXAMPLE = (
    Path(__file__).resolve().parent.parent / "app" / "examples" / "config_example.json"
)
TIMEOUT = 5.0


def wait_for(predicate, timeout=TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def fake_scheduler(count):
    """A stand-in Scheduler whose solver yields `count` schedules."""

    class FakeScheduler:
        def __init__(self, config):
            self.config = config

        def get_models(self):
            for number in range(count):
                yield [f"schedule-{number}"]

    return FakeScheduler


def run_ops(monkeypatch, count, config=None, **kwargs):
    monkeypatch.setattr(schedule_ops, "Scheduler", fake_scheduler(count))
    config = config or SimpleNamespace(limit=None, optimizer_flags=[])
    return schedule_ops.generate_schedules(config, **kwargs)


def blocking_runner(gate, schedules=("a", "b")):
    """A runner that reports one schedule found, then waits for `gate`."""

    def runner(config, limit, flags, on_progress=None, should_cancel=None):
        on_progress(1, limit)
        gate.wait(TIMEOUT)
        return GenerationResult(
            GenerationOutcome.SUCCESS,
            f"Generated {len(schedules)} schedule(s).",
            list(schedules),
        )

    return runner


def cancellable_runner(config, limit, flags, on_progress=None, should_cancel=None):
    while not should_cancel():
        time.sleep(0.01)
    return GenerationResult(
        GenerationOutcome.CANCELLED, "Generation was cancelled.", []
    )


# ---------------------------------------------------------------------- #
#  schedule_ops: progress and cancel hooks
# ---------------------------------------------------------------------- #
def test_progress_is_reported_after_every_schedule(monkeypatch):
    calls = []
    result = run_ops(
        monkeypatch,
        10,
        limit_override=3,
        on_progress=lambda found, limit: calls.append((found, limit)),
    )
    assert result.outcome == GenerationOutcome.SUCCESS
    assert len(result.schedules) == 3
    assert calls == [(1, 3), (2, 3), (3, 3)]


def test_configured_limit_is_used_without_an_override(monkeypatch):
    result = run_ops(
        monkeypatch, 10, config=SimpleNamespace(limit=2, optimizer_flags=[])
    )
    assert len(result.schedules) == 2


def test_override_beats_the_configured_limit(monkeypatch):
    result = run_ops(
        monkeypatch,
        10,
        config=SimpleNamespace(limit=2, optimizer_flags=[]),
        limit_override=4,
    )
    assert len(result.schedules) == 4


def test_without_a_limit_it_runs_until_the_solver_runs_out(monkeypatch):
    calls = []
    result = run_ops(
        monkeypatch, 4, on_progress=lambda found, limit: calls.append((found, limit))
    )
    assert len(result.schedules) == 4
    assert calls[-1] == (4, None)


def test_cancel_is_noticed_between_schedules_and_stores_nothing(monkeypatch):
    found = []
    result = run_ops(
        monkeypatch,
        10,
        limit_override=5,
        on_progress=lambda n, limit: found.append(n),
        should_cancel=lambda: len(found) >= 2,
    )
    assert result.outcome == GenerationOutcome.CANCELLED
    assert result.schedules == []
    assert found == [1, 2]


def test_cancel_before_the_first_schedule(monkeypatch):
    result = run_ops(monkeypatch, 10, should_cancel=lambda: True)
    assert result.outcome == GenerationOutcome.CANCELLED


def test_no_schedules_is_reported_as_infeasible(monkeypatch):
    assert run_ops(monkeypatch, 0).outcome == GenerationOutcome.NO_FEASIBLE_SCHEDULE


def test_solver_failure_is_a_runtime_error(monkeypatch):
    class Broken:
        def __init__(self, config):
            pass

        def get_models(self):
            raise RuntimeError("boom")
            yield  # pragma: no cover

    monkeypatch.setattr(schedule_ops, "Scheduler", Broken)
    result = schedule_ops.generate_schedules(
        SimpleNamespace(limit=None, optimizer_flags=[])
    )
    assert result.outcome == GenerationOutcome.RUNTIME_ERROR
    assert "boom" in result.message


def test_callbacks_are_optional(monkeypatch):
    assert len(run_ops(monkeypatch, 3, limit_override=2).schedules) == 2


# ---------------------------------------------------------------------- #
#  GenerationJob
# ---------------------------------------------------------------------- #
def test_job_reports_progress_while_running_then_finishes():
    gate = threading.Event()
    job = GenerationJob(SimpleNamespace(limit=10), 4, runner=blocking_runner(gate))
    job.start()
    assert wait_for(lambda: job.snapshot()["found"] == 1)
    snap = job.snapshot()
    assert (snap["state"], snap["limit"], snap["percent"], snap["outcome"]) == (
        "running",
        4,
        25,
        None,
    )

    gate.set()
    assert job.wait(TIMEOUT)
    snap = job.snapshot()
    assert (snap["state"], snap["outcome"], snap["percent"]) == (
        "finished",
        GenerationOutcome.SUCCESS,
        100,
    )
    assert job.result.schedules == ["a", "b"]


def test_percent_is_unknown_without_a_limit():
    gate = threading.Event()
    job = GenerationJob(SimpleNamespace(limit=None), None, runner=blocking_runner(gate))
    job.start()
    assert wait_for(lambda: job.snapshot()["found"] == 1)
    snap = job.snapshot()
    assert snap["limit"] is None and snap["percent"] is None
    gate.set()
    assert job.wait(TIMEOUT)


def test_job_can_be_cancelled():
    job = GenerationJob(SimpleNamespace(limit=3), None, runner=cancellable_runner)
    job.start()
    assert job.snapshot()["cancel_requested"] is False
    job.cancel()
    assert job.wait(TIMEOUT)
    snap = job.snapshot()
    assert snap["cancel_requested"] is True
    assert snap["outcome"] == GenerationOutcome.CANCELLED


def test_a_crashing_runner_becomes_a_runtime_error_result():
    def runner(*args, **kwargs):
        raise RuntimeError("boom")

    job = GenerationJob(SimpleNamespace(limit=3), None, runner=runner)
    job.start()
    assert job.wait(TIMEOUT)
    assert job.result.outcome == GenerationOutcome.RUNTIME_ERROR
    assert "boom" in job.result.message


def test_on_finish_runs_before_the_job_counts_as_finished():
    seen = []
    gate = threading.Event()
    gate.set()
    job = GenerationJob(
        SimpleNamespace(limit=3),
        None,
        runner=blocking_runner(gate),
        on_finish=lambda j, result: seen.append(j.finished),
    )
    job.start()
    assert job.wait(TIMEOUT)
    assert seen == [False]


def test_the_job_runs_on_a_copy_of_the_configuration():
    captured = []

    def runner(config, limit, flags, on_progress=None, should_cancel=None):
        captured.append(config.limit)
        return GenerationResult(GenerationOutcome.SUCCESS, "ok", ["a"])

    config = SimpleNamespace(limit=3)
    job = GenerationJob(config, None, runner=runner)
    config.limit = 99  # edited after the run was requested
    job.start()
    assert job.wait(TIMEOUT)
    assert captured == [3]


def test_a_job_cannot_be_started_twice():
    job = GenerationJob(
        SimpleNamespace(limit=1),
        None,
        runner=lambda *a, **k: GenerationResult("success", "", []),
    )
    job.start()
    assert job.wait(TIMEOUT)
    with pytest.raises(RuntimeError):
        job.start()


# ---------------------------------------------------------------------- #
#  Controller
# ---------------------------------------------------------------------- #
@pytest.fixture
def session(monkeypatch):
    fresh = Session()
    fresh.load(str(EXAMPLE))
    monkeypatch.setattr(ctrl, "get_session", lambda request: fresh)
    return fresh


def finish(session):
    assert session.generation_job.wait(TIMEOUT)


def test_start_generation_runs_in_the_background_and_stores_results(
    session, monkeypatch
):
    gate = threading.Event()
    monkeypatch.setattr(schedule_ops, "generate_schedules", blocking_runner(gate))
    limit_before = getattr(session.config, "limit", None)

    status = ctrl.start_generation(None, limit_override=4)
    assert status["state"] == "running"
    assert session.generating is True and ctrl.is_generating(None) is True

    gate.set()
    finish(session)
    assert session.generating is False
    assert session.schedules == ["a", "b"]
    assert (
        getattr(session.config, "limit", None) == limit_before
    )  # the override never touched the saved limit


def test_overrides_are_passed_to_the_runner(session, monkeypatch):
    seen = {}

    def runner(config, limit, flags, on_progress=None, should_cancel=None):
        seen.update(limit=limit, flags=flags)
        return GenerationResult(GenerationOutcome.SUCCESS, "ok", ["a"])

    monkeypatch.setattr(schedule_ops, "generate_schedules", runner)
    flag = sorted(ctrl.VALID_OPTIMIZER_FLAGS)[0]
    ctrl.start_generation(None, limit_override=7, optimizer_overrides=[flag])
    finish(session)
    assert seen == {"limit": 7, "flags": [flag]}


def test_an_overlapping_start_is_refused(session, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(schedule_ops, "generate_schedules", blocking_runner(gate))
    ctrl.start_generation(None)
    try:
        with pytest.raises(ControllerError) as info:
            ctrl.start_generation(None)
        assert info.value.message == ctrl.BUSY_MESSAGE
    finally:
        gate.set()
        finish(session)


@pytest.mark.parametrize("limit", [0, -1, True, "5"])
def test_an_invalid_limit_prevents_the_run(session, limit):
    with pytest.raises(ControllerError):
        ctrl.start_generation(None, limit_override=limit)
    assert session.generating is False and session.generation_job is None


def test_an_unknown_optimizer_flag_prevents_the_run(session):
    with pytest.raises(ControllerError):
        ctrl.start_generation(None, optimizer_overrides=["not_a_real_flag"])
    assert session.generation_job is None


def test_starting_without_a_configuration_is_refused(monkeypatch):
    empty = Session()
    monkeypatch.setattr(ctrl, "get_session", lambda request: empty)
    with pytest.raises(ControllerError):
        ctrl.start_generation(None)
    assert empty.generating is False


@pytest.mark.parametrize(
    "outcome, expected",
    [
        (GenerationOutcome.SUCCESS, ["new"]),  # replaced
        (
            GenerationOutcome.NO_FEASIBLE_SCHEDULE,
            [],
        ),  # cleared, like the synchronous path
        (GenerationOutcome.INVALID_CONFIG, ["old"]),  # kept
        (GenerationOutcome.RUNTIME_ERROR, ["old"]),  # kept
        (GenerationOutcome.CANCELLED, ["old"]),  # kept
    ],
)
def test_each_outcome_stores_the_right_schedules(
    session, monkeypatch, outcome, expected
):
    session.schedules = ["old"]
    produced = ["new"] if outcome == GenerationOutcome.SUCCESS else []
    monkeypatch.setattr(
        schedule_ops,
        "generate_schedules",
        lambda *a, **k: GenerationResult(outcome, "message", produced),
    )
    ctrl.start_generation(None)
    finish(session)
    assert session.schedules == expected
    assert session.generating is False


def test_generation_status_is_idle_without_a_job(session):
    assert ctrl.generation_status(None) == {"state": "idle"}
    assert ctrl.generation_job_active(None) is False


def test_the_finished_result_is_collected_exactly_once(session, monkeypatch):
    monkeypatch.setattr(
        schedule_ops,
        "generate_schedules",
        lambda *a, **k: GenerationResult(
            GenerationOutcome.SUCCESS, "Generated 1 schedule(s).", ["a"]
        ),
    )
    ctrl.start_generation(None)
    finish(session)
    first = ctrl.collect_generation_result(None)
    assert first.outcome == GenerationOutcome.SUCCESS
    assert ctrl.collect_generation_result(None) is None
    assert ctrl.generation_status(None) == {"state": "idle"}


def test_a_running_job_is_not_collected(session, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(schedule_ops, "generate_schedules", blocking_runner(gate))
    ctrl.start_generation(None)
    try:
        assert ctrl.collect_generation_result(None) is None
        assert ctrl.generation_job_active(None) is True
    finally:
        gate.set()
        finish(session)


def test_cancel_generation_stops_the_run_and_keeps_old_results(session, monkeypatch):
    session.schedules = ["old"]
    monkeypatch.setattr(schedule_ops, "generate_schedules", cancellable_runner)
    ctrl.start_generation(None)
    status = ctrl.cancel_generation(None)
    assert status["cancel_requested"] is True
    finish(session)
    assert session.schedules == ["old"]
    assert ctrl.collect_generation_result(None).outcome == GenerationOutcome.CANCELLED


def test_cancelling_with_nothing_running_is_an_error(session):
    with pytest.raises(ControllerError):
        ctrl.cancel_generation(None)


def test_outcomes_are_described_for_the_user():
    def level(outcome):
        return ctrl.describe_outcome(GenerationResult(outcome, "details", []))[0]

    assert level(GenerationOutcome.SUCCESS) == "success"
    assert level(GenerationOutcome.NO_FEASIBLE_SCHEDULE) == "warning"
    assert level(GenerationOutcome.CANCELLED) == "warning"
    assert level(GenerationOutcome.INVALID_CONFIG) == "error"
    assert level(GenerationOutcome.RUNTIME_ERROR) == "error"


# ---------------------------------------------------------------------- #
#  Views (Django test client)
# ---------------------------------------------------------------------- #
def poll_until_finished(client):
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        body = client.get("/generate/status/").json()
        if body["state"] != "running":
            return body
        time.sleep(0.02)
    pytest.fail("generation did not finish in time")


def test_start_poll_and_collect_through_the_endpoints(client, monkeypatch):
    def runner(config, limit, flags, on_progress=None, should_cancel=None):
        on_progress(1, 1)
        return GenerationResult(
            GenerationOutcome.SUCCESS, "Generated 1 schedule(s).", []
        )

    monkeypatch.setattr(schedule_ops, "generate_schedules", runner)
    response = client.post("/generate/start/", {"limit": "1"})
    assert response.status_code == 200
    assert response.json()["started"] is True

    body = poll_until_finished(client)
    assert body["state"] == "finished"
    assert body["outcome"] == GenerationOutcome.SUCCESS
    assert body["redirect"].endswith("/schedules/")

    assert client.get("/generate/status/").json()["state"] == "idle"  # reported once
    assert "Generated 1 schedule(s)." in client.get("/schedules/").content.decode()


def test_a_run_with_no_feasible_schedule_returns_to_the_generator(client, monkeypatch):
    monkeypatch.setattr(
        schedule_ops,
        "generate_schedules",
        lambda *a, **k: GenerationResult(
            GenerationOutcome.NO_FEASIBLE_SCHEDULE, "none", []
        ),
    )
    client.post("/generate/start/", {})
    body = poll_until_finished(client)
    assert body["outcome"] == GenerationOutcome.NO_FEASIBLE_SCHEDULE
    assert body["redirect"].endswith("/generate/")
    assert "No feasible schedule" in client.get("/generate/").content.decode()


def test_an_invalid_limit_is_rejected_with_an_explanation(client):
    response = client.post("/generate/start/", {"limit": "0"})
    assert response.status_code == 400
    body = response.json()
    assert body["started"] is False and body["errors"]


def test_a_second_start_is_refused_with_409(client, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(schedule_ops, "generate_schedules", blocking_runner(gate))
    try:
        assert client.post("/generate/start/", {}).status_code == 200
        second = client.post("/generate/start/", {})
        assert second.status_code == 409
        assert second.json()["errors"] == [ctrl.BUSY_MESSAGE]
    finally:
        gate.set()
        poll_until_finished(client)


def test_cancel_endpoint_stops_the_run(client, monkeypatch):
    monkeypatch.setattr(schedule_ops, "generate_schedules", cancellable_runner)
    assert client.post("/generate/start/", {}).status_code == 200
    response = client.post("/generate/cancel/")
    assert response.status_code == 200
    assert response.json()["status"]["cancel_requested"] is True
    body = poll_until_finished(client)
    assert body["outcome"] == GenerationOutcome.CANCELLED
    assert body["redirect"].endswith("/generate/")


def test_cancel_with_nothing_running_is_409(client):
    assert client.post("/generate/cancel/").status_code == 409


def test_endpoints_only_accept_their_methods(client):
    assert client.get("/generate/start/").status_code == 405
    assert client.get("/generate/cancel/").status_code == 405
    assert client.post("/generate/status/").status_code == 405


def test_the_page_shows_the_progress_panel_only_while_a_run_exists(client, monkeypatch):
    html = client.get("/generate/").content.decode()
    assert "data-generation-form" in html
    assert 'id="generation-progress"' in html
    assert 'data-active="true"' not in html

    gate = threading.Event()
    monkeypatch.setattr(schedule_ops, "generate_schedules", blocking_runner(gate))
    try:
        client.post("/generate/start/", {})
        assert 'data-active="true"' in client.get("/generate/").content.decode()
    finally:
        gate.set()
        poll_until_finished(client)
