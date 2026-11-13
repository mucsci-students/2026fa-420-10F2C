"""
Characterization tests for the Schedule Viewer's weekly calendar.

`calendar_characterization.json` holds what the calendar data looked like
BEFORE gui/views.py was split up: it was captured from `_schedule_grid` and
`_resource_options` at develop b03a58c, for the schedule below in every view,
with and without picked items, in both clock formats. These tests rebuild the
same data from the code as it is now (app/schedule_view.py and
gui/calendar_layout.py) and require it to be identical, so the split cannot
have changed what the calendar shows.

The schedule is deliberately awkward: three overlapping Monday meetings (one of
them 15 minutes long), a room and a lab that share a name, a lab meeting with
no lab, a section with no room, a section with no faculty member, and an online
section with no meetings at all.

Only fields the old code built but the page never showed (`sort_key`,
`day_name`, and `detail`, a one-line form of `details`) are left out of the
snapshot.
"""

import dataclasses
import json
import pathlib

import pytest

from app.schedule_io import Assignment, MeetingTime
from app.schedule_view import GROUPINGS
from gui.calendar_layout import schedule_grid

SNAPSHOT = json.loads(
    pathlib.Path(__file__)
    .with_name("calendar_characterization.json")
    .read_text(encoding="utf-8")
)

BLOCK_FIELDS = (
    "day",
    "start",
    "end",
    "start_text",
    "end_text",
    "range_text",
    "title_range",
    "course",
    "faculty",
    "meeting_type",
    "location",
    "label",
    "duration",
    "details",
    "color",
    "top",
    "height",
    "compact",
    "lane",
    "cluster",
    "lane_count",
    "left",
    "width",
)


def representative_schedule():
    return [
        Assignment(
            "CMSC 140.01",
            "Hogg",
            "Roddy 136",
            None,
            (
                MeetingTime("MON", "09:00", "09:50", 50),
                MeetingTime("WED", "09:00", "09:50", 50),
                MeetingTime("FRI", "09:00", "09:50", 50),
            ),
        ),
        Assignment(
            "CMSC 140.02",
            "Killen",
            "Roddy 136",
            None,
            (
                MeetingTime("MON", "09:30", "10:45", 75),
                MeetingTime("WED", "09:30", "10:45", 75),
            ),
        ),
        Assignment(
            "CMSC 162.01",
            "Zoppetti",
            "Roddy 140",
            "Roddy 147",
            (
                MeetingTime("TUE", "10:00", "10:50", 50),
                MeetingTime("THU", "10:00", "10:50", 50),
                MeetingTime("THU", "13:00", "14:50", 110, lab=True),
            ),
        ),
        # A room with the same name as CMSC 162's lab, and no faculty member.
        Assignment(
            "CMSC 201.01",
            None,
            "Roddy 147",
            None,
            (MeetingTime("MON", "09:15", "09:30", 15),),
        ),
        # A lab meeting, but no lab assigned.
        Assignment(
            "CMSC 330.01",
            "Killen",
            "Roddy 136",
            None,
            (
                MeetingTime("TUE", "08:00", "08:50", 50),
                MeetingTime("TUE", "14:00", "15:50", 110, lab=True),
            ),
        ),
        # No room.
        Assignment(
            "CMSC 390.01",
            "Hogg",
            None,
            None,
            (MeetingTime("FRI", "16:10", "17:25", 75),),
        ),
        # Online: no meetings at all.
        Assignment("CMSC 999.01", "Online Person", None, None, ()),
    ]


def as_snapshot(grid):
    """A ScheduleGrid as the plain data the snapshot stores."""
    return {
        "days": [
            {
                "day": day.day,
                "name": day.name,
                "meetings": [
                    {field: getattr(meeting, field) for field in BLOCK_FIELDS}
                    for meeting in day.meetings
                ],
            }
            for day in grid.days
        ],
        "hours": [dataclasses.asdict(hour) for hour in grid.hours],
        "legend": [dataclasses.asdict(item) for item in grid.legend],
        "meeting_count": grid.meeting_count,
        "without_meetings": grid.without_meetings,
        "hour_pct": grid.hour_pct,
        "height_rem": grid.height_rem,
        "columns": grid.columns,
        "day_lanes": grid.day_lanes,
    }


@pytest.mark.parametrize("case", SNAPSHOT["grids"], ids=lambda case: case["name"])
def test_calendar_matches_the_snapshot_taken_before_the_split(case):
    grid = schedule_grid(
        representative_schedule(), case["view"], case["resources"], case["time_format"]
    )
    assert as_snapshot(grid) == case["grid"]


@pytest.mark.parametrize("view", sorted(SNAPSHOT["options"]))
def test_picker_options_match_the_snapshot_taken_before_the_split(view):
    options = GROUPINGS[view].options(representative_schedule())
    assert [list(option) for option in options] == SNAPSHOT["options"][view]


def test_snapshot_covers_every_view_and_both_clocks():
    cases = SNAPSHOT["grids"]
    assert {case["view"] for case in cases} == set(GROUPINGS)
    assert {case["time_format"] for case in cases} == {"24h", "12h"}
    assert any(case["resources"] for case in cases)
    assert any(case["grid"]["meeting_count"] == 0 for case in cases)
