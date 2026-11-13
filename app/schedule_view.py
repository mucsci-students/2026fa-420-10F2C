"""Schedule view model: one schedule as meeting blocks, and the ways to group them.

Model layer (Section 20). No Django imports -- the Schedule Viewer's calendar
(gui/calendar_layout.py) is built from this module, and it is tested directly.

Two things live here:

* ``MeetingBlock`` -- one weekly meeting of one course section, with the course
  and section split apart and the room or lab kept with its kind.
  ``meeting_blocks()`` turns a schedule (``Assignment`` records, generated or
  imported) into blocks in calendar order.
* ``Grouping`` -- the Strategy pattern. A schedule can be read by course, by room
  or lab, or by faculty member. Each grouping answers the same questions in its
  own way: which item a block belongs to, what to call it, which other facts to
  show beside it, which choices to offer, and which blocks a set of picked items
  keeps. Callers hold a ``Grouping`` and never branch on which one it is.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import NamedTuple

from app.schedule_io import DAY_NAMES, DAYS, Assignment

# What a block says when a meeting has no room or lab (for example an online
# section), or when its course has no faculty member.
NO_LOCATION_LABEL = "No room assigned"
NO_FACULTY_LABEL = "No faculty assigned"

ROOM = "room"
LAB = "lab"

_DAY_ORDER = {day: index for index, day in enumerate(DAYS)}


class Resource(NamedTuple):
    """A room or a lab. The kind is part of the key, so a room and a lab that
    share a name stay two different resources."""

    kind: str  # ROOM or LAB
    name: str


def split_course(course: str) -> tuple[str, str]:
    """Split a section name at its last dot: "CMSC 140.01" -> ("CMSC 140", "01").

    A name with no dot has no section part: "CMSC 140" -> ("CMSC 140", "").
    """
    course_name, dot, section = course.rpartition(".")
    return (course_name, section) if dot else (course, "")


@dataclass(frozen=True)
class MeetingBlock:
    """One weekly meeting of one course section."""

    course: str  # the section as the schedule names it, e.g. "CMSC 140.01"
    course_name: str  # "CMSC 140"
    section: str  # "01"; "" when the name has no section part
    faculty: str | None
    resource_kind: str  # LAB for a lab meeting, otherwise ROOM
    resource_name: str | None  # None when no room or lab is assigned
    day: str  # MON..FRI
    start: str  # "HH:MM", 24-hour
    end: str  # "HH:MM", 24-hour
    duration: int  # minutes

    @property
    def resource(self) -> Resource | None:
        """The room or lab this meeting uses, or None when it has none."""
        if not self.resource_name:
            return None
        return Resource(self.resource_kind, self.resource_name)

    @property
    def location(self) -> str | None:
        """The room or lab name alone (None when there is none)."""
        return self.resource_name

    @property
    def is_lab(self) -> bool:
        return self.resource_kind == LAB

    @property
    def meeting_type(self) -> str:
        return "Lab" if self.is_lab else "Class"

    @property
    def day_name(self) -> str:
        return DAY_NAMES.get(self.day, self.day)

    @property
    def sort_key(self) -> tuple[int, str, str]:
        """Calendar order: weekday, then start time, then course."""
        return (_DAY_ORDER.get(self.day, len(_DAY_ORDER)), self.start, self.course)


def meeting_blocks(assignments: Iterable[Assignment]) -> list[MeetingBlock]:
    """Every meeting in a schedule, in calendar order.

    A lab meeting belongs to the section's lab and any other meeting to its room.
    A section with no meetings has no blocks; see ``unscheduled_sections``.
    """
    blocks = []
    for assignment in assignments:
        course_name, section = split_course(assignment.course)
        for meeting in assignment.meetings:
            blocks.append(
                MeetingBlock(
                    course=assignment.course,
                    course_name=course_name,
                    section=section,
                    faculty=assignment.faculty,
                    resource_kind=LAB if meeting.lab else ROOM,
                    resource_name=assignment.lab if meeting.lab else assignment.room,
                    day=meeting.day,
                    start=meeting.start,
                    end=meeting.end,
                    duration=meeting.duration,
                )
            )
    return sorted(blocks, key=lambda block: block.sort_key)


def unscheduled_sections(assignments: Iterable[Assignment]) -> list[str]:
    """Sections with no meeting times at all (for example an online section)."""
    return sorted(
        {assignment.course for assignment in assignments if not assignment.meetings}
    )


def resources_in(blocks: Iterable[MeetingBlock]) -> list[Resource]:
    """The distinct rooms and labs these meetings use, by name and then kind."""
    found = {block.resource for block in blocks}
    return sorted(
        (resource for resource in found if resource is not None),
        key=lambda resource: (resource.name, resource.kind),
    )


# --------------------------------------------------------------------------- #
#  Groupings (Strategy)
# --------------------------------------------------------------------------- #


class Grouping(ABC):
    """One way of reading a schedule: by course, by room or lab, or by faculty."""

    key: str  # stable identifier, also the viewer's ?view= value
    noun: str  # one item, in a sentence: "room or lab"
    plural: str  # all of them, in a sentence: "rooms and labs"

    @abstractmethod
    def owner(self, block: MeetingBlock) -> str | None:
        """The item this grouping files the block under (None when it has none)."""

    @abstractmethod
    def label(self, block: MeetingBlock) -> str:
        """The block's main text: its owner, or words saying it has none."""

    @abstractmethod
    def details(self, block: MeetingBlock) -> list[str]:
        """The two facts the label does not show, in display order. Always both:
        a missing room or faculty member is written out ("No room assigned")
        instead of silently left off."""

    @abstractmethod
    def options(self, assignments: Sequence[Assignment]) -> list[tuple[str, str]]:
        """(value, label) choices for narrowing a schedule to some of its items."""

    def matches(self, block: MeetingBlock, chosen: Sequence[str]) -> bool:
        """Whether a block belongs to one of the picked items."""
        return self.owner(block) in chosen

    def select(
        self, blocks: Iterable[MeetingBlock], chosen: Sequence[str] = ()
    ) -> list[MeetingBlock]:
        """The blocks that belong to the picked items; all of them when none is picked."""
        if not chosen:
            return list(blocks)
        return [block for block in blocks if self.matches(block, chosen)]


