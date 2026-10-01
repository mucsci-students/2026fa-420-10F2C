"""
Tests for the Class Patterns and Meetings features: controller behavior
(gui/controllers/patterns.py, meetings.py) and the pages/forms built on them
(gui/views_patterns.py, gui/views_meetings.py, gui/forms.py).

Covers user stories 22-27 (add / modify / delete a class pattern and a meeting,
including "a pattern keeps at least one meeting") and Sprint 2 Sections 10, 11
and 19: valid changes apply, invalid ones are rejected with a clear message, a
failed edit leaves the previous valid configuration untouched, and cancelling
changes nothing.

Everything runs against the REAL scheduler library and the shipped example
configuration. To avoid depending on library rules that are not under test (for
example which course needs which pattern), most tests first add a brand-new
pattern and then edit or delete only that one.
"""

import pytest

from app.session import Session
from gui import session_store
from gui.controllers import meetings as meeting_ctrl
from gui.controllers import patterns as pattern_ctrl
from gui.controllers.errors import ControllerError

EXAMPLE = "app/examples/config_example.json"

PATTERNS_URL = "/configuration/patterns/"
PATTERN_ADD_URL = "/configuration/patterns/add/"
MEETINGS_URL = "/configuration/meetings/"
MEETING_ADD_URL = "/configuration/meetings/add/"


def classes(session):
    return session.config.time_slot_config.classes


def day_of(meeting):
    return str(getattr(meeting.day, "value", meeting.day))


def shape(pattern):
    """Plain, comparable description of a pattern."""
    return (
        pattern.credits,
        bool(getattr(pattern, "disabled", False)),
        [(day_of(m), m.duration, bool(m.lab)) for m in pattern.meetings],
    )


def all_shapes(session):
    return [shape(p) for p in classes(session)]


def new_pattern(**overrides):
    """form_data for add_pattern: a 3-credit pattern with one TUE 50-minute meeting."""
    data = {
        "credits": 3,
        "start_time": None,
        "enabled": True,
        "meeting_day": "TUE",
        "meeting_duration": 50,
        "meeting_lab": False,
        "meeting_delivery": "in_person",
        "meeting_start_time": None,
    }
    data.update(overrides)
    return data


def meeting_data(**overrides):
    data = {"day": "THU", "duration": 50, "lab": False, "delivery": "in_person", "start_time": None}
    data.update(overrides)
    return data


# ---------------------------------------------------------------------- #
#  Controllers (called directly, independent of Django's request cycle)
# ---------------------------------------------------------------------- #
@pytest.fixture
def session(monkeypatch):
    """A Session holding the example config, handed to both controllers in
    place of the per-browser lookup."""
    loaded = Session()
    loaded.load(EXAMPLE)
    monkeypatch.setattr(pattern_ctrl, "get_session", lambda request: loaded)
    monkeypatch.setattr(meeting_ctrl, "get_session", lambda request: loaded)
    return loaded


@pytest.fixture
def empty_session(monkeypatch):
    blank = Session()
    monkeypatch.setattr(pattern_ctrl, "get_session", lambda request: blank)
    monkeypatch.setattr(meeting_ctrl, "get_session", lambda request: blank)
    return blank


class TestPatternAdd:
    def test_adds_a_pattern_with_its_first_meeting_and_marks_the_session_dirty(self, session):
        before = len(classes(session))
        pattern_ctrl.add_pattern(None, new_pattern())
        assert len(classes(session)) == before + 1
        assert shape(classes(session)[-1]) == (3, False, [("TUE", 50, False)])
        assert session.dirty is True

    def test_a_disabled_pattern_is_stored_as_disabled(self, session):
        pattern_ctrl.add_pattern(None, new_pattern(enabled=False))
        assert classes(session)[-1].disabled is True

    @pytest.mark.parametrize("credits", [0, -3, None])
    def test_credits_must_be_a_positive_integer(self, session, credits):
        before = all_shapes(session)
        with pytest.raises(ControllerError) as info:
            pattern_ctrl.add_pattern(None, new_pattern(credits=credits))
        assert "Credits must be a positive integer." in info.value.message
        assert all_shapes(session) == before
        assert session.dirty is False

    def test_a_bad_first_meeting_is_rejected_and_the_config_is_untouched(self, session):
        before = all_shapes(session)
        with pytest.raises(ControllerError) as info:
            pattern_ctrl.add_pattern(None, new_pattern(meeting_day="SUN", meeting_duration=0))
        fields = {item.field for item in info.value.errors}
        assert {"meeting_day", "meeting_duration"} <= fields
        assert all_shapes(session) == before

    def test_needs_a_configuration(self, empty_session):
        with pytest.raises(ControllerError) as info:
            pattern_ctrl.add_pattern(None, new_pattern())
        assert "No configuration is loaded" in info.value.message


