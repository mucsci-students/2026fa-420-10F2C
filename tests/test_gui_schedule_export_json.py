"""
Tests for exporting schedules from the Schedule Viewer (Sprint 2
Sections 18, 19, 23.4, 23.6): one schedule or the whole set, as JSON or
CSV. Covers gui/controllers/schedule_controller.export_schedule_json /
export_schedule_csv / export_schedules, the ScheduleExportForm, and the
/schedules/export/ download.

The JSON and CSV formats themselves are covered in tests/test_schedule_io.py;
these tests cover choosing what to export, the download, the "nothing to
export" states, and that a JSON export can be loaded back in (round trip).
"""

import csv
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
EXPORT_URL = "/schedules/export/"
OLD_JSON_EXPORT_URL = "/schedules/export/json/"


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


def csv_rows(content):
    return list(csv.DictReader(io.StringIO(content)))


class TestExportScheduleCsv:
    def test_exports_only_the_selected_schedule(self, session):
        session.schedules = [schedule("A"), schedule("B"), schedule("C")]
        export = ctrl.export_schedule_csv(None, 2)

        assert export.filename == "schedule-3.csv"
        assert export.content_type == "text/csv; charset=utf-8"
        assert export.schedule_count == 1
        rows = csv_rows(export.content)
        assert [(r["schedule"], r["faculty"]) for r in rows] == [("3", "C")]  # keeps the viewer's number
        assert rows[0]["day"] == "MON" and rows[0]["start"] == "09:00" and rows[0]["end"] == "09:50"

    def test_index_none_exports_every_schedule(self, session):
        session.schedules = [schedule("A"), schedule("B"), schedule("C")]
        export = ctrl.export_schedule_csv(None)

        assert export.filename == "schedules-all-3.csv"
        assert export.schedule_count == 3
        rows = csv_rows(export.content)
        assert [(r["schedule"], r["faculty"]) for r in rows] == [("1", "A"), ("2", "B"), ("3", "C")]

    def test_header_matches_the_documented_columns(self, session):
        session.schedules = [schedule("A")]
        header = ctrl.export_schedule_csv(None, 0).content.splitlines()[0]
        assert header.split(",") == list(schedule_io.CSV_COLUMNS)

    def test_no_schedules(self, session):
        with pytest.raises(ControllerError) as info:
            ctrl.export_schedule_csv(None)
        assert info.value.message == ctrl.NO_SCHEDULES_MESSAGE

    def test_export_changes_nothing(self, session):
        stored = [schedule("A")]
        session.schedules = stored
        ctrl.export_schedule_csv(None)
        assert session.schedules is stored and session.dirty is False


class TestExportSchedules:
    @pytest.mark.parametrize("file_format, filename", [("json", "schedule-1.json"), ("csv", "schedule-1.csv")])
    def test_picks_the_writer_for_the_format(self, session, file_format, filename):
        session.schedules = [schedule("A")]
        assert ctrl.export_schedules(None, 0, file_format).filename == filename

    def test_unknown_format(self, session):
        session.schedules = [schedule("A")]
        with pytest.raises(ControllerError) as info:
            ctrl.export_schedules(None, 0, "xml")
        assert "Choose JSON or CSV" in info.value.message


# ---------------------------------------------------------------------- #
#  Pages (Django test client)
# ---------------------------------------------------------------------- #
def load(client, *faculty):
    raw = schedule_io.schedules_to_json([schedule(name) for name in faculty]).encode("utf-8")
    upload = SimpleUploadedFile("fall.json", raw, content_type="application/json")
    return client.post(IMPORT_URL, {"schedule_file": upload}, follow=True)


@pytest.mark.parametrize(
    "label",
    ["Export This Schedule (JSON)", "Export This Schedule (CSV)",
     "Export All Schedules (JSON)", "Export All Schedules (CSV)"],
)
def test_export_buttons_are_disabled_when_there_are_no_schedules(client, label):
    html = client.get(VIEWER_URL).content.decode()
    assert "Nothing to export yet" in html
    assert f'disabled aria-describedby="export-unavailable">{label}</button>' in html
    assert 'name="schedule"' not in html


