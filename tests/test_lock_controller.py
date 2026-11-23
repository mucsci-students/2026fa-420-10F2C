"""
Tests for gui/controllers/locks.py: locking, unlocking and describing locked sections.

The controller works on the session's locks and reads the schedules the viewer shows. Nothing here
runs the solver. What is covered:
  * locking one section, or all of one instructor's sections, exactly as a schedule places them
  * relocking from another schedule, repeated clicks, unknown sections, missing schedules
  * refusing a lock that clashes with one already held (and locking nothing when a bulk lock clashes)
  * unlocking one section, one instructor's sections, or everything
  * the state of each section (free / locked / different) and the groups the viewer lists
"""

import pytest

from app.schedule_io import Assignment, MeetingTime
from app.session import Session
from gui.controllers import locks as lock_controller
from gui.controllers import schedule_controller
from gui.controllers.errors import ControllerError


def section(course, faculty, room, day, start="09:00", end="09:50"):
    return Assignment(course, faculty, room, None, (MeetingTime(day, start, end, 50),))


A1 = section("CMSC 141.01", "Hogg", "Roddy 136", "MON")
A2 = section("CMSC 141.02", "Hogg", "Roddy 140", "TUE", "10:00", "10:50")
B1 = section("CMSC 142.01", "Barr", "Roddy 147", "WED")
NOBODY = section("CMSC 150.01", None, "Roddy 150", "FRI")
A1_MOVED = section(
    "CMSC 141.01", "Hogg", "Roddy 136", "THU"
)  # same section, placed elsewhere
B1_CLASH = section(
    "CMSC 142.01", "Barr", "Roddy 136", "MON"
)  # takes A1's room and time

SCHEDULE_1 = [A1, A2, B1, NOBODY]
SCHEDULE_2 = [A1_MOVED, A2, B1]
SCHEDULE_3 = [B1_CLASH]


@pytest.fixture
def session(monkeypatch):
    fresh = Session()
    fresh.set_schedules([SCHEDULE_1, SCHEDULE_2, SCHEDULE_3])
    monkeypatch.setattr(lock_controller, "get_session", lambda request: fresh)
    monkeypatch.setattr(schedule_controller, "get_session", lambda request: fresh)
    return fresh


# ---------------------------------------------------------------------- #
#  Locking one section
# ---------------------------------------------------------------------- #
def test_locking_a_section_keeps_it_as_the_schedule_places_it(session):
    text = lock_controller.lock_section(None, 1, "CMSC 141.01")
    assert text.startswith('Locked "CMSC 141.01"')
    assert session.locks.get("CMSC 141.01").assignment == A1
    assert session.locks.get("CMSC 141.01").source == 1


def test_locking_the_same_placement_again_says_so(session):
    lock_controller.lock_section(None, 1, "CMSC 141.01")
    version = session.locks.version
    assert "already locked" in lock_controller.lock_section(None, 1, "CMSC 141.01")
    assert session.locks.version == version


def test_locking_from_another_schedule_replaces_the_lock(session):
    lock_controller.lock_section(None, 1, "CMSC 141.01")
    text = lock_controller.lock_section(None, 2, "CMSC 141.01")
    assert "instead of its earlier lock" in text
    assert session.locks.get("CMSC 141.01").assignment == A1_MOVED


def test_a_section_that_is_not_in_the_schedule_cannot_be_locked_from_it(session):
    with pytest.raises(ControllerError) as error:
        lock_controller.lock_section(None, 3, "CMSC 141.01")
    assert "not in schedule 3" in error.value.message
    assert len(session.locks) == 0


def test_locking_needs_a_schedule_that_exists(session):
    with pytest.raises(ControllerError):
        lock_controller.lock_section(None, 9, "CMSC 141.01")
    session.set_schedules([])
    with pytest.raises(ControllerError):
        lock_controller.lock_section(None, 1, "CMSC 141.01")
    assert len(session.locks) == 0


# ---------------------------------------------------------------------- #
#  Locking all of one instructor's sections
# ---------------------------------------------------------------------- #
def test_locking_an_instructor_locks_every_section_they_teach(session):
    text = lock_controller.lock_faculty(None, 1, "Hogg")
    assert text.startswith("Locked 2 sections taught by Hogg")
    assert session.locks.sections() == ["CMSC 141.01", "CMSC 141.02"]


def test_locking_an_instructor_with_one_section_uses_the_singular(session):
    assert lock_controller.lock_faculty(None, 1, "Barr").startswith(
        "Locked 1 section taught by Barr"
    )


def test_locking_an_instructor_again_says_so(session):
    lock_controller.lock_faculty(None, 1, "Hogg")
    assert "already locked" in lock_controller.lock_faculty(None, 1, "Hogg")


def test_an_instructor_with_no_section_in_the_schedule_is_refused(session):
    with pytest.raises(ControllerError) as error:
        lock_controller.lock_faculty(None, 3, "Hogg")
    assert "does not teach any section in schedule 3" in error.value.message


# ---------------------------------------------------------------------- #
#  Clashes
# ---------------------------------------------------------------------- #
def test_a_lock_that_clashes_with_a_held_lock_is_refused_on_the_spot(session):
    lock_controller.lock_section(None, 1, "CMSC 141.01")
    with pytest.raises(ControllerError) as error:
        lock_controller.lock_section(None, 3, "CMSC 142.01")  # same room, same time
    assert "Unlock one of them first" in error.value.message
    assert "Roddy 136" in error.value.message
    assert "CMSC 142.01" not in session.locks


