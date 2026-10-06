"""
Tests for Schedule JSON import in the Schedule Viewer (Sprint 2 Sections
17, 19, 23.4, 23.6): gui/controllers/schedule_controller.load_schedule_json,
the ScheduleImportForm, and the /schedules/import/ page flow.

The file format itself (every accepted shape and every rejection) is
covered in tests/test_schedule_io.py, and the shared helpers this feature
is built on in tests/test_gui_shared_helpers.py. These tests cover what
the user sees and that a failed load never touches the loaded schedules.
"""

import io
import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from app import schedule_io
from app.schedule_io import Assignment, MeetingTime
from app.session import Session
from gui.controllers import schedule_controller as ctrl
from gui.controllers.errors import ControllerError

VIEWER_URL = "/schedules/"
IMPORT_URL = "/schedules/import/"


def schedule(faculty):
    return [Assignment("CMSC 140.01", faculty, "Roddy 136", None, (MeetingTime("MON", "09:00", "09:50", 50),))]


def schedule_file_bytes(*faculty):
    return schedule_io.schedules_to_json([schedule(name) for name in faculty]).encode("utf-8")


def upload(raw, name="fall.json"):
    return SimpleUploadedFile(name, raw, content_type="application/json")


# ---------------------------------------------------------------------- #
#  Controller (called directly, independent of Django's request cycle)
# ---------------------------------------------------------------------- #
@pytest.fixture
def session(monkeypatch):
    fresh = Session()
    monkeypatch.setattr(ctrl, "get_session", lambda request: fresh)
    return fresh


class TestLoadScheduleJson:
    def test_loads_a_schedule_set(self, session):
        count = ctrl.load_schedule_json(None, io.BytesIO(schedule_file_bytes("A", "B", "C")))
        assert count == 3
        assert [s[0].faculty for s in session.schedules] == ["A", "B", "C"]

    def test_loads_a_single_schedule(self, session):
        single = json.dumps([Assignment("CMSC 161.01").to_dict()]).encode()
        assert ctrl.load_schedule_json(None, io.BytesIO(single)) == 1

    def test_replaces_existing_schedules(self, session):
        session.schedules = [schedule("Old")]
        ctrl.load_schedule_json(None, io.BytesIO(schedule_file_bytes("New")))
        assert [s[0].faculty for s in session.schedules] == ["New"]

    def test_loaded_schedules_are_readable_through_the_shared_helpers(self, session):
        ctrl.load_schedule_json(None, io.BytesIO(schedule_file_bytes("A", "B")))
        assert ctrl.get_schedule(None, 1)[0].faculty == "B"
        assert len(ctrl.get_schedules(None)) == 2

    def test_does_not_touch_the_configuration(self, session):
        ctrl.load_schedule_json(None, io.BytesIO(schedule_file_bytes("A")))
        assert session.config is None and session.dirty is False

    @pytest.mark.parametrize(
        "raw, fragment",
        [
            (b"{not json", "not valid JSON"),
            (b'{"config": {}, "time_slot_config": {}}', "looks like a configuration file"),
            (b'[[{"faculty": "x"}]]', "missing or invalid"),
        ],
    )
    def test_bad_file_is_rejected_and_existing_schedules_are_kept(self, session, raw, fragment):
        existing = [schedule("Keep me")]
        session.schedules = existing
        with pytest.raises(ControllerError) as info:
            ctrl.load_schedule_json(None, io.BytesIO(raw))
        assert fragment in info.value.message
        assert "Your current schedules were kept." in info.value.message
        assert session.schedules is existing
        assert {item.field for item in info.value.errors} == {"schedule_file"}

    def test_empty_file_is_rejected_on_the_file_field(self, session):
        existing = [schedule("Keep me")]
        session.schedules = existing
        with pytest.raises(ControllerError) as info:
            ctrl.load_schedule_json(None, io.BytesIO(b""))
        assert info.value.errors[0].field == "schedule_file"
        assert "empty" in info.value.message
        assert session.schedules is existing

    def test_specific_problems_are_listed_separately(self, session):
        bad = json.dumps([[{"course": "CMSC 140.01", "meetings": [{"day": "SAT", "start": "09:00", "duration": 50}]}]])
        with pytest.raises(ControllerError) as info:
            ctrl.load_schedule_json(None, io.BytesIO(bad.encode()))
        messages = [item.message for item in info.value.errors]
        assert len(messages) == 2
        assert "not a weekday" in messages[1] and messages[1].startswith("Schedule 1, assignment 1")


# ---------------------------------------------------------------------- #
#  Pages (Django test client)
# ---------------------------------------------------------------------- #
def load(client, raw, name="fall.json", **extra):
    data = {"schedule_file": upload(raw, name), **extra}
    return client.post(IMPORT_URL, data, follow=True)


