"""
Tests for generating schedules around locked sections (selective regeneration, piece 3).

The solver is replaced by stand-ins, so these run in a moment. What they cover:
  * a job hands its locks to the runner, and only when there are some
  * the Schedule Generator page (both paths) and the controller pass the session's locks
  * a LOCK_CONFLICT keeps the schedules already in the viewer and is shown as an error
  * the result remembers which locks were kept
  * the AI chat shows the locks in its review, says which were kept, reports a conflict plainly,
    and refuses a go-ahead when the locks changed after the review
How the solver itself keeps the locks is tested in tests/test_lock_solver.py and
tests/test_locks_real_solver.py.
"""

import time
from pathlib import Path

import pytest

from app import lock_solver, schedule_ops
from app.generation_job import GenerationJob
from app.schedule_io import Assignment, MeetingTime
from app.schedule_ops import GenerationOutcome, GenerationResult
from app.session import Session
from gui import session_store
from gui.ai.tools import ToolBox
from gui.controllers import schedule_controller as ctrl

EXAMPLE = (
    Path(__file__).resolve().parent.parent / "app" / "examples" / "config_example.json"
)
TIMEOUT = 5.0
CLASH = "Two locked sections need the same room at the same time."


def section(course, faculty, room, day, start="09:00", end="09:50"):
    return Assignment(course, faculty, room, None, (MeetingTime(day, start, end, 50),))


LOCK_A = section("CMSC 141.01", "Hogg", "Roddy 136", "MON")
LOCK_B = section("CMSC 142.01", "Barr", "Roddy 140", "TUE", "10:00", "10:50")


def runner_that_notes(seen, outcome=GenerationOutcome.SUCCESS, message="ok"):
    def runner(config, limit, flags, on_progress=None, should_cancel=None, locks=None):
        seen["locks"] = locks
        seen["called"] = True
        return GenerationResult(outcome, message, [], ())

    return runner


# ---------------------------------------------------------------------- #
#  The result and the job
# ---------------------------------------------------------------------- #
def test_a_result_with_no_locks_kept_says_so():
    assert GenerationResult(GenerationOutcome.SUCCESS, "ok", []).kept == ()


def test_a_job_hands_its_locks_to_the_runner():
    seen = {}
    job = GenerationJob(
        object(), runner=runner_that_notes(seen), locks=[LOCK_A, LOCK_B]
    )
    job.start()
    assert job.wait(TIMEOUT)
    assert seen["locks"] == (LOCK_A, LOCK_B)


def test_a_job_without_locks_calls_a_runner_that_knows_nothing_about_locks():
    calls = []

    def old_runner(config, limit, flags, on_progress=None, should_cancel=None):
        calls.append("called")
        return GenerationResult(GenerationOutcome.SUCCESS, "ok", [])

    job = GenerationJob(object(), runner=old_runner)
    job.start()
    assert job.wait(TIMEOUT)
    assert calls == ["called"]
    assert job.result is not None and job.result.outcome == GenerationOutcome.SUCCESS


def test_locks_changed_after_the_job_started_do_not_change_the_run():
    seen = {}
    locks = [LOCK_A]
    job = GenerationJob(object(), runner=runner_that_notes(seen), locks=locks)
    locks.append(LOCK_B)
    job.start()
    assert job.wait(TIMEOUT)
    assert seen["locks"] == (LOCK_A,)


# ---------------------------------------------------------------------- #
#  The controller
# ---------------------------------------------------------------------- #
@pytest.fixture
def session(monkeypatch):
    fresh = Session()
    fresh.load(str(EXAMPLE))
    monkeypatch.setattr(ctrl, "get_session", lambda request: fresh)
    return fresh


def test_generate_passes_the_locked_sections(session, monkeypatch):
    session.locks.lock(LOCK_A)
    session.locks.lock(LOCK_B)
    seen = {}
    monkeypatch.setattr(schedule_ops, "generate_schedules", runner_that_notes(seen))
    ctrl.generate(None, limit_override=2)
    assert seen["locks"] == [LOCK_A, LOCK_B]


def test_generate_without_locks_does_not_mention_locks(session, monkeypatch):
    calls = []

    def old_style(config, limit_override, optimizer_overrides):
        calls.append("called")
        return GenerationResult(GenerationOutcome.NO_FEASIBLE_SCHEDULE, "none", [])

    monkeypatch.setattr(schedule_ops, "generate_schedules", old_style)
    ctrl.generate(None)
    assert calls == ["called"]


