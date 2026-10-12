"""
Tests for the Time Slots feature: controller behavior (gui/controllers/timeslots.py)
and the pages/forms built on it (gui/views.py, gui/forms.py).

Covers user stories 19-21 (add / modify / delete a time slot, including the
overlap and "only block on a day" rules) and Sprint 2 Sections 10, 11, 12, 19
and 23.2/23.6: valid changes apply, invalid ones are rejected with a clear
message, a failed edit leaves the previous valid configuration untouched, and
cancelling changes nothing.

Everything runs against the REAL scheduler library and the shipped example
configuration (same approach as the "AgainstRealLibrary" tests elsewhere).
The example's weekday blocks, which several tests rely on:
    MON 08:00-19:00 (60)   TUE 08:00-12:00, 13:10-17:10 (60), 17:10-19:40 (30)
    WED 08:00-19:00 (60)   THU (same as TUE)   FRI 08:00-17:00 (60)
"""

import pytest

from app.session import Session
from gui import session_store
from gui.controllers import timeslots as ctrl
from gui.controllers.errors import ControllerError

EXAMPLE = "app/examples/config_example.json"

LIST_URL = "/configuration/timeslots/"
ADD_URL = "/configuration/timeslots/add/"
OPTIONS_URL = "/configuration/timeslots/options/"


def times_of(session, day):
    return [(b.start, b.end, b.spacing) for b in session.config.time_slot_config.times[day]]


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


class TestAdd:
    def test_adds_a_touching_block_and_marks_the_session_dirty(self, session):
        ctrl.add_timeslot(None, "MON", {"start": "19:00", "end": "20:00", "spacing": 30})
        assert times_of(session, "MON") == [("08:00", "19:00", 60), ("19:00", "20:00", 30)]
        assert session.dirty is True

    def test_new_block_is_inserted_in_time_order(self, session):
        ctrl.add_timeslot(None, "TUE", {"start": "07:00", "end": "08:00", "spacing": 30})
        starts = [b.start for b in session.config.time_slot_config.times["TUE"]]
        assert starts[0] == "07:00"
        assert starts == sorted(starts)

    def test_overlap_is_rejected_and_the_config_is_untouched(self, session):
        before = times_of(session, "MON")
        with pytest.raises(ControllerError) as info:
            ctrl.add_timeslot(None, "MON", {"start": "18:00", "end": "20:00", "spacing": 30})
        assert info.value.message == "Time Conflict: overlaps existing block 08:00-19:00"
        assert times_of(session, "MON") == before
        assert session.dirty is False

    @pytest.mark.parametrize(
        "data, field",
        [
            ({"start": "15:00", "end": "09:00", "spacing": 60}, "end"),
            ({"start": "25:00", "end": "26:00", "spacing": 60}, "start"),
            ({"start": "09:00", "end": "10:00", "spacing": 0}, "spacing"),
        ],
    )
    def test_library_rejections_are_attached_to_the_right_field(self, session, data, field):
        before = times_of(session, "FRI")
        with pytest.raises(ControllerError) as info:
            ctrl.add_timeslot(None, "FRI", data)
        assert field in {item.field for item in info.value.errors}
        assert times_of(session, "FRI") == before

    def test_unknown_day_is_rejected(self, session):
        with pytest.raises(ControllerError):
            ctrl.add_timeslot(None, "SUN", {"start": "09:00", "end": "10:00", "spacing": 30})

    def test_requires_a_loaded_configuration(self, empty_session):
        with pytest.raises(ControllerError) as info:
            ctrl.add_timeslot(None, "MON", {"start": "09:00", "end": "10:00", "spacing": 30})
        assert "No configuration is loaded" in info.value.message


class TestUpdate:
    def test_replaces_the_block_and_warns_when_meetings_no_longer_fit(self, session):
        warnings = ctrl.update_timeslot(None, "MON", 0, {"start": "09:00", "end": "10:00", "spacing": 10})
        assert times_of(session, "MON") == [("09:00", "10:00", 10)]
        assert session.dirty is True
        # The example has enabled MON patterns with 110-minute meetings.
        assert len(warnings) == 1 and "110" in warnings[0]

    def test_a_block_may_overlap_its_own_old_value(self, session):
        ctrl.update_timeslot(None, "TUE", 0, {"start": "08:00", "end": "11:00", "spacing": 60})
        assert times_of(session, "TUE")[0] == ("08:00", "11:00", 60)

    def test_overlap_with_another_block_is_rejected_and_nothing_changes(self, session):
        before = times_of(session, "TUE")
        with pytest.raises(ControllerError) as info:
            ctrl.update_timeslot(None, "TUE", 0, {"start": "12:00", "end": "14:00", "spacing": 60})
        assert info.value.message == "Time Conflict: overlaps existing block 13:10-17:10"
        assert times_of(session, "TUE") == before
        assert session.dirty is False

    def test_stale_index_is_rejected(self, session):
        with pytest.raises(ControllerError):
            ctrl.update_timeslot(None, "TUE", 9, {"start": "09:00", "end": "10:00", "spacing": 30})


