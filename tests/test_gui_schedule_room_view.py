"""
Tests for the Schedule Viewer's Courses / Rooms / Faculty filter (Sections 16.1-16.2).

Covers the ?view= parameter (default courses, unknown values fall back to
courses), the block labels in each view, the filter menu, and the pager
keeping the chosen view. Nothing here touches the session.
"""

import pathlib

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from app import schedule_io
from app.schedule_io import Assignment, MeetingTime
from gui.constants import (
    NO_FACULTY_LABEL,
    NO_LOCATION_LABEL,
    TIME_FORMAT_12,
    TIME_FORMAT_24,
    VIEW_COURSES,
    VIEW_FACULTY,
    VIEW_ROOMS,
)
from gui.views import (
    _block_detail,
    _clock_text,
    _range_text,
    _resource_chips,
    _resource_options,
    _schedule_grid,
    _view_query,
)

VIEWER_URL = "/schedules/"
IMPORT_URL = "/schedules/import/"

COURSE_TITLE = 'title="Monday 09:00-09:50: CMSC 140.01"'
ROOM_TITLE = 'title="Monday 09:00-09:50: Roddy 136"'
FACULTY_TITLE = 'title="Monday 09:00-09:50: Hogg"'


def sample_schedule():
    return [
        Assignment(
            "CMSC 140.01",
            "Hogg",
            "Roddy 136",
            None,
            (MeetingTime("MON", "09:00", "09:50", 50),),
        ),
        Assignment(
            "CMSC 162.01",
            "Killen",
            None,
            "Roddy 147",
            (MeetingTime("MON", "10:00", "11:50", 110, lab=True),),
        ),
        Assignment(
            "CMSC 201.01",
            "Zoppetti",
            "Roddy 140",
            None,
            (MeetingTime("MON", "13:00", "13:50", 50),),
        ),
    ]


def load(client, *schedules):
    raw = schedule_io.schedules_to_json(list(schedules)).encode("utf-8")
    upload = SimpleUploadedFile("fall.json", raw, content_type="application/json")
    return client.post(IMPORT_URL, {"schedule_file": upload}, follow=True)


# ---------------------------------------------------------------------- #
#  Grid labels (pure function, no Django)
# ---------------------------------------------------------------------- #
def test_courses_view_labels_blocks_with_course_names():
    monday = _schedule_grid(sample_schedule(), VIEW_COURSES)["days"][0]["meetings"]
    assert [row["label"] for row in monday] == [
        "CMSC 140.01",
        "CMSC 162.01",
        "CMSC 201.01",
    ]


def test_rooms_view_labels_blocks_with_room_or_lab_names():
    monday = _schedule_grid(sample_schedule(), VIEW_ROOMS)["days"][0]["meetings"]
    assert [row["label"] for row in monday] == ["Roddy 136", "Roddy 147", "Roddy 140"]


def test_rooms_view_uses_the_lab_for_lab_meetings_and_keeps_the_course_as_data():
    monday = _schedule_grid(sample_schedule(), VIEW_ROOMS)["days"][0]["meetings"]
    lab_row = monday[1]
    assert lab_row["meeting_type"] == "Lab"
    assert lab_row["label"] == "Roddy 147"
    assert lab_row["course"] == "CMSC 162.01"


def test_rooms_view_labels_meetings_without_a_location():
    assignments = [
        Assignment("CMSC 390.01", meetings=(MeetingTime("MON", "09:00", "09:50", 50),))
    ]
    monday = _schedule_grid(assignments, VIEW_ROOMS)["days"][0]["meetings"]
    assert monday[0]["label"] == NO_LOCATION_LABEL


def test_faculty_view_labels_blocks_with_faculty_names():
    monday = _schedule_grid(sample_schedule(), VIEW_FACULTY)["days"][0]["meetings"]
    assert [row["label"] for row in monday] == ["Hogg", "Killen", "Zoppetti"]