def test_start_generation_passes_the_locked_sections(session, monkeypatch):
    session.locks.lock(LOCK_B)
    seen = {}
    monkeypatch.setattr(schedule_ops, "generate_schedules", runner_that_notes(seen))
    ctrl.start_generation(None)
    assert session.generation_job.wait(TIMEOUT)
    assert seen["locks"] == (LOCK_B,)


def conflict_runner(
    config, limit, flags, on_progress=None, should_cancel=None, locks=None
):
    return GenerationResult(GenerationOutcome.LOCK_CONFLICT, CLASH, [])


def test_a_lock_conflict_keeps_the_schedules_on_the_sync_path(session, monkeypatch):
    session.locks.lock(LOCK_A)
    session.set_schedules([[LOCK_A], [LOCK_B]])
    monkeypatch.setattr(schedule_ops, "generate_schedules", conflict_runner)
    result = ctrl.generate(None)
    assert result.outcome == GenerationOutcome.LOCK_CONFLICT
    assert len(session.schedules) == 2


def test_a_lock_conflict_keeps_the_schedules_on_the_background_path(
    session, monkeypatch
):
    session.locks.lock(LOCK_A)
    session.set_schedules([[LOCK_A], [LOCK_B]])
    monkeypatch.setattr(schedule_ops, "generate_schedules", conflict_runner)
    ctrl.start_generation(None)
    assert session.generation_job.wait(TIMEOUT)
    assert len(session.schedules) == 2
    assert not session.generating
    result = ctrl.collect_generation_result(None)
    assert result is not None and result.outcome == GenerationOutcome.LOCK_CONFLICT


def test_a_lock_conflict_is_described_as_an_error_with_its_own_message():
    result = GenerationResult(GenerationOutcome.LOCK_CONFLICT, CLASH, [])
    assert ctrl.describe_outcome(result) == ("error", CLASH)


# ---------------------------------------------------------------------- #
#  The Schedule Generator page
# ---------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


def browser_session(client):
    """Open the browser's session (a first page view) and return it."""
    client.get("/generate/")
    (opened,) = session_store._SESSIONS.values()
    return opened


def poll_until_finished(client):
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        body = client.get("/generate/status/").json()
        if body["state"] != "running":
            return body
        time.sleep(0.02)
    pytest.fail("generation did not finish in time")


def test_the_page_starts_a_run_that_keeps_the_locks(client, monkeypatch):
    browser = browser_session(client)
    browser.locks.lock(LOCK_A)
    seen = {}
    monkeypatch.setattr(schedule_ops, "generate_schedules", runner_that_notes(seen))
    assert client.post("/generate/start/", {"limit": "1"}).status_code == 200
    poll_until_finished(client)
    assert seen["locks"] == (LOCK_A,)


def test_the_page_reports_a_conflict_and_keeps_the_schedules(client, monkeypatch):
    browser = browser_session(client)
    browser.locks.lock(LOCK_A)
    browser.set_schedules([[LOCK_A]])
    monkeypatch.setattr(schedule_ops, "generate_schedules", conflict_runner)
    client.post("/generate/start/", {"limit": "1"})
    body = poll_until_finished(client)
    assert body["outcome"] == GenerationOutcome.LOCK_CONFLICT
    assert body["message"] == CLASH
    assert body["redirect"].endswith("/generate/")
    assert CLASH in client.get("/generate/").content.decode()
    assert len(browser.schedules) == 1


def test_the_plain_form_shows_a_conflict_and_keeps_the_schedules(client, monkeypatch):
    browser = browser_session(client)
    browser.locks.lock(LOCK_A)
    browser.set_schedules([[LOCK_A]])
    monkeypatch.setattr(schedule_ops, "generate_schedules", conflict_runner)
    response = client.post("/generate/", {"limit": "1"})
    assert response.status_code == 200
    assert CLASH in response.content.decode()
    assert len(browser.schedules) == 1


# ---------------------------------------------------------------------- #
#  The AI chat
# ---------------------------------------------------------------------- #
class FakeRequest:
    """Enough of a Django request for get_session(): just a session dict."""

    def __init__(self, session=None):
        self.session = {} if session is None else dict(session)


