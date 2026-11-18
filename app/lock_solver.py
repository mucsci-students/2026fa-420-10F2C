"""
app/lock_solver.py  --  turns section locks into rules for the solver.

Model layer: no Django imports.

The scheduler library has no "lock" feature, but it builds one list of hard
rules (`SolverEngine._constraints`) and hands every rule to Z3 when
`get_models()` starts. A lock is just four more rules for one section:

    instructor == the locked instructor
    room       == the locked room
    lab        == the locked lab (or "no lab")
    time       == one of the library's time slots with the locked meetings

so the solver only searches for everything else, and every schedule it
returns keeps the locks. Nothing is generated and thrown away.

This is the ONLY module that reaches into the library's private parts
(`Scheduler._solver`). If a library update changes them, this is the one file
to fix, and tests/test_locks_real_solver.py will fail to say so.

What is here
    plan_locks     work out the rules for a list of locked placements, or say
                   why a lock cannot be kept (its room, instructor, section or
                   meeting times are not in the current configuration).
    apply_plan     add those rules to a Scheduler before it generates.
    unkept_locks   after generating: which locks a schedule does NOT keep.
                   A safety net: it should always come back empty.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import z3

from app.schedule_io import DAYS, Assignment, MeetingTime, to_assignments

# One meeting as (day 1-5, start in minutes, duration in minutes, is_lab); a
# placement's meetings are the sorted tuple of them, so order never matters.
TimesKey = tuple[tuple[int, int, int, bool], ...]
PlacementKey = tuple[str | None, str | None, str | None, TimesKey]


@dataclass(frozen=True)
class LockPlan:
    """What plan_locks worked out."""

    constraints: tuple[Any, ...] = ()  # Z3 rules to add before generating
    problems: tuple[str, ...] = ()  # sentences for the user; empty when all is well

    @property
    def ok(self) -> bool:
        """True when every lock can be applied."""
        return not self.problems


# --------------------------------------------------------------------------- #
#  Comparing placements
# --------------------------------------------------------------------------- #


def meetings_key(meetings: Iterable[MeetingTime]) -> TimesKey:
    """The meetings of one section in a form that can be compared."""
    return tuple(
        sorted(
            (DAYS.index(m.day) + 1, _minutes(m.start), m.duration, m.lab)
            for m in meetings
        )
    )


def slot_key(slot: Any) -> TimesKey:
    """The same form, for one of the library's TimeSlot objects.

    Uses the slot's own JSON dump: weekdays are 1-5, start is minutes since
    midnight, and `lab_index` says which meeting is the lab meeting.
    """
    data = slot.model_dump(mode="json")
    lab_index = data.get("lab_index")
    return tuple(
        sorted(
            (
                int(meeting["day"]),
                int(meeting["start"]),
                int(meeting["duration"]),
                lab_index is not None and index == lab_index,
            )
            for index, meeting in enumerate(data["times"])
        )
    )


def placement_key(assignment: Assignment) -> PlacementKey:
    """Everything a lock keeps, in a comparable form."""
    return (
        assignment.faculty,
        assignment.room,
        assignment.lab,
        meetings_key(assignment.meetings),
    )


def unkept_locks(schedule: Iterable[Any], locks: Sequence[Assignment]) -> list[str]:
    """Names of the locked sections that `schedule` does not keep in place."""
    placed = {assignment.course: assignment for assignment in to_assignments(schedule)}
    broken = []
    for lock in locks:
        found = placed.get(lock.course)
        if found is None or placement_key(found) != placement_key(lock):
            broken.append(lock.course)
    return broken


# --------------------------------------------------------------------------- #
#  Planning
# --------------------------------------------------------------------------- #


def plan_locks(engine: Any, locks: Sequence[Assignment]) -> LockPlan:
    """Work out the solver rules for `locks`, using a library `Scheduler`.

    A lock with any problem adds no rules at all, so a plan is either usable
    (`ok`) or comes with sentences explaining every lock that is not.
    """
    artifacts = engine._solver.artifacts
    symbols = artifacts.symbols
    slots_by_key = _slots_by_key(symbols.time_slot_constants)

    constraints: list[Any] = []
    problems: list[str] = []
    for lock in locks:
        rules, lock_problems = _plan_one(lock, artifacts, symbols, slots_by_key)
        problems.extend(lock_problems)
        if not lock_problems:
            constraints.extend(rules)
    return LockPlan(tuple(constraints), tuple(problems))


def apply_plan(engine: Any, plan: LockPlan) -> None:
    """Add the plan's rules to the Scheduler, before `get_models()` is called."""
    engine._solver._constraints.extend(plan.constraints)


def _slots_by_key(time_slot_constants: Any) -> dict[TimesKey, list[Any]]:
    by_key: dict[TimesKey, list[Any]] = {}
    for slot in time_slot_constants:
        if slot is not None:
            by_key.setdefault(slot_key(slot), []).append(slot)
    return by_key


def _plan_one(
    lock: Assignment, artifacts: Any, symbols: Any, slots_by_key: dict
) -> tuple[list[Any], list[str]]:
    section = lock.course
    variables = artifacts.course_variables.get(section)
    if variables is None:
        missing = (
            f'"{section}" is not in the current configuration, so its lock '
            "cannot be kept."
        )
        return [], [missing]

    rules: list[Any] = []
    problems: list[str] = []
    for kind, name, constants, variable in (
        ("instructor", lock.faculty, symbols.faculty_constants, variables.faculty),
        ("room", lock.room, symbols.room_constants, variables.room),
        ("lab", lock.lab, symbols.lab_constants, variables.lab),
    ):
        constant = constants.get(name)
        if constant is not None:
            rules.append(variable == constant)
        elif name is not None:
            problems.append(
                f'"{section}" is locked to {kind} {name}, but that {kind} is '
                "not in the current configuration."
            )

    if lock.meetings:  # an online section has none: nothing to pin
        candidates = slots_by_key.get(meetings_key(lock.meetings), [])
        if not candidates:
            problems.append(
                f'"{section}" is locked to meeting times that the current time '
                "slot setup does not offer."
            )
        else:
            options = [
                variables.time == symbols.time_slot_constants[slot]
                for slot in candidates
            ]
            rules.append(options[0] if len(options) == 1 else z3.Or(*options))
    return rules, problems


def _minutes(clock: str) -> int:
    hours, minutes = clock.split(":")
    return int(hours) * 60 + int(minutes)
