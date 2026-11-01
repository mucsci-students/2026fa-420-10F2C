"""
Tests for the calendar-style Schedule Viewer.

Acceptance criteria covered:
  * days and a time axis are labelled
  * blocks are positioned by start time and sized by duration
  * each meeting exposes course, section, faculty, room/lab, day and start/end
  * the selected schedule and the viewing mode are visibly identified
  * navigating schedules keeps the viewing mode
  * overlapping meetings stay individually visible
  * colour is never the only identifier
  * an understandable empty state
  * switching views never modifies the schedule data
"""

import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from app import schedule_io
from app.schedule_io import Assignment, MeetingTime
from gui import session_store
from gui.constants import DAY_NAMES, VIEW_OPTIONS
from gui.views import _schedule_grid, _schedule_rows, _split_course

VIEWER_URL = "/schedules/"
IMPORT_URL = "/schedules/import/"
EXPORT_URL = "/schedules/export/"

BLOCK_TAG = re.compile(
    r'<div class="week-grid__block schedule-grid__meeting[^"]*"[^>]*>', re.DOTALL
)


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


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
            None,
            "Roddy 140",
            None,
            (MeetingTime("MON", "13:00", "13:50", 50),),
        ),
    ]


def online_schedule():
    """A schedule whose only section has no meeting times."""
    return [Assignment("CMSC 390.01", "Hogg", None, None, ())]


def load(client, *schedules):
    raw = schedule_io.schedules_to_json(list(schedules)).encode("utf-8")
    upload = SimpleUploadedFile("fall.json", raw, content_type="application/json")
    return client.post(IMPORT_URL, {"schedule_file": upload}, follow=True)


def html_of(client, **params):
    return client.get(VIEWER_URL, params).content.decode()


def block_attrs(html):
    """One dict of data-* attributes per meeting block on the page."""
    return [
        dict(re.findall(r'(data-[\w-]+)="([^"]*)"', tag))
        for tag in BLOCK_TAG.findall(html)
    ]


def browser_session():
    return next(iter(session_store._SESSIONS.values()))


# ---------------------------------------------------------------------- #
#  Labelled days and time axis
# ---------------------------------------------------------------------- #
def test_every_weekday_column_is_labelled_with_its_full_name(client):
    load(client, sample_schedule())
    html = html_of(client)
    for name in DAY_NAMES.values():
        assert f'<div class="week-grid__day-name">{name}</div>' in html


def test_the_time_axis_labels_whole_hours_around_the_meetings(client):
    load(client, sample_schedule())  # 09:00 - 13:50, so the axis is 09:00 - 14:00
    html = html_of(client)
    for label in ("09:00", "10:00", "13:00", "14:00"):
        assert f'>{label}</span>' in html
    assert ">08:00</span>" not in html and ">15:00</span>" not in html


# ---------------------------------------------------------------------- #
#  Positioning and proportional size
# ---------------------------------------------------------------------- #
def test_blocks_are_positioned_by_start_time():
    assignments = [
        Assignment("A 100.01", meetings=(MeetingTime("MON", "09:00", "09:50", 50),)),
        Assignment("B 100.01", meetings=(MeetingTime("MON", "15:00", "15:50", 50),)),
    ]
    # axis 09:00 - 16:00 = 420 minutes
    first, second = _schedule_grid(assignments)["days"][0]["meetings"]
    assert first["top"] == "0.00"
    assert second["top"] == f"{(15 * 60 - 9 * 60) / 420 * 100:.2f}"  # 85.71


def test_blocks_are_sized_in_proportion_to_their_duration():
    assignments = [
        Assignment("A 100.01", meetings=(MeetingTime("MON", "09:00", "09:50", 50),)),
        Assignment("B 100.01", meetings=(MeetingTime("TUE", "09:00", "10:50", 110),)),
    ]
    days = {d["day"]: d["meetings"] for d in _schedule_grid(assignments)["days"]}
    short, long_ = float(days["MON"][0]["height"]), float(days["TUE"][0]["height"])
    assert long_ / short == pytest.approx(110 / 50, rel=0.01)
    assert short == pytest.approx(50 / 120 * 100, abs=0.01)  # axis 09:00 - 11:00


