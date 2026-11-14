"""Faculty-oriented export data: one schedule read faculty member by faculty member.

Model layer (Section 20). No Django imports and no PDF library: this module
decides WHAT a faculty-grouped export says, and a renderer decides how it looks
on paper. Keeping the two apart lets the content be tested directly (Sprint 4
Section 7, "Faculty-oriented export data") and lets any renderer reuse it.

Sprint 4 Section 5.2 asks each faculty section to identify the faculty member,
the course and section, the room or lab when there is one, the meeting days,
and the start and end times. A meeting with no room or lab is labelled
"No room assigned" rather than given an invented one.

Who teaches a meeting, and what a missing room or faculty member is called, come
from ``FacultyGrouping`` in app/schedule_view.py (the Schedule Viewer's Strategy),
so the printed schedule and the on-screen one always agree.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.schedule_io import DAYS, Assignment
from app.schedule_view import (
    LAB,
    NO_FACULTY_LABEL,
    NO_LOCATION_LABEL,
    MeetingBlock,
    grouping_for,
    meeting_blocks,
    split_course,
)

FACULTY = grouping_for("faculty")

# What a faculty section says when that person teaches nothing in the schedule.
NO_MEETINGS_LABEL = "No meetings scheduled"
# What a section with no meeting times at all (for example an online one) shows
# in place of its days and times.
NO_MEETING_TIMES_LABEL = "No meeting times"

DAY_ABBREVIATIONS = {
    "MON": "Mon",
    "TUE": "Tue",
    "WED": "Wed",
    "THU": "Thu",
    "FRI": "Fri",
}
_DAY_ORDER = {day: index for index, day in enumerate(DAYS)}


def _day_position(day: str) -> int:
    """Where a weekday falls in the week; anything unknown sorts last."""
    return _DAY_ORDER.get(day, len(DAYS))


@dataclass(frozen=True)
class FacultyMeetingRow:
    """One line of a faculty member's schedule.

    Meetings of the same section that share a room or lab and a time are one
    row with several days ("Mon, Wed  09:00-10:50"), the way a printed schedule
    is usually read. A lab meeting is its own row because it is somewhere else.
    """

    course: str  # the section as the schedule names it: "CMSC 140.01"
    course_name: str  # "CMSC 140"
    section: str  # "01"; "" when the name has no section part
    location_kind: str  # "Room", "Lab", or "" when there is no room or lab
    location: str  # the room or lab name, or NO_LOCATION_LABEL
    days: tuple[str, ...]  # MON..FRI in weekday order; () when it never meets
    start: str  # "HH:MM", 24-hour; "" when it never meets
    end: str  # "HH:MM", 24-hour; "" when it never meets

    @property
    def has_location(self) -> bool:
        return bool(self.location_kind)

    @property
    def location_text(self) -> str:
        """The room or lab with its kind ("Lab: Linux"), or "No room assigned"."""
        if not self.has_location:
            return self.location
        return f"{self.location_kind}: {self.location}"

    @property
    def days_text(self) -> str:
        """ "Mon, Wed", or "No meeting times" for a section that never meets."""
        if not self.days:
            return NO_MEETING_TIMES_LABEL
        return ", ".join(DAY_ABBREVIATIONS.get(day, day) for day in self.days)

    @property
    def time_text(self) -> str:
        """ "09:00-10:50" (24-hour, always the same form), or "" when it never meets."""
        if not self.start:
            return ""
        return f"{self.start}-{self.end}"

    @property
    def sort_key(self) -> tuple[int, str, str, str]:
        first_day = _day_position(self.days[0]) if self.days else len(DAYS)
        return (first_day, self.start, self.course, self.location)


@dataclass(frozen=True)
class FacultySchedule:
    """Everything one faculty member teaches in the exported schedule."""

    faculty: str  # the faculty member, or NO_FACULTY_LABEL for unassigned sections
    rows: tuple[FacultyMeetingRow, ...]

    @property
    def is_empty(self) -> bool:
        return not self.rows

    @property
    def empty_text(self) -> str:
        """What to print in place of the rows when there are none."""
        return NO_MEETINGS_LABEL if self.is_empty else ""

    @property
    def sections(self) -> list[str]:
        """The sections this person teaches, each once, in row order."""
        return list(dict.fromkeys(row.course for row in self.rows))


@dataclass(frozen=True)
class FacultyExport:
    """A faculty-grouped export of one schedule: what the PDF will contain."""

    schedule_title: str  # identifies the exported schedule, e.g. "Schedule 2 of 5"
    grouping_title: str  # identifies the grouping, e.g. "By faculty: all faculty"
    groups: tuple[FacultySchedule, ...]

    @property
    def is_empty(self) -> bool:
        """True when nothing in the export has a single meeting to show."""
        return all(group.is_empty for group in self.groups)

    @property
    def faculty_names(self) -> list[str]:
        return [group.faculty for group in self.groups]


def _location(block: MeetingBlock) -> tuple[str, str]:
    """(kind, name) of a meeting's room or lab, or ("", "No room assigned")."""
    if block.resource_name is None:
        return "", NO_LOCATION_LABEL
    return ("Lab" if block.resource_kind == LAB else "Room"), block.resource_name