def test_viewer_shows_empty_state_and_upload_form(client):
    html = client.get(VIEWER_URL).content.decode()
    assert "No schedules yet" in html
    assert 'enctype="multipart/form-data"' in html
    assert 'name="schedule_file"' in html
    assert 'name="confirm_replace"' not in html  # nothing to replace yet


def test_loading_a_file_shows_success_and_the_schedule_count(client):
    response = load(client, schedule_file_bytes("A", "B"))
    html = response.content.decode()
    assert response.redirect_chain[-1][0].endswith(VIEWER_URL)
    assert "Loaded 2 schedules from fall.json." in html
    assert "<strong>2</strong> schedules available." in html
    assert "No schedules yet" not in html


def test_loaded_schedules_persist_to_the_next_page_load(client):
    load(client, schedule_file_bytes("A", "B", "C"))
    assert "<strong>3</strong> schedules available." in client.get(VIEWER_URL).content.decode()


def test_bad_file_shows_errors_on_the_form_and_keeps_schedules(client):
    load(client, schedule_file_bytes("A", "B"))
    response = load(client, b"{not json", "bad.json", confirm_replace="on")
    html = response.content.decode()

    assert response.status_code == 200 and not response.redirect_chain  # re-rendered, not redirected
    assert "field--error" in html and "<strong>Error:</strong>" in html
    assert "not valid JSON" in html and "Your current schedules were kept." in html
    assert "<strong>2</strong> schedules available." in html
    assert "Traceback" not in html


def test_config_file_gets_a_specific_hint(client):
    config_like = json.dumps({"config": {}, "time_slot_config": {}, "limit": 10}).encode()
    html = load(client, config_like, "config_example.json").content.decode()
    assert "looks like a configuration file" in html


def test_problem_list_is_shown(client):
    bad = json.dumps([[{"course": "CMSC 140.01", "meetings": [{"day": "SAT", "start": "09:00", "duration": 50}]}]])
    html = load(client, bad.encode()).content.decode()
    assert "not a weekday" in html


def test_replacing_schedules_requires_confirmation(client):
    load(client, schedule_file_bytes("A"))
    assert 'name="confirm_replace"' in client.get(VIEWER_URL).content.decode()

    html = load(client, schedule_file_bytes("B", "C")).content.decode()
    assert "Tick this box to confirm replacing" in html
    assert "<strong>1</strong> schedule available." in html  # unchanged

    html = load(client, schedule_file_bytes("B", "C"), confirm_replace="on").content.decode()
    assert "Loaded 2 schedules" in html


def test_submitting_without_a_file(client):
    html = client.post(IMPORT_URL, {}).content.decode()
    assert "This field is required." in html


def test_get_on_the_import_url_goes_back_to_the_viewer(client):
    response = client.get(IMPORT_URL)
    assert response.status_code == 302 and response["Location"].endswith(VIEWER_URL)


# ---------------------------------------------------------------------- #
#  User story 45: "a bad file never wipes out my current schedules"
# ---------------------------------------------------------------------- #
def test_story_45_malformed_json_keeps_the_3_schedules(client):
    load(client, schedule_file_bytes("A", "B", "C"))
    before = client.get(VIEWER_URL).content.decode()
    assert "<strong>3</strong> schedules available." in before

    html = load(client, b'{"schedules": [ oops', "broken.json", confirm_replace="on").content.decode()

    assert "<strong>Error:</strong>" in html and "not valid JSON" in html
    assert "Your current schedules were kept." in html
    assert "<strong>3</strong> schedules available." in html
    exported = json.loads(client.get("/schedules/export/", {"schedule": "all"}).content.decode("utf-8"))
    assert [s[0]["faculty"] for s in exported["schedules"]] == ["A", "B", "C"]  # the same 3, untouched


def test_story_45_config_file_is_not_a_supported_schedule_format_and_nothing_is_replaced(client):
    load(client, schedule_file_bytes("A", "B", "C"))
    with open("app/examples/config_example.json", "rb") as handle:
        config_file = handle.read()

    html = load(client, config_file, "config_example.json", confirm_replace="on").content.decode()

    assert "not a supported schedule format" in html
    assert "Load it from the Configuration Editor instead." in html
    assert "<strong>3</strong> schedules available." in html
    exported = json.loads(client.get("/schedules/export/", {"schedule": "all"}).content.decode("utf-8"))
    assert [s[0]["faculty"] for s in exported["schedules"]] == ["A", "B", "C"]


@pytest.mark.parametrize(
    "raw",
    [
        b'{"format": "something-else", "version": 1, "schedules": []}',
        b'{"hello": "world"}',
        b'"just a string"',
    ],
)
def test_story_45_other_wrong_formats_use_the_same_wording(client, raw):
    load(client, schedule_file_bytes("A"))
    html = load(client, raw, "odd.json", confirm_replace="on").content.decode()
    assert "not a supported schedule format" in html
    assert "<strong>1</strong> schedule available." in html
