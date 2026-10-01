"""
Tests for the Rooms and Labs controllers (gui/controllers/rooms.py and
gui/controllers/labs.py).

Covers Sprint 2 Sections 7 (Rooms, Labs), 10, 11, 12, 19 and 23.2/23.6: create,
update and delete a room/lab; invalid input is rejected with field-level
messages; a failed edit leaves the previous valid configuration untouched;
deleting or renaming a referenced room/lab is blocked with the blocking records
listed.

Runs against the REAL scheduler library and the shipped example configuration:
    rooms Roddy 136 / 140 / 147  -- referenced by courses and faculty room prefs
    labs  Linux / Mac            -- referenced by courses and faculty lab prefs
so a freshly added room or lab is the unreferenced one.

Layout: shared helpers and fixtures, then a Rooms section, then a Labs section.
"""

import pytest

from app.crud import ValidationFailure
from app.session import Session
from gui.controllers import labs as labs_ctrl
from gui.controllers import rooms as rooms_ctrl
from gui.controllers.errors import ControllerError

EXAMPLE = "app/examples/config_example.json"


# ---------------------------------------------------------------------- #
#  Shared helpers and fixtures
# ---------------------------------------------------------------------- #
def error_fields(info):
    return {item.field for item in info.value.errors}


def room_names(session):
    return [item.name for item in session.config.config.rooms]


def room(session, name):
    return next(item for item in session.config.config.rooms if item.name == name)


def new_room(**overrides):
    data = {"name": "Roddy 150", "capacity": 30, "features": "projector, whiteboard"}
    data.update(overrides)
    return data


def lab_names(session):
    return [item.name for item in session.config.config.labs]


def lab(session, name):
    return next(item for item in session.config.config.labs if item.name == name)


def new_lab(**overrides):
    data = {"name": "Windows", "capacity": 24, "features": "gpu, dual monitors"}
    data.update(overrides)
    return data


@pytest.fixture
def session(monkeypatch):
    """A Session holding the example config, handed to BOTH controllers in
    place of the per-browser lookup."""
    loaded = Session()
    loaded.load(EXAMPLE)
    monkeypatch.setattr(rooms_ctrl, "get_session", lambda request: loaded)
    monkeypatch.setattr(labs_ctrl, "get_session", lambda request: loaded)
    return loaded


@pytest.fixture
def empty_session(monkeypatch):
    """A Session with no configuration loaded, for both controllers."""
    blank = Session()
    monkeypatch.setattr(rooms_ctrl, "get_session", lambda request: blank)
    monkeypatch.setattr(labs_ctrl, "get_session", lambda request: blank)
    return blank


# ====================================================================== #
#  ROOMS
# ====================================================================== #
class TestRoomAdd:
    def test_adds_a_room_and_marks_the_session_dirty(self, session):
        rooms_ctrl.add_room(None, new_room())
        added = room(session, "Roddy 150")
        assert added.capacity == 30
        assert sorted(added.features) == ["projector", "whiteboard"]
        assert not added.times
        assert session.dirty is True

    def test_features_can_be_a_list(self, session):
        rooms_ctrl.add_room(None, new_room(features=["b", " a ", "a", ""]))
        assert sorted(room(session, "Roddy 150").features) == ["a", "b"]

    def test_availability_is_saved(self, session):
        times = {"MON": [{"start": "09:00", "end": "12:00"}]}
        rooms_ctrl.add_room(None, new_room(times=times))
        saved = rooms_ctrl.get_room(None, "Roddy 150")
        assert saved["times"] == times
        assert saved["availability"] == [{"day": "MON", "name": "Monday", "ranges": "09:00-12:00"}]

    def test_duplicate_name_is_rejected_on_the_name_field(self, session):
        before = room_names(session)
        with pytest.raises(ControllerError) as info:
            rooms_ctrl.add_room(None, new_room(name="Roddy 136"))
        assert error_fields(info) == {"name"}
        assert "already exists" in info.value.message
        assert room_names(session) == before
        assert session.dirty is False

    @pytest.mark.parametrize(
        "overrides, field",
        [
            ({"name": "   "}, "name"),
            ({"capacity": 0}, "capacity"),
            ({"capacity": -5}, "capacity"),
            ({"capacity": "lots"}, "capacity"),
            ({"capacity": None}, "capacity"),
            ({"capacity": True}, "capacity"),
            ({"times": {"SUN": [{"start": "09:00", "end": "10:00"}]}}, "times"),
            ({"times": ["MON"]}, "times"),
        ],
    )
    def test_invalid_input_is_attached_to_the_right_field(self, session, overrides, field):
        before = room_names(session)
        with pytest.raises(ControllerError) as info:
            rooms_ctrl.add_room(None, new_room(**overrides))
        assert field in error_fields(info)
        assert room_names(session) == before
        assert session.dirty is False

    def test_all_problems_are_reported_together(self, session):
        with pytest.raises(ControllerError) as info:
            rooms_ctrl.add_room(None, new_room(name="", capacity=0))
        assert error_fields(info) == {"name", "capacity"}

    def test_requires_a_loaded_configuration(self, empty_session):
        with pytest.raises(ControllerError) as info:
            rooms_ctrl.add_room(None, new_room())
        assert "No configuration is loaded" in info.value.message