class TestPatternUpdate:
    def test_changes_credits_and_keeps_the_meetings(self, session):
        pattern_ctrl.add_pattern(None, new_pattern())
        index = len(classes(session)) - 1
        meetings_before = shape(classes(session)[index])[2]
        pattern_ctrl.update_pattern(None, index, {"credits": 4, "start_time": None, "enabled": True})
        credits, disabled, meetings = shape(classes(session)[index])
        assert (credits, disabled) == (4, False)
        assert meetings == meetings_before

    def test_can_disable_a_pattern(self, session):
        pattern_ctrl.add_pattern(None, new_pattern())
        index = len(classes(session)) - 1
        pattern_ctrl.update_pattern(None, index, {"credits": 3, "start_time": None, "enabled": False})
        assert classes(session)[index].disabled is True

    def test_rejects_non_positive_credits_and_changes_nothing(self, session):
        pattern_ctrl.add_pattern(None, new_pattern())
        index = len(classes(session)) - 1
        before = all_shapes(session)
        with pytest.raises(ControllerError) as info:
            pattern_ctrl.update_pattern(None, index, {"credits": 0, "start_time": None, "enabled": True})
        assert "Credits must be a positive integer." in info.value.message
        assert all_shapes(session) == before

    def test_a_stale_index_is_reported(self, session):
        with pytest.raises(ControllerError) as info:
            pattern_ctrl.update_pattern(None, 999, {"credits": 3, "start_time": None, "enabled": True})
        assert "no longer exists" in info.value.message


class TestPatternDelete:
    def test_removes_the_pattern(self, session):
        before = all_shapes(session)
        pattern_ctrl.add_pattern(None, new_pattern())
        pattern_ctrl.delete_pattern(None, len(classes(session)) - 1)
        assert all_shapes(session) == before

    def test_a_stale_index_is_reported(self, session):
        with pytest.raises(ControllerError) as info:
            pattern_ctrl.delete_pattern(None, 999)
        assert "no longer exists" in info.value.message


class TestPatternReads:
    def test_describe_lists_every_pattern_with_its_meetings(self, session):
        data = pattern_ctrl.describe_patterns(None)
        assert data["has_config"] is True
        assert len(data["patterns"]) == len(classes(session))
        first = data["patterns"][0]
        assert first["credits"] == 3 and first["enabled"] is True
        assert [m["day"] for m in first["meetings"]] == ["MON", "WED", "FRI"]

    def test_describe_without_a_configuration(self, empty_session):
        assert pattern_ctrl.describe_patterns(None) == {"has_config": False}


