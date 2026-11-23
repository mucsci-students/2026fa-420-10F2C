"""
Unit tests for app/schedule_export.py: one schedule arranged into sections for
a printed export, by room or lab and by faculty member (Sprint 4 Sections 5.1,
5.2, 5.4 and 7).

Pure model tests: no Django, no session, no PDF library.
"""

import copy
import dataclasses

import pytest

from app import schedule_io
from app.schedule_export import (
    BY_FACULTY,
    BY_ROOM_OR_LAB,
    EMPTY_EXPORT_LABEL,
    EXPORT_ORIENTATIONS,
    ExportError,
    ExportRow,
    ExportSection,
    ScheduleExport,
    UnknownGroupError,
    UnknownOrientationError,
    available_groups,
    build_export,
    export_grouping,
)
from app.schedule_io import Assignment, MeetingTime
from app.schedule_view import (
    FACULTY,
    GROUPINGS,
    LAB,
    NO_FACULTY_LABEL,
    NO_LOCATION_LABEL,
    ROOM,
    FacultyGrouping,
    GroupKey,
    Resource,
    RoomLabGrouping,
)


def schedule() -> list[Assignment]:
    """Two sections of one course, a course with a room and a lab, a room that
    shares the lab's name, a lab meeting with no lab, a section with no room
    and no faculty member, and an online section with no meetings at all."""
    return [
        Assignment(
            "CMSC 140.01",
            "Hogg",
            "Roddy 136",
            None,
            (
                MeetingTime("WED", "09:00", "09:50", 50),
                MeetingTime("MON", "09:00", "09:50", 50),
                MeetingTime("FRI", "09:00", "09:50", 50),
            ),
        ),
        Assignment(
            "CMSC 140.02",
            "Killen",
            "Roddy 136",
            None,
            (
                MeetingTime("TUE", "08:00", "09:15", 75),
                MeetingTime("THU", "08:00", "09:15", 75),
            ),
        ),
        Assignment(
            "CMSC 162.01",
            "Killen",
            "Roddy 140",
            "Roddy 147",
            (
                MeetingTime("TUE", "10:00", "10:50", 50),
                MeetingTime("THU", "10:00", "10:50", 50),
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
            "CMSC 330.01",
            "Zoppetti",
            "Roddy 140",
            None,
            (
                MeetingTime("MON", "11:00", "11:50", 50),
                MeetingTime("WED", "14:00", "15:50", 110, lab=True),
            ),
        ),
        Assignment(
            "CMSC 390.01", None, None, None, (MeetingTime("MON", "08:00", "08:50", 50),)
        ),
        Assignment("CMSC 999.01", "Online Person", None, None, ()),
    ]


def titles(export: ScheduleExport) -> list[tuple[str, str]]:
    return [(section.kind, section.title) for section in export.sections]


def section(export: ScheduleExport, kind: str, name: str) -> ExportSection:
    [found] = [s for s in export.sections if s.key == GroupKey(kind, name)]
    return found


def unassigned(export: ScheduleExport) -> ExportSection:
    [found] = [s for s in export.sections if s.is_unassigned]
    return found


def lines(found: ExportSection) -> list[tuple]:
    return [(row.course, row.days, row.start, row.end) for row in found.rows]


# ---------------------------------------------------------------------- #
#  Orientations
# ---------------------------------------------------------------------- #
def test_exports_are_by_room_or_lab_and_by_faculty():
    assert EXPORT_ORIENTATIONS == (BY_ROOM_OR_LAB, BY_FACULTY)
    assert isinstance(export_grouping(BY_ROOM_OR_LAB), RoomLabGrouping)
    assert isinstance(export_grouping(BY_FACULTY), FacultyGrouping)
    # the same strategy objects the Schedule Viewer uses
    assert export_grouping(BY_FACULTY) is GROUPINGS[BY_FACULTY]


@pytest.mark.parametrize("orientation", ["courses", "nonsense", "", None, 3])
def test_an_unknown_orientation_is_a_clear_error(orientation):
    with pytest.raises(UnknownOrientationError) as raised:
        build_export(schedule(), orientation)
    assert isinstance(raised.value, ExportError)
    assert raised.value.orientation == orientation
    assert "Unknown export orientation" in str(raised.value)
    assert "'rooms' or 'faculty'" in str(raised.value)


# ---------------------------------------------------------------------- #
#  By room or lab (Section 5.1)
# ---------------------------------------------------------------------- #
def test_room_export_has_a_section_per_room_and_per_lab_then_the_unassigned():
    export = build_export(schedule(), BY_ROOM_OR_LAB)
    assert titles(export) == [
        (ROOM, "Roddy 136"),
        (ROOM, "Roddy 140"),
        (LAB, "Roddy 147"),
        (ROOM, "Roddy 147"),
        ("", NO_LOCATION_LABEL),
    ]
    assert (export.orientation, export.selected) == (BY_ROOM_OR_LAB, None)


def test_room_export_includes_both_rooms_and_labs():
    kinds = {s.kind for s in build_export(schedule(), BY_ROOM_OR_LAB).sections}
    assert {ROOM, LAB} <= kinds


def test_a_room_and_a_lab_with_the_same_name_are_separate_sections():
    export = build_export(schedule(), BY_ROOM_OR_LAB)
    assert lines(section(export, LAB, "Roddy 147")) == [
        ("CMSC 162.01", ("THU",), "13:00", "14:50")
    ]
    assert lines(section(export, ROOM, "Roddy 147")) == [
        ("CMSC 201.01", ("FRI",), "08:00", "08:50")
    ]


def test_a_room_section_identifies_course_section_faculty_days_and_times():
    export = build_export(schedule(), BY_ROOM_OR_LAB)
    first = section(export, ROOM, "Roddy 136").rows[0]
    assert first == ExportRow(
        course="CMSC 140.01",
        course_name="CMSC 140",
        section="01",
        faculty="Hogg",
        resource=Resource(ROOM, "Roddy 136"),
        days=("MON", "WED", "FRI"),
        start="09:00",
        end="09:50",
        duration=50,
    )
    assert first.day_names == ("Monday", "Wednesday", "Friday")
    assert (first.faculty_label, first.location_label, first.location_kind) == (
        "Hogg",
        "Roddy 136",
        ROOM,
    )
    assert first.has_meeting_times


def test_a_lab_meeting_is_under_the_lab_and_the_lecture_under_the_room():
    export = build_export(schedule(), BY_ROOM_OR_LAB)
    assert "CMSC 162.01" in section(export, LAB, "Roddy 147").courses
    assert lines(section(export, ROOM, "Roddy 140")) == [
        ("CMSC 330.01", ("MON",), "11:00", "11:50"),
        ("CMSC 162.01", ("TUE", "THU"), "10:00", "10:50"),
    ]


def test_meetings_with_no_room_or_lab_are_listed_last_and_labelled_not_invented():
    last = build_export(schedule(), BY_ROOM_OR_LAB).sections[-1]
    assert last.is_unassigned and last.key is None and last.kind == ""
    assert last.title == NO_LOCATION_LABEL
    assert lines(last) == [
        ("CMSC 390.01", ("MON",), "08:00", "08:50"),
        # a lab meeting whose section has a room but no lab
        ("CMSC 330.01", ("WED",), "14:00", "15:50"),
        # online: never meets
        ("CMSC 999.01", (), "", ""),
    ]
    assert all(row.resource is None for row in last.rows)
    assert {row.location_label for row in last.rows} == {NO_LOCATION_LABEL}
    assert {row.location_kind for row in last.rows} == {""}


def test_a_room_row_with_no_faculty_member_says_so():
    export = build_export(schedule(), BY_ROOM_OR_LAB)
    [row] = [r for r in unassigned(export).rows if r.course == "CMSC 390.01"]
    assert row.faculty is None
    assert row.faculty_label == NO_FACULTY_LABEL


# ---------------------------------------------------------------------- #
#  By faculty (Section 5.2)
# ---------------------------------------------------------------------- #
def test_faculty_export_has_a_section_per_person_in_name_order_then_the_unassigned():
    export = build_export(schedule(), BY_FACULTY)
    assert titles(export) == [
        (FACULTY, "Hogg"),
        (FACULTY, "Killen"),
        (FACULTY, "Online Person"),
        (FACULTY, "Zoppetti"),
        ("", NO_FACULTY_LABEL),
    ]


def test_a_faculty_section_identifies_course_section_room_or_lab_days_and_times():
    export = build_export(schedule(), BY_FACULTY)
    rows = section(export, FACULTY, "Killen").rows
    assert [
        (r.course_name, r.section, r.location_kind, r.location_label, r.days, r.start)
        for r in rows
    ] == [
        ("CMSC 140", "02", ROOM, "Roddy 136", ("TUE", "THU"), "08:00"),
        ("CMSC 162", "01", ROOM, "Roddy 140", ("TUE", "THU"), "10:00"),
        ("CMSC 162", "01", LAB, "Roddy 147", ("THU",), "13:00"),
    ]
    assert {r.faculty for r in rows} == {"Killen"}


def test_a_faculty_meeting_with_no_room_or_lab_is_labelled_not_invented():
    export = build_export(schedule(), BY_FACULTY)
    [lab_meeting] = [
        r for r in section(export, FACULTY, "Zoppetti").rows if r.start == "14:00"
    ]
    assert lab_meeting.course == "CMSC 330.01"
    assert lab_meeting.resource is None
    assert lab_meeting.location_label == NO_LOCATION_LABEL
    assert lab_meeting.location_kind == ""


def test_sections_with_no_faculty_member_are_listed_last_and_labelled():
    last = build_export(schedule(), BY_FACULTY).sections[-1]
    assert last.is_unassigned and last.title == NO_FACULTY_LABEL
    assert last.courses == ["CMSC 390.01"]
    assert last.rows[0].faculty_label == NO_FACULTY_LABEL


def test_a_section_with_no_meeting_times_is_still_listed_for_its_faculty_member():
    export = build_export(schedule(), BY_FACULTY)
    [row] = section(export, FACULTY, "Online Person").rows
    assert (row.course, row.days, row.start, row.end, row.duration) == (
        "CMSC 999.01",
        (),
        "",
        "",
        0,
    )
    assert not row.has_meeting_times
    assert row.day_names == ()
    assert row.location_label == NO_LOCATION_LABEL


def test_a_section_with_no_meeting_times_keeps_its_room_or_else_its_lab():
    never_meets = [
        Assignment("A.01", "Hogg", "Roddy 136", "Roddy 147", ()),
        Assignment("B.01", "Hogg", None, "Roddy 147", ()),
    ]
    [hogg] = build_export(never_meets, BY_FACULTY).sections
    assert [row.resource for row in hogg.rows] == [
        Resource(ROOM, "Roddy 136"),
        Resource(LAB, "Roddy 147"),
    ]
    assert titles(build_export(never_meets, BY_ROOM_OR_LAB)) == [
        (ROOM, "Roddy 136"),
        (LAB, "Roddy 147"),
    ]


# ---------------------------------------------------------------------- #
#  Rows and order
# ---------------------------------------------------------------------- #
def test_the_same_place_and_time_on_several_days_is_one_row_in_weekday_order():
    export = build_export(schedule(), BY_FACULTY)
    assert lines(section(export, FACULTY, "Hogg")) == [
        ("CMSC 140.01", ("MON", "WED", "FRI"), "09:00", "09:50")
    ]


def test_different_times_on_different_days_are_different_rows():
    two_times = [
        Assignment(
            "CMSC 140.01",
            "Hogg",
            "Roddy 136",
            None,
            (
                MeetingTime("MON", "09:00", "09:50", 50),
                MeetingTime("WED", "10:00", "10:50", 50),
            ),
        )
    ]
    [hogg] = build_export(two_times, BY_FACULTY).sections
    assert lines(hogg) == [
        ("CMSC 140.01", ("MON",), "09:00", "09:50"),
        ("CMSC 140.01", ("WED",), "10:00", "10:50"),
    ]


def test_rows_are_ordered_by_first_day_then_start_then_course():
    busy = [
        Assignment(
            "C.01", "Hogg", "R", None, (MeetingTime("TUE", "08:00", "08:50", 50),)
        ),
        Assignment(
            "B.01", "Hogg", "R", None, (MeetingTime("MON", "10:00", "10:50", 50),)
        ),
        Assignment(
            "A.02", "Hogg", "R", None, (MeetingTime("MON", "09:00", "09:50", 50),)
        ),
        Assignment(
            "A.01", "Hogg", "R", None, (MeetingTime("MON", "09:00", "09:50", 50),)
        ),
        Assignment("Z.01", "Hogg", "R", None, ()),
    ]
    for orientation in EXPORT_ORIENTATIONS:
        [only] = build_export(busy, orientation).sections
        assert only.courses == ["A.01", "A.02", "B.01", "C.01", "Z.01"]


def test_the_order_does_not_depend_on_the_order_of_the_schedule_records():
    forwards = build_export(schedule(), BY_ROOM_OR_LAB)
    backwards = build_export(list(reversed(schedule())), BY_ROOM_OR_LAB)
    assert forwards == backwards


def test_a_course_with_no_section_part_has_an_empty_section():
    plain = [
        Assignment(
            "Seminar", "Hogg", "R", None, (MeetingTime("MON", "09:00", "09:50", 50),)
        )
    ]
    [row] = build_export(plain, BY_FACULTY).sections[0].rows
    assert (row.course, row.course_name, row.section) == ("Seminar", "Seminar", "")


@pytest.mark.parametrize("orientation", EXPORT_ORIENTATIONS)
def test_every_course_section_appears_in_an_export_of_all_groups(orientation):
    export = build_export(schedule(), orientation)
    listed = {course for found in export.sections for course in found.courses}
    assert listed == {assignment.course for assignment in schedule()}


@pytest.mark.parametrize("orientation", EXPORT_ORIENTATIONS)
def test_every_meeting_appears_exactly_once(orientation):
    export = build_export(schedule(), orientation)
    exported = sorted(
        (row.course, day, row.start, row.end)
        for found in export.sections
        for row in found.rows
        for day in row.days
    )
    expected = sorted(
        (assignment.course, meeting.day, meeting.start, meeting.end)
        for assignment in schedule()
        for meeting in assignment.meetings
    )
    assert exported == expected


# ---------------------------------------------------------------------- #
#  Exporting one group
# ---------------------------------------------------------------------- #
def test_available_groups_are_the_named_sections_in_export_order():
    assert available_groups(schedule(), BY_ROOM_OR_LAB) == [
        GroupKey(ROOM, "Roddy 136"),
        GroupKey(ROOM, "Roddy 140"),
        GroupKey(LAB, "Roddy 147"),
        GroupKey(ROOM, "Roddy 147"),
    ]
    assert available_groups(schedule(), BY_FACULTY) == [
        GroupKey(FACULTY, "Hogg"),
        GroupKey(FACULTY, "Killen"),
        GroupKey(FACULTY, "Online Person"),
        GroupKey(FACULTY, "Zoppetti"),
    ]


def test_exporting_one_lab_gives_only_that_labs_section():
    export = build_export(schedule(), BY_ROOM_OR_LAB, GroupKey(LAB, "Roddy 147"))
    assert titles(export) == [(LAB, "Roddy 147")]
    assert export.selected == GroupKey(LAB, "Roddy 147")
    assert export.sections[0].courses == ["CMSC 162.01"]


def test_exporting_one_faculty_member_gives_only_their_section():
    export = build_export(schedule(), BY_FACULTY, GroupKey(FACULTY, "Killen"))
    assert titles(export) == [(FACULTY, "Killen")]
    assert export.sections[0].courses == ["CMSC 140.02", "CMSC 162.01"]


def test_a_selection_can_be_a_plain_kind_and_name_pair():
    export = build_export(schedule(), BY_ROOM_OR_LAB, (ROOM, "Roddy 147"))
    assert export.selected == GroupKey(ROOM, "Roddy 147")
    assert isinstance(export.selected, GroupKey)


@pytest.mark.parametrize("orientation", EXPORT_ORIENTATIONS)
def test_one_groups_section_is_the_same_as_in_the_export_of_all_groups(orientation):
    everything = build_export(schedule(), orientation)
    for key in available_groups(schedule(), orientation):
        [alone] = build_export(schedule(), orientation, key).sections
        assert alone in everything.sections


@pytest.mark.parametrize(
    "orientation, selected",
    [
        (BY_ROOM_OR_LAB, GroupKey(ROOM, "Nowhere")),
        (BY_ROOM_OR_LAB, GroupKey(LAB, "Roddy 136")),  # a room, not a lab
        (BY_ROOM_OR_LAB, GroupKey(FACULTY, "Hogg")),  # wrong orientation
        (BY_FACULTY, GroupKey(FACULTY, "Nobody")),
        (BY_FACULTY, GroupKey(ROOM, "Roddy 136")),
    ],
)
def test_selecting_a_group_that_is_not_in_the_schedule_is_a_clear_error(
    orientation, selected
):
    with pytest.raises(UnknownGroupError) as raised:
        build_export(schedule(), orientation, selected)
    assert isinstance(raised.value, ExportError)
    assert raised.value.selected == selected
    assert repr(selected.name) in str(raised.value)
    assert "Nothing was exported" in str(raised.value)


def test_scope_says_which_groups_an_export_covers():
    assert build_export(schedule(), BY_ROOM_OR_LAB).scope == "All rooms and labs"
    assert build_export(schedule(), BY_FACULTY).scope == "All faculty"
    one_lab = build_export(schedule(), BY_ROOM_OR_LAB, (LAB, "Roddy 147"))
    assert one_lab.scope == "Roddy 147 (lab)"
    one_person = build_export(schedule(), BY_FACULTY, (FACULTY, "Hogg"))
    assert one_person.scope == "Hogg (faculty)"


# ---------------------------------------------------------------------- #
#  Empty exports (Section 5.4)
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize("orientation", EXPORT_ORIENTATIONS)
def test_an_empty_schedule_gives_a_labelled_empty_export_not_an_error(orientation):
    export = build_export([], orientation)
    assert export.sections == ()
    assert export.is_empty
    assert export.empty_label == EMPTY_EXPORT_LABEL
    assert available_groups([], orientation) == []


def test_an_export_with_rows_is_not_empty_and_has_no_empty_label():
    export = build_export(schedule(), BY_FACULTY)
    assert not export.is_empty
    assert export.empty_label == ""


def test_a_schedule_of_only_online_sections_is_not_empty():
    online = [Assignment("CMSC 999.01", "Online Person", None, None, ())]
    by_room = build_export(online, BY_ROOM_OR_LAB)
    assert titles(by_room) == [("", NO_LOCATION_LABEL)]
    assert not by_room.is_empty
    assert available_groups(online, BY_ROOM_OR_LAB) == []


def test_selecting_anything_from_an_empty_schedule_is_an_unknown_group():
    with pytest.raises(UnknownGroupError):
        build_export([], BY_FACULTY, GroupKey(FACULTY, "Hogg"))


# ---------------------------------------------------------------------- #
#  Safeguards
# ---------------------------------------------------------------------- #
def test_building_an_export_does_not_change_the_schedule():
    records = schedule()
    before = copy.deepcopy(records)
    for orientation in EXPORT_ORIENTATIONS:
        build_export(records, orientation)
        for key in available_groups(records, orientation):
            build_export(records, orientation, key)
    with pytest.raises(ExportError):
        build_export(records, "nonsense")
    with pytest.raises(ExportError):
        build_export(records, BY_FACULTY, GroupKey(FACULTY, "Nobody"))
    assert records == before


@pytest.mark.parametrize("orientation", EXPORT_ORIENTATIONS)
def test_an_imported_schedule_exports_the_same_as_the_records_built_directly(
    orientation,
):
    saved = schedule_io.schedules_to_json([schedule()])
    [imported] = schedule_io.parse_schedule_file(saved.encode("utf-8"))
    assert build_export(imported, orientation) == build_export(schedule(), orientation)


def test_an_empty_string_room_or_faculty_counts_as_none():
    blank = [
        Assignment(
            "CMSC 140.01", "", "", None, (MeetingTime("MON", "09:00", "09:50", 50),)
        )
    ]
    [by_room] = build_export(blank, BY_ROOM_OR_LAB).sections
    [by_faculty] = build_export(blank, BY_FACULTY).sections
    assert by_room.is_unassigned and by_faculty.is_unassigned
    assert by_room.rows[0].faculty is None and by_room.rows[0].resource is None


def test_export_records_are_immutable_values():
    export = build_export(schedule(), BY_FACULTY)
    for record in (export, export.sections[0], export.sections[0].rows[0]):
        assert dataclasses.is_dataclass(record)
        assert hash(record) == hash(copy.deepcopy(record))
