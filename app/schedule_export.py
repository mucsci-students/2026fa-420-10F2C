"""Export data: one schedule arranged into sections for a printed export.

Model layer (Section 20). No Django imports and no PDF library: this module
decides WHAT an export says -- which sections there are, which rows each one
holds, and in what order -- and a renderer decides how that looks on paper.

An export has an orientation, which is one of the schedule groupings from
app/schedule_view.py (the Strategy pattern):

* by room or lab: one section per room and one per lab. A room and a lab that
  share a name are two sections.
* by faculty: one section per faculty member.

``build_export`` asks the grouping where each meeting belongs and never
branches on which grouping it has. It works from schedule records alone
(``Assignment``), not the configuration, so an imported schedule exports
exactly like a generated one. Nothing here changes the schedule.

Three rules keep an export complete:

* A meeting with no room or lab, or with no faculty member, is not dropped and
  is never given an invented one. It goes in a last section titled
  "No room assigned" or "No faculty assigned".
* A section with no meeting times at all (for example an online one) still
  gets a row, marked as having no meeting times.
* So every course section in the schedule appears at least once in an export
  of all groups, in either orientation.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.schedule_io import DAY_NAMES, DAYS, Assignment
from app.schedule_view import (
    LAB,
    NO_FACULTY_LABEL,
    NO_LOCATION_LABEL,
    ROOM,
    FacultyGrouping,
    Grouping,
    GroupKey,
    Resource,
    RoomLabGrouping,
    grouping_for,
    meeting_blocks,
    split_course,
)

# The orientations an export can have: grouping keys from app/schedule_view.py.
BY_ROOM_OR_LAB = RoomLabGrouping.key
BY_FACULTY = FacultyGrouping.key
EXPORT_ORIENTATIONS = (BY_ROOM_OR_LAB, BY_FACULTY)

# What a row says in place of days and times when its section never meets.
NO_MEETING_TIMES_LABEL = "No meeting times"
# What an export says when the schedule has no course sections at all.
EMPTY_EXPORT_LABEL = "This schedule has no course sections to export."

_DAY_ORDER = {day: index for index, day in enumerate(DAYS)}


class ExportError(ValueError):
    """An export that cannot be built as asked. The message is fit to show a user."""


class UnknownOrientationError(ExportError):
    def __init__(self, orientation: object) -> None:
        self.orientation = orientation
        choices = " or ".join(repr(choice) for choice in EXPORT_ORIENTATIONS)
        super().__init__(
            f"Unknown export orientation {orientation!r}. Choose {choices}."
        )


class UnknownGroupError(ExportError):
    def __init__(self, noun: str, selected: GroupKey) -> None:
        self.selected = selected
        super().__init__(
            f"This schedule has no {noun} named {selected.name!r}"
            f" ({selected.kind}). Nothing was exported."
        )


@dataclass(frozen=True)
class ExportRow:
    """One line of a section: a course section's meetings at one place and time.

    Meetings of the same section that share a room or lab, a faculty member and
    a time are one row with several days (Monday and Wednesday, 09:00-09:50),
    the way a printed schedule is read. A lab meeting is its own row because it
    is somewhere else.
    """

    course: str  # the section as the schedule names it: "CMSC 140.01"
    course_name: str  # "CMSC 140"
    section: str  # "01"; "" when the name has no section part
    faculty: str | None  # None when no faculty member is assigned
    resource: Resource | None  # the room or lab with its kind; None when there is none
    days: tuple[str, ...]  # MON..FRI in weekday order; () when it never meets
    start: str  # "HH:MM", 24-hour; "" when it never meets
    end: str  # "HH:MM", 24-hour; "" when it never meets
    duration: int  # minutes per meeting; 0 when it never meets

    @property
    def has_meeting_times(self) -> bool:
        return bool(self.days)

    @property
    def faculty_label(self) -> str:
        """The faculty member, or "No faculty assigned"."""
        return self.faculty or NO_FACULTY_LABEL

    @property
    def location_label(self) -> str:
        """The room or lab name, or "No room assigned" -- never an invented one."""
        return self.resource.name if self.resource else NO_LOCATION_LABEL

    @property
    def location_kind(self) -> str:
        """ROOM or LAB; "" when there is no room or lab."""
        return self.resource.kind if self.resource else ""

    @property
    def day_names(self) -> tuple[str, ...]:
        """The days spelled out: ("Monday", "Wednesday")."""
        return tuple(DAY_NAMES.get(day, day) for day in self.days)

    @property
    def sort_key(self) -> tuple[int, str, str, str]:
        """Order within a section: first day, start, end, then course. A row
        with no meeting times sorts last."""
        first_day = _DAY_ORDER.get(self.days[0], len(DAYS)) if self.days else len(DAYS)
        return (first_day, self.start, self.end, self.course)


@dataclass(frozen=True)
class ExportSection:
    """Everything one room, lab or faculty member has in the exported schedule."""

    key: GroupKey | None  # None for the section of meetings that have no such item
    title: str  # the room, lab or faculty name, or "No room/faculty assigned"
    rows: tuple[ExportRow, ...]

    @property
    def kind(self) -> str:
        """ROOM, LAB or FACULTY; "" for the unassigned section."""
        return self.key.kind if self.key else ""

    @property
    def is_unassigned(self) -> bool:
        return self.key is None

    @property
    def courses(self) -> list[str]:
        """The course sections listed here, each once, in row order."""
        return list(dict.fromkeys(row.course for row in self.rows))


@dataclass(frozen=True)
class ScheduleExport:
    """One schedule arranged for export: what the printed pages will contain."""

    orientation: str  # BY_ROOM_OR_LAB or BY_FACULTY
    selected: GroupKey | None  # the one group exported; None means all groups
    sections: tuple[ExportSection, ...]

    @property
    def is_empty(self) -> bool:
        """True when there is not a single row to print."""
        return not any(section.rows for section in self.sections)

    @property
    def empty_label(self) -> str:
        """What to print in place of the sections when there are none."""
        return EMPTY_EXPORT_LABEL if self.is_empty else ""

    @property
    def grouping(self) -> Grouping:
        return grouping_for(self.orientation)

    @property
    def scope(self) -> str:
        """Which groups this export covers, in words: "All rooms and labs", or
        the one selected with its kind ("Roddy 147 (lab)", "Hogg (faculty)")."""
        if self.selected is None:
            return f"All {self.grouping.plural}"
        return f"{self.selected.name} ({self.selected.kind})"


def export_grouping(orientation: object) -> Grouping:
    """The grouping behind an export orientation.

    Raises UnknownOrientationError for anything else, including the by-course
    grouping, which the viewer has but exports do not.
    """
    if orientation not in EXPORT_ORIENTATIONS:
        raise UnknownOrientationError(orientation)
    return grouping_for(str(orientation))


def available_groups(
    assignments: Sequence[Assignment], orientation: str
) -> list[GroupKey]:
    """The rooms and labs, or the faculty members, this schedule can be exported
    for one at a time, in the order an export of all groups lists them."""
    sections = build_export(assignments, orientation).sections
    return [section.key for section in sections if section.key is not None]


def build_export(
    assignments: Sequence[Assignment],
    orientation: str,
    selected: GroupKey | tuple[str, str] | None = None,
) -> ScheduleExport:
    """Arrange one schedule into export sections.

    ``orientation`` is BY_ROOM_OR_LAB or BY_FACULTY. ``selected`` is the one
    room, lab or faculty member to export, as a (kind, name) pair from
    ``available_groups``; None exports every group, followed by the section of
    meetings that have no room or lab (or no faculty member) when there are any.

    A schedule with no course sections gives an export with no sections, whose
    ``is_empty`` is true and whose ``empty_label`` says so.

    Raises UnknownOrientationError for an orientation that does not exist and
    UnknownGroupError when ``selected`` is not in this schedule. The schedule
    is only read, never changed.
    """
    grouping = export_grouping(orientation)
    grouped = _rows_by_group(assignments, grouping)

    if selected is not None:
        selected = GroupKey(*selected)
        if selected not in grouped:
            raise UnknownGroupError(grouping.noun, selected)
        keys: list[GroupKey | None] = [selected]
    else:
        named = sorted(
            (key for key in grouped if key is not None),
            key=lambda key: (key.name, key.kind),
        )
        keys = [*named, None] if None in grouped else [*named]

    sections = tuple(
        ExportSection(
            key=key,
            title=key.name if key else grouping.unassigned_label,
            rows=tuple(sorted(grouped[key], key=lambda row: row.sort_key)),
        )
        for key in keys
    )
    return ScheduleExport(
        orientation=grouping.key, selected=selected, sections=sections
    )


# One meeting's facts before its days are merged into a row.
_Entry = tuple[str, str | None, Resource | None, str, str, int]


def _rows_by_group(
    assignments: Sequence[Assignment], grouping: Grouping
) -> dict[GroupKey | None, list[ExportRow]]:
    """Every row of the schedule under the group it belongs to (None = unassigned)."""
    days_by_entry: dict[GroupKey | None, dict[_Entry, list[str]]] = {}

    def group_entries(
        course: str, faculty: str | None, resource: Resource | None
    ) -> dict[_Entry, list[str]]:
        key = grouping.group_key(course, faculty, resource)
        return days_by_entry.setdefault(key, {})

    for block in meeting_blocks(assignments):
        faculty = block.faculty or None
        entry = (
            block.course,
            faculty,
            block.resource,
            block.start,
            block.end,
            block.duration,
        )
        entries = group_entries(block.course, faculty, block.resource)
        entries.setdefault(entry, []).append(block.day)

    for assignment in assignments:
        if not assignment.meetings:
            faculty = assignment.faculty or None
            resource = _assigned_resource(assignment)
            entry = (assignment.course, faculty, resource, "", "", 0)
            group_entries(assignment.course, faculty, resource).setdefault(entry, [])

    return {
        key: [_row(entry, days) for entry, days in entries.items()]
        for key, entries in days_by_entry.items()
    }


def _row(entry: _Entry, days: Iterable[str]) -> ExportRow:
    course, faculty, resource, start, end, duration = entry
    course_name, section = split_course(course)
    return ExportRow(
        course=course,
        course_name=course_name,
        section=section,
        faculty=faculty,
        resource=resource,
        days=tuple(sorted(set(days), key=lambda day: _DAY_ORDER.get(day, len(DAYS)))),
        start=start,
        end=end,
        duration=duration,
    )


def _assigned_resource(assignment: Assignment) -> Resource | None:
    """Where a section with no meeting times is listed: its room if it has one,
    otherwise its lab, otherwise nowhere."""
    if assignment.room:
        return Resource(ROOM, assignment.room)
    if assignment.lab:
        return Resource(LAB, assignment.lab)
    return None