def test_faculty_view_labels_meetings_without_a_faculty_member():
    assignments = [
        Assignment(
            "CMSC 390.01",
            room="Roddy 136",
            meetings=(MeetingTime("MON", "09:00", "09:50", 50),),
        )
    ]
    monday = _schedule_grid(assignments, VIEW_FACULTY)["days"][0]["meetings"]
    assert monday[0]["label"] == NO_FACULTY_LABEL


def test_rooms_view_keeps_dense_overlaps_as_separate_blocks_labelled_by_room():
    assignments = [
        Assignment(
            "CMSC 140.01",
            room="Roddy 136",
            meetings=(MeetingTime("MON", "09:00", "10:00", 60),),
        ),
        Assignment(
            "CMSC 140.02",
            room="Roddy 140",
            meetings=(MeetingTime("MON", "09:00", "10:00", 60),),
        ),
        Assignment(
            "CMSC 140.03",
            room="Roddy 144",
            meetings=(MeetingTime("MON", "09:30", "10:30", 60),),
        ),
    ]

    monday = _schedule_grid(assignments, VIEW_ROOMS)["days"][0]["meetings"]

    assert [m["label"] for m in monday] == ["Roddy 136", "Roddy 140", "Roddy 144"]
    assert len({m["color"] for m in monday}) == 3  # color follows the room here


# ---------------------------------------------------------------------- #
#  Viewer page (Django test client)
# ---------------------------------------------------------------------- #
def test_courses_view_is_the_default(client):
    load(client, sample_schedule())
    html = client.get(VIEWER_URL).content.decode()
    assert COURSE_TITLE in html
    assert ROOM_TITLE not in html


@pytest.mark.parametrize("value", ["", "lab", "ROOMS", "FACULTY"])
def test_unknown_view_falls_back_to_courses(client, value):
    load(client, sample_schedule())
    html = client.get(VIEWER_URL, {"view": value}).content.decode()
    assert COURSE_TITLE in html
    assert ROOM_TITLE not in html


def test_rooms_view_labels_blocks_with_rooms(client):
    load(client, sample_schedule())
    html = client.get(VIEWER_URL, {"view": "rooms"}).content.decode()
    assert ROOM_TITLE in html
    assert COURSE_TITLE not in html


def test_faculty_view_labels_blocks_with_faculty(client):
    load(client, sample_schedule())
    html = client.get(VIEWER_URL, {"view": "faculty"}).content.decode()
    assert FACULTY_TITLE in html
    assert COURSE_TITLE not in html
    assert ROOM_TITLE not in html


def test_view_toggle_marks_the_active_view(client):
    load(client, sample_schedule())

    courses_html = client.get(VIEWER_URL, {"schedule": "1"}).content.decode()
    assert (
        'href="?schedule=1&amp;view=courses" aria-current="true">Courses</a>'
        in courses_html
    )
    assert 'href="?schedule=1&amp;view=rooms">Rooms</a>' in courses_html
    assert 'href="?schedule=1&amp;view=faculty">Faculty</a>' in courses_html

    rooms_html = client.get(VIEWER_URL, {"view": "rooms"}).content.decode()
    assert (
        'href="?schedule=1&amp;view=rooms" aria-current="true">Rooms</a>' in rooms_html
    )
    assert 'href="?schedule=1&amp;view=courses">Courses</a>' in rooms_html

    faculty_html = client.get(VIEWER_URL, {"view": "faculty"}).content.decode()
    assert (
        'href="?schedule=1&amp;view=faculty" aria-current="true">Faculty</a>'
        in faculty_html
    )


def test_pager_keeps_the_room_view(client):
    load(client, sample_schedule(), sample_schedule())
    html = client.get(VIEWER_URL, {"view": "rooms"}).content.decode()
    assert 'href="?schedule=2&amp;view=rooms">Next</a>' in html


def test_pager_keeps_the_faculty_view(client):
    load(client, sample_schedule(), sample_schedule())
    html = client.get(VIEWER_URL, {"view": "faculty"}).content.decode()
    assert 'href="?schedule=2&amp;view=faculty">Next</a>' in html


