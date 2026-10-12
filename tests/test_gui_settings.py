"""
Tests for the Global Settings feature: controller behavior
(gui/controllers/settings.py) and the page/form built on it
(gui/views_settings.py, gui/forms.py).

Covers user stories 28-30 (set / change / reset the generation limit, enable and
disable optimizer flags, reject a non-positive limit and an unknown flag) and
Sprint 2 Sections 10, 11 and 19: valid changes apply, invalid ones are rejected
with a clear message, and a failed edit leaves the previous valid configuration
untouched.

Everything runs against the REAL scheduler library and the shipped example
configuration, which has:
    limit = 100
    optimizer flags ON:  faculty_course, faculty_room, faculty_lab,
                         same_room, same_lab, pack_rooms
    optimizer flag OFF:  pack_labs
"""

import pytest

from app.session import Session
from gui import session_store
from gui.controllers import settings as ctrl
from gui.controllers.errors import ControllerError

EXAMPLE = "app/examples/config_example.json"

PAGE_URL = "/configuration/settings/"
SAVE_URL = "/configuration/settings/save/"
RESET_URL = "/configuration/settings/reset-limit/"

EXAMPLE_FLAGS = ["faculty_course", "faculty_room", "faculty_lab", "same_room", "same_lab", "pack_rooms"]


def flag_names(session):
    return [str(getattr(flag, "value", flag)) for flag in session.config.optimizer_flags]


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
    blank = Session()
    monkeypatch.setattr(ctrl, "get_session", lambda request: blank)
    return blank


class TestGenerationLimit:
    def test_sets_the_limit_and_marks_the_session_dirty(self, session):
        assert ctrl.set_generation_limit(None, 50) == ["Generation limit set to 50."]
        assert session.config.limit == 50
        assert session.dirty is True

    def test_setting_the_same_limit_changes_nothing(self, session):
        assert ctrl.set_generation_limit(None, 100) == []
        assert session.dirty is False

    @pytest.mark.parametrize("value", [0, -10, None, "5", True])
    def test_a_non_positive_or_non_integer_limit_is_rejected(self, session, value):
        with pytest.raises(ControllerError) as info:
            ctrl.set_generation_limit(None, value)
        assert "Generation limit needs to be positive." in info.value.message
        assert {item.field for item in info.value.errors} == {"limit"}
        assert session.config.limit == 100
        assert session.dirty is False

    def test_reset_restores_the_default(self, session):
        ctrl.set_generation_limit(None, 25)
        assert ctrl.reset_generation_limit(None) == ["Generation limit reset to default (10)."]
        assert session.config.limit == 10

    def test_reset_when_already_default_changes_nothing(self, session):
        ctrl.reset_generation_limit(None)
        session.dirty = False
        assert ctrl.reset_generation_limit(None) == []
        assert session.dirty is False


class TestOptimizerFlags:
    def test_enables_a_flag_and_keeps_the_others(self, session):
        assert ctrl.enable_optimizer_flag(None, "pack_labs") == ["Optimizer flag 'pack_labs' added."]
        assert sorted(flag_names(session)) == sorted(EXAMPLE_FLAGS + ["pack_labs"])
        assert session.dirty is True

    def test_disables_a_flag_and_keeps_the_others(self, session):
        assert ctrl.disable_optimizer_flag(None, "same_room") == ["Optimizer flag 'same_room' removed."]
        assert "same_room" not in flag_names(session)
        assert sorted(flag_names(session)) == sorted(f for f in EXAMPLE_FLAGS if f != "same_room")

    def test_enabling_an_enabled_flag_or_disabling_a_disabled_one_changes_nothing(self, session):
        assert ctrl.enable_optimizer_flag(None, "same_room") == []
        assert ctrl.disable_optimizer_flag(None, "pack_labs") == []
        assert session.dirty is False
        assert sorted(flag_names(session)) == sorted(EXAMPLE_FLAGS)

    @pytest.mark.parametrize("call", [ctrl.enable_optimizer_flag, ctrl.disable_optimizer_flag])
    def test_an_unknown_flag_is_rejected_and_nothing_changes(self, session, call):
        with pytest.raises(ControllerError) as info:
            call(None, "not_a_real_flag")
        assert "'not_a_real_flag' is not a valid optimizer flag." in info.value.message
        assert sorted(flag_names(session)) == sorted(EXAMPLE_FLAGS)
        assert session.dirty is False


