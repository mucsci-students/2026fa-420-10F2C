"""
Unit tests for app/faculty_export.py: the faculty-oriented export data
(Sprint 4 Sections 5.2, 5.4 and 7, issue #167).

Pure model tests: no Django, no session, no PDF library. They check WHAT a
faculty-grouped export contains; how it is drawn on paper is the renderer's job.
"""

import dataclasses

import pytest

from app.faculty_export import (
    NO_MEETING_TIMES_LABEL,
    NO_MEETINGS_LABEL,
    FacultyExport,
    FacultyMeetingRow,
    faculty_export,
)
from app.schedule_io import Assignment, MeetingTime
from app.schedule_view import NO_FACULTY_LABEL, NO_LOCATION_LABEL


def schedule():
    """Hardy teaches two sections, Hogg has a room and a lab, Xie teaches an
    online section with no meeting times, and one section has no faculty."""
    return [
        Assignment(
            "CMSC 140.01",
            "Hardy",
            "Roddy 147",
            None,
            (
                MeetingTime("WED", "09:00", "10:50", 110),
                MeetingTime("MON", "09:00", "10:50", 110),
            ),
        ),
        Assignment(
            "CMSC 140.02",
            "Hardy",
            "Roddy 136",
            None,
            (
                MeetingTime("MON", "13:00", "14:50", 110),
                MeetingTime("WED", "13:00", "14:50", 110),
            ),
        ),
        Assignment(
            "CMSC 380.01",
            "Hogg",
            "Roddy 140",
            "Linux",
            (
                MeetingTime("TUE", "10:00", "11:50", 110),
                MeetingTime("THU", "10:00", "11:50", 110, lab=True),
            ),
        ),
        Assignment("CMSC 476.01", "Xie", None, None, ()),
        Assignment(
            "CMSC 152.01",
            None,
            "Roddy 140",
            None,
            (MeetingTime("FRI", "08:00", "09:50", 110),),
        ),
    ]


def group(export: FacultyExport, name: str):
    return next(g for g in export.groups if g.faculty == name)


# --------------------------------------------------------------------------- #
#  Who is in the export, and in what order
# --------------------------------------------------------------------------- #


def test_all_faculty_in_name_order_with_unassigned_last():
    export = faculty_export(schedule(), "Schedule 1 of 3")
    assert export.faculty_names == ["Hardy", "Hogg", "Xie", NO_FACULTY_LABEL]


def test_titles_identify_the_schedule_and_the_grouping():
    everyone = faculty_export(schedule(), "Schedule 2 of 5")
    assert everyone.schedule_title == "Schedule 2 of 5"
    assert everyone.grouping_title == "By faculty: all faculty"

    one = faculty_export(schedule(), "Schedule 2 of 5", chosen=["Hogg"])
    assert one.grouping_title == "By faculty: Hogg"


def test_one_chosen_faculty_member_gets_only_their_meetings():
    export = faculty_export(schedule(), "Schedule 1", chosen=["Hogg"])
    assert export.faculty_names == ["Hogg"]
    assert {row.course for row in export.groups[0].rows} == {"CMSC 380.01"}


def test_choosing_the_same_name_twice_lists_it_once():
    export = faculty_export(schedule(), "Schedule 1", chosen=["Hogg", "Hogg"])
    assert export.faculty_names == ["Hogg"]


def test_chosen_order_is_kept():
    export = faculty_export(schedule(), "Schedule 1", chosen=["Xie", "Hardy"])
    assert export.faculty_names == ["Xie", "Hardy"]


# --------------------------------------------------------------------------- #
#  What each row says (Section 5.2)
# --------------------------------------------------------------------------- #


def test_row_identifies_course_section_room_days_and_times():
    rows = group(faculty_export(schedule(), "S"), "Hardy").rows
    first = rows[0]
    assert first.course == "CMSC 140.01"
    assert first.course_name == "CMSC 140"
    assert first.section == "01"
    assert first.location_text == "Room: Roddy 147"
    assert first.days == ("MON", "WED")
    assert first.days_text == "Mon, Wed"
    assert first.start == "09:00"
    assert first.end == "10:50"
    assert first.time_text == "09:00-10:50"