class TestDelete:
    def test_removes_the_block(self, session):
        ctrl.delete_timeslot(None, "TUE", 1)
        assert times_of(session, "TUE") == [("08:00", "12:00", 60), ("17:10", "19:40", 30)]
        assert session.dirty is True

    def test_the_only_block_on_a_day_cannot_be_deleted(self, session):
        before = times_of(session, "MON")
        with pytest.raises(ControllerError) as info:
            ctrl.delete_timeslot(None, "MON", 0)
        assert info.value.message == "Can't delete the only time block on MON -- every weekday needs at least one."
        assert times_of(session, "MON") == before
        assert session.dirty is False

    def test_stale_index_is_rejected(self, session):
        with pytest.raises(ControllerError):
            ctrl.delete_timeslot(None, "TUE", 7)


class TestTimingOptions:
    def test_updates_the_global_options(self, session):
        ctrl.update_timing_options(None, {"max_time_gap": 25, "min_time_overlap": 45})
        assert session.config.time_slot_config.max_time_gap == 25
        assert session.config.time_slot_config.min_time_overlap == 45
        assert session.dirty is True


class TestDescribe:
    def test_no_configuration(self, empty_session):
        assert ctrl.describe_timeslots(None) == {"has_config": False}

    def test_days_blocks_and_grid_geometry(self, session):
        data = ctrl.describe_timeslots(None)
        assert [d["day"] for d in data["days"]] == ["MON", "TUE", "WED", "THU", "FRI"]
        monday, tuesday = data["days"][0], data["days"][1]
        assert monday["only_block"] is True and len(monday["blocks"]) == 1
        assert [b["index"] for b in tuesday["blocks"]] == [0, 1, 2]
        # Axis runs 08:00-20:00, so MON 08:00-19:00 starts at the top and fills 660 of 720 minutes.
        assert monday["blocks"][0]["top"] == "0.00"
        assert monday["blocks"][0]["height"] == "91.67"
        assert data["hours"][0]["label"] == "08:00" and data["hours"][-1]["label"] == "20:00"
        assert data["max_time_gap"] == 30 and data["min_time_overlap"] == 45

    def test_get_timeslot(self, session):
        block = ctrl.get_timeslot(None, "TUE", 1)
        assert (block["start"], block["end"], block["spacing"], block["is_only_block"]) == ("13:10", "17:10", 60, False)
        with pytest.raises(ControllerError):
            ctrl.get_timeslot(None, "TUE", 5)


# ---------------------------------------------------------------------- #
#  Pages and forms (through Django's test client)
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


def test_page_lists_blocks_and_shows_no_unsaved_changes(client):
    response = client.get(LIST_URL)
    assert response.status_code == 200
    text = page(response)
    assert "Time Slots" in text and "MON 08:00-19:00" in text and "TUE 17:10-19:40" in text
    assert "Unsaved changes" not in text


def test_page_shows_the_empty_state_when_no_configuration_is_loaded(client, monkeypatch):
    monkeypatch.setattr(session_store, "AUTO_LOAD_EXAMPLE", False)
    response = client.get(LIST_URL)
    assert response.status_code == 200
    assert "No configuration is loaded" in page(response)


def test_adding_a_block_confirms_and_flags_unsaved_changes(client):
    response = client.post(
        ADD_URL, {"day": "FRI", "start": "17:00", "end": "18:00", "spacing": "30"}, follow=True
    )
    text = page(response)
    assert "Time Slot Added Successfully" in text
    assert "FRI 17:00-18:00" in text
    assert "Unsaved changes" in text
    assert times_of(browser_session(), "FRI") == [("08:00", "17:00", 60), ("17:00", "18:00", 30)]


def test_adding_an_overlapping_block_shows_the_conflict_and_changes_nothing(client):
    response = client.post(ADD_URL, {"day": "MON", "start": "18:00", "end": "20:00", "spacing": "30"})
    assert response.status_code == 200
    assert "Time Conflict: overlaps existing block 08:00-19:00" in page(response)
    assert times_of(browser_session(), "MON") == [("08:00", "19:00", 60)]


