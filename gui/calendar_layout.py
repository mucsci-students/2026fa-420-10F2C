"""Weekly calendar layout for the Schedule Viewer.

View layer (Section 20), presentation only: where each meeting block sits on
the week grid, how overlapping blocks share a day column, which color each
label gets, and how times are written. No Django imports and no request
handling -- gui/views.py calls ``schedule_grid()`` and hands the result to
gui/templates/gui/schedule_viewer.html.

What a schedule contains and how it is grouped (by course, room or lab, or
faculty) comes from the model, app/schedule_view.py. This module only draws it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.schedule_io import Assignment
from app.schedule_view import (
    Grouping,
    MeetingBlock,
    grouping_for,
    meeting_blocks,
    unscheduled_sections,
)
from gui.constants import (
    DAY_NAMES,
    TIME_FORMAT_12,
    TIME_FORMAT_24,
    VIEW_COURSES,
)

MINUTES_PER_HOUR = 60
TIME_AXIS_REM = 3.5  # width of the hour labels on the left
LANE_PADDING_FR = 0.5  # extra share per day, so a one-lane day is not squeezed
PALETTE_SIZE = 12  # matches .schedule-color-0..11 in style.css
HOUR_HEIGHT_REM = (
    5.5  # every hour of the calendar is this tall, so a 50-minute class fits 4 lines
)
COMPACT_BELOW_REM = (
    3.0  # only blocks shorter than this (about 30 minutes) drop the detail lines
)
DEFAULT_AXIS_HOURS = (8, 17)  # the hours shown when there is nothing to place


# ---------------------------------------------------------------------- #
#  What the template receives
# ---------------------------------------------------------------------- #
@dataclass(frozen=True)
class PositionedBlock:
    """One meeting block as drawn: its text, color, and place in its day column.

    Positions are CSS percentages already formatted as text.
    """

    block: MeetingBlock
    label: str  # the grouping's own item: course, room/lab, or faculty member
    details: list[str]  # the other two facts, always both
    detail: str  # the same on one line, leaving out whatever is missing
    start_text: str
    end_text: str
    range_text: str
    title_range: str  # range_text with a plain hyphen, for the tooltip
    color: int  # index into .schedule-color-N
    top: str
    height: str
    compact: bool  # too short for the detail lines
    lane: int  # zero-based position among the blocks it overlaps
    lane_count: int  # how many lanes its overlap group uses
    cluster: int  # which overlap group of the day it is in
    left: str
    width: str

    @property
    def course(self) -> str:
        return self.block.course

    @property
    def faculty(self) -> str | None:
        return self.block.faculty

    @property
    def location(self) -> str | None:
        return self.block.location

    @property
    def meeting_type(self) -> str:
        return self.block.meeting_type

    @property
    def day(self) -> str:
        return self.block.day

    @property
    def start(self) -> str:
        return self.block.start

    @property
    def end(self) -> str:
        return self.block.end

    @property
    def duration(self) -> int:
        return self.block.duration


@dataclass(frozen=True)
class DayColumn:
    day: str  # MON..FRI
    name: str  # Monday..Friday
    meetings: list[PositionedBlock]


@dataclass(frozen=True)
class HourMark:
    label: str
    top: str


@dataclass(frozen=True)
class LegendItem:
    label: str
    color: int


@dataclass(frozen=True)
class ScheduleGrid:
    """Everything the weekly calendar needs to render one schedule."""

    days: list[DayColumn]
    hours: list[HourMark]
    legend: list[LegendItem]
    meeting_count: int  # how many blocks are drawn (0 shows the empty state)
    without_meetings: list[str]  # sections with no meeting times at all
    hour_pct: str
    height_rem: str
    columns: str  # the grid-template-columns value
    day_lanes: list[int]


@dataclass(frozen=True)
class Lane:
    """Where one block sits among the blocks it overlaps."""

    lane: int
    lane_count: int
    cluster: int


# ---------------------------------------------------------------------- #
#  Times as text
# ---------------------------------------------------------------------- #
def clock_minutes(value: str) -> int:
    """Convert a validated 24-hour clock string into minutes after midnight."""
    hour, minute = value.split(":", 1)
    return int(hour) * MINUTES_PER_HOUR + int(minute)


def clock_text(value: str, time_format: str = TIME_FORMAT_24) -> str:
    """A clock time as shown on screen: 13:05 stays 13:05 in 24-hour, becomes 1:05 PM in 12-hour."""
    if time_format != TIME_FORMAT_12:
        return value
    hour, minute = divmod(clock_minutes(value), MINUTES_PER_HOUR)
    return f"{hour % 12 or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"


def range_text(start: str, end: str, time_format: str = TIME_FORMAT_24) -> str:
    """A start-end range: 09:00-09:50, or in 12-hour 9:00-9:50 AM (AM/PM written once when both share it)."""
    first, last = clock_text(start, time_format), clock_text(end, time_format)
    if time_format == TIME_FORMAT_12 and first[-2:] == last[-2:]:
        first = first[:-3]
    return f"{first}–{last}"


def hour_label(hour: int, time_format: str = TIME_FORMAT_24) -> str:
    """Label of one hour mark on the time axis."""
    if time_format == TIME_FORMAT_12:
        return f"{hour % 12 or 12} {'AM' if hour < 12 else 'PM'}"
    return f"{hour:02d}:00"


# ---------------------------------------------------------------------- #
#  The grid
# ---------------------------------------------------------------------- #
def as_resources(resources: str | Iterable[str] | None) -> list[str]:
    """One value (as a plain string) or several, as a list; an empty string means none."""
    if isinstance(resources, str):
        return [resources] if resources else []
    return list(resources or [])


def schedule_grid(
    assignments: Iterable[Assignment],
    view_mode: str = VIEW_COURSES,
    resources: str | Iterable[str] | None = "",
    time_format: str = TIME_FORMAT_24,
) -> ScheduleGrid:
    """Lay one schedule out as a weekly calendar.

    `view_mode` picks the grouping (courses, rooms or faculty) and `resources`
    (one value or several) keeps only those items' meetings: the picked courses
    (or all sections of a course), rooms/labs, or faculty.
    `time_format` decides how the on-screen times are written; positions and
    ordering always use the 24-hour times.
    """
    assignments = list(assignments)
    grouping = grouping_for(view_mode)
    everything = meeting_blocks(assignments)
    shown = grouping.select(everything, as_resources(resources))
    return layout_week(
        shown, everything, grouping, time_format, unscheduled_sections(assignments)
    )


def layout_week(
    shown: Sequence[MeetingBlock],
    everything: Sequence[MeetingBlock],
    grouping: Grouping,
    time_format: str = TIME_FORMAT_24,
    without_meetings: Sequence[str] = (),
) -> ScheduleGrid:
    """Place the `shown` blocks on the week grid.

    The time axis and the colors come from `everything` (the whole schedule), so
    neither shifts when the picker narrows the calendar to some rooms or people.
    """
    axis_start, axis_end = axis_bounds(
        [
            minutes
            for block in everything
            for minutes in (clock_minutes(block.start), clock_minutes(block.end))
        ]
    )
    span = axis_end - axis_start

    # One color per distinct label, so overlapping blocks always differ.
    color_of = {
        label: index % PALETTE_SIZE
        for index, label in enumerate(
            sorted({grouping.label(block) for block in everything})
        )
    }
    shown_labels = {grouping.label(block) for block in shown}

    blocks_by_day: dict[str, list[MeetingBlock]] = {day: [] for day in DAY_NAMES}
    for block in shown:
        blocks_by_day[block.day].append(block)

    days, day_lanes = [], []
    for day, name in DAY_NAMES.items():
        ordered = sorted(
            blocks_by_day[day], key=lambda block: (block.start, block.end, block.course)
        )
        lanes = assign_lanes(ordered)
        meetings = [
            _position(block, lane, grouping, color_of, axis_start, span, time_format)
            for block, lane in zip(ordered, lanes, strict=True)
        ]
        day_lanes.append(max((lane.lane_count for lane in lanes), default=1))
        days.append(DayColumn(day=day, name=name, meetings=meetings))

    # The days share whatever width the window gives the calendar, so there is no
    # sideways scrolling. A busy day (more overlapping blocks side by side) gets a
    # wider column, so lanes stay about the same width.
    columns = f"{TIME_AXIS_REM:g}rem " + " ".join(
        f"minmax(0, {lanes + LANE_PADDING_FR:g}fr)" for lanes in day_lanes
    )

    return ScheduleGrid(
        days=days,
        hours=[
            HourMark(
                label=hour_label(minutes // MINUTES_PER_HOUR, time_format),
                top=f"{(minutes - axis_start) / span * 100:.2f}",
            )
            for minutes in range(axis_start, axis_end + 1, MINUTES_PER_HOUR)
        ],
        legend=[
            LegendItem(label=label, color=color)
            for label, color in color_of.items()
            if label in shown_labels
        ],
        meeting_count=len(shown),
        without_meetings=list(without_meetings),
        hour_pct=f"{MINUTES_PER_HOUR / span * 100:.3f}",
        height_rem=f"{span / MINUTES_PER_HOUR * HOUR_HEIGHT_REM:g}",
        columns=columns,
        day_lanes=day_lanes,
    )


def _position(
    block: MeetingBlock,
    lane: Lane,
    grouping: Grouping,
    color_of: dict[str, int],
    axis_start: int,
    span: int,
    time_format: str,
) -> PositionedBlock:
    start, end = clock_minutes(block.start), clock_minutes(block.end)
    label = grouping.label(block)
    times = range_text(block.start, block.end, time_format)
    return PositionedBlock(
        block=block,
        label=label,
        details=grouping.details(block),
        detail=grouping.detail(block),
        start_text=clock_text(block.start, time_format),
        end_text=clock_text(block.end, time_format),
        range_text=times,
        title_range=times.replace("–", "-"),
        color=color_of[label],
        top=f"{(start - axis_start) / span * 100:.2f}",
        height=f"{(end - start) / span * 100:.2f}",
        compact=(end - start) / MINUTES_PER_HOUR * HOUR_HEIGHT_REM < COMPACT_BELOW_REM,
        lane=lane.lane,
        lane_count=lane.lane_count,
        cluster=lane.cluster,
        left=f"{lane.lane / lane.lane_count * 100:.2f}",
        width=f"{100 / lane.lane_count:.2f}",
    )


def assign_lanes(blocks: Sequence[MeetingBlock]) -> list[Lane]:
    """Give overlapping meetings separate horizontal lanes in a day column.

    `blocks` are one day's meetings ordered by start, end and course; the result
    has one Lane per block, in the same order. A connected overlap group shares
    its widest lane count, so adjacent blocks never jump between widths while one
    course remains in progress.
    """
    lanes: list[Lane] = []
    group: list[MeetingBlock] = []
    latest_end: int | None = None
    cluster = 0

    for block in blocks:
        start, end = clock_minutes(block.start), clock_minutes(block.end)
        if group and latest_end is not None and start >= latest_end:
            lanes.extend(_overlap_group_lanes(group, cluster))
            cluster += 1
            group = []
            latest_end = None
        group.append(block)
        latest_end = end if latest_end is None else max(latest_end, end)

    if group:
        lanes.extend(_overlap_group_lanes(group, cluster))
    return lanes


def _overlap_group_lanes(blocks: Sequence[MeetingBlock], cluster: int) -> list[Lane]:
    """Lane positions for one connected overlap group: each block takes the
    first lane that is free again by the time it starts."""
    lane_end_times: list[int] = []
    positions: list[int] = []
    for block in blocks:
        start, end = clock_minutes(block.start), clock_minutes(block.end)
        lane = next(
            (
                index
                for index, lane_end in enumerate(lane_end_times)
                if lane_end <= start
            ),
            len(lane_end_times),
        )
        if lane == len(lane_end_times):
            lane_end_times.append(end)
        else:
            lane_end_times[lane] = end
        positions.append(lane)

    lane_count = len(lane_end_times)
    return [
        Lane(lane=lane, lane_count=lane_count, cluster=cluster) for lane in positions
    ]


def axis_bounds(minutes: Sequence[int]) -> tuple[int, int]:
    """Return whole-hour bounds that contain every meeting in the grid."""
    if not minutes:
        first, last = DEFAULT_AXIS_HOURS
        return first * MINUTES_PER_HOUR, last * MINUTES_PER_HOUR
    earliest = min(minutes) // MINUTES_PER_HOUR * MINUTES_PER_HOUR
    latest = -(-max(minutes) // MINUTES_PER_HOUR) * MINUTES_PER_HOUR
    return earliest, max(latest, earliest + MINUTES_PER_HOUR)
