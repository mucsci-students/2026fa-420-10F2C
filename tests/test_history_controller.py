"""
Tests for gui/controllers/history_controller.py (Sprint 2 Sections 8, 11, 12, 20):
what the Undo / Redo / "go back" / "Restore previous" buttons do, and what they
say when they cannot. They use the shipped example configuration.
"""

import pytest

from app.commands.common import apply_session_edit
from app.session import Session
from gui.controllers import history_controller as ctrl
from gui.controllers.errors import ControllerError
from gui.session_store import EXAMPLE_CONFIG_PATH


@pytest.fixture
def session(monkeypatch):
    loaded = Session()
    loaded.load(str(EXAMPLE_CONFIG_PATH))
    monkeypatch.setattr(ctrl, "get_session", lambda request: loaded)
    return loaded


def rename_first_room(session, name):
    def mutate(draft):
        draft.config.rooms[0].capacity = sum(
            map(ord, name)
        )  # a different value for each name

    apply_session_edit(session, session.config, "room", mutate, label=name)


def test_undo_and_redo_report_what_they_reversed(session):
    rename_first_room(session, "one")
    assert ctrl.undo(None) == "one"
    assert ctrl.redo(None) == "one"


def test_the_token_the_page_was_drawn_from_is_checked(session):
    rename_first_room(session, "one")
    state = ctrl.describe_history(None)
    with pytest.raises(ControllerError, match="changed since"):
        ctrl.undo(None, token="0")
    assert session.history.can_undo  # nothing happened
    assert ctrl.undo(None, token=state["token"]) == "one"


def test_nothing_to_undo_is_explained(session):
    with pytest.raises(ControllerError, match="nothing to undo"):
        ctrl.undo(None)
    with pytest.raises(ControllerError, match="nothing to redo"):
        ctrl.redo(None)


def test_without_a_configuration_there_is_nothing_to_undo(monkeypatch):
    empty = Session()
    monkeypatch.setattr(ctrl, "get_session", lambda request: empty)
    with pytest.raises(ControllerError, match="No configuration is loaded"):
        ctrl.undo(None)


def test_go_to_returns_the_labels_it_moved_over(session):
    for name in ("one", "two", "three"):
        rename_first_room(session, name)
    oldest = ctrl.describe_history(None)["undo_entries"][-1]
    assert ctrl.go_to(None, oldest["id"]) == ["three", "two", "one"]
    with pytest.raises(ControllerError, match="does not exist"):
        ctrl.go_to(None, "nonsense")


def test_restore_previous_names_what_came_back(session):
    first_name = session.config_name
    session.new_config()
    previous = ctrl.describe_previous(None)
    assert previous is not None
    assert previous["name"] == first_name
    assert ctrl.restore_previous(None) == first_name


def test_restore_previous_with_nothing_kept_explains(session):
    assert ctrl.describe_previous(None) is None
    with pytest.raises(ControllerError, match="no previous configuration"):
        ctrl.restore_previous(None)


def test_restore_previous_waits_for_a_running_generation(session):
    session.new_config()
    session.generating = True
    with pytest.raises(ControllerError, match="being generated"):
        ctrl.restore_previous(None)
    assert session.previous is not None  # still there for later
