"""
Tests for the Configuration Editor lifecycle actions (Sprint 2 Sections 8, 9,
10, 19, 23.2 and 23.6): New / Load / Save / Validate, the unsaved-changes
confirmation, and "a failed action leaves the current configuration alone".

Same approach as tests/test_gui_timeslots.py: everything runs against the REAL
scheduler library and the shipped example configuration. The controller is
tested directly first (independent of Django's request cycle), then the pages.
"""

import json
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from app.session import Session
from gui import session_store
from gui.controllers import config_controller as ctrl
from gui.controllers.errors import ControllerError

EXAMPLE = "app/examples/config_example.json"

EDITOR_URL = "/configuration/"
NEW_URL = "/configuration/new/"
LOAD_URL = "/configuration/load/"
SAVE_URL = "/configuration/save/"
VALIDATE_URL = "/configuration/validate/"


def example_bytes() -> bytes:
    return Path(EXAMPLE).read_bytes()


def upload(raw: bytes, name: str = "fall.json") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, raw, content_type="application/json")


def message_of(error: ControllerError) -> str:
    return error.message


# ---------------------------------------------------------------------- #
#  Controller (called directly, independent of Django's request cycle)
# ---------------------------------------------------------------------- #
@pytest.fixture
def session(monkeypatch):
    """A Session holding the example config, handed to the controller in place
    of the per-browser lookup."""
    loaded = Session()
    loaded.load(EXAMPLE)
    monkeypatch.setattr(ctrl, "get_session", lambda request: loaded)
    return loaded


@pytest.fixture
def empty_session(monkeypatch):
    empty = Session()
    monkeypatch.setattr(ctrl, "get_session", lambda request: empty)
    return empty


class TestLoad:
    def test_loads_a_valid_file_and_records_its_name(self, empty_session):
        name = ctrl.load_configuration(None, upload(example_bytes()))
        assert name == "fall.json"
        assert empty_session.config is not None
        assert empty_session.config_name == "fall.json"
        assert empty_session.dirty is False

    def test_load_replaces_unsaved_state_and_clears_schedules(self, session):
        session.dirty = True
        session.schedules = ["old schedule"]
        ctrl.load_configuration(None, upload(example_bytes()))
        assert session.dirty is False
        assert session.schedules == []

    def test_invalid_json_is_rejected_and_the_current_config_kept(self, session):
        before = session.config
        with pytest.raises(ControllerError) as info:
            ctrl.load_configuration(None, upload(b"{not json"))
        assert "not valid JSON" in message_of(info.value)
        assert "current configuration was kept" in message_of(info.value)
        assert session.config is before

    def test_json_that_is_not_an_object_is_rejected(self, session):
        before = session.config
        with pytest.raises(ControllerError) as info:
            ctrl.load_configuration(None, upload(b"[1, 2, 3]"))
        assert "JSON object" in message_of(info.value)
        assert session.config is before

    def test_a_file_that_fails_validation_is_rejected_and_the_current_config_kept(self, session):
        data = json.loads(example_bytes())
        data["config"]["rooms"] = []
        before = session.config
        with pytest.raises(ControllerError) as info:
            ctrl.load_configuration(None, upload(json.dumps(data).encode()))
        assert "not a valid configuration" in message_of(info.value)
        assert "current configuration was kept" in message_of(info.value)
        assert session.config is before

    def test_an_empty_file_is_rejected(self, session):
        before = session.config
        with pytest.raises(ControllerError) as info:
            ctrl.load_configuration(None, upload(b"   "))
        assert "empty" in message_of(info.value)
        assert session.config is before

    def test_no_file_is_rejected(self, session):
        with pytest.raises(ControllerError):
            ctrl.load_configuration(None, None)


class TestNew:
    def test_starts_a_fresh_configuration(self, session):
        session.dirty = True
        session.schedules = ["old schedule"]
        ctrl.new_configuration(None)
        assert session.config is not None
        assert session.config_name is None
        assert session.dirty is False
        assert session.schedules == []


class TestSave:
    def test_returns_json_named_after_the_loaded_file_and_clears_the_flag(self, session):
        session.config_name = "fall.json"
        session.dirty = True
        filename, content = ctrl.save_configuration(None)
        assert filename == "fall.json"
        assert "config" in json.loads(content)
        assert session.dirty is False

    def test_uses_a_default_name_when_the_config_has_none(self, empty_session):
        empty_session.new_config()
        filename, _ = ctrl.save_configuration(None)
        assert filename == "scheduler_config.json"

    def test_download_names_are_made_safe(self, session):
        session.config_name = 'my "config" ../v2'
        filename, _ = ctrl.save_configuration(None)
        assert filename.endswith(".json")
        assert '"' not in filename and "/" not in filename

    def test_a_saved_file_loads_back_unchanged(self, session):
        _, content = ctrl.save_configuration(None)
        other = Session()
        other.load_bytes(content.encode("utf-8"), "round-trip.json")
        assert other.dumps() == content

    def test_without_a_configuration_it_explains_what_to_do(self, empty_session):
        with pytest.raises(ControllerError) as info:
            ctrl.save_configuration(None)
        assert "No configuration is loaded" in message_of(info.value)


class TestValidate:
    def test_a_valid_configuration_has_no_problems(self, session):
        assert ctrl.validate_configuration(None) == []

    def test_an_invalid_configuration_lists_plain_language_problems(self, session):
        session.config.config.rooms.clear()  # bypasses edit mode on purpose
        problems = ctrl.validate_configuration(None)
        assert problems
        assert all("Traceback" not in problem for problem in problems)

    def test_without_a_configuration_it_explains_what_to_do(self, empty_session):
        with pytest.raises(ControllerError) as info:
            ctrl.validate_configuration(None)
        assert "No configuration is loaded" in message_of(info.value)