def _rows_for(blocks: Iterable[MeetingBlock]) -> list[FacultyMeetingRow]:
    """Merge one person's meeting blocks into rows (same section, place and time)."""
    merged: dict[tuple[str, str, str, str, str], list[MeetingBlock]] = {}
    for block in blocks:
        kind, name = _location(block)
        key = (block.course, kind, name, block.start, block.end)
        merged.setdefault(key, []).append(block)
    rows = []
    for (course, kind, name, start, end), same in merged.items():
        days = sorted({block.day for block in same}, key=_day_position)
        rows.append(
            FacultyMeetingRow(
                course=course,
                course_name=same[0].course_name,
                section=same[0].section,
                location_kind=kind,
                location=name,
                days=tuple(days),
                start=start,
                end=end,
            )
        )
    return rows


def _never_meets_row(assignment: Assignment) -> FacultyMeetingRow:
    """A row for a section with no meeting times (for example an online one)."""
    course_name, section = split_course(assignment.course)
    if assignment.room:
        kind, name = "Room", assignment.room
    elif assignment.lab:
        kind, name = "Lab", assignment.lab
    else:
        kind, name = "", NO_LOCATION_LABEL
    return FacultyMeetingRow(
        course=assignment.course,
        course_name=course_name,
        section=section,
        location_kind=kind,
        location=name,
        days=(),
        start="",
        end="",
    )


def faculty_export(
    assignments: Sequence[Assignment],
    schedule_title: str,
    chosen: Sequence[str] = (),
) -> FacultyExport:
    """Group one schedule by faculty member for export.

    ``chosen`` names the faculty members to export; empty means everyone who
    teaches in the schedule, plus a "No faculty assigned" group for sections
    with no faculty member (listed last). A chosen name that teaches nothing
    still gets a group, marked empty, so the export says so instead of
    silently leaving the person out (Sprint 4 Section 5.4).

    The schedule is only read, never changed.
    """
    owned: dict[str, list[MeetingBlock]] = {}
    for block in meeting_blocks(assignments):
        owned.setdefault(FACULTY.label(block), []).append(block)
    by_faculty = {name: _rows_for(blocks) for name, blocks in owned.items()}
    for assignment in assignments:
        if not assignment.meetings:
            name = assignment.faculty or NO_FACULTY_LABEL
            by_faculty.setdefault(name, []).append(_never_meets_row(assignment))

    if chosen:
        names = list(dict.fromkeys(chosen))
        grouping_title = f"By faculty: {', '.join(names)}"
    else:
        names = sorted(name for name in by_faculty if name != NO_FACULTY_LABEL)
        if NO_FACULTY_LABEL in by_faculty:
            names.append(NO_FACULTY_LABEL)
        grouping_title = "By faculty: all faculty"

    groups = tuple(
        FacultySchedule(
            faculty=name,
            rows=tuple(sorted(by_faculty.get(name, []), key=lambda row: row.sort_key)),
        )
        for name in names
    )
    return FacultyExport(
        schedule_title=schedule_title,
        grouping_title=grouping_title,
        groups=groups,
    )