def test_the_page_applies_the_computed_position_and_height(client):
    load(client, [sample_schedule()[0], sample_schedule()[2]])
    html = html_of(client)
    meetings = [m for d in _schedule_grid(sample_schedule()[0::2])["days"] for m in d["meetings"]]
    for meeting in meetings:
        assert f"top: {meeting['top']}%" in html
        assert f"height: calc({meeting['height']}% - 3px)" in html


# ---------------------------------------------------------------------- #
#  Meeting details
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "course, expected",
    [
        ("CMSC 140.01", ("CMSC 140", "01")),
        ("CMSC 140.A", ("CMSC 140", "A")),
        ("CMSC 140", ("CMSC 140", "")),
        ("", ("", "")),
    ],
)
def test_a_course_label_is_split_into_course_and_section(course, expected):
    assert _split_course(course) == expected


def test_every_block_carries_all_the_meeting_details(client):
    load(client, sample_schedule())
    by_course = {a["data-course"]: a for a in block_attrs(html_of(client))}

    lecture = by_course["CMSC 140.01"]
    assert lecture["data-course-id"] == "CMSC 140"
    assert lecture["data-section"] == "01"
    assert lecture["data-faculty"] == "Hogg"
    assert lecture["data-location"] == "Roddy 136"
    assert lecture["data-when"] == "Monday 09:00–09:50 (50 min)"
    assert lecture["data-type"] == "Class"

    lab = by_course["CMSC 162.01"]
    assert lab["data-location"] == "Roddy 147" and lab["data-type"] == "Lab"
    assert lab["data-when"] == "Monday 10:00–11:50 (110 min)"

    assert by_course["CMSC 201.01"]["data-faculty"] == "No faculty assigned"


def test_the_meeting_list_gives_the_same_facts_as_text_in_time_order(client):
    load(client, sample_schedule())
    html = html_of(client)
    table = re.search(
        r'<details class="card meeting-list">.*?</details>', html, re.DOTALL
    ).group(0)
    assert "3 meetings" in table
    cells = re.findall(r"<td>(.*?)</td>", table)
    rows = [cells[i : i + 8] for i in range(0, len(cells), 8)]
    assert rows == [
        ["Monday", "09:00", "09:50", "CMSC 140.01", "01", "Hogg", "Roddy 136", "Class"],
        ["Monday", "10:00", "11:50", "CMSC 162.01", "01", "Killen", "Roddy 147", "Lab"],
        ["Monday", "13:00", "13:50", "CMSC 201.01", "01", "—", "Roddy 140", "Class"],
    ]


def test_meeting_rows_are_chronological_across_days():
    assignments = [
        Assignment("B 1.01", meetings=(MeetingTime("WED", "09:00", "09:50", 50),)),
        Assignment("A 1.01", meetings=(MeetingTime("MON", "11:00", "11:50", 50),)),
        Assignment("C 1.01", meetings=(MeetingTime("MON", "09:00", "09:50", 50),)),
    ]
    assert [r["course"] for r in _schedule_rows(assignments)] == [
        "C 1.01",
        "A 1.01",
        "B 1.01",
    ]


# ---------------------------------------------------------------------- #
#  Selected schedule and view are identified
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize("view", list(VIEW_OPTIONS))
def test_the_heading_names_the_schedule_and_the_view(client, view):
    load(client, sample_schedule(), sample_schedule(), sample_schedule())
    html = html_of(client, schedule="2", view=view)
    assert "Schedule 2 weekly overview" in html
    assert "Schedule 2 of 3" in html
    assert f'data-view-mode="{view}"' in html
    assert f">{VIEW_OPTIONS[view]} view</span>" in html


def test_an_unknown_view_is_shown_as_the_courses_view(client):
    load(client, sample_schedule())
    html = html_of(client, view="nonsense")
    assert 'data-view-mode="courses"' in html and ">Courses view</span>" in html


# ---------------------------------------------------------------------- #
#  Navigation keeps the viewing mode
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize("view", ["rooms", "faculty"])
def test_previous_and_next_keep_the_chosen_view(client, view):
    load(client, sample_schedule(), sample_schedule(), sample_schedule())
    html = html_of(client, schedule="2", view=view)
    assert f'href="?schedule=1&amp;view={view}">Previous</a>' in html
    assert f'href="?schedule=3&amp;view={view}">Next</a>' in html
    following = html_of(client, schedule="3", view=view)
    assert f'data-view-mode="{view}"' in following


