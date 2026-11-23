"""Tests for app/lock_solver.py: turning locks into solver rules.

The solver parts use the real z3 with small hand-made tables (no scheduler
library), so they are fast. tests/test_locks_real_solver.py runs the real thing.
"""

from dataclasses import dataclass
from types import SimpleNamespace

import z3

from app.lock_solver import (
    LockPlan,
    apply_plan,
    meetings_key,
    placement_key,
    plan_locks,
    slot_key,
    unkept_locks,
)
from app.schedule_io import Assignment, MeetingTime


def meet(day, start, end, duration, lab=False):
    """One meeting."""
    return MeetingTime(day, start, end, duration, lab)


MWF_8 = (
    meet("MON", "08:00", "08:50", 50),
    meet("WED", "08:00", "08:50", 50),
    meet("FRI", "08:00", "08:50", 50),
)
TR_10 = (
    meet("TUE", "10:00", "11:15", 75),
    meet("THU", "10:00", "11:15", 75),
)
LAB_WEEK = (
    meet("MON", "09:00", "09:50", 50),
    meet("FRI", "09:00", "10:50", 110, True),
)


@dataclass(frozen=True)
class FakeSlot:
    """Stand-in for the library's TimeSlot: (day, start, duration) per meeting."""

    times: tuple
    lab_index: int | None = None
    tag: str = ""  # makes two slots with the same times different objects

    def model_dump(self, mode="python"):
        """The same JSON shape the real TimeSlot gives."""
        return {
            "times": [
                {"day": day, "start": start, "duration": duration, "delivery": "x"}
                for day, start, duration in self.times
            ],
            "lab_index": self.lab_index,
            "max_time_gap": 30,
        }


SLOT_MWF = FakeSlot(((1, 480, 50), (3, 480, 50), (5, 480, 50)))
SLOT_TR = FakeSlot(((2, 600, 75), (4, 600, 75)))
SLOT_LAB = FakeSlot(((1, 540, 50), (5, 540, 110)), lab_index=1)

LOCK_140 = Assignment("CMSC 140.01", "Hogg", "Roddy 140", None, MWF_8)
LOCK_162 = Assignment("CMSC 162.01", "Xie", "Roddy 147", "Linux", LAB_WEEK)


def make_env(duplicate_slot=False, room_none=False):
    """A tiny solver world: two sections, two instructors, two rooms, two labs.

    Every call gets its own Z3 context, because a context refuses a second
    enumeration sort with the same name.
    """
    ctx = z3.Context()
    faculty_sort, (hogg, xie) = z3.EnumSort("FacultyT", ["hogg", "xie"], ctx=ctx)
    room_names = ["r140", "r147"] + (["noroom"] if room_none else [])
    room_sort, room_consts = z3.EnumSort("RoomT", room_names, ctx=ctx)
    lab_sort, (nolab, linux) = z3.EnumSort("LabT", ["nolab", "linux"], ctx=ctx)
    slots = [SLOT_MWF, SLOT_TR, SLOT_LAB]
    if duplicate_slot:
        slots.append(FakeSlot(SLOT_TR.times, tag="again"))
    slot_names = [f"slot{i}" for i in range(len(slots))]
    time_sort, times = z3.EnumSort("TimeT", slot_names, ctx=ctx)

    def variables(prefix):
        return SimpleNamespace(
            time=z3.Const(f"{prefix}_time", time_sort),
            faculty=z3.Const(f"{prefix}_faculty", faculty_sort),
            room=z3.Const(f"{prefix}_room", room_sort),
            lab=z3.Const(f"{prefix}_lab", lab_sort),
        )

    room_constants = {"Roddy 140": room_consts[0], "Roddy 147": room_consts[1]}
    if room_none:
        room_constants[None] = room_consts[2]
    v140, v162 = variables("c140"), variables("c162")
    symbols = SimpleNamespace(
        faculty_constants={"Hogg": hogg, "Xie": xie},
        room_constants=room_constants,
        lab_constants={None: nolab, "Linux": linux},
        time_slot_constants=dict(zip(slots, times)),
    )
    artifacts = SimpleNamespace(
        symbols=symbols,
        course_variables={"CMSC 140.01": v140, "CMSC 162.01": v162},
    )
    solver_part = SimpleNamespace(artifacts=artifacts, _constraints=[])
    return SimpleNamespace(
        ctx=ctx,
        engine=SimpleNamespace(_solver=solver_part),
        v140=v140,
        v162=v162,
        hogg=hogg,
        xie=xie,
        r140=room_consts[0],
        r147=room_consts[1],
        noroom=room_consts[2] if room_none else None,
        nolab=nolab,
        linux=linux,
        times=times,
    )