class TestDescribe:
    def test_nothing_loaded(self, empty_session):
        state = ctrl.describe_configuration(None)
        assert state["has_config"] is False
        assert state["counts"] == {}
        assert state["discard_note"] == ""

    def test_counts_match_the_loaded_configuration(self, session):
        state = ctrl.describe_configuration(None)
        assert state["has_config"] is True
        assert state["counts"]["rooms"] == len(session.config.config.rooms)
        assert state["counts"]["courses"] == len(session.config.config.courses)
        assert state["counts"]["faculty"] == len(session.config.config.faculty)
        assert state["counts"]["time_blocks"] > 0

    def test_discard_note_names_everything_that_would_be_lost(self, session):
        session.dirty = True
        session.schedules = ["a", "b"]
        note = ctrl.describe_configuration(None)["discard_note"]
        assert note == "your unsaved changes and the 2 schedules loaded now"


# ---------------------------------------------------------------------- #
#  Pages (Django test client)
# ---------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


def browser_session():
    """The single Session the current test client created."""
    return next(iter(session_store._SESSIONS.values()))


def page(response):
    return response.content.decode()


def test_editor_page_shows_the_actions_and_every_area(client):
    response = client.get(EDITOR_URL)
    assert response.status_code == 200
    text = page(response)
    for label in ("Save configuration", "Validate configuration", "Start new configuration", "Load configuration"):
        assert label in text
    for area in ("Time Slots", "Rooms", "Labs", "Courses", "Faculty", "Class Patterns", "Meetings", "Global Settings"):
        assert area in text


def test_editor_page_shows_the_empty_state_when_nothing_is_loaded(client, monkeypatch):
    monkeypatch.setattr(session_store, "AUTO_LOAD_EXAMPLE", False)
    response = client.get(EDITOR_URL)
    assert response.status_code == 200
    assert "No configuration loaded" in page(response)


def test_loading_a_valid_file_confirms_and_replaces_the_configuration(client):
    client.get(EDITOR_URL)
    response = client.post(LOAD_URL, {"load-config_file": upload(example_bytes())}, follow=True)
    assert "Loaded and validated fall.json" in page(response)
    assert browser_session().config_name == "fall.json"


def test_loading_over_unsaved_changes_needs_confirmation(client):
    client.get(EDITOR_URL)
    before = browser_session().config
    browser_session().dirty = True

    refused = client.post(LOAD_URL, {"load-config_file": upload(example_bytes())})
    assert refused.status_code == 200
    assert "Tick this box to confirm discarding your unsaved changes" in page(refused)
    assert browser_session().config is before
    assert browser_session().dirty is True

    accepted = client.post(
        LOAD_URL, {"load-config_file": upload(example_bytes()), "load-confirm_replace": "on"}, follow=True
    )
    assert "Loaded and validated fall.json" in page(accepted)
    assert browser_session().dirty is False


def test_loading_a_bad_file_shows_the_problem_and_keeps_the_configuration(client):
    client.get(EDITOR_URL)
    before = browser_session().config
    response = client.post(LOAD_URL, {"load-config_file": upload(b"{oops")})
    assert response.status_code == 200
    text = page(response)
    assert "not valid JSON" in text
    assert "current configuration was kept" in text
    assert browser_session().config is before


def test_starting_a_new_configuration_over_unsaved_changes_needs_confirmation(client):
    client.get(EDITOR_URL)
    browser_session().dirty = True

    refused = client.post(NEW_URL, {})
    assert refused.status_code == 200
    assert "Tick this box to confirm discarding your unsaved changes" in page(refused)
    assert browser_session().dirty is True

    accepted = client.post(NEW_URL, {"new-confirm_replace": "on"}, follow=True)
    assert "Started a new configuration" in page(accepted)
    assert browser_session().dirty is False
    assert browser_session().config_name is None


def test_starting_a_new_configuration_with_nothing_to_lose_needs_no_confirmation(client):
    client.get(EDITOR_URL)
    response = client.post(NEW_URL, {}, follow=True)
    assert "Started a new configuration" in page(response)


def test_save_downloads_the_configuration_and_clears_the_unsaved_flag(client):
    client.get(EDITOR_URL)
    browser_session().dirty = True
    response = client.post(SAVE_URL)
    assert response.status_code == 200
    assert "attachment" in response["Content-Disposition"]
    assert ".json" in response["Content-Disposition"]
    assert "config" in json.loads(response.content)
    assert browser_session().dirty is False


def test_save_is_post_only(client):
    response = client.get(SAVE_URL)
    assert response.status_code == 302


def test_save_without_a_configuration_explains_what_to_do(client, monkeypatch):
    monkeypatch.setattr(session_store, "AUTO_LOAD_EXAMPLE", False)
    response = client.post(SAVE_URL, follow=True)
    assert "No configuration is loaded" in page(response)


def test_validate_reports_a_valid_configuration(client):
    response = client.post(VALIDATE_URL, follow=True)
    assert "Configuration is valid" in page(response)


def test_validate_reports_problems_without_changing_anything(client):
    client.get(EDITOR_URL)
    browser_session().config.config.rooms.clear()  # bypasses edit mode on purpose
    response = client.post(VALIDATE_URL)
    assert response.status_code == 200
    assert "The configuration has problems" in page(response)