def test_pager_links_stay_plain_in_the_courses_view(client):
    load(client, sample_schedule(), sample_schedule())
    html = client.get(VIEWER_URL, {"schedule": "2"}).content.decode()
    assert 'href="?schedule=1">Previous</a>' in html


def test_block_detail_shows_the_facts_the_label_does_not():
    assert (
        _block_detail(VIEW_COURSES, "CMSC 140.01", "Roddy 136", "Hogg")
        == "Roddy 136 · Hogg"
    )
    assert (
        _block_detail(VIEW_ROOMS, "CMSC 140.01", "Roddy 136", "Hogg")
        == "CMSC 140.01 · Hogg"
    )
    assert (
        _block_detail(VIEW_FACULTY, "CMSC 140.01", "Roddy 136", "Hogg")
        == "CMSC 140.01 · Roddy 136"
    )


def test_block_detail_skips_missing_values():
    assert _block_detail(VIEW_COURSES, "CMSC 390.01", None, "Hogg") == "Hogg"
    assert _block_detail(VIEW_ROOMS, "CMSC 390.01", None, None) == "CMSC 390.01"
    assert _block_detail(VIEW_FACULTY, "CMSC 390.01", None, None) == "CMSC 390.01"


def test_rows_expose_duration_and_detail():
    [row] = _schedule_grid(
        [
            Assignment(
                "CMSC 140.01",
                "Hogg",
                "Roddy 136",
                None,
                (MeetingTime("MON", "09:00", "09:50", 50),),
            )
        ],
        VIEW_FACULTY,
    )["days"][0]["meetings"]
    assert row["duration"] == 50
    assert row["detail"] == "CMSC 140.01 · Roddy 136"


def test_color_follows_the_active_view_label():
    # Same course, two rooms: one color per course, two colors per room.
    assignments = [
        Assignment(
            "CMSC 140.01",
            room="Roddy 136",
            meetings=(MeetingTime("MON", "09:00", "09:50", 50),),
        ),
        Assignment(
            "CMSC 140.01",
            room="Roddy 140",
            meetings=(MeetingTime("TUE", "09:00", "09:50", 50),),
        ),
    ]

    def colors(view):
        days = _schedule_grid(assignments, view)["days"]
        return {m["color"] for d in days for m in d["meetings"]}

    assert len(colors(VIEW_COURSES)) == 1
    assert len(colors(VIEW_ROOMS)) == 2


# ---------------------------------------------------------------------- #
#  Room / faculty picker, color key and toolbar
# ---------------------------------------------------------------------- #
def block_titles(grid):
    return [
        (day["day"], row["label"], row["detail"])
        for day in grid["days"]
        for row in day["meetings"]
    ]


def two_sections():
    return [
        Assignment(
            "CMSC 140.01",
            "Hogg",
            "Roddy 136",
            None,
            (MeetingTime("MON", "09:00", "09:50", 50),),
        ),
        Assignment(
            "CMSC 140.02",
            "Killen",
            "Roddy 140",
            None,
            (MeetingTime("TUE", "13:00", "14:15", 75),),
        ),
        Assignment(
            "CMSC 201.01",
            "Zoppetti",
            "Roddy 140",
            None,
            (MeetingTime("WED", "15:30", "16:20", 50),),
        ),
    ]


def pairs(*names):
    return [(name, name) for name in names]


def test_picker_options_are_the_courses_rooms_and_labs_or_faculty_with_meetings():
    schedule = sample_schedule()
    assert _resource_options(schedule, VIEW_COURSES) == pairs(
        "CMSC 140.01", "CMSC 162.01", "CMSC 201.01"
    )
    assert _resource_options(schedule, VIEW_ROOMS) == pairs(
        "Roddy 136", "Roddy 140", "Roddy 147"
    )
    assert _resource_options(schedule, VIEW_FACULTY) == pairs(
        "Hogg", "Killen", "Zoppetti"
    )


