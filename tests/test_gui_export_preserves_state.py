"""
Exporting changes nothing (Sprint 4 Section 5.4, issue #170, user story 6).

Story 6: with a saved configuration loaded (no unsaved changes), 3 schedules,
and schedule 2 of 3 open in the Faculty view, exporting a PDF, JSON or CSV
leaves everything as it was: the configuration and its "no unsaved changes"
state, the undo history, the schedules, and the viewer's schedule and view.

These tests drive the application through the Django test client the way a
user does (load a configuration file, import schedules, open the viewer, click
Export), then compare the session and the pages before and after. Successful
exports, failed ones, and exports of every format are all covered.
"""

import json
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from app import schedule_io
from app.schedule_io import Assignment, MeetingTime
from gui import session_store, views

EXAMPLE_CONFIG = Path("app/examples/config_example.json")

LOAD_CONFIG_URL = "/configuration/load/"
EDITOR_URL = "/configuration/"
VIEWER_URL = "/schedules/"
IMPORT_URL = "/schedules/import/"
EXPORT_URL = "/schedules/export/"
PDF_URL = "/schedules/export/pdf/"

FACULTY = ["Hogg", "Hardy", "Yang"]  # who teaches CMSC 140.01 in schedules 1, 2, 3


def schedule(faculty: str) -> list[Assignment]:
    return [
        Assignment(
            "CMSC 140.01",
            faculty,
            "Roddy 136",
            None,
            (
                MeetingTime("MON", "09:00", "09:50", 50),
                MeetingTime("WED", "09:00", "09:50", 50),
            ),
        ),
        Assignment(
            "CMSC 162.01",
            "Killen",
            "Roddy 140",
            "Linux",
            (
                MeetingTime("TUE", "10:00", "10:50", 50),
                MeetingTime("THU", "13:00", "14:50", 110, lab=True),
            ),
        ),
    ]


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


def browser_session():
    """The one Session the test client's browser created."""
    return next(iter(session_store._SESSIONS.values()))


def upload(name: str, raw: bytes, content_type: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, raw, content_type=content_type)


@pytest.fixture
def story(client):
    """Story 6's starting point: the example configuration loaded from a file
    (so there are no unsaved changes) and 3 schedules imported."""
    loaded = client.post(
        LOAD_CONFIG_URL,
        {
            "load-config_file": upload(
                "fall.json", EXAMPLE_CONFIG.read_bytes(), "application/json"
            )
        },
        follow=True,
    )
    assert loaded.status_code == 200
    raw = schedule_io.schedules_to_json([schedule(name) for name in FACULTY])
    imported = client.post(
        IMPORT_URL,
        {"schedule_file": upload("three.json", raw.encode(), "application/json")},
        follow=True,
    )
    assert "Loaded 3 schedules" in imported.content.decode()
    session = browser_session()
    assert session.config is not None
    assert session.dirty is False
    return client


def snapshot(client) -> dict:
    """Everything an export must leave alone, read from the session itself."""
    session = browser_session()
    return {
        "config": session.config.model_dump_json() if session.config else None,
        "config_name": session.config_name,
        "dirty": session.dirty,
        "can_undo": session.history.can_undo,
        "can_redo": session.history.can_redo,
        "schedules_version": session.schedules_version,
        "schedules": client.get(EXPORT_URL, {"schedule": "all"}).content,
    }


def viewer(client, query: str = "schedule=2&view=faculty") -> str:
    return client.get(f"{VIEWER_URL}?{query}").content.decode()


def faculty_view_is_active(page: str) -> bool:
    return 'aria-current="true">Faculty</a>' in page


# ---------------------------------------------------------------------- #
#  Story 6, scenario 1: exporting leaves the configuration and schedules
# ---------------------------------------------------------------------- #
class TestPdfExportChangesNothing:
    def test_a_pdf_export_of_schedule_2_changes_nothing(self, story):
        page_before = viewer(story)
        assert "Schedule 2 of 3" in page_before
        assert faculty_view_is_active(page_before)
        before = snapshot(story)

        response = story.get(
            PDF_URL, {"schedule": "2", "what": "rooms", "view": "faculty"}
        )

        assert response["Content-Type"] == "application/pdf"
        assert response.content.startswith(b"%PDF-")
        assert snapshot(story) == before
        assert browser_session().dirty is False

    def test_the_editor_still_says_no_unsaved_changes(self, story):
        story.get(PDF_URL, {"schedule": "2", "what": "rooms"})
        page = story.get(EDITOR_URL).content.decode()
        assert "No unsaved changes." in page
        assert "<strong>Unsaved changes.</strong>" not in page

    def test_the_configuration_editor_shows_the_same_configuration(self, story):
        before = browser_session().config_name, snapshot(story)["config"]
        story.get(PDF_URL, {"schedule": "2", "what": "faculty"})
        page = story.get(EDITOR_URL).content.decode()
        assert (browser_session().config_name, snapshot(story)["config"]) == before
        assert "No unsaved changes." in page

    def test_the_viewer_still_shows_schedule_2_in_the_faculty_view(self, story):
        story.get(PDF_URL, {"schedule": "2", "what": "rooms", "view": "faculty"})
        after = viewer(story)
        assert "Schedule 2 of 3" in after
        assert faculty_view_is_active(after)
        assert "Hardy" in after  # schedule 2's instructor for CMSC 140.01

    def test_exporting_every_schedule_in_both_orientations_changes_nothing(self, story):
        before = snapshot(story)
        for number in ("1", "2", "3"):
            for what in ("rooms", "faculty", "faculty:faculty:Killen"):
                response = story.get(PDF_URL, {"schedule": number, "what": what})
                assert response["Content-Type"] == "application/pdf"
        assert snapshot(story) == before