class TestUpdateSettings:
    def test_changes_the_limit_and_flags_together(self, session):
        messages = ctrl.update_settings(
            None, {"limit": 40, "optimizer_flags": ["faculty_course", "faculty_room", "faculty_lab", "pack_labs"]}
        )
        assert "Generation limit set to 40." in messages
        assert "Optimizer flag 'pack_labs' added." in messages
        assert "Optimizer flag 'same_room' removed." in messages
        assert session.config.limit == 40
        assert sorted(flag_names(session)) == sorted(["faculty_course", "faculty_room", "faculty_lab", "pack_labs"])

    def test_submitting_the_current_values_changes_nothing(self, session):
        assert ctrl.update_settings(None, {"limit": 100, "optimizer_flags": EXAMPLE_FLAGS}) == []
        assert session.dirty is False

    def test_a_bad_limit_leaves_both_settings_untouched(self, session):
        with pytest.raises(ControllerError):
            ctrl.update_settings(None, {"limit": 0, "optimizer_flags": ["pack_labs"]})
        assert session.config.limit == 100
        assert sorted(flag_names(session)) == sorted(EXAMPLE_FLAGS)

    def test_an_unknown_flag_leaves_both_settings_untouched(self, session):
        with pytest.raises(ControllerError) as info:
            ctrl.update_settings(None, {"limit": 60, "optimizer_flags": ["nonsense"]})
        assert {item.field for item in info.value.errors} == {"optimizer_flags"}
        assert session.config.limit == 100
        assert sorted(flag_names(session)) == sorted(EXAMPLE_FLAGS)


class TestReads:
    def test_describe_reports_the_current_settings(self, session):
        data = ctrl.describe_settings(None)
        assert data["has_config"] is True
        assert data["limit"] == 100 and data["default_limit"] == 10
        assert data["is_default_limit"] is False
        assert sorted(data["enabled_flags"]) == sorted(EXAMPLE_FLAGS)
        flags = {item["name"]: item["enabled"] for item in data["flags"]}
        assert flags["pack_labs"] is False and flags["same_room"] is True

    def test_every_library_flag_is_offered(self):
        assert {"faculty_course", "same_room", "pack_labs"} <= set(ctrl.known_flags())

    def test_without_a_configuration(self, empty_session):
        assert ctrl.describe_settings(None) == {"has_config": False}
        with pytest.raises(ControllerError) as info:
            ctrl.set_generation_limit(None, 5)
        assert "No configuration is loaded" in info.value.message


# ---------------------------------------------------------------------- #
#  Page (Django test client)
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


def test_the_configuration_home_links_to_the_page(client):
    assert PAGE_URL in page(client.get("/configuration/"))


def test_the_page_shows_the_current_settings_and_a_form(client):
    response = client.get(PAGE_URL)
    text = page(response)
    assert response.status_code == 200
    assert "Generation limit" in text and "100" in text
    assert "same_room" in text and "pack_labs" in text
    assert "Save settings" in text


def test_saving_changes_applies_them_and_reports_each_one(client):
    client.get(PAGE_URL)
    response = client.post(
        SAVE_URL,
        {"limit": "50", "optimizer_flags": ["faculty_course", "faculty_room", "faculty_lab", "same_room", "same_lab", "pack_rooms", "pack_labs"]},
        follow=True,
    )
    text = page(response)
    assert "Generation limit set to 50." in text
    assert "Optimizer flag &#x27;pack_labs&#x27; added." in text
    assert "Unsaved changes" in text
    assert browser_session().config.limit == 50
    assert "pack_labs" in flag_names(browser_session())


def test_unticking_a_flag_removes_it(client):
    client.get(PAGE_URL)
    flags = [f for f in EXAMPLE_FLAGS if f != "same_room"]
    response = client.post(SAVE_URL, {"limit": "100", "optimizer_flags": flags}, follow=True)
    assert "Optimizer flag &#x27;same_room&#x27; removed." in page(response)
    assert "same_room" not in flag_names(browser_session())


def test_saving_without_changes_says_so(client):
    client.get(PAGE_URL)
    response = client.post(SAVE_URL, {"limit": "100", "optimizer_flags": EXAMPLE_FLAGS}, follow=True)
    assert "No changes to save." in page(response)
    assert browser_session().dirty is False


@pytest.mark.parametrize("limit", ["0", "-10", "abc", ""])
def test_a_bad_limit_is_reported_on_the_form_and_changes_nothing(client, limit):
    client.get(PAGE_URL)
    response = client.post(SAVE_URL, {"limit": limit, "optimizer_flags": EXAMPLE_FLAGS})
    assert response.status_code == 200
    assert "Error:" in page(response)
    assert browser_session().config.limit == 100


def test_an_unknown_flag_is_rejected_by_the_form_and_changes_nothing(client):
    client.get(PAGE_URL)
    response = client.post(SAVE_URL, {"limit": "100", "optimizer_flags": ["not_a_real_flag"]})
    assert "Error:" in page(response)
    assert sorted(flag_names(browser_session())) == sorted(EXAMPLE_FLAGS)


def test_reset_puts_the_limit_back_to_the_default(client):
    client.get(PAGE_URL)
    response = client.post(RESET_URL, follow=True)
    assert "Generation limit reset to default (10)." in page(response)
    assert browser_session().config.limit == 10


def test_resetting_an_already_default_limit_says_so(client):
    client.get(PAGE_URL)
    client.post(RESET_URL)
    response = client.post(RESET_URL, follow=True)
    assert "already the default" in page(response)


def test_get_on_the_action_urls_just_redirects(client):
    assert client.get(SAVE_URL).status_code == 302
    assert client.get(RESET_URL).status_code == 302