def _where(block: MeetingBlock) -> str:
    return block.location or NO_LOCATION_LABEL


def _who(block: MeetingBlock) -> str:
    return block.faculty or NO_FACULTY_LABEL


class CourseGrouping(Grouping):
    """By course section. Picking a course name picks all of its sections."""

    key = "courses"
    noun = "course"
    plural = "courses"

    def owner(self, block: MeetingBlock) -> str | None:
        return block.course

    def label(self, block: MeetingBlock) -> str:
        return block.course

    def details(self, block: MeetingBlock) -> list[str]:
        return [_where(block), _who(block)]

    def options(self, assignments: Sequence[Assignment]) -> list[tuple[str, str]]:
        """Every section, plus an "all sections" choice for a course that has
        several: "CMSC 140" next to "CMSC 140.01" and "CMSC 140.02"."""
        sections = {assignment.course for assignment in assignments}
        section_counts: dict[str, int] = {}
        for course in sections:
            course_name = split_course(course)[0]
            if course_name != course:  # the name has a section part
                section_counts[course_name] = section_counts.get(course_name, 0) + 1
        choices = {course: course for course in sections}
        for course_name, how_many in section_counts.items():
            if how_many > 1 and course_name not in choices:
                choices[course_name] = f"{course_name} (all sections)"
        return sorted(choices.items())

    def matches(self, block: MeetingBlock, chosen: Sequence[str]) -> bool:
        return any(course_matches(block.course, item) for item in chosen)


class RoomLabGrouping(Grouping):
    """By room or lab: a lab meeting under the lab, any other under the room."""

    key = "rooms"
    noun = "room or lab"
    plural = "rooms and labs"

    def owner(self, block: MeetingBlock) -> str | None:
        return block.location

    def label(self, block: MeetingBlock) -> str:
        return _where(block)

    def details(self, block: MeetingBlock) -> list[str]:
        return [block.course, _who(block)]

    def options(self, assignments: Sequence[Assignment]) -> list[tuple[str, str]]:
        """One choice per name. A room and a lab that share a name are one choice
        here, and picking it shows both; ``resources_in`` keeps them apart."""
        names = {
            resource.name for resource in resources_in(meeting_blocks(assignments))
        }
        return [(name, name) for name in sorted(names)]


class FacultyGrouping(Grouping):
    """By faculty member."""

    key = "faculty"
    noun = "faculty member"
    plural = "faculty"

    def owner(self, block: MeetingBlock) -> str | None:
        return block.faculty

    def label(self, block: MeetingBlock) -> str:
        return _who(block)

    def details(self, block: MeetingBlock) -> list[str]:
        return [block.course, _where(block)]

    def options(self, assignments: Sequence[Assignment]) -> list[tuple[str, str]]:
        """Everyone who teaches a section, including one with no meeting times."""
        names = {assignment.faculty for assignment in assignments if assignment.faculty}
        return [(name, name) for name in sorted(names)]


def course_matches(course: str, picked: str) -> bool:
    """A picked course matches that section, or every section when it names the whole course."""
    return course == picked or course.startswith(f"{picked}.")


# Every grouping by its key, in display order.
GROUPINGS: dict[str, Grouping] = {
    grouping.key: grouping
    for grouping in (CourseGrouping(), RoomLabGrouping(), FacultyGrouping())
}
DEFAULT_GROUPING = CourseGrouping.key


def grouping_for(key: str | None) -> Grouping:
    """The grouping with this key; anything unknown means by course."""
    return GROUPINGS.get(key or "", GROUPINGS[DEFAULT_GROUPING])