class TestMeetings:
    @pytest.fixture
    def index(self, session):
        """Index of a freshly added one-meeting pattern (TUE, 50 minutes)."""
        pattern_ctrl.add_pattern(None, new_pattern())
        return len(classes(session)) - 1

    def test_adds_a_meeting_to_a_pattern(self, session, index):
        meeting_ctrl.add_meeting(None, index, meeting_data(day="THU", duration=75, lab=True))
        assert shape(classes(session)[index])[2] == [("TUE", 50, False), ("THU", 75, True)]
        assert session.dirty is True

    def test_updates_a_meeting(self, session, index):
        meeting_ctrl.update_meeting(None, index, 0, meeting_data(day="WED", duration=60))
        assert shape(classes(session)[index])[2] == [("WED", 60, False)]

    def test_deletes_a_meeting_when_the_pattern_has_another(self, session, index):
        meeting_ctrl.add_meeting(None, index, meeting_data())
        meeting_ctrl.delete_meeting(None, index, 0)
        assert shape(classes(session)[index])[2] == [("THU", 50, False)]

    def test_the_only_meeting_cannot_be_deleted(self, session, index):
        before = all_shapes(session)
        with pytest.raises(ControllerError) as info:
            meeting_ctrl.delete_meeting(None, index, 0)
        assert info.value.message == meeting_ctrl.LAST_MEETING_MESSAGE
        assert all_shapes(session) == before

    @pytest.mark.parametrize(
        "bad, field",
        [({"day": "SUN"}, "day"), ({"duration": 0}, "duration"), ({"duration": -10}, "duration")],
    )
    def test_invalid_input_is_rejected_and_the_config_is_untouched(self, session, index, bad, field):
        before = all_shapes(session)
        with pytest.raises(ControllerError) as info:
            meeting_ctrl.add_meeting(None, index, meeting_data(**bad))
        assert field in {item.field for item in info.value.errors}
        assert all_shapes(session) == before

    def test_a_failed_update_keeps_the_original_meeting(self, session, index):
        before = all_shapes(session)
        with pytest.raises(ControllerError):
            meeting_ctrl.update_meeting(None, index, 0, meeting_data(duration=0))
        assert all_shapes(session) == before

    def test_stale_indexes_are_reported(self, session, index):
        for call in (
            lambda: meeting_ctrl.add_meeting(None, 999, meeting_data()),
            lambda: meeting_ctrl.update_meeting(None, index, 9, meeting_data()),
            lambda: meeting_ctrl.delete_meeting(None, index, 9),
            lambda: meeting_ctrl.get_meeting(None, 999, 0),
        ):
            with pytest.raises(ControllerError) as info:
                call()
            assert "no longer exists" in info.value.message

    def test_a_meeting_longer_than_every_time_block_warns_but_is_allowed(self, session, index):
        # FRI's example blocks are 08:00-17:00, so a 600-minute meeting cannot fit.
        warnings = meeting_ctrl.add_meeting(None, index, meeting_data(day="FRI", duration=600))
        assert any("do not fit" in w for w in warnings)

    def test_describe_marks_a_patterns_only_meeting(self, session, index):
        data = meeting_ctrl.describe_meetings(None)
        entry = data["patterns"][index]
        assert entry["only_meeting"] is True
        assert (index, entry["label"]) in data["pattern_choices"]

    def test_needs_a_configuration(self, empty_session):
        with pytest.raises(ControllerError) as info:
            meeting_ctrl.add_meeting(None, 0, meeting_data())
        assert "No configuration is loaded" in info.value.message
        assert meeting_ctrl.describe_meetings(None) == {"has_config": False}


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


def add_pattern_via_page(client, **overrides):
    """POST the Add Class Pattern form; returns the new pattern's index."""
    data = {
        "credits": "3",
        "enabled": "on",
        "meeting_day": "TUE",
        "meeting_duration": "50",
        "meeting_delivery": "in_person",
    }
    data.update(overrides)
    response = client.post(PATTERN_ADD_URL, data, follow=True)
    assert "Class pattern added." in page(response)
    return len(classes(browser_session())) - 1


def test_the_configuration_home_links_to_both_pages(client):
    text = page(client.get("/configuration/"))
    assert PATTERNS_URL in text and MEETINGS_URL in text


def test_the_patterns_page_lists_the_example_patterns_and_the_add_form(client):
    response = client.get(PATTERNS_URL)
    text = page(response)
    assert response.status_code == 200
    assert "Add a class pattern" in text
    assert "MON 50 min" in text


def test_adding_a_pattern_from_the_page(client):
    client.get(PATTERNS_URL)
    before = len(classes(browser_session()))
    index = add_pattern_via_page(client)
    assert len(classes(browser_session())) == before + 1
    assert shape(classes(browser_session())[index]) == (3, False, [("TUE", 50, False)])


def test_zero_credits_is_reported_on_the_form_and_nothing_is_added(client):
    client.get(PATTERNS_URL)
    before = all_shapes(browser_session())
    response = client.post(
        PATTERN_ADD_URL,
        {"credits": "0", "enabled": "on", "meeting_day": "TUE", "meeting_duration": "50", "meeting_delivery": "in_person"},
    )
    assert response.status_code == 200
    assert "Error:" in page(response)
    assert all_shapes(browser_session()) == before


def test_a_blank_first_meeting_is_reported_on_the_form(client):
    client.get(PATTERNS_URL)
    before = all_shapes(browser_session())
    response = client.post(PATTERN_ADD_URL, {"credits": "3", "enabled": "on"})
    assert "Error:" in page(response)
    assert all_shapes(browser_session()) == before


def test_get_on_the_add_url_just_redirects(client):
    assert client.get(PATTERN_ADD_URL).status_code == 302
    assert client.get(MEETING_ADD_URL).status_code == 302


def test_editing_a_pattern_applies_only_on_submit(client):
    client.get(PATTERNS_URL)
    index = add_pattern_via_page(client)
    url = f"{PATTERNS_URL}{index}/edit/"
    assert client.get(url).status_code == 200
    assert classes(browser_session())[index].credits == 3  # viewing changes nothing

    response = client.post(url, {"credits": "4", "enabled": "on"}, follow=True)
    assert "Class pattern updated." in page(response)
    assert shape(classes(browser_session())[index]) == (4, False, [("TUE", 50, False)])


