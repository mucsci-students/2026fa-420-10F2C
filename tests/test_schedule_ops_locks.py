"""Tests for the locks part of schedule_ops.generate_schedules().

The scheduler library is replaced by a fake, so these are fast. They check the
order of events (conflict check, then rules, then solving, then verifying) and
the outcome for each way a run can end.
"""

from types import SimpleNamespace

from app import lock_solver, schedule_ops
from app.lock_solver import LockPlan
from app.schedule_io import Assignment, MeetingTime

Outcome = schedule_ops.GenerationOutcome

MWF_8 = (
    MeetingTime("MON", "08:00", "08:50", 50),
    MeetingTime("WED", "08:00", "08:50", 50),
    MeetingTime("FRI", "08:00", "08:50", 50),
)
TR_10 = (
    MeetingTime("TUE", "10:00", "11:15", 75),
    MeetingTime("THU", "10:00", "11:15", 75),
)

LOCK_A = Assignment("CMSC 140.01", "Zoppetti", "Roddy 140", None, MWF_8)
LOCK_B = Assignment("CMSC 380.01", "Hogg", "Roddy 147", None, TR_10)
OTHER = Assignment("CMSC 162.01", "Xie", "Roddy 136", None, TR_10)


def install(monkeypatch, schedules, plan=None, plan_error=None):
    """Replace the library's Scheduler and the rule-building with fakes."""
    calls = SimpleNamespace(constructed=0, planned=[], applied=[])

    class FakeScheduler:
        """Yields the prepared schedules."""

        def __init__(self, config):
            calls.constructed += 1

        def get_models(self):
            yield from schedules

    def fake_plan(engine, locks):
        calls.planned.append(list(locks))
        if plan_error is not None:
            raise plan_error
        return plan or LockPlan()

    monkeypatch.setattr(schedule_ops, "Scheduler", FakeScheduler)
    monkeypatch.setattr(lock_solver, "plan_locks", fake_plan)
    monkeypatch.setattr(
        lock_solver, "apply_plan", lambda engine, plan: calls.applied.append(plan)
    )
    return calls


def generate(locks=None):
    """Run generate_schedules on a throwaway config."""
    return schedule_ops.generate_schedules(SimpleNamespace(limit=None), locks=locks)


def test_without_locks_nothing_about_locks_happens(monkeypatch):
    """No locks: the old behavior, with the old message."""
    calls = install(monkeypatch, [[OTHER], [OTHER]])

    result = generate()

    assert result.outcome == Outcome.SUCCESS
    assert result.message == "Generated 2 schedule(s)."
    assert calls.planned == []
    assert calls.applied == []


def test_an_empty_lock_list_behaves_like_no_locks(monkeypatch):
    """An empty list is the same as None."""
    calls = install(monkeypatch, [[OTHER]])

    result = generate(locks=[])

    assert result.message == "Generated 1 schedule(s)."
    assert calls.planned == []


def test_no_feasible_schedule_without_locks_is_unchanged(monkeypatch):
    """Without locks, an empty result is still 'no feasible schedule'."""
    install(monkeypatch, [])
    assert generate().outcome == Outcome.NO_FEASIBLE_SCHEDULE


def test_conflicting_locks_stop_before_the_solver_is_even_built(monkeypatch):
    """Two sections locked into one room at one time: refuse, naming both."""
    clash = Assignment("CMSC 330.01", "Xie", "Roddy 140", None, MWF_8)
    calls = install(monkeypatch, [[LOCK_A, clash]])

    result = generate(locks=[LOCK_A, clash])

    assert result.outcome == Outcome.LOCK_CONFLICT
    assert result.schedules == []
    assert '"CMSC 140.01" and "CMSC 330.01"' in result.message
    assert "same room (Roddy 140)" in result.message
    assert "Unlock one of them" in result.message
    assert "unchanged" in result.message
    assert calls.constructed == 0


def test_an_invalid_configuration_is_still_reported_as_such(monkeypatch):
    """The library refusing the configuration comes before any lock work."""

    def refuse(config):
        raise ValueError("room Roddy 1 has no capacity")

    monkeypatch.setattr(schedule_ops, "Scheduler", refuse)

    result = generate(locks=[LOCK_A])

    assert result.outcome == Outcome.INVALID_CONFIG
    assert "no capacity" in result.message


def test_locks_that_cannot_be_applied_are_reported_and_nothing_runs(monkeypatch):
    """Problems from plan_locks become one clear message; the solver never runs."""
    plan = LockPlan(problems=('"CMSC 140.01" is not in the current configuration.',))
    calls = install(monkeypatch, [[LOCK_A]], plan=plan)

    result = generate(locks=[LOCK_A])

    assert result.outcome == Outcome.LOCK_CONFLICT
    assert "is not in the current configuration" in result.message
    assert "Unlock those sections" in result.message
    assert calls.applied == []
    assert result.schedules == []


def test_a_plan_that_raises_is_a_runtime_error(monkeypatch):
    """If the library's internals changed, say so instead of crashing."""
    install(monkeypatch, [[LOCK_A]], plan_error=AttributeError("no _solver"))

    result = generate(locks=[LOCK_A])

    assert result.outcome == Outcome.RUNTIME_ERROR
    assert "Could not apply the locked sections" in result.message
    assert "no _solver" in result.message


def test_locks_are_applied_and_the_success_message_says_so(monkeypatch):
    """With locks that hold, rules are applied once and the message counts them."""
    plan = LockPlan(constraints=("rule",))
    calls = install(monkeypatch, [[LOCK_A, LOCK_B, OTHER], [LOCK_A, LOCK_B]], plan=plan)

    result = generate(locks=[LOCK_A, LOCK_B])

    assert result.outcome == Outcome.SUCCESS
    assert len(result.schedules) == 2
    assert result.message == (
        "Generated 2 schedule(s). Kept 2 locked section(s) in place."
    )
    assert calls.planned == [[LOCK_A, LOCK_B]]
    assert calls.applied == [plan]


def test_no_schedule_with_locks_is_a_lock_conflict_not_no_feasible(monkeypatch):
    """With locks, an empty result means 'these locks cannot all be kept'."""
    install(monkeypatch, [])

    result = generate(locks=[LOCK_A, LOCK_B])

    assert result.outcome == Outcome.LOCK_CONFLICT
    assert "No schedule can keep all 2 locked section(s)" in result.message
    assert '"CMSC 140.01"' in result.message
    assert '"CMSC 380.01"' in result.message
    assert "unchanged" in result.message
    assert result.schedules == []


def test_a_long_list_of_locks_is_shortened_in_the_message(monkeypatch):
    """The message names the first few locked sections and counts the rest."""
    many = [
        Assignment(f"CMSC {n}.01", "Hogg", f"Room {n}", None, ())
        for n in range(100, 109)
    ]
    install(monkeypatch, [])

    result = generate(locks=many)

    assert "No schedule can keep all 9 locked section(s)" in result.message
    assert "and 3 more" in result.message


def test_a_schedule_that_breaks_a_lock_is_never_returned(monkeypatch):
    """The safety net: if the solver ignored a lock, nothing is saved."""
    moved = Assignment("CMSC 140.01", "Zoppetti", "Roddy 147", None, MWF_8)
    install(monkeypatch, [[moved, OTHER]])

    result = generate(locks=[LOCK_A])

    assert result.outcome == Outcome.RUNTIME_ERROR
    assert "did not keep" in result.message
    assert '"CMSC 140.01"' in result.message
    assert result.schedules == []