def test_viewer_lists_every_schedule_to_export(client):
    load(client, "A", "B", "C")
    html = client.get(VIEWER_URL).content.decode()
    assert 'action="/schedules/export/"' in html
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


# ---------------------------------------------------------------------- #
#  Whole set and CSV (Section 18: "the complete available schedule set";
#  Sprint 1 CSV export stays available)
# ---------------------------------------------------------------------- #
def test_viewer_has_this_schedule_and_all_schedules_buttons(client):
    load(client, "A", "B", "C")
    html = client.get(VIEWER_URL).content.decode()
    assert 'name="file_format" value="json" class="btn btn-primary">Export This Schedule (JSON)</button>' in html
    assert 'name="file_format" value="csv" class="btn">Export This Schedule (CSV)</button>' in html
    assert '<input type="hidden" name="schedule" value="all">' in html
    assert ">Export All Schedules (JSON)</button>" in html
    assert ">Export All Schedules (CSV)</button>" in html
    assert '<option value="all"' not in html  # "all" has its own buttons, not a list entry


def test_all_schedules_works_with_a_single_schedule(client):
    load(client, "A")
    response = client.get(EXPORT_URL, {"schedule": "all", "file_format": "json"})
    assert response["Content-Disposition"] == 'attachment; filename="schedules-all-1.json"'


def test_download_all_as_json_loads_back_every_schedule(client):
    """User story 43: export all 5 schedules to one file, load it later, see the same 5."""
    names = ["A", "B", "C", "D", "E"]
    load(client, *names)
    response = client.get(EXPORT_URL, {"schedule": "all", "file_format": "json"})

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json; charset=utf-8"
    assert response["Content-Disposition"] == 'attachment; filename="schedules-all-5.json"'
    data = json.loads(response.content.decode("utf-8"))
    assert data["schedule_count"] == 5
    assert [s[0]["faculty"] for s in data["schedules"]] == names

    later = type(client)()  # a later session in a fresh browser
    upload = SimpleUploadedFile("schedules-all-5.json", response.content, content_type="application/json")
    html = later.post(IMPORT_URL, {"schedule_file": upload}, follow=True).content.decode()
    assert "Loaded 5 schedules from schedules-all-5.json." in html
    assert "<strong>5</strong> schedules available." in html
    reexported = json.loads(later.get(EXPORT_URL, {"schedule": "all"}).content.decode("utf-8"))
    assert reexported["schedules"] == data["schedules"]  # the same 5 schedules


def test_download_one_as_csv(client):
    load(client, "A", "B", "C")
    response = client.get(EXPORT_URL, {"schedule": "2", "file_format": "csv"})

    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv; charset=utf-8"
    assert response["Content-Disposition"] == 'attachment; filename="schedule-2.csv"'
    rows = csv_rows(response.content.decode("utf-8"))
    assert [(r["schedule"], r["faculty"]) for r in rows] == [("2", "B")]


def test_download_all_as_csv(client):
    load(client, "A", "B", "C")
    response = client.get(EXPORT_URL, {"schedule": "all", "file_format": "csv"})

    assert response["Content-Disposition"] == 'attachment; filename="schedules-all-3.csv"'
    rows = csv_rows(response.content.decode("utf-8"))
    assert [r["faculty"] for r in rows] == ["A", "B", "C"]


def test_format_defaults_to_json(client):
    load(client, "A", "B")
    response = client.get(EXPORT_URL, {"schedule": "1"})
    assert response["Content-Disposition"] == 'attachment; filename="schedule-1.json"'


def test_older_json_export_url_still_works(client):
    load(client, "A", "B")
    response = client.get(OLD_JSON_EXPORT_URL, {"schedule": "2"})
    assert response["Content-Disposition"] == 'attachment; filename="schedule-2.json"'


def test_unknown_format_explains_the_choices(client):
    load(client, "A", "B")
    response = client.get(EXPORT_URL, {"schedule": "1", "file_format": "xml"}, follow=True)
    assert response.redirect_chain[-1][0].endswith(VIEWER_URL)
    assert "Choose JSON or CSV as the export format." in response.content.decode()
