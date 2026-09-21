
"""
Unit tests for meeting CRUD in app/commands.py.
 
Meetings live nested inside each class pattern's `meetings` list
(confirmed in config_example.json: time_slot_config.classes[].meetings),
so add/modify/delete all work by first picking a pattern (by index),
then a meeting within it (also by index) -- same index-based approach
already used for pattern CRUD itself, since meetings have no name/id
field either.
 
Same design note as test_crud_faculty.py: these tests substitute a
lightweight fake CombinedConfig honoring edit_mode()'s documented
contract, so what's under test is app/commands.py's own logic (picking
the right pattern/meeting, the "can't delete the last meeting" guard,
rollback-on-failure) rather than the real library's exact validation
rules.
"""
from contextlib import contextmanager
from types import SimpleNamespace
 
import pytest
 
import app.commands as commands
import app.crud as crud
from app.session import Session
 
 
class FakeValidationError(Exception):
    """Stand-in for scheduler.config.ValidationError -- see
    test_crud_faculty.py for why patching app.crud.ValidationError is
    enough to make apply_edit()'s except clause catch it."""
 
 
class FakeMeeting:
    """Stand-in for scheduler.config.Meeting."""
 
    def __init__(self, **kwargs):
        """Store arbitrary meeting fields on the fake model."""
        self.__dict__.update(kwargs)
 
 
class FakePattern:
    """Stand-in for one time_slot_config.classes[] entry. Needs credits
    too (not just meetings) since _list_patterns()/_format_pattern()
    print it when showing which pattern to pick."""
 
    def __init__(self, meetings=None, credits=3):
        """Create a pattern with the fields used by meeting commands."""
        self.meetings = list(meetings or [])
        self.credits = credits
        self.start_time = None
        self.disabled = False
 
 
class FakeCombinedConfig:
    """Mirrors edit_mode()'s documented contract: yields an
    independently-editable draft; commits back to self on a clean exit;
    leaves self untouched if the `with` block raises."""
 
    def __init__(self, classes=None, reject=False):
        """Create a fake configuration that can optionally reject edits."""
        self.time_slot_config = SimpleNamespace(classes=list(classes or []))
        self.reject = reject
 
    @contextmanager
    def edit_mode(self):
        """Yield a draft and commit it only when validation succeeds."""
        import copy
        draft = FakeCombinedConfig(classes=copy.deepcopy(self.time_slot_config.classes))
        yield draft
        if self.reject:
            raise FakeValidationError("simulated whole-config validation failure")
        self.time_slot_config.classes = draft.time_slot_config.classes
 
 
@pytest.fixture(autouse=True)
def patch_library_types(monkeypatch):
    """Replace external scheduler types with controlled test doubles."""
    monkeypatch.setattr(commands, "Meeting", FakeMeeting)
    monkeypatch.setattr(crud, "ValidationError", FakeValidationError)
 
 
def make_session(classes=None, reject=False):
    """Build a session containing the fake configuration under test."""
    session = Session()
    session.config = FakeCombinedConfig(classes=classes, reject=reject)
    return session
 
 
def feed_inputs(monkeypatch, answers):
    """Make input() return each supplied answer in order."""
    it = iter(answers)
 
    def fake_input(prompt=""):
        """Return the next answer or fail on an unexpected prompt."""
        try:
            return next(it)
        except StopIteration:
            raise AssertionError("input() was called more times than the test expected")
 
    monkeypatch.setattr("builtins.input", fake_input)
 
 
def _meeting_answers(day="MON", duration="150", lab="n", delivery="in_person", start_time=""):
    """Return prompt responses for the fields of one meeting."""
    return [day, duration, lab, delivery, start_time]
 
 
# ---------- add_meeting ----------
 
def test_add_meeting_happy_path(monkeypatch, capsys):
    """Add a valid meeting to the selected class pattern."""
    pattern = FakePattern(meetings=[FakeMeeting(day="MON", duration=150, lab=False,
                                                 delivery="in_person", start_time=None)])
    session = make_session(classes=[pattern])
    feed_inputs(monkeypatch, ["0"] + _meeting_answers("WED", "75", "y", "in_person", "10:00"))
 
    commands.add_meeting(session)
 
    meetings = session.config.time_slot_config.classes[0].meetings
    assert len(meetings) == 2
    added = meetings[1]
    assert added.day == "WED"
    assert added.duration == 75
    assert added.lab is True
    assert added.start_time == "10:00"
    assert "meeting added" in capsys.readouterr().out.lower()
 
 
def test_add_meeting_no_patterns_is_a_no_op(monkeypatch, capsys):
    """Leave the configuration unchanged when no pattern exists."""
    session = make_session(classes=[])
    feed_inputs(monkeypatch, [])
 
    commands.add_meeting(session)
 
    assert session.config.time_slot_config.classes == []
    assert "add a class pattern first" in capsys.readouterr().out.lower()
 
 
