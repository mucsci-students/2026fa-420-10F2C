"""
Tests for faculty CRUD in app/commands.py.

Two sections, deliberately separated by class, not just by test:

  TestFacultyCRUDLogic -- runs against a lightweight fake
  CombinedConfig/FacultyConfig that honors the *documented contract* of
  edit_mode() from app/crud.py's own comments (mutate a draft, commit
  only on a clean exit, leave the original completely untouched if the
  block raises). What's under test here is app/commands.py's OWN logic:
  duplicate/blank name checks, delete confirmation, the
  reference-check-before-delete, rollback-on-failure, and what gets
  passed into FacultyConfig(**fields) -- including whether
  mandatory_days/maximum_days are included or correctly omitted. This
  can't tell you whether the real scheduler.config.FacultyConfig
  actually accepts those field names.

  TestFacultyDayLimitsAgainstRealLibrary -- runs against the REAL,
  installed scheduler.config.FacultyConfig and CombinedConfig, no
  patching at all. This is what actually confirms mandatory_days and
  maximum_days are real, accepted fields under these names/types, and
  that a config carrying them serializes and reloads correctly.

IMPORTANT: the autouse patch fixture below (_patch_library_types) is
scoped to TestFacultyCRUDLogic specifically, via a fixture defined
INSIDE that class. Do not hoist it back to module level -- that would
silently patch the real library out from under
TestFacultyDayLimitsAgainstRealLibrary too, and its tests would go back
to "passing" without checking anything real, with no visible sign that
happened.
"""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.commands as commands
import app.crud as crud
from app.session import Session

_EXAMPLE_CONFIG = "app/examples/config_example.json"


# --------------------------------------------------------------------- #
#  Shared helpers (used by both sections below)
# --------------------------------------------------------------------- #

def feed_inputs(monkeypatch, answers):
    """Replace input() with a sequence of predetermined answers."""
    it = iter(answers)

    def fake_input(prompt=""):
        """Return the next answer or fail on an unexpected prompt."""
        try:
            return next(it)
        except StopIteration:
            raise AssertionError("input() was called more times than the test expected")

    monkeypatch.setattr("builtins.input", fake_input)


def _skip_times():
    """Input sequence for _prompt_faculty_times() alone: 'n/a' for all
    5 weekdays."""
    return ["n/a"] * 5


def _skip_times_and_prefs():
    """Input sequence for _prompt_faculty_times() + the day-limit
    prompts + the three preference loops, for tests that don't care
    about their content.

    All 5 weekdays are 'n/a', so times ends up {} and
    _prompt_mandatory_days() finds no available days and returns
    WITHOUT reading any input at all -- do NOT add a blank entry for
    it here, or every subsequent scripted answer shifts by one.
    _prompt_maximum_days() has no such short-circuit and always reads
    exactly one line regardless -- hence the single blank entry below
    -- followed by a blank line to stop each of the three preference
    loops (course/room/lab)."""
    return _skip_times() + [""] + ["", "", ""]


# ======================================================================= #
#  SECTION 1: commands.py's own logic, against fakes
# ======================================================================= #

class FakeValidationError(Exception):
    """Stand-in for scheduler.config.ValidationError."""


class FakeFacultyConfig:
    """Stand-in for scheduler.config.FacultyConfig. Just holds whatever
    kwargs commands.py builds it with."""

    def __init__(self, **kwargs):
        """Initialize the test double with the supplied values."""
        self.__dict__.update(kwargs)


class FakeCourse:
    def __init__(self, course_id, faculty=None):
        """Initialize the test double with the supplied values."""
        self.course_id = course_id
        self.faculty = list(faculty or [])


class FakeRoom:
    def __init__(self, name):
        """Initialize the test double with the supplied values."""
        self.name = name


