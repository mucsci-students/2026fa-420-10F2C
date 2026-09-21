"""
Unit tests for timeslot CRUD (time_slot_config.times) and the global
timing options (max_time_gap / min_time_overlap) in app/commands.py.

Same design note as the other test_crud_*.py files: these substitute a
lightweight fake CombinedConfig honoring edit_mode()'s documented
contract (mutate a draft, commit only on a clean exit, leave the
original untouched on a raised ValidationError), so what's under test
is app/commands.py's own logic -- overlap detection, the "can't delete
the last block on a day" guard, index validation, rollback-on-failure
-- rather than the real library's exact validation rules.
"""
import copy
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import app.commands as commands
import app.crud as crud
from app.session import Session


class FakeValidationError(Exception):
    """Stand-in for scheduler.config.ValidationError -- patching
    app.crud.ValidationError to this class is enough for apply_edit()'s
    except clause to catch it (see test_crud_faculty.py for why)."""


class FakeTimeBlock:
    """Stand-in for scheduler.config.TimeBlock."""

    def __init__(self, start, end, spacing):
        self.start = start
        self.end = end
        self.spacing = spacing

    def __eq__(self, other):
        return isinstance(other, FakeTimeBlock) and self.__dict__ == other.__dict__

    def __repr__(self):
        return f"FakeTimeBlock({self.start}-{self.end}, spacing={self.spacing})"


class FakeCombinedConfig:
    """Mirrors edit_mode()'s documented contract: yields an
    independently-editable draft; commits back to self on a clean exit;
    leaves self untouched if the `with` block raises."""

    def __init__(self, times=None, max_time_gap=30, min_time_overlap=45, reject=False):
        self.time_slot_config = SimpleNamespace(
            times=dict(times or {}),
            max_time_gap=max_time_gap,
            min_time_overlap=min_time_overlap,
        )
        self.reject = reject

    @contextmanager
    def edit_mode(self):
        draft = FakeCombinedConfig(
            times=copy.deepcopy(self.time_slot_config.times),
            max_time_gap=self.time_slot_config.max_time_gap,
            min_time_overlap=self.time_slot_config.min_time_overlap,
        )
        yield draft
        if self.reject:
            raise FakeValidationError("simulated whole-config validation failure")
        self.time_slot_config.times = draft.time_slot_config.times
        self.time_slot_config.max_time_gap = draft.time_slot_config.max_time_gap
        self.time_slot_config.min_time_overlap = draft.time_slot_config.min_time_overlap


@pytest.fixture(autouse=True)
def patch_library_types(monkeypatch):
    monkeypatch.setattr(commands, "TimeBlock", FakeTimeBlock)
    monkeypatch.setattr(crud, "ValidationError", FakeValidationError)


def make_session(times=None, max_time_gap=30, min_time_overlap=45, reject=False):
    session = Session()
    session.config = FakeCombinedConfig(
        times=times, max_time_gap=max_time_gap, min_time_overlap=min_time_overlap, reject=reject
    )
    return session


