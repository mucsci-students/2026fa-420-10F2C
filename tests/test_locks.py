"""Tests for app/locks.py: the lock list and the lock-conflict check.

Pure Python: no Django and no scheduler library.
"""

from app.locks import Lock, LockSet, find_conflicts
from app.schedule_io import Assignment, MeetingTime


def meeting(day, start, end, lab=False):
    """A meeting; duration is worked out from the clock times."""
    hours_s, minutes_s = start.split(":")
    hours_e, minutes_e = end.split(":")
    duration = (int(hours_e) * 60 + int(minutes_e)) - (
        int(hours_s) * 60 + int(minutes_s)
    )
    return MeetingTime(day, start, end, duration, lab)


def placed(course, faculty="Hogg", room="Roddy 140", lab=None, meetings=()):
    """An Assignment with the given placement."""
    return Assignment(course, faculty, room, lab, tuple(meetings))


MWF_8 = (
    meeting("MON", "08:00", "08:50"),
    meeting("WED", "08:00", "08:50"),
    meeting("FRI", "08:00", "08:50"),
)


# ---------------------------------------------------------------- LockSet


def test_new_lock_set_is_empty():
    """A fresh LockSet has no locks."""
    locks = LockSet()
    assert len(locks) == 0
    assert locks.sections() == []
    assert locks.assignments() == []
    assert "CMSC 140.01" not in locks
    assert locks.get("CMSC 140.01") is None
    assert locks.version == 0


def test_lock_adds_a_section():
    """Locking records the placement and bumps the version."""
    locks = LockSet()
    a = placed("CMSC 140.01", "Zoppetti", meetings=MWF_8)

    assert locks.lock(a, source=2) is True

    assert "CMSC 140.01" in locks
    assert len(locks) == 1
    lock = locks.get("CMSC 140.01")
    assert isinstance(lock, Lock)
    assert lock.assignment == a
    assert lock.section == "CMSC 140.01"
    assert lock.source == 2
    assert locks.version == 1


def test_locking_the_same_placement_again_changes_nothing():
    """A repeat lock is a no-op and does not bump the version."""
    locks = LockSet()
    a = placed("CMSC 140.01", meetings=MWF_8)
    locks.lock(a)

    assert locks.lock(a) is False

    assert len(locks) == 1
    assert locks.version == 1


def test_locking_a_different_placement_replaces_the_lock():
    """Re-locking a section from another schedule replaces its placement."""
    locks = LockSet()
    first = placed("CMSC 140.01", room="Roddy 140", meetings=MWF_8)
    second = placed("CMSC 140.01", room="Roddy 147", meetings=MWF_8)
    locks.lock(first, source=1)

    assert locks.lock(second, source=3) is True

    assert len(locks) == 1
    lock = locks.get("CMSC 140.01")
    assert lock is not None
    assert lock.assignment == second
    assert lock.source == 3
    assert locks.version == 2


def test_lock_many_counts_only_real_changes():
    """lock_many reports how many locks actually changed."""
    locks = LockSet()
    a = placed("CMSC 140.01", meetings=MWF_8)
    b = placed("CMSC 162.01", meetings=())
    locks.lock(a)

    assert locks.lock_many([a, b], source=1) == 1
    assert locks.sections() == ["CMSC 140.01", "CMSC 162.01"]


def test_unlock_removes_only_that_section():
    """Unlocking one section leaves the others locked."""
    locks = LockSet()
    locks.lock(placed("CMSC 140.01"))
    locks.lock(placed("CMSC 380.01"))
    version = locks.version

    assert locks.unlock("CMSC 140.01") is True

    assert locks.sections() == ["CMSC 380.01"]
    assert locks.version == version + 1


def test_unlock_of_a_section_that_is_not_locked():
    """Unlocking something that is not locked changes nothing."""
    locks = LockSet()
    locks.lock(placed("CMSC 140.01"))
    version = locks.version

    assert locks.unlock("CMSC 999.01") is False

    assert locks.sections() == ["CMSC 140.01"]
    assert locks.version == version