def test_a_bulk_lock_that_clashes_locks_nothing(session):
    lock_controller.lock_section(None, 3, "CMSC 142.01")  # holds Roddy 136, MON 09:00
    with pytest.raises(ControllerError):
        lock_controller.lock_faculty(None, 1, "Hogg")  # 141.01 needs that room and time
    assert session.locks.sections() == ["CMSC 142.01"]


def test_relocking_a_section_does_not_clash_with_its_own_old_lock(session):
    lock_controller.lock_section(None, 1, "CMSC 141.01")
    lock_controller.lock_section(
        None, 2, "CMSC 141.01"
    )  # moved: must not clash with itself
    assert session.locks.get("CMSC 141.01").assignment == A1_MOVED


# ---------------------------------------------------------------------- #
#  Unlocking
# ---------------------------------------------------------------------- #
def test_unlocking_a_section(session):
    lock_controller.lock_section(None, 1, "CMSC 141.01")
    assert lock_controller.unlock_section(None, "CMSC 141.01").startswith(
        'Unlocked "CMSC 141.01"'
    )
    assert len(session.locks) == 0


def test_unlocking_a_section_that_is_not_locked_is_explained(session):
    with pytest.raises(ControllerError) as error:
        lock_controller.unlock_section(None, "CMSC 141.01")
    assert "is not locked" in error.value.message


def test_unlocking_an_instructor_unlocks_only_their_sections(session):
    lock_controller.lock_faculty(None, 1, "Hogg")
    lock_controller.lock_section(None, 1, "CMSC 142.01")
    assert (
        lock_controller.unlock_faculty(None, "Hogg")
        == "Unlocked 2 sections taught by Hogg."
    )
    assert session.locks.sections() == ["CMSC 142.01"]


def test_unlocking_an_instructor_with_no_locks_is_explained(session):
    with pytest.raises(ControllerError) as error:
        lock_controller.unlock_faculty(None, "Hogg")
    assert "None of the sections taught by Hogg is locked" in error.value.message


def test_clearing_unlocks_everything_and_counts(session):
    lock_controller.lock_faculty(None, 1, "Hogg")
    lock_controller.lock_section(None, 1, "CMSC 142.01")
    assert lock_controller.clear_all(None) == 3
    assert lock_controller.lock_count(None) == 0
    assert lock_controller.clear_all(None) == 0


# ---------------------------------------------------------------------- #
#  Reading
# ---------------------------------------------------------------------- #
def test_locked_assignments_are_ordered_by_section(session):
    lock_controller.lock_section(None, 1, "CMSC 142.01")
    lock_controller.lock_section(None, 1, "CMSC 141.02")
    assert [item.course for item in lock_controller.locked_assignments(None)] == [
        "CMSC 141.02",
        "CMSC 142.01",
    ]


def test_each_section_is_free_locked_or_placed_differently(session):
    lock_controller.lock_section(None, 1, "CMSC 141.01")
    lock_controller.lock_section(None, 1, "CMSC 142.01")
    assert lock_controller.section_states(None, SCHEDULE_1) == {
        "CMSC 141.01": lock_controller.LOCKED,
        "CMSC 141.02": lock_controller.FREE,
        "CMSC 142.01": lock_controller.LOCKED,
        "CMSC 150.01": lock_controller.FREE,
    }
    assert lock_controller.section_states(None, SCHEDULE_2)["CMSC 141.01"] == (
        lock_controller.DIFFERENT
    )


def test_groups_are_by_instructor_with_no_faculty_last(session):
    groups = lock_controller.faculty_groups(None, SCHEDULE_1)
    assert [group.faculty for group in groups] == ["Barr", "Hogg", None]
    hogg = groups[1]
    assert [row.assignment.course for row in hogg.rows] == [
        "CMSC 141.01",
        "CMSC 141.02",
    ]
    assert hogg.in_schedule == 2 and hogg.to_lock == 2 and hogg.locked_now == 0


def test_group_counts_follow_the_locks(session):
    lock_controller.lock_section(None, 1, "CMSC 141.01")
    lock_controller.lock_section(None, 2, "CMSC 141.02")
    hogg = next(
        group
        for group in lock_controller.faculty_groups(None, SCHEDULE_1)
        if group.faculty == "Hogg"
    )
    assert hogg.locked_now == 2
    assert hogg.to_lock == 0  # both are already locked exactly like this
    assert [row.state for row in hogg.rows] == ["locked", "locked"]


def test_groups_list_only_the_shown_sections_but_count_them_all(session):
    groups = lock_controller.faculty_groups(None, SCHEDULE_1, shown={"CMSC 141.02"})
    assert [group.faculty for group in groups] == ["Hogg"]
    assert [row.assignment.course for row in groups[0].rows] == ["CMSC 141.02"]
    assert groups[0].in_schedule == 2


def test_sections_without_an_instructor_have_no_bulk_count(session):
    lock_controller.lock_section(None, 1, "CMSC 150.01")
    nobody = lock_controller.faculty_groups(None, SCHEDULE_1)[-1]
    assert nobody.faculty is None and nobody.locked_now == 0
    assert nobody.rows[0].state == lock_controller.LOCKED
