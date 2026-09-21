"""
Unit tests for class-pattern CRUD (time_slot_config.classes) in
app/commands.py.

Patterns have no name/id field (confirmed against config_example.json),
so add/modify/delete identify one by its position in the list -- same
design as meetings. Each pattern also owns a list of meetings, built
through the same _prompt_meeting() used by meeting CRUD, so these tests
feed a full meeting's worth of answers (day/duration/lab/delivery/
start_time) every time a pattern is created or replaced.

Same fake-CombinedConfig approach as the other test_crud_*.py files:
mirrors edit_mode()'s documented contract so what's under test is
app/commands.py's own logic (credits/meetings validation, rollback-on-
failure) rather than the real library's exact validation rules.
"""
import copy
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import app.commands as commands
import app.crud as crud
from app.session import Session


class FakeValidationError(Exception):
    """Stand-in for scheduler.config.ValidationError."""


class FakeMeeting:
    """Stand-in for scheduler.config.Meeting."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __eq__(self, other):
        return isinstance(other, FakeMeeting) and self.__dict__ == other.__dict__

    def __repr__(self):
        return f"FakeMeeting({self.__dict__})"


class FakeClassPattern:
    """Stand-in for scheduler.config.ClassPattern."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __eq__(self, other):
        return isinstance(other, FakeClassPattern) and self.__dict__ == other.__dict__

    def __repr__(self):
        return f"FakeClassPattern({self.__dict__})"


class FakeCombinedConfig:
    """Mirrors edit_mode()'s documented contract: yields an
    independently-editable draft; commits back to self on a clean exit;
    leaves self untouched if the `with` block raises."""

    def __init__(self, classes=None, reject=False):
        self.time_slot_config = SimpleNamespace(classes=list(classes or []))
        self.reject = reject

    @contextmanager
    def edit_mode(self):
        draft = FakeCombinedConfig(classes=copy.deepcopy(self.time_slot_config.classes))
        yield draft
        if self.reject:
            raise FakeValidationError("simulated whole-config validation failure")
        self.time_slot_config.classes = draft.time_slot_config.classes


@pytest.fixture(autouse=True)
def patch_library_types(monkeypatch):
    monkeypatch.setattr(commands, "Meeting", FakeMeeting)
    monkeypatch.setattr(commands, "ClassPattern", FakeClassPattern)
    monkeypatch.setattr(crud, "ValidationError", FakeValidationError)


def make_session(classes=None, reject=False):
    session = Session()
    session.config = FakeCombinedConfig(classes=classes, reject=reject)
    return session