class FakeCombinedConfig:
    """Mirrors the documented edit_mode() contract quoted in
    app/crud.py: yields an independently-editable draft; on a clean
    exit, copies the draft back onto self; if the `with` block raises,
    self is left completely untouched."""

    def __init__(self, faculty=None, courses=None, rooms=None, labs=None, reject=False):
        """Initialize the test double with the supplied values."""
        self.config = SimpleNamespace(
            faculty=list(faculty or []),
            courses=list(courses or []),
            rooms=list(rooms or []),
            labs=list(labs or []),
        )
        self.reject = reject

    @contextmanager
    def edit_mode(self):
        """Yield an isolated draft and commit it only after validation."""
        draft = FakeCombinedConfig(
            faculty=list(self.config.faculty),
            courses=list(self.config.courses),
            rooms=list(self.config.rooms),
            labs=list(self.config.labs),
        )
        yield draft
        if self.reject:
            raise FakeValidationError("simulated whole-config validation failure")
        self.config.faculty = draft.config.faculty
        self.config.courses = draft.config.courses
        self.config.rooms = draft.config.rooms
        self.config.labs = draft.config.labs


def make_session(faculty=None, courses=None, rooms=None, labs=None, reject=False):
    """Create an initialized session for a test."""
    session = Session()
    session.config = FakeCombinedConfig(faculty=faculty, courses=courses, rooms=rooms, labs=labs, reject=reject)
    return session


