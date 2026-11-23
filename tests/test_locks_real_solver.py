"""End to end: the REAL scheduler library with the example configuration.

This is the test that proves locking works (and the one that will fail if a
library update changes the private parts app/lock_solver.py relies on). It runs
the actual solver a few times, so it takes a few seconds.
"""

import dataclasses
from pathlib import Path

import pytest
from scheduler import load_config_from_file
from scheduler.config import CombinedConfig

from app import schedule_io, schedule_ops
from app.lock_solver import placement_key

Outcome = schedule_ops.GenerationOutcome
EXAMPLE = (
    Path(__file__).resolve().parent.parent / "app" / "examples" / "config_example.json"
)


@pytest.fixture(scope="module")
def config():
    """The example configuration shipped with the app."""
    return load_config_from_file(CombinedConfig, str(EXAMPLE))


@pytest.fixture(scope="module")
def first_schedule(config):
    """One generated schedule, as Assignment records."""
    result = schedule_ops.generate_schedules(config, limit_override=1)
    assert result.outcome == Outcome.SUCCESS
    return schedule_io.to_assignments(result.schedules[0])


def pick_locks(placements):
    """A few sections to lock, including one with a lab when there is one."""
    chosen = list(placements[:2])
    with_lab = [p for p in placements if p.lab and p not in chosen]
    return chosen + with_lab[:1]


def assert_kept(schedules, locks):
    """Every schedule places every locked section exactly as locked."""
    for schedule in schedules:
        placed = {a.course: a for a in schedule_io.to_assignments(schedule)}
        for lock in locks:
            assert placement_key(placed[lock.course]) == placement_key(lock)


def test_every_new_schedule_keeps_the_locked_sections(config, first_schedule):
    """The point of the feature: several new schedules, all keeping the locks."""
    locks = pick_locks(first_schedule)

    result = schedule_ops.generate_schedules(config, limit_override=3, locks=locks)

    assert result.outcome == Outcome.SUCCESS
    assert result.schedules
    assert_kept(result.schedules, locks)
    assert f"Kept {len(locks)} locked section(s) in place" in result.message


def test_locks_from_a_saved_and_reloaded_schedule_work_too(config, first_schedule):
    """Locks taken from an imported schedule file behave the same."""
    text = schedule_io.schedules_to_json([first_schedule])
    loaded = schedule_io.parse_schedule_file(text.encode("utf-8"))[0]
    locks = pick_locks(loaded)

    result = schedule_ops.generate_schedules(config, limit_override=2, locks=locks)

    assert result.outcome == Outcome.SUCCESS
    assert_kept(result.schedules, locks)


def test_a_lock_on_a_room_that_does_not_exist_is_refused(config, first_schedule):
    """The library's own room list decides what can be kept."""
    lock = dataclasses.replace(first_schedule[0], room="Nowhere 999")

    result = schedule_ops.generate_schedules(config, limit_override=1, locks=[lock])

    assert result.outcome == Outcome.LOCK_CONFLICT
    assert "Nowhere 999" in result.message
    assert result.schedules == []
