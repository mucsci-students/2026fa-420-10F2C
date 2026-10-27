"""
Unit tests for app/history.py (Sprint 2 Sections 11, 12, 23.2).

These need no Django and no scheduler library: a tiny fake configuration and a
fake session stand in, so they exercise only the undo/redo rules themselves.
"""

import pytest

from app.commands.common import apply_session_edit
from app.history import ConfigHistory, HistoryError
from tests.fakes import FakeConfig, course, room


class FakeSession:
    def __init__(self):
        self.config = FakeConfig(rooms=[room("A")])
        self.dirty = False
        self.history = ConfigHistory()


def rooms_of(session):
    return [item.name for item in session.config.config.rooms]


def edit(session, label, names):
    """Do what apply_session_edit() does around a successful edit."""
    before = session.history.capture(session.config)
    dirty_before = session.dirty
    session.config.config.rooms = [room(name) for name in names]
    session.history.record(label, before, dirty_before, after=session.config)
    session.dirty = True


def test_a_new_history_has_nothing_to_undo_or_redo():
    history = ConfigHistory()
    assert not history.can_undo and not history.can_redo
    assert history.undo_label is None and history.redo_label is None


def test_undo_restores_the_earlier_configuration_and_names_the_change():
    session = FakeSession()
    edit(session, "Add room 'B'", ["A", "B"])
    assert session.history.undo_label == "Add room 'B'"
    assert session.history.undo(session) == "Add room 'B'"
    assert rooms_of(session) == ["A"]


def test_redo_reapplies_what_was_undone():
    session = FakeSession()
    edit(session, "Add room 'B'", ["A", "B"])
    session.history.undo(session)
    assert session.history.redo_label == "Add room 'B'"
    session.history.redo(session)
    assert rooms_of(session) == ["A", "B"]


def test_several_undos_walk_back_in_order():
    session = FakeSession()
    edit(session, "one", ["A", "1"])
    edit(session, "two", ["A", "1", "2"])
    edit(session, "three", ["A", "1", "2", "3"])
    assert session.history.undo(session) == "three"
    assert session.history.undo(session) == "two"
    assert rooms_of(session) == ["A", "1"]
    assert session.history.undo(session) == "one"
    assert rooms_of(session) == ["A"]
    assert not session.history.can_undo


def test_a_new_edit_clears_redo():
    session = FakeSession()
    edit(session, "one", ["A", "1"])
    session.history.undo(session)
    assert session.history.can_redo
    edit(session, "other", ["A", "x"])
    assert not session.history.can_redo


def test_undo_and_redo_on_empty_history_raise_a_clear_error():
    session = FakeSession()
    with pytest.raises(HistoryError, match="nothing to undo"):
        session.history.undo(session)
    with pytest.raises(HistoryError, match="nothing to redo"):
        session.history.redo(session)


def test_snapshots_are_independent_copies():
    session = FakeSession()
    edit(session, "one", ["A", "1"])
    session.history.undo(session)
    session.config.config.rooms.append(room("changed after undo"))
    session.history.redo(session)
    assert rooms_of(session) == ["A", "1"]


def test_only_the_newest_entries_are_kept():
    session = FakeSession()
    session.history = ConfigHistory(limit=3)
    for number in range(5):
        edit(session, f"edit {number}", ["A", str(number)])
    assert session.history.state()["undo_count"] == 3
    assert session.history.undo_label == "edit 4"


def test_undoing_back_to_a_clean_state_clears_the_unsaved_flag():
    session = FakeSession()
    edit(session, "one", ["A", "1"])
    assert session.dirty is True
    session.history.undo(session)
    assert session.dirty is False
    session.history.redo(session)
    assert session.dirty is True


def test_after_a_save_older_states_count_as_unsaved():
    session = FakeSession()
    edit(session, "one", ["A", "1"])
    session.history.mark_saved()  # what Session.save()/mark_saved() do
    session.dirty = False
    session.history.undo(session)
    assert session.dirty is True  # the saved file still has the edit in it


def test_clear_forgets_everything():
    session = FakeSession()
    edit(session, "one", ["A", "1"])
    session.history.undo(session)
    session.history.clear()
    assert not session.history.can_undo and not session.history.can_redo


def test_state_describes_both_buttons():
    session = FakeSession()
    edit(session, "one", ["A", "1"])
    state = session.history.state()
    assert state["can_undo"] and state["undo_label"] == "one"
    assert not state["can_redo"] and state["redo_label"] is None


# ---------------------------------------------------------------------- #
#  Versions, tokens, jumping, descriptions, and the inline Undo offer
# ---------------------------------------------------------------------- #
def test_every_state_has_its_own_version_and_undo_restores_the_old_one():
    session = FakeSession()
    first = session.history.version
    edit(session, "one", ["A", "1"])
    second = session.history.version
    assert second != first
    session.history.undo(session)
    assert session.history.version == first  # back to exactly the earlier state
    session.history.redo(session)
    assert session.history.version == second


def test_two_histories_never_share_a_version():
    assert ConfigHistory().version != ConfigHistory().version


def test_a_stale_token_refuses_to_undo_or_redo():
    session = FakeSession()
    edit(session, "one", ["A", "1"])
    stale = session.history.version - 1
    with pytest.raises(HistoryError, match="changed since"):
        session.history.undo(session, expected=stale)
    assert rooms_of(session) == ["A", "1"]  # nothing was undone
    session.history.undo(
        session, expected=session.history.version
    )  # the right token works
    with pytest.raises(HistoryError, match="changed since"):
        session.history.redo(session, expected="0")