def test_same_place_and_time_on_several_days_is_one_row():
    rows = group(faculty_export(schedule(), "S"), "Hardy").rows
    assert len(rows) == 2  # two sections, each meeting Mon and Wed
    assert all(row.days == ("MON", "WED") for row in rows)


def test_rows_are_in_day_then_time_order():
    rows = group(faculty_export(schedule(), "S"), "Hardy").rows
    assert [row.start for row in rows] == ["09:00", "13:00"]


def test_lab_meeting_is_its_own_row_and_names_the_lab():
    rows = group(faculty_export(schedule(), "S"), "Hogg").rows
    assert [(row.days_text, row.location_text) for row in rows] == [
        ("Tue", "Room: Roddy 140"),
        ("Thu", "Lab: Linux"),
    ]


def test_meeting_without_a_room_is_labelled_not_invented():
    online = Assignment(
        "CMSC 499.01", "Yang", None, None, (MeetingTime("MON", "18:00", "19:50", 110),)
    )
    row = faculty_export([online], "S").groups[0].rows[0]
    assert not row.has_location
    assert row.location == NO_LOCATION_LABEL
    assert row.location_text == NO_LOCATION_LABEL


def test_section_with_no_meeting_times_is_still_listed():
    xie = group(faculty_export(schedule(), "S"), "Xie")
    assert not xie.is_empty
    (row,) = xie.rows
    assert row.course == "CMSC 476.01"
    assert row.days == ()
    assert row.days_text == NO_MEETING_TIMES_LABEL
    assert row.time_text == ""
    assert row.location_text == NO_LOCATION_LABEL


def test_section_with_no_meeting_times_keeps_its_room_or_lab():
    rooms = [
        Assignment("CMSC 1.01", "A", "Roddy 136", None, ()),
        Assignment("CMSC 2.01", "A", None, "Mac", ()),
    ]
    rows = faculty_export(rooms, "S").groups[0].rows
    assert [row.location_text for row in rows] == ["Room: Roddy 136", "Lab: Mac"]


def test_sections_without_faculty_are_grouped_under_no_faculty_assigned():
    unassigned = group(faculty_export(schedule(), "S"), NO_FACULTY_LABEL)
    assert unassigned.sections == ["CMSC 152.01"]


def test_course_without_a_section_part():
    plain = Assignment(
        "CMSC 999", "A", "R", None, (MeetingTime("FRI", "08:00", "08:50", 50),)
    )
    row = faculty_export([plain], "S").groups[0].rows[0]
    assert (row.course_name, row.section) == ("CMSC 999", "")


# --------------------------------------------------------------------------- #
#  Empty selections (Section 5.4)
# --------------------------------------------------------------------------- #


def test_chosen_faculty_member_with_no_meetings_is_marked_empty():
    export = faculty_export(schedule(), "S", chosen=["Rogers"])
    (rogers,) = export.groups
    assert rogers.faculty == "Rogers"
    assert rogers.is_empty
    assert rogers.empty_text == NO_MEETINGS_LABEL
    assert export.is_empty


def test_empty_schedule_gives_an_empty_export():
    export = faculty_export([], "Schedule 1")
    assert export.groups == ()
    assert export.is_empty


def test_export_with_meetings_is_not_empty():
    export = faculty_export(schedule(), "S")
    assert not export.is_empty
    assert group(export, "Hardy").empty_text == ""


# --------------------------------------------------------------------------- #
#  Exporting changes nothing (Section 5.4)
# --------------------------------------------------------------------------- #


def test_export_does_not_change_the_schedule():
    original = schedule()
    copy = [dataclasses.replace(a) for a in original]
    faculty_export(original, "S")
    faculty_export(original, "S", chosen=["Hogg", "Nobody"])
    assert original == copy


def test_rows_are_immutable():
    row = group(faculty_export(schedule(), "S"), "Hardy").rows[0]
    assert isinstance(row, FacultyMeetingRow)
    with pytest.raises(dataclasses.FrozenInstanceError):
        field_name = "course"
        setattr(row, field_name, "changed")