def later(request):
    """The NEXT message from the same browser."""
    return FakeRequest(request.session)


@pytest.fixture
def request_():
    request = FakeRequest()
    session_store.get_session(request)
    return request


def chat_session(request_):
    return session_store.get_session(request_)


@pytest.fixture
def stand_in_solver(monkeypatch):
    """A solver that finds a few schedules, and a lock planner that accepts every lock."""

    class FakeScheduler:
        def __init__(self, config):
            pass

        def get_models(self):
            for number in range(3):
                yield [
                    LOCK_A,
                    LOCK_B,
                    section(f"CMSC 15{number}.01", "Roddy", "Roddy 147", "WED"),
                ]

    monkeypatch.setattr(schedule_ops, "Scheduler", FakeScheduler)
    monkeypatch.setattr(
        lock_solver, "plan_locks", lambda engine, locks: lock_solver.LockPlan()
    )
    monkeypatch.setattr(lock_solver, "apply_plan", lambda engine, plan: None)
    monkeypatch.setattr(lock_solver, "unkept_locks", lambda schedule, locks: [])


def review_and_run(request_):
    ToolBox(request_).call("prepare_schedule_generation", {})
    return ToolBox(later(request_)).call("confirm_schedule_generation")


def test_the_review_lists_the_locked_sections(request_):
    chat_session(request_).locks.lock(LOCK_A)
    chat_session(request_).locks.lock(LOCK_B)
    text = ToolBox(request_).call("prepare_schedule_generation", {}).message
    assert "2 locked sections will be kept exactly where they are" in text
    assert "CMSC 141.01" in text and "CMSC 142.01" in text


def test_the_review_uses_the_singular_for_one_lock(request_):
    chat_session(request_).locks.lock(LOCK_A)
    text = ToolBox(request_).call("prepare_schedule_generation", {}).message
    assert "1 locked section will be kept exactly where it is" in text


def test_the_review_does_not_mention_locks_when_there_are_none(request_):
    text = ToolBox(request_).call("prepare_schedule_generation", {}).message
    assert "locked" not in text


def test_the_reply_says_which_locks_were_kept(request_, stand_in_solver):
    chat_session(request_).locks.lock(LOCK_A)
    chat_session(request_).locks.lock(LOCK_B)
    result = review_and_run(request_)
    assert result.ok
    assert "Generated 3 schedules." in result.message
    assert (
        "Kept 2 locked sections in place: CMSC 141.01, CMSC 142.01." in result.message
    )
    assert len(chat_session(request_).schedules) == 3


def test_the_reply_does_not_mention_locks_when_none_were_kept(
    request_, stand_in_solver
):
    result = review_and_run(request_)
    assert result.ok
    assert "locked" not in result.message


def test_a_conflict_is_reported_plainly_and_keeps_the_schedules(request_, monkeypatch):
    chat_session(request_).locks.lock(LOCK_A)
    chat_session(request_).set_schedules([[LOCK_A], [LOCK_B]])
    monkeypatch.setattr(schedule_ops, "generate_schedules", conflict_runner)
    result = review_and_run(request_)
    assert not result.ok
    assert CLASH in result.message
    assert "were kept" not in result.message  # the conflict message already says it
    assert len(chat_session(request_).schedules) == 2
    assert not chat_session(request_).generating


def test_a_go_ahead_is_refused_when_the_locks_changed_after_the_review(
    request_, monkeypatch
):
    chat_session(request_).locks.lock(LOCK_A)
    ToolBox(request_).call("prepare_schedule_generation", {})

    def refuse(config):
        raise AssertionError("the solver must not start")

    monkeypatch.setattr(schedule_ops, "Scheduler", refuse)
    chat_session(request_).locks.lock(LOCK_B)
    result = ToolBox(later(request_)).call("confirm_schedule_generation")
    assert not result.ok
    assert "locked sections changed" in result.message
    assert chat_session(request_).schedules == []


def test_a_go_ahead_works_when_the_locks_did_not_change(request_, stand_in_solver):
    chat_session(request_).locks.lock(LOCK_A)
    ToolBox(request_).call("prepare_schedule_generation", {})
    chat_session(request_).locks.lock(LOCK_A)  # same placement: nothing changed
    result = ToolBox(later(request_)).call("confirm_schedule_generation")
    assert result.ok