class TestRoomUpdate:
    def test_updates_in_place_and_keeps_list_order(self, session):
        order = room_names(session)
        rooms_ctrl.update_room(None, "Roddy 140", new_room(name="Roddy 140", capacity=35, features=""))
        assert room_names(session) == order
        assert room(session, "Roddy 140").capacity == 35
        assert session.dirty is True

    def test_unreferenced_room_can_be_renamed(self, session):
        rooms_ctrl.add_room(None, new_room())
        rooms_ctrl.update_room(None, "Roddy 150", new_room(name="Roddy 151"))
        assert "Roddy 151" in room_names(session)
        assert "Roddy 150" not in room_names(session)

    def test_rename_to_an_existing_name_is_rejected(self, session):
        rooms_ctrl.add_room(None, new_room())
        with pytest.raises(ControllerError) as info:
            rooms_ctrl.update_room(None, "Roddy 150", new_room(name="Roddy 136"))
        assert error_fields(info) == {"name"}
        assert "Roddy 150" in room_names(session)

    def test_renaming_a_referenced_room_is_blocked_and_lists_references(self, session):
        before = room_names(session)
        with pytest.raises(ControllerError) as info:
            rooms_ctrl.update_room(None, "Roddy 136", new_room(name="Roddy 999"))
        assert error_fields(info) == {"name"}
        assert "still referenced by" in info.value.message and "CMSC 140" in info.value.message
        assert room_names(session) == before

    def test_invalid_change_leaves_the_room_untouched(self, session):
        original = room(session, "Roddy 136").capacity
        with pytest.raises(ControllerError):
            rooms_ctrl.update_room(None, "Roddy 136", new_room(name="Roddy 136", capacity=0))
        assert room(session, "Roddy 136").capacity == original
        assert session.dirty is False

    def test_missing_room_is_reported(self, session):
        with pytest.raises(ControllerError) as info:
            rooms_ctrl.update_room(None, "Nowhere", new_room(name="Nowhere"))
        assert "no longer exists" in info.value.message


class TestRoomDelete:
    def test_removes_an_unreferenced_room(self, session):
        rooms_ctrl.add_room(None, new_room())
        session.dirty = False
        rooms_ctrl.delete_room(None, "Roddy 150")
        assert "Roddy 150" not in room_names(session)
        assert session.dirty is True

    def test_referenced_room_is_blocked_and_nothing_changes(self, session):
        before = room_names(session)
        with pytest.raises(ControllerError) as info:
            rooms_ctrl.delete_room(None, "Roddy 136")
        assert "Cannot delete 'Roddy 136'" in info.value.message
        assert "CMSC 140" in info.value.message
        assert room_names(session) == before
        assert session.dirty is False

    def test_faculty_room_preferences_count_as_references(self, session):
        blockers = rooms_ctrl._references(session.config, "Roddy 147")
        assert any("room preference" in item for item in blockers)

    def test_stale_name_is_rejected(self, session):
        with pytest.raises(ControllerError):
            rooms_ctrl.delete_room(None, "Nowhere")


class TestRoomRollback:
    def test_failed_whole_config_validation_is_reported_and_config_is_unchanged(self, session, monkeypatch):
        def reject(session_, config, area, mutate):
            raise ValidationFailure(area, "simulated whole-config rejection")

        monkeypatch.setattr(rooms_ctrl, "apply_session_edit", reject)
        before = room_names(session)
        with pytest.raises(ControllerError) as info:
            rooms_ctrl.add_room(None, new_room())
        assert "simulated whole-config rejection" in info.value.message
        assert room_names(session) == before
        assert session.dirty is False