def satisfiable(env, *extra):
    """Can the rules added so far (plus `extra`) all be true at once?"""
    solver = z3.Solver(ctx=env.ctx)
    solver.add(*env.engine._solver._constraints, *extra)
    return solver.check() == z3.sat


# ---------------------------------------------------------------- comparing


def test_meetings_key_ignores_meeting_order():
    """The same meetings in any order give the same key."""
    assert meetings_key(MWF_8) == meetings_key(reversed(MWF_8))


def test_a_slot_key_matches_the_equivalent_meetings():
    """A library slot and a lock's meetings compare equal when they agree."""
    assert slot_key(SLOT_MWF) == meetings_key(MWF_8)
    assert slot_key(SLOT_TR) == meetings_key(TR_10)
    assert slot_key(SLOT_LAB) == meetings_key(LAB_WEEK)


def test_the_lab_flag_is_part_of_the_key():
    """Which meeting is the lab meeting matters."""
    no_lab_flag = tuple(meet(m.day, m.start, m.end, m.duration) for m in LAB_WEEK)
    assert slot_key(SLOT_LAB) != meetings_key(no_lab_flag)


def test_a_slot_without_a_lab_index_has_no_lab_meeting():
    """lab_index None means no meeting is flagged as the lab."""
    assert all(not is_lab for *_, is_lab in slot_key(SLOT_MWF))


def test_placement_key_ignores_meeting_order_but_not_room():
    """Two placements are the same only if instructor, room, lab and times agree."""
    same = Assignment("CMSC 140.01", "Hogg", "Roddy 140", None, tuple(reversed(MWF_8)))
    other_room = Assignment("CMSC 140.01", "Hogg", "Roddy 147", None, MWF_8)
    assert placement_key(same) == placement_key(LOCK_140)
    assert placement_key(other_room) != placement_key(LOCK_140)


# ---------------------------------------------------------------- planning


def test_a_matching_lock_pins_instructor_room_lab_and_time():
    """The four rules of a lock make the other choices impossible."""
    env = make_env()

    plan = plan_locks(env.engine, [LOCK_140])

    assert plan.ok
    assert plan.problems == ()
    assert len(plan.constraints) == 4
    apply_plan(env.engine, plan)
    v = env.v140
    assert satisfiable(env)
    assert satisfiable(
        env,
        v.faculty == env.hogg,
        v.room == env.r140,
        v.lab == env.nolab,
        v.time == env.times[0],
    )
    assert not satisfiable(env, v.faculty == env.xie)
    assert not satisfiable(env, v.room == env.r147)
    assert not satisfiable(env, v.lab == env.linux)
    assert not satisfiable(env, v.time == env.times[1])


def test_a_lab_lock_pins_the_lab_and_its_slot():
    """A lock on a lab section pins the lab and the slot with the lab meeting."""
    env = make_env()
    apply_plan(env.engine, plan_locks(env.engine, [LOCK_162]))
    v = env.v162
    assert satisfiable(env, v.lab == env.linux, v.time == env.times[2])
    assert not satisfiable(env, v.lab == env.nolab)
    assert not satisfiable(env, v.time == env.times[0])


def test_locking_one_section_leaves_the_others_free():
    """Other sections keep all their options."""
    env = make_env()
    apply_plan(env.engine, plan_locks(env.engine, [LOCK_140]))
    other = env.v162
    assert satisfiable(env, other.faculty == env.hogg)
    assert satisfiable(env, other.faculty == env.xie)
    assert satisfiable(env, other.time == env.times[1])


def test_two_locks_that_cannot_both_hold_make_the_rules_unsatisfiable():
    """Contradictory locks are visible to the solver (it will find no schedule)."""
    env = make_env()
    clash = Assignment("CMSC 140.01", "Xie", "Roddy 140", None, MWF_8)
    plan = plan_locks(env.engine, [LOCK_140, clash])
    apply_plan(env.engine, plan)
    assert not satisfiable(env)


def test_an_unknown_section_is_a_problem():
    """A lock on a section that is not in the configuration cannot be kept."""
    env = make_env()
    ghost = Assignment("CMSC 999.01", "Hogg", "Roddy 140", None, MWF_8)

    plan = plan_locks(env.engine, [ghost])

    assert not plan.ok
    assert plan.constraints == ()
    assert '"CMSC 999.01" is not in the current configuration' in plan.problems[0]


def test_an_unknown_instructor_room_or_lab_is_a_problem():
    """Each missing thing is named in its own sentence."""
    env = make_env()
    bad = Assignment("CMSC 140.01", "Nobody", "Nowhere 1", "Moon", MWF_8)

    plan = plan_locks(env.engine, [bad])

    assert len(plan.problems) == 3
    joined = " ".join(plan.problems)
    assert "instructor Nobody" in joined
    assert "room Nowhere 1" in joined
    assert "lab Moon" in joined
    assert plan.constraints == ()