def test_a_course_with_several_sections_also_gets_an_all_sections_choice():
    assert _resource_options(two_sections(), VIEW_COURSES) == [
        ("CMSC 140", "CMSC 140 (all sections)"),
        ("CMSC 140.01", "CMSC 140.01"),
        ("CMSC 140.02", "CMSC 140.02"),
        ("CMSC 201.01", "CMSC 201.01"),
    ]


def test_picking_one_section_keeps_only_that_section():
    grid = _schedule_grid(two_sections(), VIEW_COURSES, "CMSC 140.02")
    assert [row["course"] for day in grid["days"] for row in day["meetings"]] == [
        "CMSC 140.02"
    ]


def test_picking_a_whole_course_keeps_every_section_of_it():
    grid = _schedule_grid(two_sections(), VIEW_COURSES, "CMSC 140")
    assert [row["course"] for day in grid["days"] for row in day["meetings"]] == [
        "CMSC 140.01",
        "CMSC 140.02",
    ]


def test_picking_a_course_does_not_match_a_longer_course_number():
    schedule = two_sections() + [
        Assignment("CMSC 1400.01", meetings=(MeetingTime("FRI", "09:00", "09:50", 50),))
    ]
    grid = _schedule_grid(schedule, VIEW_COURSES, "CMSC 140")
    assert "CMSC 1400.01" not in [
        row["course"] for day in grid["days"] for row in day["meetings"]
    ]


def test_picking_a_faculty_member_keeps_only_their_meetings_and_still_names_them():
    grid = _schedule_grid(sample_schedule(), VIEW_FACULTY, "Hogg")
    assert block_titles(grid) == [("MON", "Hogg", "CMSC 140.01 · Roddy 136")]


def test_picking_a_lab_keeps_only_the_meetings_held_there():
    grid = _schedule_grid(sample_schedule(), VIEW_ROOMS, "Roddy 147")
    assert block_titles(grid) == [("MON", "Roddy 147", "CMSC 162.01 · Killen")]


def test_picking_a_resource_does_not_move_the_time_axis():
    everything = _schedule_grid(sample_schedule(), VIEW_FACULTY)
    one_person = _schedule_grid(sample_schedule(), VIEW_FACULTY, "Hogg")
    assert one_person["hours"] == everything["hours"]
    assert one_person["hour_pct"] == everything["hour_pct"]


def test_the_color_key_lists_each_label_once_with_its_color():
    legend = _schedule_grid(sample_schedule(), VIEW_FACULTY)["legend"]
    assert [item["label"] for item in legend] == ["Hogg", "Killen", "Zoppetti"]
    assert len({item["color"] for item in legend}) == 3


def test_the_picker_is_shown_in_every_view(client):
    load(client, sample_schedule())
    courses_html = client.get(VIEWER_URL).content.decode()
    assert '<select id="resource-picker" name="resource" multiple size="6">' in (
        courses_html
    )
    assert 'data-picker-all="All courses"' in courses_html
    assert '<option value="CMSC 162.01">CMSC 162.01</option>' in courses_html

    faculty_html = client.get(VIEWER_URL, {"view": "faculty"}).content.decode()
    assert 'id="resource-picker"' in faculty_html
    assert 'data-picker-all="All faculty"' in faculty_html
    assert '<option value="Hogg">Hogg</option>' in faculty_html

    rooms_html = client.get(VIEWER_URL, {"view": "rooms"}).content.decode()
    assert 'data-picker-all="All rooms and labs"' in rooms_html
    assert '<option value="Roddy 147">Roddy 147</option>' in rooms_html


def test_picking_a_course_shows_only_that_courses_blocks(client):
    load(client, sample_schedule())
    html = client.get(VIEWER_URL, {"resource": "CMSC 162.01"}).content.decode()
    assert '<option value="CMSC 162.01" selected>CMSC 162.01</option>' in html
    assert 'title="Monday 10:00-11:50: CMSC 162.01"' in html
    assert COURSE_TITLE not in html