def feed_inputs(monkeypatch, answers):
    it = iter(answers)

    def fake_input(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise AssertionError("input() was called more times than the test expected")

    monkeypatch.setattr("builtins.input", fake_input)


# ---------- add_timeslot ----------

def test_add_timeslot_happy_path(monkeypatch, capsys):
    session = make_session(times={})
    feed_inputs(monkeypatch, ["MON", "09:00", "17:00", "60"])

    commands.add_timeslot(session)

    blocks = session.config.time_slot_config.times["MON"]
    assert len(blocks) == 1
    assert blocks[0].start == "09:00"
    assert blocks[0].end == "17:00"
    assert blocks[0].spacing == 60
    assert "added successfully" in capsys.readouterr().out.lower()


def test_add_timeslot_rejects_invalid_day(monkeypatch, capsys):
    session = make_session(times={})
    feed_inputs(monkeypatch, ["FUNDAY"])

    commands.add_timeslot(session)

    assert session.config.time_slot_config.times == {}
    assert "not a valid day" in capsys.readouterr().out.lower()


def test_add_timeslot_rejects_overlap(monkeypatch, capsys):
    existing = FakeTimeBlock("09:00", "12:00", 30)
    session = make_session(times={"MON": [existing]})
    feed_inputs(monkeypatch, ["MON", "10:00", "13:00", "30"])  # overlaps 09:00-12:00

    commands.add_timeslot(session)

    assert session.config.time_slot_config.times["MON"] == [existing]
    assert "time conflict" in capsys.readouterr().out.lower()


def test_add_timeslot_rejects_bad_spacing(monkeypatch, capsys):
    session = make_session(times={})
    feed_inputs(monkeypatch, ["MON", "09:00", "17:00", "not-a-number"])

    commands.add_timeslot(session)

    assert session.config.time_slot_config.times == {}
    assert "not a valid number of minutes" in capsys.readouterr().out.lower()


# ---------- modify_timeslot ----------

def test_modify_timeslot_applies_valid_change(monkeypatch):
    original = FakeTimeBlock("09:00", "12:00", 30)
    session = make_session(times={"MON": [original]})
    feed_inputs(monkeypatch, ["MON", "0", "10:00", "14:00", "45"])

    commands.modify_timeslot(session)

    updated = session.config.time_slot_config.times["MON"][0]
    assert updated.start == "10:00"
    assert updated.end == "14:00"
    assert updated.spacing == 45


def test_modify_timeslot_rejects_overlap_with_another_block(monkeypatch, capsys):
    block_a = FakeTimeBlock("09:00", "11:00", 30)
    block_b = FakeTimeBlock("13:00", "15:00", 30)
    session = make_session(times={"MON": [block_a, block_b]})
    # try to move block_a (index 0) to overlap block_b
    feed_inputs(monkeypatch, ["MON", "0", "12:00", "14:00", "30"])

    commands.modify_timeslot(session)

    blocks = session.config.time_slot_config.times["MON"]
    assert blocks[0] is block_a  # unchanged
    assert blocks[0].start == "09:00"
    assert "time conflict" in capsys.readouterr().out.lower()


def test_modify_timeslot_no_blocks_on_day_is_a_no_op(monkeypatch, capsys):
    session = make_session(times={})
    feed_inputs(monkeypatch, ["TUE"])

    commands.modify_timeslot(session)

    assert "no time slots defined" in capsys.readouterr().out.lower()


def test_modify_timeslot_invalid_index_is_a_no_op(monkeypatch, capsys):
    original = FakeTimeBlock("09:00", "12:00", 30)
    session = make_session(times={"MON": [original]})
    feed_inputs(monkeypatch, ["MON", "5"])  # out of range

    commands.modify_timeslot(session)

    assert session.config.time_slot_config.times["MON"] == [original]
    assert "not a valid selection" in capsys.readouterr().out.lower()


# ---------- delete_timeslot ----------

def test_delete_timeslot_removes_confirmed_block(monkeypatch):
    block_a = FakeTimeBlock("09:00", "11:00", 30)
    block_b = FakeTimeBlock("13:00", "15:00", 30)
    session = make_session(times={"MON": [block_a, block_b]})
    feed_inputs(monkeypatch, ["MON", "0", "confirm"])

    commands.delete_timeslot(session)

    assert session.config.time_slot_config.times["MON"] == [block_b]


def test_delete_timeslot_cancel_keeps_block(monkeypatch):
    block_a = FakeTimeBlock("09:00", "11:00", 30)
    block_b = FakeTimeBlock("13:00", "15:00", 30)
    session = make_session(times={"MON": [block_a, block_b]})
    feed_inputs(monkeypatch, ["MON", "0", "cancel"])

    commands.delete_timeslot(session)

    assert session.config.time_slot_config.times["MON"] == [block_a, block_b]


def test_delete_timeslot_blocked_when_only_one_remains(monkeypatch, capsys):
    only_block = FakeTimeBlock("09:00", "17:00", 60)
    session = make_session(times={"MON": [only_block]})
    feed_inputs(monkeypatch, ["MON"])  # returns before asking which index / confirming

    commands.delete_timeslot(session)

    assert session.config.time_slot_config.times["MON"] == [only_block]
    assert "every weekday needs at least one" in capsys.readouterr().out.lower()


# ---------- modify_timing_options ----------

def test_modify_timing_options_updates_both_values(monkeypatch):
    session = make_session(max_time_gap=30, min_time_overlap=45)
    feed_inputs(monkeypatch, ["20", "60"])

    commands.modify_timing_options(session)

    assert session.config.time_slot_config.max_time_gap == 20
    assert session.config.time_slot_config.min_time_overlap == 60


def test_modify_timing_options_blank_keeps_current_values(monkeypatch):
    session = make_session(max_time_gap=30, min_time_overlap=45)
    feed_inputs(monkeypatch, ["", ""])

    commands.modify_timing_options(session)

    assert session.config.time_slot_config.max_time_gap == 30
    assert session.config.time_slot_config.min_time_overlap == 45


def test_modify_timing_options_rejects_non_numeric_input(monkeypatch, capsys):
    session = make_session(max_time_gap=30, min_time_overlap=45)
    feed_inputs(monkeypatch, ["not-a-number", "60"])

    commands.modify_timing_options(session)

    # nothing should have been touched
    assert session.config.time_slot_config.max_time_gap == 30
    assert session.config.time_slot_config.min_time_overlap == 45
    assert "please enter whole numbers" in capsys.readouterr().out.lower()


def test_modify_timing_options_rolls_back_on_validation_failure(monkeypatch, capsys):
    session = make_session(max_time_gap=30, min_time_overlap=45, reject=True)
    feed_inputs(monkeypatch, ["20", "60"])

    commands.modify_timing_options(session)

    assert session.config.time_slot_config.max_time_gap == 30
    assert session.config.time_slot_config.min_time_overlap == 45
    assert "could not update timing options" in capsys.readouterr().out.lower()