class TestFacultyCRUDLogic:
    """Every test method in this class gets the fake library types
    patched in automatically, via the fixture immediately below. That
    fixture is defined HERE, inside this class, specifically so it
    cannot affect TestFacultyDayLimitsAgainstRealLibrary further down
    in this file."""

    @pytest.fixture(autouse=True)
    def _patch_library_types(self, monkeypatch):
        """Patch scheduler types only for the fake-library test class."""
        monkeypatch.setattr(commands, "FacultyConfig", FakeFacultyConfig)
        monkeypatch.setattr(crud, "ValidationError", FakeValidationError)

    # ---------- _prompt_mandatory_days / _prompt_maximum_days ----------

    def test_prompt_mandatory_days_blank_returns_none(self, monkeypatch):
        """Verify that prompt mandatory days blank returns none."""
        times = {d: [{"start": "09:00", "end": "17:00"}] for d in commands._VALID_DAYS}
        feed_inputs(monkeypatch, [""])
        assert commands._prompt_mandatory_days(times) is None

    def test_prompt_mandatory_days_valid_selection(self, monkeypatch):
        """Verify that prompt mandatory days valid selection."""
        times = {d: [{"start": "09:00", "end": "17:00"}] for d in commands._VALID_DAYS}
        feed_inputs(monkeypatch, ["MON, WED"])
        assert commands._prompt_mandatory_days(times) == ["MON", "WED"]

    def test_prompt_mandatory_days_rejects_unavailable_day(self, monkeypatch):
        """Verify that prompt mandatory days rejects unavailable day."""
        times = {
            "MON": [{"start": "09:00", "end": "17:00"}],
            "WED": [{"start": "09:00", "end": "17:00"}],
        }
        feed_inputs(monkeypatch, ["TUE, WED"])
        assert commands._prompt_mandatory_days(times) == ["WED"]

    def test_prompt_mandatory_days_no_available_days_skips_prompt(self, monkeypatch):
        """Verify that prompt mandatory days no available days skips prompt."""
        feed_inputs(monkeypatch, [])
        assert commands._prompt_mandatory_days({}) is None

    def test_prompt_mandatory_days_dedupes_and_uppercases(self, monkeypatch):
        """Verify that prompt mandatory days dedupes and uppercases."""
        times = {d: [{"start": "09:00", "end": "17:00"}] for d in commands._VALID_DAYS}
        feed_inputs(monkeypatch, ["mon, MON, Wed"])
        assert commands._prompt_mandatory_days(times) == ["MON", "WED"]

    def test_prompt_maximum_days_blank_returns_none(self, monkeypatch):
        """Verify that prompt maximum days blank returns none."""
        feed_inputs(monkeypatch, [""])
        assert commands._prompt_maximum_days(mandatory_days=None) is None

    def test_prompt_maximum_days_valid_value(self, monkeypatch):
        """Verify that prompt maximum days valid value."""
        feed_inputs(monkeypatch, ["4"])
        assert commands._prompt_maximum_days(mandatory_days=None) == 4

    def test_prompt_maximum_days_non_numeric_returns_none(self, monkeypatch):
        """Verify that prompt maximum days non numeric returns none."""
        feed_inputs(monkeypatch, ["banana"])
        assert commands._prompt_maximum_days(mandatory_days=["MON", "WED"]) is None

    def test_prompt_maximum_days_zero_or_negative_returns_none(self, monkeypatch):
        """Verify that prompt maximum days zero or negative returns none."""
        feed_inputs(monkeypatch, ["0"])
        assert commands._prompt_maximum_days(mandatory_days=None) is None

    def test_prompt_maximum_days_bumped_up_to_match_mandatory_count(self, monkeypatch):
        """Verify that prompt maximum days bumped up to match mandatory count."""
        feed_inputs(monkeypatch, ["1"])
        assert commands._prompt_maximum_days(mandatory_days=["MON", "WED", "FRI"]) == 3

    def test_prompt_maximum_days_not_bumped_when_already_sufficient(self, monkeypatch):
        """Verify that prompt maximum days not bumped when already sufficient."""
        feed_inputs(monkeypatch, ["5"])
        assert commands._prompt_maximum_days(mandatory_days=["MON", "WED"]) == 5

    # ---------- add_faculty ----------

    def test_add_faculty_happy_path(self, monkeypatch, capsys):
        """Verify that add faculty happy path."""
        session = make_session(faculty=[])
        feed_inputs(monkeypatch, ["Dr. Test", "full"] + _skip_times_and_prefs())

        commands.add_faculty(session)

        assert len(session.config.config.faculty) == 1
        added = session.config.config.faculty[0]
        assert added.name == "Dr. Test"
        assert added.maximum_credits == 12
        assert added.unique_course_limit == 2
        assert added.times == {}
        assert added.course_preferences == {}
        assert not hasattr(added, "mandatory_days")
        assert not hasattr(added, "maximum_days")
        assert "faculty added" in capsys.readouterr().out.lower()

    def test_add_faculty_captures_times_and_preferences(self, monkeypatch):
        """Verify that add faculty captures times and preferences."""
        session = make_session(
            faculty=[],
            courses=[FakeCourse("CMSC 420"), FakeCourse("CMSC 350")],
            rooms=[FakeRoom("Roddy 136")],
        )
        feed_inputs(monkeypatch, [
            "Dr. Full", "full",
            "",              # MON -> default 09:00-17:00
            "n/a",           # TUE -> unavailable
            "10:00-14:00",   # WED -> custom
            "n/a",           # THU -> unavailable
            "",              # FRI -> default
            "MON, FRI",      # mandatory_days (both available -- valid)
            "2",             # maximum_days (already sufficient, no bump)
            "CMSC 420", "8", "CMSC 350", "5", "",   # course prefs, then stop
            "Roddy 136", "7", "",                    # room prefs, then stop
            "",                                       # lab prefs -> none (no labs exist)
        ])

        commands.add_faculty(session)

        added = session.config.config.faculty[0]
        assert added.times == {
            "MON": [{"start": "09:00", "end": "17:00"}],
            "WED": [{"start": "10:00", "end": "14:00"}],
            "FRI": [{"start": "09:00", "end": "17:00"}],
        }
        assert added.mandatory_days == ["MON", "FRI"]
        assert added.maximum_days == 2
        assert added.course_preferences == {"CMSC 420": 8, "CMSC 350": 5}
        assert added.room_preferences == {"Roddy 136": 7}
        assert added.lab_preferences == {}

    def test_add_faculty_rejects_unknown_preference_name_and_retries(self, monkeypatch):
        """Verify that add faculty rejects unknown preference name and retries."""
        session = make_session(faculty=[], courses=[FakeCourse("CMSC 420")])
        feed_inputs(monkeypatch, [
            "Dr. Full", "full",
        ] + _skip_times() + [
            "",                              # maximum_days: blank -> None
            "CS999", "CMSC 420", "6", "",   # bad name, then the real one, then stop
            "",                              # no rooms exist -> stop immediately
            "",                              # no labs exist -> stop immediately
        ])

        commands.add_faculty(session)

        added = session.config.config.faculty[0]
        assert added.course_preferences == {"CMSC 420": 6}

    def test_add_faculty_adjunct_defaults(self, monkeypatch):
        """Verify that add faculty adjunct defaults."""
        session = make_session(faculty=[])
        feed_inputs(monkeypatch, ["Dr. Adjunct", "adjunct"] + _skip_times_and_prefs())

        commands.add_faculty(session)

        added = session.config.config.faculty[0]
        assert added.maximum_credits == 4
        assert added.unique_course_limit == 1

    def test_add_faculty_rejects_blank_name(self, monkeypatch, capsys):
        """Verify that add faculty rejects blank name."""
        session = make_session(faculty=[])
        feed_inputs(monkeypatch, ["", "full"] + _skip_times_and_prefs())

        commands.add_faculty(session)

        assert session.config.config.faculty == []
        assert "blank name" in capsys.readouterr().out.lower()

    def test_add_faculty_rejects_duplicate_name(self, monkeypatch, capsys):
        """Verify that add faculty rejects duplicate name."""
        existing = FakeFacultyConfig(name="Dr. Test")
        session = make_session(faculty=[existing])
        feed_inputs(monkeypatch, ["Dr. Test", "full"] + _skip_times_and_prefs())

        commands.add_faculty(session)

        assert len(session.config.config.faculty) == 1
        assert "already in the system" in capsys.readouterr().out.lower()

    def test_add_faculty_rolls_back_on_validation_failure(self, monkeypatch, capsys):
        """Verify that add faculty rolls back on validation failure."""
        session = make_session(faculty=[], reject=True)
        feed_inputs(monkeypatch, ["Dr. Test", "full"] + _skip_times_and_prefs())

        commands.add_faculty(session)

        assert session.config.config.faculty == []
        assert "could not add faculty" in capsys.readouterr().out.lower()

    def test_add_faculty_captures_mandatory_and_maximum_days(self, monkeypatch):
        """Verify that add faculty captures mandatory and maximum days."""
        session = make_session(faculty=[])
        feed_inputs(monkeypatch, [
            "Dr. Days", "full",
            "", "", "", "", "",
            "MON, WED",
            "1",   # should be bumped up to 2
            "", "", "",
        ])

        commands.add_faculty(session)

        added = session.config.config.faculty[0]
        assert added.mandatory_days == ["MON", "WED"]
        assert added.maximum_days == 2

    def test_add_faculty_omits_mandatory_and_maximum_days_when_blank(self, monkeypatch):
        """Verify that add faculty omits mandatory and maximum days when blank."""
        session = make_session(faculty=[])
        feed_inputs(monkeypatch, [
            "Dr. NoDays", "adjunct",
            "", "n/a", "n/a", "n/a", "n/a",   # MON available, rest unavailable
            "",   # mandatory_days: blank -> None
            "",   # maximum_days: blank -> None
            "", "", "",
        ])

        commands.add_faculty(session)

        added = session.config.config.faculty[0]
        assert not hasattr(added, "mandatory_days")
        assert not hasattr(added, "maximum_days")

    # ---------- modify_faculty ----------

    def test_modify_faculty_applies_valid_change(self, monkeypatch):
        """Verify that modify faculty applies valid change."""
        existing = FakeFacultyConfig(name="Dr. Test", maximum_credits=12, unique_course_limit=2)
        session = make_session(faculty=[existing])
        feed_inputs(monkeypatch, ["Dr. Test", "Dr. Test", "adjunct"] + _skip_times_and_prefs())

        commands.modify_faculty(session)

        faculty = session.config.config.faculty
        assert len(faculty) == 1
        assert faculty[0].maximum_credits == 4
        assert faculty[0].unique_course_limit == 1

    def test_modify_faculty_nonexistent_name_is_a_no_op(self, monkeypatch, capsys):
        """Verify that modify faculty nonexistent name is a no op."""
        existing = FakeFacultyConfig(name="Dr. Test")
        session = make_session(faculty=[existing])
        feed_inputs(monkeypatch, ["Nobody"])

        commands.modify_faculty(session)

        assert session.config.config.faculty == [existing]
        assert "does not exist" in capsys.readouterr().out.lower()

    def test_modify_faculty_restores_previous_state_on_invalid_edit(self, monkeypatch, capsys):
        """Verify that modify faculty restores previous state on invalid edit."""
        existing = FakeFacultyConfig(name="Dr. Test", maximum_credits=12)
        session = make_session(faculty=[existing], reject=True)
        feed_inputs(monkeypatch, ["Dr. Test", "Dr. Test", "adjunct"] + _skip_times_and_prefs())

        commands.modify_faculty(session)

        faculty = session.config.config.faculty
        assert faculty == [existing]
        assert faculty[0].maximum_credits == 12
        assert "previous version kept" in capsys.readouterr().out.lower()

    def test_modify_faculty_updates_mandatory_and_maximum_days(self, monkeypatch):
        """Verify that modify faculty updates mandatory and maximum days."""
        existing = FakeFacultyConfig(name="Dr. Test", maximum_credits=12, unique_course_limit=2)
        session = make_session(faculty=[existing])
        feed_inputs(monkeypatch, [
            "Dr. Test", "Dr. Test", "full",
            "", "", "", "", "",
            "WED",
            "3",
            "", "", "",
        ])

        commands.modify_faculty(session)

        updated = session.config.config.faculty[0]
        assert updated.mandatory_days == ["WED"]
        assert updated.maximum_days == 3

    # ---------- delete_faculty ----------

    def test_delete_faculty_removes_confirmed_record(self, monkeypatch):
        """Verify that delete faculty removes confirmed record."""
        existing = FakeFacultyConfig(name="Dr. Test")
        session = make_session(faculty=[existing], courses=[])
        feed_inputs(monkeypatch, ["Dr. Test", "y"])

        commands.delete_faculty(session)

        assert session.config.config.faculty == []

    def test_delete_faculty_cancel_keeps_record(self, monkeypatch):
        """Verify that delete faculty cancel keeps record."""
        existing = FakeFacultyConfig(name="Dr. Test")
        session = make_session(faculty=[existing], courses=[])
        feed_inputs(monkeypatch, ["Dr. Test", "n"])

        commands.delete_faculty(session)

        assert session.config.config.faculty == [existing]

    def test_delete_faculty_nonexistent_name_is_a_no_op(self, monkeypatch, capsys):
        """Verify that delete faculty nonexistent name is a no op."""
        existing = FakeFacultyConfig(name="Dr. Test")
        session = make_session(faculty=[existing])
        feed_inputs(monkeypatch, ["Nobody"])

        commands.delete_faculty(session)

        assert session.config.config.faculty == [existing]
        assert "does not exist" in capsys.readouterr().out.lower()

    def test_delete_faculty_blocked_by_referencing_course(self, monkeypatch, capsys):
        """Verify that delete faculty blocked by referencing course."""
        existing = FakeFacultyConfig(name="Dr. Test")
        referencing_course = FakeCourse(course_id="CMSC 999", faculty=["Dr. Test"])
        session = make_session(faculty=[existing], courses=[referencing_course])
        feed_inputs(monkeypatch, ["Dr. Test"])

        commands.delete_faculty(session)

        assert session.config.config.faculty == [existing]
        assert "CMSC 999" in capsys.readouterr().out

    def test_delete_faculty_ignores_courses_with_faculty_set_to_none(self, monkeypatch):
        """Verify that delete faculty ignores courses with faculty set to none."""
        existing = FakeFacultyConfig(name="Dr. Test")
        unassigned_course = FakeCourse(course_id="CMSC 140")
        unassigned_course.faculty = None
        session = make_session(faculty=[existing], courses=[unassigned_course])
        feed_inputs(monkeypatch, ["Dr. Test", "y"])

        commands.delete_faculty(session)

        assert session.config.config.faculty == []

    def test_delete_faculty_rolls_back_on_validation_failure(self, monkeypatch, capsys):
        """Verify that delete faculty rolls back on validation failure."""
        existing = FakeFacultyConfig(name="Dr. Test")
        session = make_session(faculty=[existing], courses=[], reject=True)
        feed_inputs(monkeypatch, ["Dr. Test", "y"])

        commands.delete_faculty(session)

        assert session.config.config.faculty == [existing]
        assert "could not remove faculty" in capsys.readouterr().out.lower()


