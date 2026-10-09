"""
Tests for clearing schedules in the Schedule Viewer (Sprint 2 Section 15
"clear or replace the currently available schedule results"; user stories
32, 54 and 57).

Story 54: "When I click Clear Schedules, I'm asked to confirm before they
are removed." Story 57: "Given no schedules exist, the export and clear
buttons are disabled."
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from app import schedule_io
from app.schedule_io import Assignment, MeetingTime
from app.session import Session
from gui.controllers import schedule_controller as ctrl
from gui.controllers.errors import ControllerError

VIEWER_URL = "/schedules/"
IMPORT_URL = "/schedules/import/"
CLEAR_URL = "/schedules/clear/"


def page(response) -> str:
    return response.content.decode()


def schedule(faculty):
    return [Assignment("CMSC 140.01", faculty, "Roddy 136", None, (MeetingTime("MON", "09:00", "09:50", 50),))]


def load(client, *faculty):
    raw = schedule_io.schedules_to_json([schedule(name) for name in faculty]).encode("utf-8")
    upload = SimpleUploadedFile("fall.json", raw, content_type="application/json")
    return client.post(IMPORT_URL, {"schedule_file": upload}, follow=True)


# ---------------------------------------------------------------------- #
#  Controller
# ---------------------------------------------------------------------- #
@pytest.fixture
def session(monkeypatch):
    fresh = Session()
    monkeypatch.setattr(ctrl, "get_session", lambda request: fresh)
    return fresh


class TestClearSchedules:
    def test_removes_every_schedule_and_reports_how_many(self, session):
        session.schedules = [schedule("A"), schedule("B"), schedule("C")]
        assert ctrl.clear_schedules(None) == 3
        assert session.schedules == []
        assert ctrl.schedule_count(None) == 0

    def test_nothing_to_clear(self, session):
        with pytest.raises(ControllerError) as info:
            ctrl.clear_schedules(None)
        assert info.value.message == ctrl.NO_SCHEDULES_MESSAGE

    def test_configuration_is_not_touched(self, session):
        session.load("app/examples/config_example.json")
        config = session.config
        session.schedules = [schedule("A")]
        ctrl.clear_schedules(None)
        assert session.config is config


# ---------------------------------------------------------------------- #
#  Viewer button (story 57)
# ---------------------------------------------------------------------- #
def test_clear_button_is_disabled_when_there_are_no_schedules(client):
    html = page(client.get(VIEWER_URL))
    assert "Nothing to clear yet." in html
    assert 'disabled aria-describedby="clear-unavailable">Clear schedules</button>' in html
    assert f'href="{CLEAR_URL}"' not in html


def test_clear_button_links_to_the_confirmation_when_schedules_exist(client):
    load(client, "A", "B")
    html = page(client.get(VIEWER_URL))
    assert f'<a class="btn btn-danger" href="{CLEAR_URL}">Clear schedules</a>' in html
    assert "clear-unavailable" not in html


# ---------------------------------------------------------------------- #
#  Confirmation (story 54)
# ---------------------------------------------------------------------- #
def test_clicking_clear_asks_for_confirmation_first(client):
    load(client, "A", "B", "C")
    response = client.get(CLEAR_URL)
    html = page(response)
    assert response.status_code == 200
    assert "Remove all <strong>3</strong> schedules from the viewer?" in html
    assert "This cannot be undone." in html
    assert 'name="action" value="confirm"' in html and 'name="action" value="cancel"' in html
    assert "<strong>3</strong> schedules available." in page(client.get(VIEWER_URL))  # nothing removed yet


def test_cancel_keeps_the_schedules(client):
    load(client, "A", "B", "C")
    response = client.post(CLEAR_URL, {"action": "cancel"}, follow=True)
    html = page(response)
    assert response.redirect_chain[-1][0].endswith(VIEWER_URL)
    assert "Cancelled. Your 3 schedules were kept." in html
    assert "<strong>3</strong> schedules available." in html


def test_confirm_clears_the_schedules(client):
    load(client, "A", "B", "C")
    response = client.post(CLEAR_URL, {"action": "confirm"}, follow=True)
    html = page(response)
    assert response.redirect_chain[-1][0].endswith(VIEWER_URL)
    assert "Cleared 3 schedules." in html
    assert "No schedules yet" in html
    assert "Nothing to clear yet." in html  # and the button is disabled again


def test_a_post_without_confirm_does_not_clear(client):
    load(client, "A")
    client.post(CLEAR_URL, {})
    assert "<strong>1</strong> schedule available." in page(client.get(VIEWER_URL))


def test_one_schedule_uses_singular_wording(client):
    load(client, "A")
    assert "Remove all <strong>1</strong> schedule from the viewer?" in page(client.get(CLEAR_URL))
    assert "Cleared 1 schedule." in page(client.post(CLEAR_URL, {"action": "confirm"}, follow=True))


@pytest.mark.parametrize("method", ["get", "post"])
def test_nothing_to_clear_goes_back_to_the_viewer(client, method):
    response = getattr(client, method)(CLEAR_URL, {"action": "confirm"}, follow=True)
    assert response.redirect_chain[-1][0].endswith(VIEWER_URL)
    assert "There are no schedules to clear." in page(response)


def test_clearing_keeps_the_configuration(client):
    load(client, "A")
    client.post(CLEAR_URL, {"action": "confirm"})
    assert "none loaded" not in page(client.get("/"))  # the config status in the nav is unchanged
