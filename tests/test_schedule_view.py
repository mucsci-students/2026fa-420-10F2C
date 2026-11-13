"""
Unit tests for app/schedule_view.py: a schedule as typed meeting blocks, and the
groupings (Strategy pattern) the Schedule Viewer reads it by.

Pure model tests: no Django, no session. The calendar drawn from these blocks
is covered by test_calendar_characterization.py and the viewer page tests.
"""

import dataclasses
import inspect

import pytest

from app import schedule_io
from app.schedule_io import Assignment, MeetingTime
from app.schedule_view import (
    DEFAULT_GROUPING,
    GROUPINGS,
    LAB,
    NO_FACULTY_LABEL,
    NO_LOCATION_LABEL,
    ROOM,
    CourseGrouping,
    FacultyGrouping,
    Grouping,
    MeetingBlock,
    Resource,
    RoomLabGrouping,
    course_matches,
    grouping_for,
    meeting_blocks,
    resources_in,
    split_course,
    unscheduled_sections,
)
from gui.constants import VIEW_COURSES, VIEW_FACULTY, VIEW_OPTIONS, VIEW_ROOMS

COURSES = GROUPINGS[VIEW_COURSES]
ROOMS = GROUPINGS[VIEW_ROOMS]
FACULTY = GROUPINGS[VIEW_FACULTY]


def schedule():
    """Two sections of one course, a course with a room and a lab, a room that
    shares the lab's name, a section with nothing assigned, and an online one."""
    return [
        Assignment(
            "CMSC 140.01",
            "Hogg",
            "Roddy 136",
            None,
            (
                MeetingTime("WED", "09:00", "09:50", 50),
                MeetingTime("MON", "09:00", "09:50", 50),
            ),
        ),
        Assignment(
            "CMSC 140.02",
            "Killen",
            "Roddy 136",
            None,
            (MeetingTime("MON", "09:00", "09:50", 50),),
        ),
        Assignment(
            "CMSC 162.01",
            "Killen",
            "Roddy 140",
            "Roddy 147",
            (
                MeetingTime("TUE", "10:00", "10:50", 50),
                MeetingTime("THU", "13:00", "14:50", 110, lab=True),
            ),
        ),
        Assignment(
            "CMSC 201.01",
            "Zoppetti",
            "Roddy 147",
            None,
            (MeetingTime("FRI", "08:00", "08:50", 50),),
        ),
        Assignment(
            "CMSC 390.01", None, None, None, (MeetingTime("MON", "08:00", "08:50", 50),)
        ),
        Assignment("CMSC 999.01", "Online Person", None, None, ()),
    ]


def block(
    course: str = "CMSC 140.01",
    faculty: str | None = "Hogg",
    room: str | None = "Roddy 136",
    lab: str | None = None,
    is_lab: bool = False,
) -> MeetingBlock:
    [only] = meeting_blocks(
        [
            Assignment(
                course,
                faculty,
                room,
                lab,
                (MeetingTime("MON", "09:00", "09:50", 50, lab=is_lab),),
            )
        ]
    )
    return only


# ---------------------------------------------------------------------- #
#  Course and section
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "course, expected",
    [
        ("CMSC 140.01", ("CMSC 140", "01")),
        ("CMSC 140", ("CMSC 140", "")),
        ("MATH 161.H.02", ("MATH 161.H", "02")),
        ("", ("", "")),
    ],
)
def test_split_course_separates_the_section_at_the_last_dot(course, expected):
    assert split_course(course) == expected


def test_a_block_carries_the_course_and_section_separately():
    only = block("CMSC 140.01")
    assert (only.course, only.course_name, only.section) == (
        "CMSC 140.01",
        "CMSC 140",
        "01",
    )
    no_section = block("Seminar")
    assert (no_section.course_name, no_section.section) == ("Seminar", "")


# ---------------------------------------------------------------------- #
#  Meeting blocks
# ---------------------------------------------------------------------- #
def test_blocks_are_in_calendar_order_day_then_start_then_course():
    assert [(b.day, b.start, b.course) for b in meeting_blocks(schedule())] == [
        ("MON", "08:00", "CMSC 390.01"),
        ("MON", "09:00", "CMSC 140.01"),
        ("MON", "09:00", "CMSC 140.02"),
        ("TUE", "10:00", "CMSC 162.01"),
        ("WED", "09:00", "CMSC 140.01"),
        ("THU", "13:00", "CMSC 162.01"),
        ("FRI", "08:00", "CMSC 201.01"),
    ]


