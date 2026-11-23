"""
app/locks.py  --  section locks ("selective regeneration").

Model layer: no Django imports, no scheduler-library imports.

A lock says: "in the schedule I was looking at, this section's placement is
good, so keep it exactly like that the next time schedules are generated."
It records one section's placement (an Assignment: instructor, room, lab and
meetings), nothing else.

Where this lives
    Session.locks (app/session.py) holds one LockSet per browser session. The
    Schedule Viewer, the Schedule Generator and the AI chat all read and
    write that one list, which is how the pages stay in step.

What locks are NOT
    They are not part of the configuration. Locking and unlocking never marks
    the configuration as changed and never enters the undo history.

What is here
    Lock            one locked section (frozen).
    LockSet         the locks of one session: lock, unlock, clear, look up.
    find_conflicts  spots locks that cannot all be true at once (same room,
                    same lab or same instructor at overlapping times), so the
                    generator can refuse with a message naming both sections.
                    The solver stays the final judge of anything subtler.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from app.schedule_io import DAY_NAMES, Assignment, MeetingTime


@dataclass(frozen=True)
class Lock:
    """One locked section: the placement to keep."""

    assignment: Assignment
    # Number (1-based) of the schedule it was locked from, when known. Only for
    # display ("locked from schedule 2"); it never affects generation.
    source: int | None = None

    @property
    def section(self) -> str:
        """The section name, e.g. 'CMSC 140.01'."""
        return self.assignment.course


class LockSet:
    """The locks of one session, keyed by section name.

    A section has at most one lock. Locking it again replaces the old
    placement. `version` goes up on every real change (never on a no-op), so a
    caller can tell whether the locks changed since it last looked.
    """

    def __init__(self) -> None:
        self._locks: dict[str, Lock] = {}
        self.version = 0

    # ----------------------------------------------------------- reading
    def __len__(self) -> int:
        return len(self._locks)

    def __contains__(self, section: object) -> bool:
        return section in self._locks

    def __iter__(self) -> Iterator[Lock]:
        """Every lock, ordered by section name."""
        for section in sorted(self._locks):
            yield self._locks[section]

    def get(self, section: str) -> Lock | None:
        """The lock on `section`, or None."""
        return self._locks.get(section)

    def sections(self) -> list[str]:
        """Locked section names, in order."""
        return sorted(self._locks)

    def assignments(self) -> list[Assignment]:
        """The locked placements, ordered by section name."""
        return [lock.assignment for lock in self]

    def for_faculty(self, faculty: str) -> list[Lock]:
        """Every lock whose section is taught by `faculty`."""
        return [lock for lock in self if lock.assignment.faculty == faculty]

    def holds(self, assignment: Assignment) -> bool:
        """True when `assignment` is exactly the placement its section is locked to.

        The viewer uses this to tell "locked and in place" from "locked, but
        this schedule places the section somewhere else".
        """
        lock = self._locks.get(assignment.course)
        return lock is not None and lock.assignment == assignment

    # ----------------------------------------------------------- changing
    def lock(self, assignment: Assignment, source: int | None = None) -> bool:
        """Lock a section to this placement. Returns True if anything changed.

        Locking a section that is already locked to the same placement changes
        nothing (False). Locking it to a different placement replaces the lock.
        """
        existing = self._locks.get(assignment.course)
        if existing is not None and existing.assignment == assignment:
            return False
        self._locks[assignment.course] = Lock(assignment, source)
        self.version += 1
        return True

    def lock_many(
        self, assignments: Iterable[Assignment], source: int | None = None
    ) -> int:
        """Lock several sections (e.g. all of one instructor's). Returns how many changed."""
        return sum(1 for assignment in assignments if self.lock(assignment, source))

    def unlock(self, section: str) -> bool:
        """Remove one lock. Returns False when the section was not locked."""
        if section not in self._locks:
            return False
        del self._locks[section]
        self.version += 1
        return True

    def unlock_many(self, sections: Iterable[str]) -> int:
        """Remove several locks. Returns how many were removed."""
        return sum(1 for section in list(sections) if self.unlock(section))

    def clear(self) -> int:
        """Remove every lock. Returns how many there were."""
        count = len(self._locks)
        if count:
            self._locks.clear()
            self.version += 1
        return count


# --------------------------------------------------------------------------- #
#  Conflicts between locks
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LockConflict:
    """Two locked sections that cannot both hold."""

    kind: str  # "room", "lab" or "faculty"
    resource: str  # the shared room / lab / instructor name
    first: str  # section names, in alphabetical order
    second: str
    day: str  # MON..FRI
    start: str  # the overlapping window, "HH:MM"
    end: str

    @property
    def message(self) -> str:
        """A sentence for the user that names both sections."""
        when = f"{DAY_NAMES.get(self.day, self.day)} {self.start}-{self.end}"
        pair = f'"{self.first}" and "{self.second}"'
        if self.kind == "faculty":
            return (
                f"{pair} are both taught by {self.resource} and are locked at "
                f"overlapping times ({when})."
            )
        return (
            f"{pair} are locked into the same {self.kind} ({self.resource}) at "
            f"overlapping times ({when})."
        )


def find_conflicts(assignments: Iterable[Assignment]) -> list[LockConflict]:
    """Find locked placements that cannot all be true together.

    Looks at every pair of sections and reports, for each kind (room, lab,
    instructor), the first meeting pair that collides. A lab meeting uses the
    lab; any other meeting uses the room. Meetings that merely touch (one ends
    when the next starts) do not collide. Results come back in a stable order.
    """
    ordered = sorted(assignments, key=lambda assignment: assignment.course)
    found: list[LockConflict] = []
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            found.extend(_pair_conflicts(left, right))
    return found


def _pair_conflicts(left: Assignment, right: Assignment) -> list[LockConflict]:
    reported: set[str] = set()
    found: list[LockConflict] = []
    for left_meeting in left.meetings:
        for right_meeting in right.meetings:
            window = _overlap(left_meeting, right_meeting)
            if window is None:
                continue
            for kind, resource in _shared_resources(
                left, left_meeting, right, right_meeting
            ):
                if kind in reported:
                    continue
                reported.add(kind)
                found.append(
                    LockConflict(
                        kind,
                        resource,
                        left.course,
                        right.course,
                        left_meeting.day,
                        window[0],
                        window[1],
                    )
                )
    return found


def _shared_resources(
    left: Assignment,
    left_meeting: MeetingTime,
    right: Assignment,
    right_meeting: MeetingTime,
) -> list[tuple[str, str]]:
    shared: list[tuple[str, str]] = []
    both_lab = left_meeting.lab and right_meeting.lab
    neither_lab = not left_meeting.lab and not right_meeting.lab
    if both_lab and left.lab is not None and left.lab == right.lab:
        shared.append(("lab", left.lab))
    if neither_lab and left.room is not None and left.room == right.room:
        shared.append(("room", left.room))
    if left.faculty is not None and left.faculty == right.faculty:
        shared.append(("faculty", left.faculty))
    return shared


def _overlap(left: MeetingTime, right: MeetingTime) -> tuple[str, str] | None:
    """The overlapping window of two meetings on the same day, or None."""
    if left.day != right.day:
        return None
    start = max(left.start, right.start, key=_minutes)
    end = min(left.end, right.end, key=_minutes)
    if _minutes(start) < _minutes(end):
        return start, end
    return None


def _minutes(clock: str) -> int:
    hours, minutes = clock.split(":")
    return int(hours) * 60 + int(minutes)