def test_unlock_many_counts_removed_locks():
    """unlock_many reports how many locks it removed."""
    locks = LockSet()
    locks.lock_many([placed("A 1.01"), placed("B 2.01"), placed("C 3.01")])

    assert locks.unlock_many(["A 1.01", "C 3.01", "Z 9.01"]) == 2
    assert locks.sections() == ["B 2.01"]


def test_clear_removes_every_lock():
    """clear() empties the set and says how many it removed."""
    locks = LockSet()
    locks.lock_many([placed("A 1.01"), placed("B 2.01")])
    version = locks.version

    assert locks.clear() == 2

    assert len(locks) == 0
    assert locks.version == version + 1


def test_clear_on_an_empty_set_is_a_no_op():
    """Clearing nothing does not bump the version."""
    locks = LockSet()
    assert locks.clear() == 0
    assert locks.version == 0


def test_iteration_and_assignments_are_ordered_by_section():
    """Locks come back in section order whatever order they were added in."""
    locks = LockSet()
    locks.lock(placed("CMSC 380.01"))
    locks.lock(placed("CMSC 140.01"))
    locks.lock(placed("CMSC 162.01"))

    assert [lock.section for lock in locks] == [
        "CMSC 140.01",
        "CMSC 162.01",
        "CMSC 380.01",
    ]
    assert [a.course for a in locks.assignments()] == locks.sections()


def test_for_faculty_returns_only_that_instructors_locks():
    """for_faculty filters by instructor."""
    locks = LockSet()
    locks.lock(placed("CMSC 380.01", faculty="Hogg"))
    locks.lock(placed("CMSC 162.01", faculty="Hogg"))
    locks.lock(placed("CMSC 140.01", faculty="Zoppetti"))

    assert [lock.section for lock in locks.for_faculty("Hogg")] == [
        "CMSC 162.01",
        "CMSC 380.01",
    ]
    assert locks.for_faculty("Nobody") == []


def test_holds_tells_in_place_from_placed_elsewhere():
    """holds() is True only for the exact locked placement."""
    locks = LockSet()
    locked = placed("CMSC 140.01", room="Roddy 140", meetings=MWF_8)
    locks.lock(locked)

    assert locks.holds(locked) is True
    assert locks.holds(placed("CMSC 140.01", room="Roddy 147", meetings=MWF_8)) is False
    assert locks.holds(placed("CMSC 162.01", meetings=MWF_8)) is False


# ----------------------------------------------------------- find_conflicts


def test_no_conflicts_for_separate_rooms_and_people():
    """Different rooms, different people: nothing to report."""
    a = placed("CMSC 140.01", "Hogg", "Roddy 140", meetings=MWF_8)
    b = placed("CMSC 330.01", "Xie", "Roddy 147", meetings=MWF_8)
    assert find_conflicts([a, b]) == []


def test_same_room_at_overlapping_times_is_a_conflict():
    """The scenario from the user story: two sections, one room, one time."""
    a = placed("CMSC 140.01", "Zoppetti", "Roddy 140", meetings=MWF_8)
    b = placed("CMSC 330.01", "Xie", "Roddy 140", meetings=MWF_8)

    conflicts = find_conflicts([b, a])

    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.kind == "room"
    assert conflict.resource == "Roddy 140"
    assert (conflict.first, conflict.second) == ("CMSC 140.01", "CMSC 330.01")
    assert conflict.day == "MON"
    assert (conflict.start, conflict.end) == ("08:00", "08:50")
    assert '"CMSC 140.01" and "CMSC 330.01"' in conflict.message
    assert "same room (Roddy 140)" in conflict.message
    assert "Monday 08:00-08:50" in conflict.message


def test_partial_overlap_reports_the_overlapping_window():
    """Only the part where both meetings run is reported."""
    a = placed("A 1.01", "P", "R1", meetings=[meeting("TUE", "09:00", "10:30")])
    b = placed("B 2.01", "Q", "R1", meetings=[meeting("TUE", "10:00", "11:00")])

    (conflict,) = find_conflicts([a, b])

    assert (conflict.start, conflict.end) == ("10:00", "10:30")