def test_the_all_sections_choice_is_labeled_in_the_page(client):
    load(client, two_sections())
    html = client.get(VIEWER_URL).content.decode()
    assert '<option value="CMSC 140">CMSC 140 (all sections)</option>' in html


def test_picking_a_faculty_member_shows_only_that_persons_blocks(client):
    load(client, sample_schedule())
    html = client.get(
        VIEWER_URL, {"view": "faculty", "resource": "Hogg"}
    ).content.decode()
    assert '<option value="Hogg" selected>Hogg</option>' in html
    assert FACULTY_TITLE in html
    assert 'title="Monday 10:00-11:50: Killen"' not in html
    assert 'title="Monday 13:00-13:50: Zoppetti"' not in html


def test_an_unknown_resource_shows_everything(client):
    load(client, sample_schedule())
    html = client.get(
        VIEWER_URL, {"view": "faculty", "resource": "Nobody"}
    ).content.decode()
    assert (
        " selected>" not in html.split('id="resource-picker"')[1].split("</select>")[0]
    )
    assert FACULTY_TITLE in html
    assert 'title="Monday 10:00-11:50: Killen"' in html


def test_the_pager_keeps_the_picked_resource(client):
    load(client, sample_schedule(), sample_schedule())
    html = client.get(
        VIEWER_URL, {"view": "faculty", "resource": "Hogg"}
    ).content.decode()
    assert 'href="?schedule=2&amp;view=faculty&amp;resource=Hogg">Next</a>' in html


def test_the_toolbar_names_the_schedule_the_view_and_has_a_color_key(client):
    load(client, sample_schedule())
    html = client.get(VIEWER_URL, {"view": "faculty"}).content.decode()
    assert "Schedule 1 of 1" in html
    assert 'class="btn btn-primary" href="?schedule=1&amp;view=faculty"' in html
    assert "Schedule 1 weekly overview" in html and "Faculty view" in html
    assert "Color key (3)" in html


# ---------------------------------------------------------------------- #
#  12-hour / 24-hour clock
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("00:00", "12:00 AM"),
        ("00:30", "12:30 AM"),
        ("09:05", "9:05 AM"),
        ("11:59", "11:59 AM"),
        ("12:00", "12:00 PM"),
        ("13:10", "1:10 PM"),
        ("23:45", "11:45 PM"),
    ],
)
def test_twelve_hour_clock_text(value, expected):
    assert _clock_text(value, TIME_FORMAT_12) == expected


def test_twenty_four_hour_clock_text_is_unchanged():
    assert _clock_text("13:10", TIME_FORMAT_24) == "13:10"
    assert _clock_text("09:05") == "09:05"


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("09:00", "09:50", "9:00\u20139:50 AM"),
        ("13:10", "15:00", "1:10\u20133:00 PM"),
        ("11:00", "12:50", "11:00 AM\u201312:50 PM"),
    ],
)
def test_twelve_hour_ranges_write_am_pm_once_when_it_is_shared(start, end, expected):
    assert _range_text(start, end, TIME_FORMAT_12) == expected


def test_twenty_four_hour_range_is_start_dash_end():
    assert _range_text("09:00", "09:50") == "09:00\u201309:50"


def test_the_grid_axis_and_blocks_follow_the_time_format():
    schedule = [
        Assignment("A", meetings=(MeetingTime("MON", "11:00", "12:50", 110),)),
        Assignment("B", meetings=(MeetingTime("MON", "14:00", "14:50", 50),)),
    ]
    plain = _schedule_grid(schedule)
    assert [hour["label"] for hour in plain["hours"]][:2] == ["11:00", "12:00"]
    twelve = _schedule_grid(schedule, time_format=TIME_FORMAT_12)
    assert [hour["label"] for hour in twelve["hours"]] == [
        "11 AM",
        "12 PM",
        "1 PM",
        "2 PM",
        "3 PM",
    ]
    monday = twelve["days"][0]["meetings"]
    assert [row["range_text"] for row in monday] == [
        "11:00 AM\u201312:50 PM",
        "2:00\u20132:50 PM",
    ]
    # Position and size still come from the real 24-hour times.
    assert [row["top"] for row in monday] == [
        row["top"] for row in plain["days"][0]["meetings"]
    ]