def test_invalid_input_is_reported_on_the_form_and_keeps_what_was_typed(client):
    response = client.post(ADD_URL, {"day": "MON", "start": "25:00", "end": "26:00", "spacing": "45"})
    text = page(response)
    assert "Enter a valid time." in text
    assert 'value="45"' in text
    assert times_of(browser_session(), "MON") == [("08:00", "19:00", 60)]


def test_end_before_start_shows_the_library_rule_in_plain_language(client):
    response = client.post(ADD_URL, {"day": "MON", "start": "20:00", "end": "19:30", "spacing": "30"})
    assert "End time must be later than the start time." in page(response)


def test_get_on_the_add_url_just_redirects(client):
    assert client.get(ADD_URL).status_code == 302


def test_editing_a_block_applies_only_on_submit(client):
    edit_url = "/configuration/timeslots/TUE/0/edit/"
    response = client.get(edit_url)
    assert response.status_code == 200
    assert "currently <strong>08:00-12:00</strong>" in page(response)  # the block's own values are shown
    assert times_of(browser_session(), "TUE")[0] == ("08:00", "12:00", 60)  # viewing changes nothing

    response = client.post(edit_url, {"start": "08:00", "end": "11:00", "spacing": "30"}, follow=True)
    assert "Time Changed Successfully" in page(response)
    assert times_of(browser_session(), "TUE")[0] == ("08:00", "11:00", 30)


def test_editing_into_a_conflict_is_rejected_and_the_block_is_unchanged(client):
    response = client.post(
        "/configuration/timeslots/TUE/0/edit/", {"start": "12:00", "end": "14:00", "spacing": "60"}
    )
    assert "Time Conflict: overlaps existing block 13:10-17:10" in page(response)
    assert times_of(browser_session(), "TUE")[0] == ("08:00", "12:00", 60)


def test_editing_a_block_that_no_longer_exists_redirects_with_an_error(client):
    response = client.get("/configuration/timeslots/TUE/9/edit/", follow=True)
    assert "no longer exists" in page(response)


def test_unknown_weekday_in_the_url_is_a_404(client):
    assert client.get("/configuration/timeslots/SUN/0/edit/").status_code == 404


def test_delete_asks_for_confirmation_and_cancel_changes_nothing(client):
    url = "/configuration/timeslots/TUE/1/delete/"
    text = page(client.get(url))
    assert "Are you sure" in text
    assert "TUE 13:10-17:10" in text  # names the block being deleted
    response = client.post(url, {"action": "cancel"}, follow=True)
    assert "Cancelled." in page(response)
    assert len(times_of(browser_session(), "TUE")) == 3


def test_confirming_a_delete_removes_the_block(client):
    response = client.post("/configuration/timeslots/TUE/1/delete/", {"action": "confirm"}, follow=True)
    assert "Time slot deleted." in page(response)
    assert times_of(browser_session(), "TUE") == [("08:00", "12:00", 60), ("17:10", "19:40", 30)]


def test_the_only_block_on_a_day_cannot_be_deleted_from_the_page(client):
    url = "/configuration/timeslots/MON/0/delete/"
    assert "only time block on Monday" in page(client.get(url))
    response = client.post(url, {"action": "confirm"}, follow=True)
    assert "only time block on MON" in page(response)
    assert times_of(browser_session(), "MON") == [("08:00", "19:00", 60)]


def test_shrinking_a_block_warns_that_meetings_may_not_fit(client):
    response = client.post(
        "/configuration/timeslots/MON/0/edit/",
        {"start": "09:00", "end": "10:00", "spacing": "60"},
        follow=True,
    )
    text = page(response)
    assert "Time Changed Successfully" in text
    assert "do not fit" in text and "110" in text


def test_timing_options_can_be_changed_from_the_page(client):
    response = client.post(OPTIONS_URL, {"max_time_gap": "25", "min_time_overlap": "45"}, follow=True)
    assert "Timing options updated." in page(response)
    assert browser_session().config.time_slot_config.max_time_gap == 25


def test_timing_options_reject_a_negative_number_on_the_form(client):
    response = client.post(OPTIONS_URL, {"max_time_gap": "-5", "min_time_overlap": "45"})
    assert "Error:" in page(response)
    assert browser_session().config.time_slot_config.max_time_gap == 30