def test_switching_view_keeps_the_selected_schedule(client):
    load(client, sample_schedule(), sample_schedule())
    html = html_of(client, schedule="2")
    assert 'href="?schedule=2&amp;view=rooms">Rooms</a>' in html
    assert 'href="?schedule=2&amp;view=faculty">Faculty</a>' in html


# ---------------------------------------------------------------------- #
#  Overlapping meetings
# ---------------------------------------------------------------------- #
def overlapping():
    return [
        Assignment("A 100.01", "X", "R1", None, (MeetingTime("MON", "09:00", "10:00", 60),)),
        Assignment("B 100.01", "Y", "R2", None, (MeetingTime("MON", "09:30", "10:30", 60),)),
    ]


def test_overlapping_meetings_get_separate_lanes():
    first, second = _schedule_grid(overlapping())["days"][0]["meetings"]
    assert (first["lane"], second["lane"]) == (0, 1)
    assert first["left"] != second["left"]
    assert first["width"] == second["width"] == "50.00"


def test_overlapping_meetings_are_each_present_and_focusable(client):
    load(client, overlapping())
    html = html_of(client)
    assert {a["data-course"] for a in block_attrs(html)} == {"A 100.01", "B 100.01"}
    assert len(BLOCK_TAG.findall(html)) == 2
    assert all('tabindex="0"' in tag for tag in BLOCK_TAG.findall(html))


# ---------------------------------------------------------------------- #
#  Colour is not the only identifier
# ---------------------------------------------------------------------- #
def test_each_block_shows_its_label_and_time_as_text_beside_its_colour(client):
    load(client, sample_schedule())
    html = html_of(client)
    for course in ("CMSC 140.01", "CMSC 162.01", "CMSC 201.01"):
        assert f'<span class="week-grid__label">{course}</span>' in html
    assert html.count('class="schedule-grid__time"') == 3
    assert "09:00&ndash;09:50" in html
    assert all("schedule-color-" in tag for tag in BLOCK_TAG.findall(html))
    for tag in BLOCK_TAG.findall(html):  # screen readers get the facts too
        assert 'aria-label="' in tag and "Monday" in tag


# ---------------------------------------------------------------------- #
#  Empty state
# ---------------------------------------------------------------------- #
def test_grid_reports_whether_it_has_meetings():
    assert _schedule_grid(online_schedule())["has_meetings"] is False
    assert _schedule_grid(sample_schedule())["has_meetings"] is True
    assert _schedule_grid(sample_schedule())["meeting_count"] == 3


@pytest.mark.parametrize("view", list(VIEW_OPTIONS))
def test_a_schedule_without_meetings_shows_an_empty_state_in_every_view(client, view):
    load(client, online_schedule())
    html = html_of(client, view=view)
    assert "No meetings to show" in html
    assert "has 1 course section" in html
    assert 'class="week-grid schedule-grid"' not in html
    assert "meeting-list" not in html
    assert f'data-view-mode="{view}"' in html  # the mode is still identified


def test_the_empty_state_is_per_schedule_not_global(client):
    load(client, online_schedule(), sample_schedule())
    assert "No meetings to show" in html_of(client, schedule="1")
    second = html_of(client, schedule="2")
    assert "No meetings to show" not in second
    assert 'class="week-grid schedule-grid"' in second


# ---------------------------------------------------------------------- #
#  Switching views never modifies the data
# ---------------------------------------------------------------------- #
def test_switching_views_and_schedules_leaves_the_schedule_data_untouched(client):
    load(client, sample_schedule(), overlapping())
    stored = browser_session().schedules
    before = client.get(EXPORT_URL, {"schedule": "all"}).content

    for number in ("1", "2"):
        for view in VIEW_OPTIONS:
            assert client.get(VIEWER_URL, {"schedule": number, "view": view}).status_code == 200

    assert browser_session().schedules is stored
    assert client.get(EXPORT_URL, {"schedule": "all"}).content == before


def test_the_view_changes_labels_but_not_the_meetings(client):
    load(client, sample_schedule())
    shown = {
        view: sorted((a["data-course"], a["data-when"]) for a in block_attrs(html_of(client, view=view)))
        for view in VIEW_OPTIONS
    }
    assert shown["courses"] == shown["rooms"] == shown["faculty"]