def test_editing_with_bad_credits_shows_the_error_and_changes_nothing(client):
    client.get(PATTERNS_URL)
    index = add_pattern_via_page(client)
    response = client.post(f"{PATTERNS_URL}{index}/edit/", {"credits": "0", "enabled": "on"})
    assert "Error:" in page(response)
    assert classes(browser_session())[index].credits == 3


def test_editing_a_pattern_that_no_longer_exists_redirects_with_an_error(client):
    response = client.get(f"{PATTERNS_URL}999/edit/", follow=True)
    assert "no longer exists" in page(response)


def test_deleting_a_pattern_asks_first_and_cancel_changes_nothing(client):
    client.get(PATTERNS_URL)
    index = add_pattern_via_page(client)
    url = f"{PATTERNS_URL}{index}/delete/"
    assert "Are you sure" in page(client.get(url))
    before = len(classes(browser_session()))
    response = client.post(url, {"action": "cancel"}, follow=True)
    assert "Cancelled." in page(response)
    assert len(classes(browser_session())) == before


def test_confirming_removes_the_pattern(client):
    client.get(PATTERNS_URL)
    index = add_pattern_via_page(client)
    before = len(classes(browser_session()))
    response = client.post(f"{PATTERNS_URL}{index}/delete/", {"action": "confirm"}, follow=True)
    assert "Class pattern removed." in page(response)
    assert len(classes(browser_session())) == before - 1


def test_the_meetings_page_lists_every_pattern(client):
    response = client.get(MEETINGS_URL)
    text = page(response)
    assert response.status_code == 200
    assert "Pattern 0: 3 credits" in text
    assert "Add a meeting" in text


def test_adding_a_meeting_from_the_page(client):
    client.get(PATTERNS_URL)
    index = add_pattern_via_page(client)
    response = client.post(
        MEETING_ADD_URL,
        {"pattern": str(index), "day": "THU", "duration": "75", "delivery": "online"},
        follow=True,
    )
    assert "Meeting added." in page(response)
    assert shape(classes(browser_session())[index])[2] == [("TUE", 50, False), ("THU", 75, False)]


def test_a_bad_meeting_is_reported_on_the_form_and_changes_nothing(client):
    client.get(PATTERNS_URL)
    index = add_pattern_via_page(client)
    before = all_shapes(browser_session())
    response = client.post(
        MEETING_ADD_URL, {"pattern": str(index), "day": "THU", "duration": "0", "delivery": "online"}
    )
    assert "Error:" in page(response)
    assert all_shapes(browser_session()) == before


def test_editing_a_meeting_applies_only_on_submit(client):
    client.get(PATTERNS_URL)
    index = add_pattern_via_page(client)
    url = f"{MEETINGS_URL}{index}/0/edit/"
    assert "TUE 50 min" in page(client.get(url))
    assert shape(classes(browser_session())[index])[2] == [("TUE", 50, False)]

    response = client.post(url, {"day": "WED", "duration": "50", "delivery": "in_person"}, follow=True)
    assert "Meeting updated." in page(response)
    assert shape(classes(browser_session())[index])[2] == [("WED", 50, False)]


def test_deleting_a_meeting_asks_first_then_removes_it(client):
    client.get(PATTERNS_URL)
    index = add_pattern_via_page(client)
    client.post(MEETING_ADD_URL, {"pattern": str(index), "day": "THU", "duration": "50", "delivery": "in_person"})
    url = f"{MEETINGS_URL}{index}/0/delete/"
    assert "Are you sure" in page(client.get(url))
    assert "Cancelled." in page(client.post(url, {"action": "cancel"}, follow=True))
    assert len(classes(browser_session())[index].meetings) == 2

    response = client.post(url, {"action": "confirm"}, follow=True)
    assert "Meeting removed." in page(response)
    assert shape(classes(browser_session())[index])[2] == [("THU", 50, False)]


def test_the_only_meeting_on_a_pattern_cannot_be_deleted_from_the_page(client):
    client.get(PATTERNS_URL)
    index = add_pattern_via_page(client)
    url = f"{MEETINGS_URL}{index}/0/delete/"
    assert "only meeting on pattern" in page(client.get(url))
    response = client.post(url, {"action": "confirm"}, follow=True)
    assert "Can&#x27;t delete the only meeting on this pattern" in page(response)
    assert shape(classes(browser_session())[index])[2] == [("TUE", 50, False)]


def test_editing_a_meeting_that_no_longer_exists_redirects_with_an_error(client):
    response = client.get(f"{MEETINGS_URL}0/99/edit/", follow=True)
    assert "no longer exists" in page(response)