def test_the_time_toggle_marks_the_active_format_and_keeps_the_view(client):
    load(client, sample_schedule())
    html = client.get(VIEWER_URL, {"view": "faculty"}).content.decode()
    assert 'aria-label="Time format"' in html
    assert (
        'class="btn btn-primary" href="?schedule=1&amp;view=faculty&amp;time=24h"'
        in html
    )
    assert 'class="btn" href="?schedule=1&amp;view=faculty&amp;time=12h"' in html


def test_the_page_defaults_to_the_24_hour_clock(client):
    load(client, sample_schedule())
    html = client.get(VIEWER_URL).content.decode()
    assert "09:00\u201309:50" in html
    assert "9:00\u20139:50 AM" not in html


def test_choosing_12_hour_shows_am_pm_and_is_remembered(client):
    load(client, sample_schedule())
    html = client.get(VIEWER_URL, {"time": "12h"}).content.decode()
    assert "9:00\u20139:50 AM" in html
    assert 'title="Monday 9:00-9:50 AM: CMSC 140.01"' in html
    assert "9 AM" in html

    # No ?time= on the next request, but the choice stays (paging, switching views).
    again = client.get(VIEWER_URL, {"view": "rooms"}).content.decode()
    assert "9:00\u20139:50 AM" in again

    back = client.get(VIEWER_URL, {"time": "24h"}).content.decode()
    assert "09:00\u201309:50" in back and "9:00\u20139:50 AM" not in back


def test_an_unknown_time_format_is_ignored(client):
    load(client, sample_schedule())
    html = client.get(VIEWER_URL, {"time": "banana"}).content.decode()
    assert "09:00\u201309:50" in html


# ---------------------------------------------------------------------- #
#  Picking several items at once
# ---------------------------------------------------------------------- #
def shown(grid):
    return [
        (row["day"], row["label"]) for day in grid["days"] for row in day["meetings"]
    ]


def test_several_faculty_keep_the_faculty_names_as_labels():
    grid = _schedule_grid(sample_schedule(), VIEW_FACULTY, ["Hogg", "Killen"])
    assert shown(grid) == [("MON", "Hogg"), ("MON", "Killen")]


def test_several_rooms_and_labs_keep_the_meetings_held_in_any_of_them():
    grid = _schedule_grid(sample_schedule(), VIEW_ROOMS, ["Roddy 136", "Roddy 147"])
    assert shown(grid) == [("MON", "Roddy 136"), ("MON", "Roddy 147")]


def test_several_courses_keep_any_of_them():
    grid = _schedule_grid(two_sections(), VIEW_COURSES, ["CMSC 140.02", "CMSC 201.01"])
    assert shown(grid) == [("TUE", "CMSC 140.02"), ("WED", "CMSC 201.01")]


def test_a_course_and_one_of_its_sections_do_not_show_a_meeting_twice():
    grid = _schedule_grid(two_sections(), VIEW_COURSES, ["CMSC 140", "CMSC 140.01"])
    assert shown(grid) == [("MON", "CMSC 140.01"), ("TUE", "CMSC 140.02")]


def test_one_picked_item_reads_the_same_as_several_and_a_plain_string_still_works():
    as_list = _schedule_grid(sample_schedule(), VIEW_FACULTY, ["Hogg"])
    as_text = _schedule_grid(sample_schedule(), VIEW_FACULTY, "Hogg")
    assert shown(as_list) == shown(as_text) == [("MON", "Hogg")]


def test_view_query_repeats_resource_for_each_picked_item():
    assert _view_query(VIEW_COURSES) == ""
    assert _view_query(VIEW_COURSES, ["CMSC 140"]) == "&resource=CMSC%20140"
    assert (
        _view_query(VIEW_FACULTY, ["Hogg", "Zoppetti, J."])
        == "&view=faculty&resource=Hogg&resource=Zoppetti%2C%20J."
    )


