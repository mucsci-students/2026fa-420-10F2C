"""
gui/controllers/locks.py -- locking sections so that the next generation keeps them.

This is the controller behind the padlock buttons on the Schedule Viewer and the "Locked sections"
card on the Schedule Generator. Both pages read and change the SAME list, the session's locks
(app/locks.py), so they always agree with each other.

    lock_section(request, 2, "CMSC 141.01")     lock one section, as placed in schedule 2
    lock_faculty(request, 2, "Hogg")            lock every section Hogg teaches in schedule 2
    unlock_section(request, "CMSC 141.01")
    unlock_faculty(request, "Hogg")             unlock every locked section Hogg teaches
    clear_all(request)                          unlock everything

A lock remembers the section's whole placement (instructor, room, lab, days and times) as it was in
the schedule the user locked it from. Nothing here touches the configuration, the saved schedules or
the undo history.

Every refusal is a ControllerError with a plain sentence for the user. A lock that would clash with
one already held (the same room, lab or instructor at overlapping times) is refused on the spot, so
the user hears about it when they click, not later when generating fails.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.locks import LockSet, find_conflicts
from app.schedule_io import Assignment
from gui.controllers import schedule_controller
from gui.controllers.errors import ControllerError
from gui.session_store import get_session

FREE = "free"  # not locked
LOCKED = "locked"  # locked, and this schedule places it exactly as locked
DIFFERENT = "different"  # locked, but this schedule places it somewhere else


@dataclass(frozen=True)
class SectionRow:
    """One section of the viewed schedule and how it is locked."""

    assignment: Assignment
    state: str


@dataclass(frozen=True)
class FacultyGroup:
    """The viewed schedule's sections for one instructor, with what the bulk buttons need."""

    faculty: str | None
    rows: tuple[SectionRow, ...]  # the sections to list (may be fewer than in_schedule)
    in_schedule: int  # every section this instructor teaches in the viewed schedule
    to_lock: int  # of those, how many are not yet locked exactly like this
    locked_now: int  # locked sections of this instructor, from any schedule


def _locks(request) -> LockSet:
    return get_session(request).locks


# ---------------------------------------------------------------------- #
#  Reading
# ---------------------------------------------------------------------- #
def lock_count(request) -> int:
    """How many sections are locked."""
    return len(_locks(request))


def locked_assignments(request) -> list[Assignment]:
    """The locked placements, ordered by section name."""
    return _locks(request).assignments()


def section_states(request, assignments) -> dict[str, str]:
    """For each section: FREE, LOCKED or DIFFERENT, judged against the given schedule."""
    locks = _locks(request)
    states: dict[str, str] = {}
    for assignment in assignments:
        if assignment.course not in locks:
            states[assignment.course] = FREE
        elif locks.holds(assignment):
            states[assignment.course] = LOCKED
        else:
            states[assignment.course] = DIFFERENT
    return states


def faculty_groups(
    request, schedule: list[Assignment], shown=None
) -> list[FacultyGroup]:
    """The schedule's sections grouped by instructor (A to Z, "no faculty" last).

    `shown` limits which sections are listed (for example the ones the calendar is showing);
    the counts for the bulk buttons always cover the whole schedule.
    """
    locks = _locks(request)
    states = section_states(request, schedule)
    wanted = None if shown is None else set(shown)

    by_faculty: dict[str | None, list[Assignment]] = {}
    for assignment in schedule:
        by_faculty.setdefault(assignment.faculty, []).append(assignment)

    groups: list[FacultyGroup] = []
    for faculty in sorted(
        by_faculty, key=lambda name: (name is None, (name or "").lower())
    ):
        members = sorted(by_faculty[faculty], key=lambda item: item.course)
        rows = tuple(
            SectionRow(item, states[item.course])
            for item in members
            if wanted is None or item.course in wanted
        )
        if not rows:
            continue
        groups.append(
            FacultyGroup(
                faculty=faculty,
                rows=rows,
                in_schedule=len(members),
                to_lock=sum(1 for item in members if states[item.course] != LOCKED),
                locked_now=len(locks.for_faculty(faculty))
                if faculty is not None
                else 0,
            )
        )
    return groups


# ---------------------------------------------------------------------- #
#  Changing
# ---------------------------------------------------------------------- #
def _refuse_clashes(locks: LockSet, new: list[Assignment]) -> None:
    """Refuse when locking `new` would clash with a lock already held (or with each other)."""
    names = {item.course for item in new}
    prospective = {item.course: item for item in locks.assignments()}
    prospective.update({item.course: item for item in new})
    clashes = [
        clash
        for clash in find_conflicts(prospective.values())
        if clash.first in names or clash.second in names
    ]
    if clashes:
        raise ControllerError(
            " ".join(clash.message for clash in clashes)
            + " Unlock one of them first. Nothing was locked."
        )


def lock_section(request, schedule_number: int, section: str) -> str:
    """Lock `section` exactly as schedule `schedule_number` (1-based) places it."""
    schedule = schedule_controller.get_schedule(request, schedule_number - 1)
    found = next((item for item in schedule if item.course == section), None)
    if found is None:
        raise ControllerError(
            f'"{section}" is not in schedule {schedule_number}, so it cannot be locked from there.'
        )
    locks = _locks(request)
    earlier = locks.get(section)
    _refuse_clashes(locks, [found])
    if not locks.lock(found, schedule_number):
        return f'"{section}" was already locked exactly like this.'
    if earlier is not None:
        return (
            f'Locked "{section}" to the placement in schedule {schedule_number} '
            "instead of its earlier lock."
        )
    return f'Locked "{section}". It stays exactly as it is the next time you generate schedules.'


def lock_faculty(request, schedule_number: int, faculty: str) -> str:
    """Lock every section `faculty` teaches in schedule `schedule_number` (1-based)."""
    schedule = schedule_controller.get_schedule(request, schedule_number - 1)
    sections = [item for item in schedule if item.faculty == faculty]
    if not sections:
        raise ControllerError(
            f"{faculty} does not teach any section in schedule {schedule_number}."
        )
    locks = _locks(request)
    _refuse_clashes(locks, sections)
    changed = locks.lock_many(sections, schedule_number)
    total = _count(len(sections))
    if changed == 0:
        return f"All {total} taught by {faculty} were already locked exactly like this."
    return (
        f"Locked {total} taught by {faculty}. They stay exactly as they are "
        "the next time you generate schedules."
    )


def unlock_section(request, section: str) -> str:
    """Remove the lock on one section."""
    if not _locks(request).unlock(section):
        raise ControllerError(f'"{section}" is not locked.')
    return f'Unlocked "{section}". It can change the next time you generate schedules.'


def unlock_faculty(request, faculty: str) -> str:
    """Remove the lock on every locked section `faculty` teaches."""
    locks = _locks(request)
    sections = [lock.section for lock in locks.for_faculty(faculty)]
    if not sections:
        raise ControllerError(f"None of the sections taught by {faculty} is locked.")
    locks.unlock_many(sections)
    return f"Unlocked {_count(len(sections))} taught by {faculty}."


def clear_all(request) -> int:
    """Remove every lock. Returns how many there were."""
    return _locks(request).clear()


def _count(number: int) -> str:
    return f"{number} section{'' if number == 1 else 's'}"
