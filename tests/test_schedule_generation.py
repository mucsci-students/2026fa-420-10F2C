"""
Unit tests for commands.generate_schedule() in app/commands.py (Req #8).

generate_schedule() is a thin dispatcher over app/schedule_ops.py's
generate_schedules(), which does the real work against the scheduler
library's solver. These tests monkeypatch schedule_ops.generate_schedules
itself to return each of the four GenerationOutcome values Req #8
requires (SUCCESS, NO_FEASIBLE_SCHEDULE, INVALID_CONFIG, RUNTIME_ERROR)
and check that commands.py:
  - stores the returned schedules on the session only on SUCCESS
  - clears session.schedules on NO_FEASIBLE_SCHEDULE (a stale schedule
    list from a previous run shouldn't look valid after a fresh failed
    attempt)
  - leaves session.schedules alone on INVALID_CONFIG/RUNTIME_ERROR (a
    bad or crashing generation attempt shouldn't wipe out schedules
    from an earlier successful run)
  - prints a message that distinguishes all four outcomes
This does not exercise the real Z3 solver -- schedule_ops.py's own
module docstring lists what's still unconfirmed there. Full solver
exhaustiveness testing is explicitly out of scope for Sprint 1 (see
requirements §12: "solver-exhaustiveness testing is not required").
"""
from types import SimpleNamespace

import app.commands as commands
from app import schedule_ops
from app.session import Session


def make_session():
    session = Session()
    session.config = SimpleNamespace()  # generate_schedule() just passes this through
    return session


def fake_result(outcome, message="", schedules=None):
    return schedule_ops.GenerationResult(outcome, message, schedules or [])


def test_generate_schedule_success_stores_schedules(monkeypatch, capsys):
    session = make_session()
    fake_schedules = [["course_instance_1"], ["course_instance_2"]]
    monkeypatch.setattr(
        schedule_ops, "generate_schedules",
        lambda config, limit_override: fake_result(
            schedule_ops.GenerationOutcome.SUCCESS, "Generated 2 schedule(s).", fake_schedules
        ),
    )

    commands.generate_schedule(session)

    assert session.schedules == fake_schedules
    assert "generated 2 schedule(s)" in capsys.readouterr().out.lower()


def test_generate_schedule_no_feasible_schedule_clears_session_schedules(monkeypatch, capsys):
    session = make_session()
    session.schedules = ["stale", "schedules", "from", "last", "run"]
    monkeypatch.setattr(
        schedule_ops, "generate_schedules",
        lambda config, limit_override: fake_result(
            schedule_ops.GenerationOutcome.NO_FEASIBLE_SCHEDULE,
            "The solver found no schedule satisfying every hard constraint.",
        ),
    )

    commands.generate_schedule(session)

    assert session.schedules == []
    assert "no feasible schedule" in capsys.readouterr().out.lower()


def test_generate_schedule_invalid_config_does_not_touch_schedules(monkeypatch, capsys):
    session = make_session()
    session.schedules = ["previous", "valid", "schedules"]
    monkeypatch.setattr(
        schedule_ops, "generate_schedules",
        lambda config, limit_override: fake_result(
            schedule_ops.GenerationOutcome.INVALID_CONFIG, "3 courses reference an unknown room.",
        ),
    )

    commands.generate_schedule(session)

    # an invalid config shouldn't wipe out schedules from a previous,
    # successful run
    assert session.schedules == ["previous", "valid", "schedules"]
    assert "not valid for generation" in capsys.readouterr().out.lower()


def test_generate_schedule_runtime_error_does_not_touch_schedules(monkeypatch, capsys):
    session = make_session()
    session.schedules = ["previous", "valid", "schedules"]
    monkeypatch.setattr(
        schedule_ops, "generate_schedules",
        lambda config, limit_override: fake_result(
            schedule_ops.GenerationOutcome.RUNTIME_ERROR, "Z3 solver crashed unexpectedly.",
        ),
    )

    commands.generate_schedule(session)

    assert session.schedules == ["previous", "valid", "schedules"]
    assert "unexpected error during generation" in capsys.readouterr().out.lower()


def test_generate_schedule_passes_limit_override_through(monkeypatch):
    session = make_session()
    captured = {}

    def fake_generate(config, limit_override):
        captured["limit_override"] = limit_override
        return fake_result(schedule_ops.GenerationOutcome.SUCCESS, "Generated 1 schedule(s).", [["x"]])

    monkeypatch.setattr(schedule_ops, "generate_schedules", fake_generate)

    commands.generate_schedule(session, limit_override=5)

    assert captured["limit_override"] == 5


def test_generate_schedule_default_limit_override_is_none(monkeypatch):
    session = make_session()
    captured = {}

    def fake_generate(config, limit_override):
        captured["limit_override"] = limit_override
        return fake_result(schedule_ops.GenerationOutcome.SUCCESS, "Generated 1 schedule(s).", [["x"]])

    monkeypatch.setattr(schedule_ops, "generate_schedules", fake_generate)

    commands.generate_schedule(session)  # no limit_override passed

    assert captured["limit_override"] is None