def test_each_chip_links_to_the_view_without_that_item():
    options = _resource_options(sample_schedule(), VIEW_FACULTY)
    chips = _resource_chips(1, VIEW_FACULTY, ["Hogg", "Killen"], options)
    assert chips == [
        {"label": "Hogg", "href": "?schedule=1&view=faculty&resource=Killen"},
        {"label": "Killen", "href": "?schedule=1&view=faculty&resource=Hogg"},
    ]


def test_removing_the_last_chip_goes_back_to_showing_everything():
    options = _resource_options(sample_schedule(), VIEW_COURSES)
    chips = _resource_chips(2, VIEW_COURSES, ["CMSC 162.01"], options)
    assert chips == [{"label": "CMSC 162.01", "href": "?schedule=2"}]


def test_the_all_sections_chip_uses_its_readable_label():
    options = _resource_options(two_sections(), VIEW_COURSES)
    chips = _resource_chips(1, VIEW_COURSES, ["CMSC 140"], options)
    assert chips[0]["label"] == "CMSC 140 (all sections)"


def test_picking_several_shows_only_their_blocks_and_selects_them_all(client):
    load(client, sample_schedule())
    html = client.get(
        VIEWER_URL, {"view": "faculty", "resource": ["Hogg", "Killen"]}
    ).content.decode()
    assert '<option value="Hogg" selected>Hogg</option>' in html
    assert '<option value="Killen" selected>Killen</option>' in html
    assert '<option value="Zoppetti">Zoppetti</option>' in html
    assert FACULTY_TITLE in html
    assert 'title="Monday 10:00-11:50: Killen"' in html
    assert 'title="Monday 13:00-13:50: Zoppetti"' not in html
    assert "Faculty view: Hogg, Killen" in html


def test_chips_show_what_is_picked_and_can_be_removed_one_by_one(client):
    load(client, sample_schedule())
    html = client.get(
        VIEWER_URL, {"view": "faculty", "resource": ["Hogg", "Killen"]}
    ).content.decode()
    assert "Showing only:" in html
    assert (
        'href="?schedule=1&amp;view=faculty&amp;resource=Killen" title="Remove Hogg"'
        in html
    )
    assert 'class="schedule-chips__clear" href="?schedule=1&amp;view=faculty"' in html


def test_no_chips_when_nothing_is_picked(client):
    load(client, sample_schedule())
    html = client.get(VIEWER_URL, {"view": "faculty"}).content.decode()
    assert "Showing only:" not in html


def test_the_pager_keeps_every_picked_item(client):
    load(client, sample_schedule(), sample_schedule())
    html = client.get(
        VIEWER_URL, {"view": "faculty", "resource": ["Hogg", "Killen"]}
    ).content.decode()
    assert (
        'href="?schedule=2&amp;view=faculty&amp;resource=Hogg&amp;resource=Killen">Next</a>'
        in html
    )


def test_unknown_and_repeated_items_are_dropped(client):
    load(client, sample_schedule())
    html = client.get(
        VIEWER_URL,
        {"view": "faculty", "resource": ["Hogg", "Nobody", "Hogg"]},
    ).content.decode()
    assert html.count("Remove Hogg") == 1
    assert "Nobody" not in html


# ---------------------------------------------------------------------- #
#  Every block says the same three things
# ---------------------------------------------------------------------- #
def all_rows(grid):
    return [row for day in grid["days"] for row in day["meetings"]]


def test_every_block_leads_with_the_views_own_item_and_lists_the_other_two():
    expected = {
        VIEW_COURSES: ("CMSC 140.01", ["Roddy 136", "Hogg"]),
        VIEW_ROOMS: ("Roddy 136", ["CMSC 140.01", "Hogg"]),
        VIEW_FACULTY: ("Hogg", ["CMSC 140.01", "Roddy 136"]),
    }
    for view, (label, details) in expected.items():
        row = all_rows(_schedule_grid(sample_schedule(), view))[0]
        assert (row["label"], row["details"]) == (label, details), view