class TestRoomDescribe:
    def test_no_configuration(self, empty_session):
        assert rooms_ctrl.describe_rooms(None) == {"has_config": False}

    def test_lists_rooms_with_availability_and_references(self, session):
        data = rooms_ctrl.describe_rooms(None)
        assert data["has_config"] is True
        assert [item["name"] for item in data["rooms"]] == ["Roddy 136", "Roddy 140", "Roddy 147"]
        first = data["rooms"][0]
        assert first["capacity"] == 28
        assert first["unrestricted"] is True and first["availability"] == []
        assert first["can_delete"] is False and first["referenced_by"]

    def test_new_room_can_be_deleted(self, session):
        rooms_ctrl.add_room(None, new_room())
        added = next(item for item in rooms_ctrl.describe_rooms(None)["rooms"] if item["name"] == "Roddy 150")
        assert added["can_delete"] is True and added["referenced_by"] == []

    def test_get_room_and_missing_room(self, session):
        assert rooms_ctrl.get_room(None, "Roddy 140")["capacity"] == 28
        with pytest.raises(ControllerError):
            rooms_ctrl.get_room(None, "Nowhere")

    def test_saved_configuration_with_new_room_reloads(self, session, tmp_path):
        rooms_ctrl.add_room(None, new_room())
        path = tmp_path / "rooms.json"
        session.save(str(path))
        reloaded = Session()
        reloaded.load(str(path))
        assert "Roddy 150" in room_names(reloaded)


# ====================================================================== #
#  LABS
# ====================================================================== #
class TestLabAdd:
    def test_adds_a_lab_and_marks_the_session_dirty(self, session):
        labs_ctrl.add_lab(None, new_lab())
        added = lab(session, "Windows")
        assert added.capacity == 24
        assert sorted(added.features) == ["dual monitors", "gpu"]
        assert not added.times
        assert session.dirty is True

    def test_features_can_be_a_list(self, session):
        labs_ctrl.add_lab(None, new_lab(features=["b", " a ", "a", ""]))
        assert sorted(lab(session, "Windows").features) == ["a", "b"]

    def test_availability_is_saved(self, session):
        times = {"TUE": [{"start": "13:00", "end": "17:00"}]}
        labs_ctrl.add_lab(None, new_lab(times=times))
        saved = labs_ctrl.get_lab(None, "Windows")
        assert saved["times"] == times
        assert saved["availability"] == [{"day": "TUE", "name": "Tuesday", "ranges": "13:00-17:00"}]

    def test_duplicate_name_is_rejected_on_the_name_field(self, session):
        before = lab_names(session)
        with pytest.raises(ControllerError) as info:
            labs_ctrl.add_lab(None, new_lab(name="Linux"))
        assert error_fields(info) == {"name"}
        assert "already exists" in info.value.message
        assert lab_names(session) == before
        assert session.dirty is False

    @pytest.mark.parametrize(
        "overrides, field",
        [
            ({"name": "   "}, "name"),
            ({"capacity": 0}, "capacity"),
            ({"capacity": -5}, "capacity"),
            ({"capacity": "lots"}, "capacity"),
            ({"capacity": None}, "capacity"),
            ({"capacity": True}, "capacity"),
            ({"times": {"SUN": [{"start": "09:00", "end": "10:00"}]}}, "times"),
            ({"times": ["MON"]}, "times"),
        ],
    )
    def test_invalid_input_is_attached_to_the_right_field(self, session, overrides, field):
        before = lab_names(session)
        with pytest.raises(ControllerError) as info:
            labs_ctrl.add_lab(None, new_lab(**overrides))
        assert field in error_fields(info)
        assert lab_names(session) == before
        assert session.dirty is False

    def test_all_problems_are_reported_together(self, session):
        with pytest.raises(ControllerError) as info:
            labs_ctrl.add_lab(None, new_lab(name="", capacity=0))
        assert error_fields(info) == {"name", "capacity"}

    def test_requires_a_loaded_configuration(self, empty_session):
        with pytest.raises(ControllerError) as info:
            labs_ctrl.add_lab(None, new_lab())
        assert "No configuration is loaded" in info.value.message


