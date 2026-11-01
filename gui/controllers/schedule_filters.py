"""
Which rooms, labs or faculty members the Schedule Viewer shows (Sections 16.1-16.2).

In the Rooms & labs view and the Faculty view a checkbox popup lists every room, lab or faculty
member that appears in the loaded schedules. Ticking some of them limits the calendar to their
meetings; ticking none shows everything. The choice travels in the URL as repeated
?resource=<name> values, so it survives Previous/Next and can be bookmarked, and nothing is
stored in the session.

Plain functions over the neutral schedule records in app/schedule_io.py: no Django, no session,
so the view only asks "what are the choices", "what was picked" and "does this meeting match".
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.schedule_io import Assignment, MeetingTime
from gui.constants import (
    NO_FACULTY_LABEL,
    NO_LOCATION_LABEL,
    VIEW_FACULTY,
    VIEW_ROOMS,
)

# The ?resource= value for "meetings with no room/lab" or "sections with no faculty member".
# Room and faculty names come from the configuration, which never uses this spelling.
NONE_VALUE = "__none__"

# What the picker calls the things it lists, per view.
RESOURCE_NOUNS = {VIEW_ROOMS: "rooms & labs", VIEW_FACULTY: "faculty"}


@dataclass
class ResourceOption:
    value: str  # what goes in ?resource=
    label: str  # what the checkbox says
    meetings: int = 0  # how many meetings it has in the schedule on screen
    checked: bool = False


@dataclass
class ResourceGroup:
    title: str
    options: list[ResourceOption] = field(default_factory=list)


def filters_view(view_mode: str) -> bool:
    """True for the views that have a checkbox popup (not the Courses view)."""
    return view_mode in RESOURCE_NOUNS


def meeting_resource(
    view_mode: str, assignment: Assignment, meeting: MeetingTime
) -> str:
    """The ?resource= value one meeting belongs to in this view ("" in the Courses view).

    A lab meeting belongs to the section's lab and every other meeting to its room, the same
    rule the calendar uses to label blocks in the Rooms & labs view.
    """
    if view_mode == VIEW_ROOMS:
        location = assignment.lab if meeting.lab else assignment.room
        return location or NONE_VALUE
    if view_mode == VIEW_FACULTY:
        return assignment.faculty or NONE_VALUE
    return ""


def resource_groups(
    schedules: Iterable[Sequence[Assignment]],
    view_mode: str,
    current: Sequence[Assignment] = (),
    selected: Iterable[str] = (),
) -> list[ResourceGroup]:
    """The popup's checkbox groups for this view, built from every loaded schedule.

    Using all schedules (not just the one on screen) keeps the same list while paging, so a
    picked room never silently drops out because one schedule happens not to use it.
    `meetings` counts only the schedule on screen, so the popup shows which choices have
    anything to show right now. Empty groups are left out; the Courses view has none.
    """
    if not filters_view(view_mode):
        return []

    rooms: set[str] = set()
    labs: set[str] = set()
    people: set[str] = set()
    unassigned = False
    for schedule in schedules:
        for assignment in schedule:
            for meeting in assignment.meetings:
                value = meeting_resource(view_mode, assignment, meeting)
                if value == NONE_VALUE:
                    unassigned = True
                elif view_mode == VIEW_FACULTY:
                    people.add(value)
                elif meeting.lab:
                    labs.add(value)
                else:
                    rooms.add(value)

    counts: dict[str, int] = {}
    for assignment in current:
        for meeting in assignment.meetings:
            value = meeting_resource(view_mode, assignment, meeting)
            counts[value] = counts.get(value, 0) + 1

    picked = {value.strip() for value in selected}

    def group(title: str, names: Iterable[str]) -> ResourceGroup:
        return ResourceGroup(
            title,
            [
                ResourceOption(name, name, counts.get(name, 0), name in picked)
                for name in sorted(names, key=str.casefold)
            ],
        )

    if view_mode == VIEW_FACULTY:
        groups = [group("Faculty", people)]
        none_label = NO_FACULTY_LABEL
    else:
        # A name used both as a room and a lab is listed once, under Rooms.
        groups = [group("Rooms", rooms), group("Labs", labs - rooms)]
        none_label = NO_LOCATION_LABEL
    if unassigned:
        groups.append(
            ResourceGroup(
                "Not assigned",
                [
                    ResourceOption(
                        NONE_VALUE,
                        none_label,
                        counts.get(NONE_VALUE, 0),
                        NONE_VALUE in picked,
                    )
                ],
            )
        )
    return [g for g in groups if g.options]


def all_options(groups: Iterable[ResourceGroup]) -> list[ResourceOption]:
    return [option for group in groups for option in group.options]


def selected_resources(
    requested: Iterable[str], groups: Iterable[ResourceGroup]
) -> list[str]:
    """The requested ?resource= values that are real choices, once each, in list order.

    Anything unknown (a typo, a room from schedules that were since cleared) is ignored rather
    than producing an empty calendar with no explanation.
    """
    wanted = {value.strip() for value in requested}
    return [option.value for option in all_options(groups) if option.value in wanted]


def label_for(value: str, groups: Iterable[ResourceGroup]) -> str:
    for option in all_options(groups):
        if option.value == value:
            return option.label
    return value


def shows(row_resource: str, selected: Sequence[str]) -> bool:
    """Whether a calendar block stays visible: everything when nothing is picked."""
    return not selected or row_resource in selected