def test_a_missing_room_or_faculty_member_is_written_out_not_left_off():
    schedule = [
        Assignment(
            "CMSC 390.01", None, None, None, (MeetingTime("MON", "09:00", "09:50", 50),)
        )
    ]
    assert all_rows(_schedule_grid(schedule, VIEW_COURSES))[0]["details"] == [
        NO_LOCATION_LABEL,
        NO_FACULTY_LABEL,
    ]
    assert all_rows(_schedule_grid(schedule, VIEW_ROOMS))[0]["details"] == [
        "CMSC 390.01",
        NO_FACULTY_LABEL,
    ]
    assert all_rows(_schedule_grid(schedule, VIEW_FACULTY))[0]["details"] == [
        "CMSC 390.01",
        NO_LOCATION_LABEL,
    ]


def test_short_classes_keep_their_details_and_only_tiny_blocks_drop_them():
    schedule = [
        Assignment(
            "A",
            "Hogg",
            "Roddy 136",
            None,
            (MeetingTime("MON", "09:00", "09:50", 50),),
        ),
        Assignment(
            "B",
            "Hogg",
            "Roddy 136",
            None,
            (MeetingTime("TUE", "09:00", "09:15", 15),),
        ),
        # A full teaching day, so the calendar spans 09:00-18:00 like a real week.
        Assignment(
            "C",
            "Hogg",
            "Roddy 136",
            None,
            (MeetingTime("FRI", "17:00", "18:00", 60),),
        ),
    ]
    rows = {row["course"]: row for row in all_rows(_schedule_grid(schedule))}
    assert rows["A"]["compact"] is False  # a 50-minute class keeps both details
    assert rows["B"]["compact"] is True  # a 15-minute block has no room for them


def test_the_page_writes_each_block_with_both_details(client):
    load(client, sample_schedule())
    html = client.get(VIEWER_URL).content.decode()
    assert (
        '<div class="schedule-grid__details"><span class="schedule-grid__detail">Roddy 136</span>'
        '<span class="schedule-grid__detail">Hogg</span></div>'
    ) in html


# ---------------------------------------------------------------------- #
#  What fits in a block (the layout itself needs a browser; these guard the pieces it relies on)
# ---------------------------------------------------------------------- #
CSS = pathlib.Path("gui/static/gui/css/style.css").read_text()


def test_every_block_is_laid_out_the_same_whatever_its_size():
    assert "@container" not in CSS and "cqi" not in CSS
    time_rule = CSS.split(".schedule-grid__time {")[1].split("}")[0]
    assert "display: block;" in time_rule and "flex: 1 0 100%;" in time_rule


def test_each_hour_is_tall_enough_for_a_50_minute_class_to_hold_four_lines(client):
    from gui.views import HOUR_HEIGHT_REM

    # name 0.75rem*1.15 + time 0.68*1.2 + two facts 0.68*1.25 each + padding, for 50 of 60 minutes
    assert HOUR_HEIGHT_REM * 50 / 60 >= 3.6
    load(client, sample_schedule())
    html = client.get(VIEWER_URL).content.decode()
    assert "--grid-height: " in html


def test_a_blocks_name_and_facts_are_never_allowed_to_wrap_past_the_block():
    label = CSS.split(".schedule-grid__header .week-grid__label {")[1].split("}")[0]
    detail = CSS.split(".schedule-grid__detail {")[1].split("}")[0]
    for rule in (label, detail):
        assert "white-space: nowrap;" in rule and "text-overflow: ellipsis;" in rule


def test_the_12_hour_clock_still_marks_the_grid(client):
    load(client, sample_schedule())
    plain = client.get(VIEWER_URL).content.decode()
    twelve = client.get(VIEWER_URL, {"time": "12h"}).content.decode()
    assert "schedule-grid--12h" not in plain
    assert 'class="week-grid schedule-grid schedule-grid--12h"' in twelve