# ======================================================================= #
#  SECTION 2: the REAL library, no patching
# ======================================================================= #

class TestFacultyDayLimitsAgainstRealLibrary:
    """No fixture here patches commands.FacultyConfig or
    crud.ValidationError -- deliberately. commands.add_faculty() and
    commands.modify_faculty() in these tests call the real,
    installed scheduler.config.FacultyConfig."""

    @pytest.fixture
    def session(self):
        """Create a session backed by the real scheduler configuration."""
        if not Path(_EXAMPLE_CONFIG).exists():
            pytest.skip(f"{_EXAMPLE_CONFIG} not found -- run from the repo root")
        s = Session()
        s.load(_EXAMPLE_CONFIG)
        return s

    def test_add_faculty_with_day_limits_against_real_library(self, session, monkeypatch, capsys):
        """Verify that add faculty with day limits against real library."""
        feed_inputs(monkeypatch, [
            "Library Test Faculty", "full",
            "", "", "", "", "",
            "MON, WED",
            "3",
            "", "", "",
        ])

        commands.add_faculty(session)

        out = capsys.readouterr().out
        assert "could not add faculty" not in out.lower(), out
        assert "faculty added" in out.lower()

        added = next(
            f for f in session.config.config.faculty
            if f.name == "Library Test Faculty"
        )
        # CONFIRMED against the real library: mandatory_days comes back
        # as a set, not a list -- order isn't preserved and duplicates
        # are deduped by the library itself. Compare as sets.
        assert set(added.mandatory_days) == {"MON", "WED"}
        assert added.maximum_days == 3

    def test_add_faculty_without_day_limits_against_real_library(self, session, monkeypatch, capsys):
        """Verify that add faculty without day limits against real library."""
        feed_inputs(monkeypatch, [
            "No Day Limits Library Test", "adjunct",
            "n/a", "n/a", "n/a", "n/a", "n/a",
            "",
            "", "", "",
        ])

        commands.add_faculty(session)

        out = capsys.readouterr().out
        assert "could not add faculty" not in out.lower(), out

        added = next(
            f for f in session.config.config.faculty
            if f.name == "No Day Limits Library Test"
        )
        assert added is not None

    def test_modify_faculty_updates_day_limits_against_real_library(self, session, monkeypatch, capsys):
        """Verify that modify faculty updates day limits against real library."""
        # Deliberately does NOT modify one of the shipped example's
        # existing faculty. Some of those (e.g. the first in the list)
        # have course_preferences that other courses in the example
        # rely on to derive an implicit faculty assignment (a course
        # with "faculty": null gets it inferred from whichever faculty
        # prefers it). modify_faculty() re-prompts every field from
        # scratch and does not preserve the old preferences, so editing
        # one of those faculty members here would correctly fail whole-
        # config validation -- for a reason entirely unrelated to
        # mandatory_days/maximum_days. Isolate this test from that
        # pre-existing (and separately worth fixing) limitation by
        # adding a fresh, preference-free record first and modifying
        # that instead.
        feed_inputs(monkeypatch, [
            "Modify Target", "full",
            "", "", "", "", "",
            "",   # no mandatory_days yet
            "",   # no maximum_days yet
            "", "", "",
        ])
        commands.add_faculty(session)
        capsys.readouterr()  # discard add_faculty's own output

        feed_inputs(monkeypatch, [
            "Modify Target", "Modify Target", "full",
            "", "", "", "", "",
            "FRI",
            "1",
            "", "", "",
        ])

        commands.modify_faculty(session)

        out = capsys.readouterr().out
        assert "previous version kept" not in out.lower(), out
        assert "faculty updated" in out.lower()

        updated = next(f for f in session.config.config.faculty if f.name == "Modify Target")
        assert set(updated.mandatory_days) == {"FRI"}
        assert updated.maximum_days == 1

    def test_day_limits_survive_save_and_reload(self, session, monkeypatch, tmp_path):
        """Verify that day limits survive save and reload."""
        feed_inputs(monkeypatch, [
            "Round Trip Faculty", "full",
            "", "", "", "", "",
            "TUE, THU",
            "2",
            "", "", "",
        ])
        commands.add_faculty(session)

        out_path = tmp_path / "round_trip_config.json"
        session.save(str(out_path))

        reloaded = Session()
        reloaded.load(str(out_path))

        added = next(
            f for f in reloaded.config.config.faculty
            if f.name == "Round Trip Faculty"
        )
        assert set(added.mandatory_days) == {"TUE", "THU"}
        assert added.maximum_days == 2