def test_meeting_times_the_library_does_not_offer_are_a_problem():
    """If no slot has exactly those meetings, the lock cannot be kept."""
    env = make_env()
    odd = Assignment(
        "CMSC 140.01", "Hogg", "Roddy 140", None, (meet("MON", "07:00", "07:50", 50),)
    )

    plan = plan_locks(env.engine, [odd])

    assert not plan.ok
    assert "meeting times" in plan.problems[0]


def test_a_lock_with_a_problem_adds_no_rules_but_good_locks_still_do():
    """Problems are per lock: only the bad lock is left out of the rules."""
    env = make_env()
    bad = Assignment("CMSC 999.01", "Hogg", "Roddy 140", None, MWF_8)

    plan = plan_locks(env.engine, [bad, LOCK_140])

    assert len(plan.problems) == 1
    assert len(plan.constraints) == 4


def test_a_section_without_meetings_pins_everything_but_the_time():
    """An online section has no meetings, so its time is left to the solver."""
    env = make_env()
    online = Assignment("CMSC 140.01", "Hogg", "Roddy 140", None, ())

    plan = plan_locks(env.engine, [online])
    apply_plan(env.engine, plan)

    assert plan.ok
    assert len(plan.constraints) == 3
    assert satisfiable(env, env.v140.time == env.times[1])


def test_a_locked_no_room_is_pinned_when_the_library_has_a_no_room_value():
    """room None means 'no room' when the solver models that."""
    env = make_env(room_none=True)
    lock = Assignment("CMSC 140.01", "Hogg", None, None, MWF_8)

    plan = plan_locks(env.engine, [lock])
    apply_plan(env.engine, plan)

    assert len(plan.constraints) == 4
    assert satisfiable(env, env.v140.room == env.noroom)
    assert not satisfiable(env, env.v140.room == env.r140)


def test_a_locked_no_room_is_skipped_when_the_library_has_no_such_value():
    """With no 'no room' value there is nothing to pin, and that is not an error."""
    env = make_env()
    lock = Assignment("CMSC 140.01", "Hogg", None, None, MWF_8)

    plan = plan_locks(env.engine, [lock])

    assert plan.ok
    assert len(plan.constraints) == 3


def test_several_slots_with_the_same_meetings_are_all_allowed():
    """If the library has duplicate-looking slots, any of them satisfies the lock."""
    env = make_env(duplicate_slot=True)
    lock = Assignment("CMSC 140.01", "Hogg", "Roddy 140", None, TR_10)

    apply_plan(env.engine, plan_locks(env.engine, [lock]))

    assert satisfiable(env, env.v140.time == env.times[1])
    assert satisfiable(env, env.v140.time == env.times[3])
    assert not satisfiable(env, env.v140.time == env.times[0])


def test_apply_plan_adds_to_the_solvers_own_list():
    """The rules go into the very list the solver reads."""
    env = make_env()
    rules = env.engine._solver._constraints

    apply_plan(env.engine, plan_locks(env.engine, [LOCK_140]))

    assert env.engine._solver._constraints is rules
    assert len(rules) == 4


def test_an_empty_plan_is_ok_and_adds_nothing():
    """No locks, no rules."""
    env = make_env()
    plan = plan_locks(env.engine, [])
    assert plan == LockPlan()
    assert plan.ok
    apply_plan(env.engine, plan)
    assert env.engine._solver._constraints == []


# ---------------------------------------------------------------- unkept_locks


def test_unkept_locks_is_empty_when_every_lock_is_kept():
    """A schedule that keeps the locks (meeting order aside) reports nothing."""
    schedule = [
        Assignment("CMSC 140.01", "Hogg", "Roddy 140", None, tuple(reversed(MWF_8))),
        LOCK_162,
        Assignment("CMSC 380.01", "Xie", "Roddy 136", None, TR_10),
    ]
    assert unkept_locks(schedule, [LOCK_140, LOCK_162]) == []


def test_unkept_locks_names_a_moved_section():
    """A section placed somewhere else is reported."""
    moved = Assignment("CMSC 140.01", "Hogg", "Roddy 147", None, MWF_8)
    assert unkept_locks([moved, LOCK_162], [LOCK_140, LOCK_162]) == ["CMSC 140.01"]


def test_unkept_locks_names_a_missing_section():
    """A locked section that is not in the schedule at all is reported."""
    assert unkept_locks([LOCK_162], [LOCK_140, LOCK_162]) == ["CMSC 140.01"]
