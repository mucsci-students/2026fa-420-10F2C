"""
Tests for the Schedule Viewer's Courses / Rooms / Faculty filter (Sections 16.1-16.2).

Covers the ?view= parameter (default courses, unknown values fall back to
courses), the block labels in each view, the filter menu, and the pager
keeping the chosen view. Nothing here touches the session.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from app import schedule_io
from app.schedule_io import Assignment, MeetingTime
from gui.constants import NO_FACULTY_LABEL, NO_LOCATION_LABEL, VIEW_COURSES, VIEW_FACULTY, VIEW_ROOMS
from gui.views import _schedule_grid

VIEWER_URL = "/schedules/"
IMPORT_URL = "/schedules/import/"

COURSE_TITLE = 'title="Monday 09:00-09:50: CMSC 140.01"'
ROOM_TITLE = 'title="Monday 09:00-09:50: Roddy 136"'
FACULTY_TITLE = 'title="Monday 09:00-09:50: Hogg"'


def sample_schedule():
    return [
        Assignment("CMSC 140.01", "Hogg", "Roddy 136", None, (MeetingTime("MON", "09:00", "09:50", 50),)),
        Assignment(
            "CMSC 162.01", "Killen", None, "Roddy 147", (MeetingTime("MON", "10:00", "11:50", 110, lab=True),)
        ),
        Assignment("CMSC 201.01", "Zoppetti", "Roddy 140", None, (MeetingTime("MON", "13:00", "13:50", 50),)),
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
    assert [row["label"] for row in monday] == ["CMSC 140.01", "CMSC 162.01", "CMSC 201.01"]


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
    assignments = [Assignment("CMSC 390.01", meetings=(MeetingTime("MON", "09:00", "09:50", 50),))]
    monday = _schedule_grid(assignments, VIEW_ROOMS)["days"][0]["meetings"]
    assert monday[0]["label"] == NO_LOCATION_LABEL


def test_faculty_view_labels_blocks_with_faculty_names():
    monday = _schedule_grid(sample_schedule(), VIEW_FACULTY)["days"][0]["meetings"]
    assert [row["label"] for row in monday] == ["Hogg", "Killen", "Zoppetti"]


def test_faculty_view_labels_meetings_without_a_faculty_member():
    assignments = [Assignment("CMSC 390.01", room="Roddy 136", meetings=(MeetingTime("MON", "09:00", "09:50", 50),))]
    monday = _schedule_grid(assignments, VIEW_FACULTY)["days"][0]["meetings"]
    assert monday[0]["label"] == NO_FACULTY_LABEL


def test_rooms_view_stacks_dense_clusters_by_room():
    assignments = [
        Assignment("CMSC 140.01", room="Roddy 136", meetings=(MeetingTime("MON", "09:00", "10:00", 60),)),
        Assignment("CMSC 140.02", room="Roddy 140", meetings=(MeetingTime("MON", "09:00", "10:00", 60),)),
        Assignment("CMSC 140.03", room="Roddy 144", meetings=(MeetingTime("MON", "09:30", "10:30", 60),)),
    ]
    [cluster] = _schedule_grid(assignments, VIEW_ROOMS)["days"][0]["clusters"]
    assert [meeting["label"] for meeting in cluster["meetings"]] == ["Roddy 136", "Roddy 140", "Roddy 144"]


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
    assert 'href="?schedule=1&amp;view=courses" aria-current="true">Courses</a>' in courses_html
    assert 'href="?schedule=1&amp;view=rooms">Rooms</a>' in courses_html
    assert 'href="?schedule=1&amp;view=faculty">Faculty</a>' in courses_html

    rooms_html = client.get(VIEWER_URL, {"view": "rooms"}).content.decode()
    assert 'href="?schedule=1&amp;view=rooms" aria-current="true">Rooms</a>' in rooms_html
    assert 'href="?schedule=1&amp;view=courses">Courses</a>' in rooms_html

    faculty_html = client.get(VIEWER_URL, {"view": "faculty"}).content.decode()
    assert 'href="?schedule=1&amp;view=faculty" aria-current="true">Faculty</a>' in faculty_html


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