def test_a_lab_meeting_uses_the_lab_and_any_other_meeting_the_room():
    by_day = {b.day: b for b in meeting_blocks(schedule()) if b.course == "CMSC 162.01"}
    lecture, lab = by_day["TUE"], by_day["THU"]
    assert lecture.resource == Resource(ROOM, "Roddy 140")
    assert (lecture.is_lab, lecture.meeting_type) == (False, "Class")
    assert lab.resource == Resource(LAB, "Roddy 147")
    assert (lab.is_lab, lab.meeting_type, lab.location) == (True, "Lab", "Roddy 147")


def test_a_lab_meeting_with_no_lab_assigned_has_no_resource_even_if_there_is_a_room():
    only = block(room="Roddy 136", lab=None, is_lab=True)
    assert only.resource is None and only.location is None
    assert only.resource_kind == LAB


def test_a_block_keeps_the_meeting_time_and_names_its_day():
    only = block()
    assert (only.day, only.day_name, only.start, only.end, only.duration) == (
        "MON",
        "Monday",
        "09:00",
        "09:50",
        50,
    )


def test_a_block_is_an_immutable_value():
    assert dataclasses.is_dataclass(MeetingBlock)
    # only a frozen dataclass is hashable, and equal blocks are one set member
    assert {block(), block()} == {block()}


def test_a_section_with_no_meetings_has_no_blocks_but_is_reported():
    assert "CMSC 999.01" not in {b.course for b in meeting_blocks(schedule())}
    assert unscheduled_sections(schedule()) == ["CMSC 999.01"]


def test_no_assignments_means_no_blocks_and_nothing_unscheduled():
    assert meeting_blocks([]) == []
    assert unscheduled_sections([]) == []


def test_building_blocks_does_not_change_the_schedule():
    before = schedule()
    after = schedule()
    meeting_blocks(after)
    for grouping in GROUPINGS.values():
        grouping.options(after)
        grouping.select(meeting_blocks(after), ["Hogg"])
    assert after == before


def test_an_imported_schedule_gives_the_same_blocks_as_the_same_records_built_directly():
    exported = schedule_io.schedules_to_json([schedule()])
    [imported] = schedule_io.parse_schedule_file(exported.encode("utf-8"))
    assert meeting_blocks(imported) == meeting_blocks(schedule())
    assert unscheduled_sections(imported) == unscheduled_sections(schedule())


# ---------------------------------------------------------------------- #
#  Rooms and labs keyed by kind and name
# ---------------------------------------------------------------------- #
def test_a_room_and_a_lab_with_the_same_name_are_two_resources():
    assert resources_in(meeting_blocks(schedule())) == [
        Resource(ROOM, "Roddy 136"),
        Resource(ROOM, "Roddy 140"),
        Resource(LAB, "Roddy 147"),
        Resource(ROOM, "Roddy 147"),
    ]


def test_meetings_with_no_room_or_lab_are_not_resources():
    assert resources_in([block(room=None), block(room="")]) == []


# ---------------------------------------------------------------------- #
#  Groupings (Strategy)
# ---------------------------------------------------------------------- #
def test_there_is_one_grouping_per_viewer_view_in_the_same_order():
    assert list(GROUPINGS) == list(VIEW_OPTIONS)
    assert [type(g) for g in GROUPINGS.values()] == [
        CourseGrouping,
        RoomLabGrouping,
        FacultyGrouping,
    ]
    assert all(isinstance(g, Grouping) for g in GROUPINGS.values())
    assert all(key == grouping.key for key, grouping in GROUPINGS.items())


def test_an_unknown_grouping_key_means_by_course():
    assert DEFAULT_GROUPING == VIEW_COURSES
    assert grouping_for("rooms") is ROOMS
    for unknown in ("nonsense", "", None):
        assert grouping_for(unknown) is COURSES


def test_the_abstract_grouping_cannot_be_used_directly():
    assert inspect.isabstract(Grouping)
    assert not any(inspect.isabstract(type(g)) for g in GROUPINGS.values())


def test_each_grouping_names_its_items_for_the_page():
    assert [(g.noun, g.plural) for g in GROUPINGS.values()] == [
        ("course", "courses"),
        ("room or lab", "rooms and labs"),
        ("faculty member", "faculty"),
    ]


def test_each_grouping_files_a_block_under_its_own_item():
    only = block("CMSC 140.01", "Hogg", "Roddy 136")
    assert (COURSES.owner(only), ROOMS.owner(only), FACULTY.owner(only)) == (
        "CMSC 140.01",
        "Roddy 136",
        "Hogg",
    )
    assert (COURSES.label(only), ROOMS.label(only), FACULTY.label(only)) == (
        "CMSC 140.01",
        "Roddy 136",
        "Hogg",
    )


def test_each_grouping_shows_the_other_two_facts():
    only = block("CMSC 140.01", "Hogg", "Roddy 136")
    assert COURSES.details(only) == ["Roddy 136", "Hogg"]
    assert ROOMS.details(only) == ["CMSC 140.01", "Hogg"]
    assert FACULTY.details(only) == ["CMSC 140.01", "Roddy 136"]


