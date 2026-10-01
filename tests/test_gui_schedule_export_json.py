"""
Tests for exporting a selected schedule as JSON from the Schedule Viewer
(Sprint 2 Sections 18, 19, 23.4, 23.6):
gui/controllers/schedule_controller.export_schedule_json, the
ScheduleExportForm, and the /schedules/export/json/ download.

The JSON format itself is covered in tests/test_schedule_io.py; these tests
cover choosing the schedule, the download, the "nothing to export" states,
and that an export can be loaded back in (round trip).
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
EXPORT_URL = "/schedules/export/json/"


def schedule(faculty):
    return [Assignment("CMSC 140.01", faculty, "Roddy 136", None, (MeetingTime("MON", "09:00", "09:50", 50),))]


# ---------------------------------------------------------------------- #
#  Controller (called directly, independent of Django's request cycle)
# ---------------------------------------------------------------------- #
@pytest.fixture
def session(monkeypatch):
    fresh = Session()
    monkeypatch.setattr(ctrl, "get_session", lambda request: fresh)
    return fresh


class TestExportScheduleJson:
    def test_exports_only_the_selected_schedule(self, session):
        session.schedules = [schedule("A"), schedule("B"), schedule("C")]
        export = ctrl.export_schedule_json(None, 1)

        assert export.filename == "schedule-2.json"
        assert export.content_type == "application/json; charset=utf-8"
        assert export.schedule_count == 1
        data = json.loads(export.content)
        assert data["format"] == schedule_io.FORMAT_NAME and data["schedule_count"] == 1
        assert data["schedules"][0][0]["faculty"] == "B"

    def test_index_none_exports_every_schedule(self, session):
        session.schedules = [schedule("A"), schedule("B"), schedule("C")]
        export = ctrl.export_schedule_json(None)
        assert export.filename == "schedules-all-3.json"
        assert [s[0]["faculty"] for s in json.loads(export.content)["schedules"]] == ["A", "B", "C"]

    def test_exported_schedule_loads_back_the_same(self, session):
        session.schedules = [schedule("A"), schedule("B")]
        export = ctrl.export_schedule_json(None, 1)

        session.schedules = []
        assert ctrl.load_schedule_json(None, io.BytesIO(export.content.encode("utf-8"))) == 1
        assert session.schedules == [schedule("B")]

    def test_generated_schedules_export_too(self, session):
        class FakeCourseInstance:  # what the generator stores: the library's objects
            def as_json(self):
                return {"course": "CMSC 140.01", "faculty": "Gen", "room": "Roddy 136", "lab": None,
                        "times": [{"day": "MON", "start": "09:00", "duration": 50}]}

        session.schedules = [[FakeCourseInstance()]]
        data = json.loads(ctrl.export_schedule_json(None, 0).content)
        assert data["schedules"][0][0]["faculty"] == "Gen"

    def test_non_ascii_names_survive(self, session):
        session.schedules = [schedule("Muñoz")]
        export = ctrl.export_schedule_json(None, 0)
        assert "Muñoz" in export.content
        assert json.loads(export.content.encode("utf-8"))["schedules"][0][0]["faculty"] == "Muñoz"

    def test_export_changes_nothing(self, session):
        stored = [schedule("A"), schedule("B")]
        session.schedules = stored
        ctrl.export_schedule_json(None, 0)
        assert session.schedules is stored and session.dirty is False

    def test_no_schedules(self, session):
        with pytest.raises(ControllerError) as info:
            ctrl.export_schedule_json(None, 0)
        assert info.value.message == ctrl.NO_SCHEDULES_MESSAGE

    @pytest.mark.parametrize("index", [-1, 2, 50])
    def test_schedule_that_does_not_exist(self, session, index):
        session.schedules = [schedule("A"), schedule("B")]
        with pytest.raises(ControllerError) as info:
            ctrl.export_schedule_json(None, index)
        assert "There are 2 schedule(s)." in info.value.message


# ---------------------------------------------------------------------- #
#  Pages (Django test client)
# ---------------------------------------------------------------------- #
def load(client, *faculty):
    raw = schedule_io.schedules_to_json([schedule(name) for name in faculty]).encode("utf-8")
    upload = SimpleUploadedFile("fall.json", raw, content_type="application/json")
    return client.post(IMPORT_URL, {"schedule_file": upload}, follow=True)


def test_export_is_disabled_when_there_are_no_schedules(client):
    html = client.get(VIEWER_URL).content.decode()
    assert "Nothing to export yet" in html
    assert "disabled" in html and "Export this schedule (JSON)" in html
    assert 'name="schedule"' not in html


def test_viewer_lists_every_schedule_to_export(client):
    load(client, "A", "B", "C")
    html = client.get(VIEWER_URL).content.decode()
    assert 'action="/schedules/export/json/"' in html
    for number in (1, 2, 3):
        assert f"Schedule {number} of 3" in html
    assert '<option value="1" selected>' in html


def test_current_schedule_is_preselected(client):
    load(client, "A", "B", "C")
    html = client.get(VIEWER_URL, {"schedule": "2"}).content.decode()
    assert '<option value="2" selected>' in html


def test_download_contains_only_the_chosen_schedule(client):
    load(client, "A", "B", "C")
    response = client.get(EXPORT_URL, {"schedule": "2"})

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json; charset=utf-8"
    assert response["Content-Disposition"] == 'attachment; filename="schedule-2.json"'
    data = json.loads(response.content.decode("utf-8"))
    assert data["schedule_count"] == 1
    assert data["schedules"][0][0]["faculty"] == "B"


def test_downloaded_file_loads_back_in_a_later_session(client):
    load(client, "A", "B", "C")
    exported = client.get(EXPORT_URL, {"schedule": "3"}).content

    later = type(client)()  # a fresh browser
    upload = SimpleUploadedFile("schedule-3.json", exported, content_type="application/json")
    html = later.post(IMPORT_URL, {"schedule_file": upload}, follow=True).content.decode()
    assert "Loaded 1 schedule from schedule-3.json." in html


def test_export_does_not_change_the_viewer(client):
    load(client, "A", "B", "C")
    client.get(EXPORT_URL, {"schedule": "1"})
    assert "<strong>3</strong> schedules available." in client.get(VIEWER_URL).content.decode()


def test_export_with_no_schedules_explains_why(client):
    response = client.get(EXPORT_URL, {"schedule": "1"}, follow=True)
    assert response.redirect_chain[-1][0].endswith(VIEWER_URL)
    assert "There are no schedules yet." in response.content.decode()


@pytest.mark.parametrize("value", ["9", "0", "abc", ""])
def test_bad_schedule_number_explains_the_range(client, value):
    load(client, "A", "B", "C")
    response = client.get(EXPORT_URL, {"schedule": value}, follow=True)
    assert response.redirect_chain[-1][0].endswith(VIEWER_URL)
    assert "Choose a schedule from 1 to 3 to export." in response.content.decode()