# ---------------------------------------------------------------------- #
#  A failed export changes nothing and returns to the same place
# ---------------------------------------------------------------------- #
class TestFailedPdfExport:
    def test_a_bad_choice_goes_back_to_the_same_schedule_and_view(self, story):
        before = snapshot(story)
        response = story.get(
            PDF_URL,
            {"schedule": "2", "what": "faculty:faculty:Nobody", "view": "faculty"},
            follow=True,
        )
        url, status = response.redirect_chain[-1]
        assert (url, status) == (
            "/schedules/?schedule=2&view=faculty#export-pdf",
            302,
        )
        page = response.content.decode()
        assert "Schedule 2 of 3" in page
        assert faculty_view_is_active(page)
        assert snapshot(story) == before

    def test_picked_faculty_members_are_kept_too(self, story):
        response = story.get(
            PDF_URL,
            {
                "schedule": "2",
                "what": "nonsense",
                "view": "faculty",
                "resource": ["Hardy", "Killen"],
            },
            follow=True,
        )
        url, _ = response.redirect_chain[-1]
        assert url == (
            "/schedules/?schedule=2&view=faculty"
            "&resource=Hardy&resource=Killen#export-pdf"
        )

    def test_an_unknown_view_is_left_out_of_the_way_back(self, story):
        response = story.get(
            PDF_URL,
            {"schedule": "2", "what": "nonsense", "view": "sideways"},
            follow=True,
        )
        url, _ = response.redirect_chain[-1]
        assert url == "/schedules/?schedule=2#export-pdf"

    def test_a_drawing_failure_changes_nothing(self, story, monkeypatch):
        def broken(schedule_export, title, time_format="24h"):
            raise RuntimeError("out of paper")

        monkeypatch.setattr(views, "render_pdf", broken)
        before = snapshot(story)
        response = story.get(
            PDF_URL,
            {"schedule": "2", "what": "rooms", "view": "faculty"},
            follow=True,
        )
        page = response.content.decode()
        assert "The PDF could not be created." in page
        assert "Schedule 2 of 3" in page
        assert faculty_view_is_active(page)
        assert snapshot(story) == before

    def test_a_schedule_that_does_not_exist_changes_nothing(self, story):
        before = snapshot(story)
        response = story.get(PDF_URL, {"schedule": "9", "what": "rooms"}, follow=True)
        assert "Choose a schedule from 1 to 3 to export." in response.content.decode()
        assert snapshot(story) == before


# ---------------------------------------------------------------------- #
#  The viewer's PDF form carries the view, so the way back can keep it
# ---------------------------------------------------------------------- #
class TestPdfFormCarriesTheView:
    def test_the_form_sends_the_view_being_shown(self, story):
        page = viewer(story, "schedule=2&view=faculty")
        form = page[page.index('id="export-pdf"') :]
        assert 'name="schedule" value="2"' in form
        assert 'name="view" value="faculty"' in form

    def test_the_form_sends_the_picked_faculty_members(self, story):
        page = viewer(story, "schedule=2&view=faculty&resource=Hardy&resource=Killen")
        form = page[page.index('id="export-pdf"') :]
        assert 'name="resource" value="Hardy"' in form
        assert 'name="resource" value="Killen"' in form


# ---------------------------------------------------------------------- #
#  Story 6, scenario 2: JSON and CSV export still work
# ---------------------------------------------------------------------- #
class TestJsonAndCsvStillWork:
    def test_json_export_contains_schedule_1(self, story):
        response = story.get(EXPORT_URL, {"schedule": "1", "file_format": "json"})
        assert response["Content-Type"].startswith("application/json")
        exported = schedule_io.parse_schedule_file(response.content)
        loaded_back = schedule_io.parse_schedule_file(
            schedule_io.schedules_to_json([schedule("Hogg")]).encode("utf-8")
        )
        assert exported == loaded_back

    def test_csv_export_contains_schedule_1_only(self, story):
        response = story.get(EXPORT_URL, {"schedule": "1", "file_format": "csv"})
        assert response["Content-Type"].startswith("text/csv")
        text = response.content.decode()
        assert "CMSC 140" in text and "Hogg" in text
        assert "Hardy" not in text and "Yang" not in text  # schedules 2 and 3

    def test_json_and_csv_exports_change_nothing(self, story):
        before = snapshot(story)
        for file_format in ("json", "csv"):
            for number in ("1", "2", "3", "all"):
                story.get(EXPORT_URL, {"schedule": number, "file_format": file_format})
        assert snapshot(story) == before
        assert "No unsaved changes." in story.get(EDITOR_URL).content.decode()

    def test_the_json_export_is_still_valid_json(self, story):
        response = story.get(EXPORT_URL, {"schedule": "2", "file_format": "json"})
        json.loads(response.content)