def test_add_meeting_rolls_back_on_validation_failure(monkeypatch, capsys):
    """Discard a new meeting when whole-config validation fails."""
    pattern = FakePattern(meetings=[FakeMeeting(day="MON", duration=150, lab=False,
                                                 delivery="in_person", start_time=None)])
    session = make_session(classes=[pattern], reject=True)
    feed_inputs(monkeypatch, ["0"] + _meeting_answers("WED"))
 
    commands.add_meeting(session)
 
    assert len(session.config.time_slot_config.classes[0].meetings) == 1
    assert "could not add meeting" in capsys.readouterr().out.lower()
 
 
# ---------- modify_meeting ----------
 
def test_modify_meeting_applies_valid_change(monkeypatch):
    """Replace the selected meeting with valid edited values."""
    pattern = FakePattern(meetings=[
        FakeMeeting(day="MON", duration=150, lab=False, delivery="in_person", start_time=None),
        FakeMeeting(day="WED", duration=75, lab=True, delivery="in_person", start_time="10:00"),
    ])
    session = make_session(classes=[pattern])
    feed_inputs(monkeypatch, ["0", "1"] + _meeting_answers("THU", "90", "n", "online", ""))
 
    commands.modify_meeting(session)
 
    meetings = session.config.time_slot_config.classes[0].meetings
    assert len(meetings) == 2
    assert meetings[1].day == "THU"
    assert meetings[1].duration == 90
    assert meetings[1].delivery == "online"
 
 
def test_modify_meeting_restores_previous_state_on_invalid_edit(monkeypatch, capsys):
    """Preserve the original meeting when an edit is rejected."""
    original = FakeMeeting(day="MON", duration=150, lab=False, delivery="in_person", start_time=None)
    pattern = FakePattern(meetings=[original])
    session = make_session(classes=[pattern], reject=True)
    feed_inputs(monkeypatch, ["0", "0"] + _meeting_answers("THU", "90"))
 
    commands.modify_meeting(session)
 
    meetings = session.config.time_slot_config.classes[0].meetings
    assert meetings == [original]
    assert meetings[0].day == "MON"
    assert "previous version kept" in capsys.readouterr().out.lower()
 
 
def test_modify_meeting_invalid_pattern_index_is_a_no_op(monkeypatch, capsys):
    """Reject an out-of-range pattern selection without mutation."""
    pattern = FakePattern(meetings=[FakeMeeting(day="MON", duration=150, lab=False,
                                                 delivery="in_person", start_time=None)])
    session = make_session(classes=[pattern])
    feed_inputs(monkeypatch, ["5"])  # out of range -- only pattern 0 exists
 
    commands.modify_meeting(session)
 
    assert len(session.config.time_slot_config.classes[0].meetings) == 1
    assert "no pattern at index" in capsys.readouterr().out.lower()
 
 
# ---------- delete_meeting ----------
 
def test_delete_meeting_removes_confirmed_record(monkeypatch):
    """Remove the selected meeting after confirmation."""
    pattern = FakePattern(meetings=[
        FakeMeeting(day="MON", duration=150, lab=False, delivery="in_person", start_time=None),
        FakeMeeting(day="WED", duration=75, lab=True, delivery="in_person", start_time=None),
    ])
    session = make_session(classes=[pattern])
    feed_inputs(monkeypatch, ["0", "1", "y"])
 
    commands.delete_meeting(session)
 
    meetings = session.config.time_slot_config.classes[0].meetings
    assert len(meetings) == 1
    assert meetings[0].day == "MON"
 
 
def test_delete_meeting_cancel_keeps_record(monkeypatch):
    """Keep all meetings when deletion is not confirmed."""
    pattern = FakePattern(meetings=[
        FakeMeeting(day="MON", duration=150, lab=False, delivery="in_person", start_time=None),
        FakeMeeting(day="WED", duration=75, lab=True, delivery="in_person", start_time=None),
    ])
    session = make_session(classes=[pattern])
    feed_inputs(monkeypatch, ["0", "1", "n"])
 
    commands.delete_meeting(session)
 
    assert len(session.config.time_slot_config.classes[0].meetings) == 2
 
 
def test_delete_meeting_blocked_when_only_one_remains(monkeypatch, capsys):
    """Prevent deletion of a pattern's only meeting."""
    pattern = FakePattern(meetings=[FakeMeeting(day="MON", duration=150, lab=False,
                                                 delivery="in_person", start_time=None)])
    session = make_session(classes=[pattern])
    feed_inputs(monkeypatch, ["0"])  # returns before asking which meeting / confirming
 
    commands.delete_meeting(session)
 
    assert len(session.config.time_slot_config.classes[0].meetings) == 1
    assert "can't delete the only meeting" in capsys.readouterr().out.lower()
 
 
def test_delete_meeting_rolls_back_on_validation_failure(monkeypatch, capsys):
    """Restore a deleted meeting when validation rejects the draft."""
    pattern = FakePattern(meetings=[
        FakeMeeting(day="MON", duration=150, lab=False, delivery="in_person", start_time=None),
        FakeMeeting(day="WED", duration=75, lab=True, delivery="in_person", start_time=None),
    ])
    session = make_session(classes=[pattern], reject=True)
    feed_inputs(monkeypatch, ["0", "1", "y"])
 
    commands.delete_meeting(session)
 
    assert len(session.config.time_slot_config.classes[0].meetings) == 2
    assert "could not remove meeting" in capsys.readouterr().out.lower()
 