def test_go_to_undoes_everything_after_an_entry_and_can_come_back():
    session = FakeSession()
    edit(session, "one", ["A", "1"])
    edit(session, "two", ["A", "1", "2"])
    edit(session, "three", ["A", "1", "2", "3"])
    state = session.history.state()
    rows = {row["label"]: row for row in state["undo_entries"]}
    assert [row["label"] for row in state["undo_entries"]] == ["three", "two", "one"]
    assert rows["two"]["steps"] == 2

    labels = session.history.go_to(session, rows["two"]["id"])
    assert labels == ["three", "two"]
    assert rooms_of(session) == ["A", "1"]  # just before "two"
    assert session.history.undo_label == "one"

    redo_rows = {row["label"]: row for row in session.history.state()["redo_entries"]}
    assert session.history.go_to(session, redo_rows["three"]["id"]) == ["two", "three"]
    assert rooms_of(session) == ["A", "1", "2", "3"]


def test_go_to_an_unknown_entry_changes_nothing():
    session = FakeSession()
    edit(session, "one", ["A", "1"])
    with pytest.raises(HistoryError, match="does not exist"):
        session.history.go_to(session, 99999999)
    with pytest.raises(HistoryError, match="does not exist"):
        session.history.go_to(session, "not a number")
    assert rooms_of(session) == ["A", "1"]


def test_the_inline_undo_offer_is_given_once_after_an_edit():
    session = FakeSession()
    assert session.history.take_fresh() is None
    edit(session, "Add room 'B'", ["A", "B"])
    offer = session.history.take_fresh()
    assert offer is not None
    assert (
        offer["label"] == "Add room 'B'" and offer["token"] == session.history.version
    )
    assert session.history.take_fresh() is None  # consumed
    edit(session, "two", ["A", "B", "C"])
    session.history.undo(session)
    assert session.history.take_fresh() is None  # an undo is not offered an undo


def test_the_history_state_describes_each_change():
    session = FakeSession()
    edit(session, "Delete room 'A'", [])
    row = session.history.state()["undo_entries"][0]
    assert row["label"] == "Delete room 'A'"
    assert row["summary"] == "Removed room A"
    assert row["steps"] == 1 and row["when"]


def test_an_edit_without_a_label_is_named_after_what_it_changed():
    session = FakeSession()
    before = session.history.capture(session.config)
    session.config.config.rooms = [room("A"), room("B")]
    entry = session.history.record(
        None, before, False, after=session.config, area="room"
    )
    assert entry is not None
    assert entry.label == "Added room B"


def test_an_edit_that_changed_nothing_is_not_remembered():
    session = FakeSession()
    edit(session, "one", ["A", "1"])
    session.history.undo(session)
    version = session.history.version
    before = session.history.capture(session.config)
    assert (
        session.history.record("Edit room 'A'", before, False, after=session.config)
        is None
    )
    assert not session.history.can_undo
    assert session.history.can_redo  # redo is kept, as nothing new happened
    assert session.history.version == version
    assert session.history.take_fresh() is None  # and no Undo is offered


def test_a_very_long_description_is_shortened_for_the_label():
    session = FakeSession()
    session.config.config.courses = [course(f"CMSC {n}", credits=1) for n in range(40)]
    before = session.history.capture(session.config)
    session.config.config.courses = [course(f"CMSC {n}", credits=2) for n in range(40)]
    session.config.config.rooms = [room("B")]
    entry = session.history.record(None, before, False, after=session.config)
    assert entry is not None
    assert len(entry.label) <= 70 and entry.summary.startswith("Removed room A")


def test_only_the_parts_that_changed_are_remembered():
    session = FakeSession()
    edit(session, "one", ["A", "1"])
    assert session.history._undo[-1].memento.areas == ["rooms"]


def test_a_restore_the_library_refuses_changes_nothing_and_keeps_the_entry():
    session = FakeSession()
    edit(session, "one", ["A", "1"])
    session.config.refuse_edits = True
    with pytest.raises(HistoryError, match="could not be restored"):
        session.history.undo(session)
    assert rooms_of(session) == ["A", "1"]
    assert session.history.can_undo and not session.history.can_redo
    session.config.refuse_edits = False
    assert session.history.undo(session) == "one"
    assert rooms_of(session) == ["A"]


def test_a_change_to_several_parts_is_one_step():
    session = FakeSession()
    session.config.config.courses = [course("CMSC 140", rooms=["A"])]
    before = session.history.capture(session.config)
    session.config.config.rooms = []
    session.config.config.courses = [course("CMSC 140", rooms=[])]
    session.history.record("Delete room 'A'", before, False, after=session.config)
    entry = session.history._undo[-1]
    assert entry.memento.areas == ["rooms", "courses"]
    session.history.undo(session)
    assert rooms_of(session) == ["A"]
    assert session.config.config.courses == [course("CMSC 140", rooms=["A"])]


def test_submitting_an_edit_with_no_change_adds_no_history_and_leaves_the_flag_alone():
    session = FakeSession()
    apply_session_edit(
        session, session.config, "room", lambda draft: None, label="Edit room 'A'"
    )
    assert not session.history.can_undo and session.dirty is False

    def same_values(draft):
        draft.config.rooms[:] = [room("A")]  # rewritten, but identical

    apply_session_edit(session, session.config, "room", same_values)
    assert not session.history.can_undo and session.dirty is False


def test_a_real_edit_still_counts():
    session = FakeSession()
    apply_session_edit(
        session,
        session.config,
        "room",
        lambda draft: draft.config.rooms.append(room("B")),
        label="Add room 'B'",
    )
    assert session.history.undo_label == "Add room 'B'" and session.dirty is True