def test_back_to_back_meetings_do_not_conflict():
    """One ending exactly when the next starts is fine."""
    a = placed("A 1.01", "P", "R1", meetings=[meeting("MON", "08:00", "08:50")])
    b = placed("B 2.01", "Q", "R1", meetings=[meeting("MON", "08:50", "09:40")])
    assert find_conflicts([a, b]) == []


def test_same_time_on_different_days_does_not_conflict():
    """Overlap needs the same day."""
    a = placed("A 1.01", "P", "R1", meetings=[meeting("MON", "08:00", "08:50")])
    b = placed("B 2.01", "Q", "R1", meetings=[meeting("TUE", "08:00", "08:50")])
    assert find_conflicts([a, b]) == []


def test_same_instructor_at_overlapping_times_is_a_conflict():
    """One person cannot teach two sections at once, even in different rooms."""
    a = placed("CMSC 380.01", "Hogg", "Roddy 147", meetings=MWF_8)
    b = placed("CMSC 162.01", "Hogg", "Roddy 140", meetings=MWF_8)

    (conflict,) = find_conflicts([a, b])

    assert conflict.kind == "faculty"
    assert conflict.resource == "Hogg"
    assert "both taught by Hogg" in conflict.message


def test_same_lab_at_overlapping_lab_meetings_is_a_conflict():
    """Lab meetings collide on the lab, not the room."""
    lab_meeting = [meeting("FRI", "09:00", "10:50", lab=True)]
    a = placed("A 1.01", "P", "R1", "Linux", lab_meeting)
    b = placed("B 2.01", "Q", "R2", "Linux", lab_meeting)

    (conflict,) = find_conflicts([a, b])

    assert conflict.kind == "lab"
    assert conflict.resource == "Linux"
    assert "same lab (Linux)" in conflict.message


def test_a_lab_meeting_and_a_room_meeting_do_not_share_a_resource():
    """A lab meeting does not occupy the room, and vice versa."""
    a = placed("A 1.01", "P", "R1", "Linux", [meeting("MON", "09:00", "09:50")])
    b = placed("B 2.01", "Q", "R1", "Linux", [meeting("MON", "09:00", "09:50", True)])
    assert find_conflicts([a, b]) == []


def test_sections_without_a_room_or_meetings_never_conflict():
    """Online sections (no room, no meetings) have nothing to collide on."""
    a = placed("A 1.01", "P", None, meetings=[meeting("MON", "08:00", "08:50")])
    b = placed("B 2.01", "Q", None, meetings=[meeting("MON", "08:00", "08:50")])
    c = placed("C 3.01", "R", "R1", meetings=())
    assert find_conflicts([a, b, c]) == []


def test_each_kind_is_reported_once_per_pair():
    """Three colliding days still give one room conflict for the pair."""
    a = placed("A 1.01", "P", "R1", meetings=MWF_8)
    b = placed("B 2.01", "Q", "R1", meetings=MWF_8)
    assert len(find_conflicts([a, b])) == 1


def test_a_pair_can_report_room_and_faculty_together():
    """Same room and same person at once gives two separate findings."""
    a = placed("A 1.01", "Hogg", "R1", meetings=MWF_8)
    b = placed("B 2.01", "Hogg", "R1", meetings=MWF_8)
    assert sorted(c.kind for c in find_conflicts([a, b])) == ["faculty", "room"]


def test_three_way_clash_reports_each_pair_in_order():
    """Every colliding pair is listed, in section order."""
    a = placed("A 1.01", "P", "R1", meetings=MWF_8)
    b = placed("B 2.01", "Q", "R1", meetings=MWF_8)
    c = placed("C 3.01", "S", "R1", meetings=MWF_8)

    pairs = [(x.first, x.second) for x in find_conflicts([c, a, b])]

    assert pairs == [("A 1.01", "B 2.01"), ("A 1.01", "C 3.01"), ("B 2.01", "C 3.01")]


def test_find_conflicts_accepts_an_empty_list():
    """No locks, no conflicts."""
    assert find_conflicts([]) == []