def test_a_missing_room_or_faculty_member_is_written_out_never_invented():
    bare = block("CMSC 390.01", None, None)
    assert ROOMS.owner(bare) is None and FACULTY.owner(bare) is None
    assert ROOMS.label(bare) == NO_LOCATION_LABEL
    assert FACULTY.label(bare) == NO_FACULTY_LABEL
    assert COURSES.details(bare) == [NO_LOCATION_LABEL, NO_FACULTY_LABEL]
    assert ROOMS.details(bare) == ["CMSC 390.01", NO_FACULTY_LABEL]
    assert FACULTY.details(bare) == ["CMSC 390.01", NO_LOCATION_LABEL]


def test_course_options_list_every_section_and_all_sections_of_a_repeated_course():
    assert COURSES.options(schedule()) == [
        ("CMSC 140", "CMSC 140 (all sections)"),
        ("CMSC 140.01", "CMSC 140.01"),
        ("CMSC 140.02", "CMSC 140.02"),
        ("CMSC 162.01", "CMSC 162.01"),
        ("CMSC 201.01", "CMSC 201.01"),
        ("CMSC 390.01", "CMSC 390.01"),
        ("CMSC 999.01", "CMSC 999.01"),
    ]


def test_room_options_list_each_room_and_lab_name_once():
    assert ROOMS.options(schedule()) == [
        ("Roddy 136", "Roddy 136"),
        ("Roddy 140", "Roddy 140"),
        ("Roddy 147", "Roddy 147"),
    ]


def test_faculty_options_include_someone_whose_section_has_no_meetings():
    assert FACULTY.options(schedule()) == [
        ("Hogg", "Hogg"),
        ("Killen", "Killen"),
        ("Online Person", "Online Person"),
        ("Zoppetti", "Zoppetti"),
    ]


def test_options_of_an_empty_schedule_are_empty():
    assert [g.options([]) for g in GROUPINGS.values()] == [[], [], []]


def test_selecting_nothing_keeps_every_block():
    blocks = meeting_blocks(schedule())
    for grouping in GROUPINGS.values():
        assert grouping.select(blocks) == blocks
        assert grouping.select(blocks, []) == blocks


def test_selecting_a_course_name_keeps_all_of_its_sections():
    blocks = meeting_blocks(schedule())
    assert {b.course for b in COURSES.select(blocks, ["CMSC 140"])} == {
        "CMSC 140.01",
        "CMSC 140.02",
    }
    assert {b.course for b in COURSES.select(blocks, ["CMSC 140.02"])} == {
        "CMSC 140.02"
    }


def test_a_course_name_only_matches_whole_names():
    assert course_matches("CMSC 140.01", "CMSC 140")
    assert course_matches("CMSC 140.01", "CMSC 140.01")
    assert not course_matches("CMSC 1401.01", "CMSC 140")
    assert not course_matches("CMSC 140", "CMSC 140.01")


def test_selecting_a_shared_name_keeps_the_room_meetings_and_the_lab_meetings():
    blocks = meeting_blocks(schedule())
    assert [(b.course, b.resource) for b in ROOMS.select(blocks, ["Roddy 147"])] == [
        ("CMSC 162.01", Resource(LAB, "Roddy 147")),
        ("CMSC 201.01", Resource(ROOM, "Roddy 147")),
    ]


def test_selecting_faculty_keeps_only_their_meetings():
    blocks = meeting_blocks(schedule())
    assert {b.course for b in FACULTY.select(blocks, ["Killen", "Zoppetti"])} == {
        "CMSC 140.02",
        "CMSC 162.01",
        "CMSC 201.01",
    }


def test_a_block_with_no_owner_is_never_selected():
    blocks = meeting_blocks(schedule())
    assert "CMSC 390.01" not in {b.course for b in ROOMS.select(blocks, ["Roddy 136"])}
    assert "CMSC 390.01" not in {b.course for b in FACULTY.select(blocks, ["Hogg"])}


def test_selecting_something_that_is_not_in_the_schedule_keeps_nothing():
    blocks = meeting_blocks(schedule())
    assert [g.select(blocks, ["Nobody"]) for g in GROUPINGS.values()] == [[], [], []]


def test_selection_keeps_calendar_order():
    blocks = meeting_blocks(schedule())
    picked = FACULTY.select(blocks, ["Killen", "Hogg"])
    assert picked == sorted(picked, key=lambda b: b.sort_key)


def test_blocks_are_plain_comparable_records():
    assert block() == block()
    assert isinstance(block(), MeetingBlock)
    assert block() != block(faculty="Killen")