def feed_inputs(monkeypatch, answers):
    it = iter(answers)

    def fake_input(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise AssertionError("input() was called more times than the test expected")

    monkeypatch.setattr("builtins.input", fake_input)


def _one_meeting_answers(day="MON", duration="150", lab="n", delivery="in_person", start_time=""):
    """Inputs for a single _prompt_meeting() call."""
    return [day, duration, lab, delivery, start_time]


def _pattern_answers(credits="3", meeting_answers=None, add_another="n",
                      pattern_start_time="", disabled="n"):
    """Inputs for one full _prompt_pattern_fields() call: credits, one
    meeting, whether to add another (n = just the one), a fixed start
    time for the pattern, and whether it starts disabled."""
    meeting_answers = meeting_answers or _one_meeting_answers()
    return [credits] + meeting_answers + [add_another, pattern_start_time, disabled]


def _existing_pattern(credits=3, meetings=None, start_time=None, disabled=False):
    return FakeClassPattern(
        credits=credits,
        meetings=meetings or [FakeMeeting(day="MON", duration=150, lab=False,
                                           delivery="in_person", start_time=None)],
        start_time=start_time,
        disabled=disabled,
    )


# ---------- add_pattern ----------

def test_add_pattern_happy_path(monkeypatch, capsys):
    session = make_session(classes=[])
    feed_inputs(monkeypatch, _pattern_answers())

    commands.add_pattern(session)

    patterns = session.config.time_slot_config.classes
    assert len(patterns) == 1
    assert patterns[0].credits == 3
    assert len(patterns[0].meetings) == 1
    assert patterns[0].meetings[0].day == "MON"
    assert "class pattern added" in capsys.readouterr().out.lower()


def test_add_pattern_with_multiple_meetings(monkeypatch):
    session = make_session(classes=[])
    feed_inputs(monkeypatch, [
        "4",
        *_one_meeting_answers("MON", "110", "y", "in_person", ""),
        "y",  # add another
        *_one_meeting_answers("WED", "110", "y", "in_person", ""),
        "n",  # stop
        "",   # pattern start_time
        "n",  # not disabled
    ])

    commands.add_pattern(session)

    pattern = session.config.time_slot_config.classes[0]
    assert len(pattern.meetings) == 2
    assert [m.day for m in pattern.meetings] == ["MON", "WED"]


def test_add_pattern_rejects_zero_credits(monkeypatch, capsys):
    session = make_session(classes=[])
    feed_inputs(monkeypatch, _pattern_answers(credits="0"))

    commands.add_pattern(session)

    assert session.config.time_slot_config.classes == []
    assert "must be a positive integer" in capsys.readouterr().out.lower()


def test_add_pattern_rolls_back_on_validation_failure(monkeypatch, capsys):
    session = make_session(classes=[], reject=True)
    feed_inputs(monkeypatch, _pattern_answers())

    commands.add_pattern(session)

    assert session.config.time_slot_config.classes == []
    assert "could not add pattern" in capsys.readouterr().out.lower()


# ---------- modify_pattern ----------

def test_modify_pattern_applies_valid_change(monkeypatch):
    session = make_session(classes=[_existing_pattern(credits=3)])
    feed_inputs(monkeypatch, ["0"] + _pattern_answers(credits="4", meeting_answers=_one_meeting_answers("THU", "90")))

    commands.modify_pattern(session)

    patterns = session.config.time_slot_config.classes
    assert len(patterns) == 1
    assert patterns[0].credits == 4
    assert patterns[0].meetings[0].day == "THU"


def test_modify_pattern_rejects_zero_credits(monkeypatch, capsys):
    original = _existing_pattern(credits=3)
    session = make_session(classes=[original])
    feed_inputs(monkeypatch, ["0"] + _pattern_answers(credits="0"))

    commands.modify_pattern(session)

    assert session.config.time_slot_config.classes == [original]
    assert "must be a positive integer" in capsys.readouterr().out.lower()


def test_modify_pattern_invalid_index_is_a_no_op(monkeypatch, capsys):
    original = _existing_pattern()
    session = make_session(classes=[original])
    feed_inputs(monkeypatch, ["5"])  # out of range -- only index 0 exists

    commands.modify_pattern(session)

    assert session.config.time_slot_config.classes == [original]
    assert "no pattern at index" in capsys.readouterr().out.lower()


def test_modify_pattern_restores_previous_state_on_invalid_edit(monkeypatch, capsys):
    original = _existing_pattern(credits=3)
    session = make_session(classes=[original], reject=True)
    feed_inputs(monkeypatch, ["0"] + _pattern_answers(credits="4"))

    commands.modify_pattern(session)

    patterns = session.config.time_slot_config.classes
    assert patterns == [original]
    assert patterns[0].credits == 3
    assert "previous version kept" in capsys.readouterr().out.lower()


# ---------- delete_pattern ----------

def test_delete_pattern_removes_confirmed_record(monkeypatch):
    pattern_a = _existing_pattern(credits=3)
    pattern_b = _existing_pattern(credits=4)
    session = make_session(classes=[pattern_a, pattern_b])
    feed_inputs(monkeypatch, ["0", "y"])

    commands.delete_pattern(session)

    assert session.config.time_slot_config.classes == [pattern_b]


def test_delete_pattern_cancel_keeps_record(monkeypatch):
    pattern_a = _existing_pattern(credits=3)
    session = make_session(classes=[pattern_a])
    feed_inputs(monkeypatch, ["0", "n"])

    commands.delete_pattern(session)

    assert session.config.time_slot_config.classes == [pattern_a]


def test_delete_pattern_no_patterns_is_a_no_op(monkeypatch, capsys):
    session = make_session(classes=[])
    feed_inputs(monkeypatch, [])

    commands.delete_pattern(session)

    assert session.config.time_slot_config.classes == []
    assert "no class patterns defined" in capsys.readouterr().out.lower()


def test_delete_pattern_rolls_back_on_validation_failure(monkeypatch, capsys):
    pattern_a = _existing_pattern(credits=3)
    session = make_session(classes=[pattern_a], reject=True)
    feed_inputs(monkeypatch, ["0", "y"])

    commands.delete_pattern(session)

    assert session.config.time_slot_config.classes == [pattern_a]
    assert "could not remove pattern" in capsys.readouterr().out.lower()