class TestLabUpdate:
    def test_updates_in_place_and_keeps_list_order(self, session):
        order = lab_names(session)
        labs_ctrl.update_lab(None, "Linux", new_lab(name="Linux", capacity=32, features=""))
        assert lab_names(session) == order
        assert lab(session, "Linux").capacity == 32
        assert session.dirty is True

    def test_unreferenced_lab_can_be_renamed(self, session):
        labs_ctrl.add_lab(None, new_lab())
        labs_ctrl.update_lab(None, "Windows", new_lab(name="Windows 11"))
        assert "Windows 11" in lab_names(session)
        assert "Windows" not in lab_names(session)

    def test_rename_to_an_existing_name_is_rejected(self, session):
        labs_ctrl.add_lab(None, new_lab())
        with pytest.raises(ControllerError) as info:
            labs_ctrl.update_lab(None, "Windows", new_lab(name="Mac"))
        assert error_fields(info) == {"name"}
        assert "Windows" in lab_names(session)

    def test_renaming_a_referenced_lab_is_blocked_and_lists_references(self, session):
        before = lab_names(session)
        with pytest.raises(ControllerError) as info:
            labs_ctrl.update_lab(None, "Linux", new_lab(name="Ubuntu"))
        assert error_fields(info) == {"name"}
        assert "still referenced by" in info.value.message and "CMSC" in info.value.message
        assert lab_names(session) == before

    def test_invalid_change_leaves_the_lab_untouched(self, session):
        original = lab(session, "Linux").capacity
        with pytest.raises(ControllerError):
            labs_ctrl.update_lab(None, "Linux", new_lab(name="Linux", capacity=0))
        assert lab(session, "Linux").capacity == original
        assert session.dirty is False

    def test_missing_lab_is_reported(self, session):
        with pytest.raises(ControllerError) as info:
            labs_ctrl.update_lab(None, "Nowhere", new_lab(name="Nowhere"))
        assert "no longer exists" in info.value.message


class TestLabDelete:
    def test_removes_an_unreferenced_lab(self, session):
        labs_ctrl.add_lab(None, new_lab())
        session.dirty = False
        labs_ctrl.delete_lab(None, "Windows")
        assert "Windows" not in lab_names(session)
        assert session.dirty is True

    def test_referenced_lab_is_blocked_and_nothing_changes(self, session):
        before = lab_names(session)
        with pytest.raises(ControllerError) as info:
            labs_ctrl.delete_lab(None, "Linux")
        assert "Cannot delete 'Linux'" in info.value.message
        assert "CMSC" in info.value.message
        assert lab_names(session) == before
        assert session.dirty is False

    def test_faculty_lab_preferences_count_as_references(self, session):
        blockers = labs_ctrl._references(session.config, "Mac")
        assert any("lab preference" in item for item in blockers)

    def test_stale_name_is_rejected(self, session):
        with pytest.raises(ControllerError):
            labs_ctrl.delete_lab(None, "Nowhere")


class TestLabRollback:
    def test_failed_whole_config_validation_is_reported_and_config_is_unchanged(self, session, monkeypatch):
        def reject(session_, config, area, mutate):
            raise ValidationFailure(area, "simulated whole-config rejection")

        monkeypatch.setattr(labs_ctrl, "apply_session_edit", reject)
        before = lab_names(session)
        with pytest.raises(ControllerError) as info:
            labs_ctrl.add_lab(None, new_lab())
        assert "simulated whole-config rejection" in info.value.message
        assert lab_names(session) == before
        assert session.dirty is False


class TestLabDescribe:
    def test_no_configuration(self, empty_session):
        assert labs_ctrl.describe_labs(None) == {"has_config": False}

    def test_lists_labs_with_availability_and_references(self, session):
        data = labs_ctrl.describe_labs(None)
        assert data["has_config"] is True
        assert [item["name"] for item in data["labs"]] == ["Linux", "Mac"]
        first = data["labs"][0]
        assert first["capacity"] == 28
        assert first["unrestricted"] is True and first["availability"] == []
        assert first["can_delete"] is False and first["referenced_by"]

    def test_new_lab_can_be_deleted(self, session):
        labs_ctrl.add_lab(None, new_lab())
        added = next(item for item in labs_ctrl.describe_labs(None)["labs"] if item["name"] == "Windows")
        assert added["can_delete"] is True and added["referenced_by"] == []

    def test_get_lab_and_missing_lab(self, session):
        assert labs_ctrl.get_lab(None, "Mac")["capacity"] == 28
        with pytest.raises(ControllerError):
            labs_ctrl.get_lab(None, "Nowhere")

    def test_saved_configuration_with_new_lab_reloads(self, session, tmp_path):
        labs_ctrl.add_lab(None, new_lab())
        path = tmp_path / "labs.json"
        session.save(str(path))
        reloaded = Session()
        reloaded.load(str(path))
        assert "Windows" in lab_names(reloaded)


# ====================================================================== #
#  Rooms and labs together
# ====================================================================== #
class TestRoomsAndLabsAreIndependent:
    def test_a_room_and_a_lab_may_be_added_in_the_same_session(self, session):
        rooms_ctrl.add_room(None, new_room())
        labs_ctrl.add_lab(None, new_lab())
        assert "Roddy 150" in room_names(session)
        assert "Windows" in lab_names(session)

    def test_a_failed_room_edit_does_not_touch_labs(self, session):
        labs_before = lab_names(session)
        with pytest.raises(ControllerError):
            rooms_ctrl.add_room(None, new_room(capacity=0))
        assert lab_names(session) == labs_before