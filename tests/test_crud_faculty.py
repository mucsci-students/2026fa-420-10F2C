"""
Unit tests for faculty CRUD in app/commands.py.

Design note: app/commands.py builds faculty records via
scheduler.config.FacultyConfig and validates the whole config through
CombinedConfig.edit_mode() (see app/crud.py). Both are still marked
CONFIRM / "best reconstruction, not verified" in the code's own
comments as of this pass -- the exact FacultyConfig field names and
edit_mode()'s exact validation rules haven't been checked against the
installed library yet.

So these tests deliberately do NOT depend on the real schema being
right. They substitute a lightweight fake CombinedConfig that honors
the *documented contract* of edit_mode() from app/crud.py's own
comments (mutate a draft, commit only on a clean exit, leave the
original completely untouched if the block raises) -- so what's
actually under test is app/commands.py's OWN logic: duplicate/blank
name checks, delete confirmation, the reference-check-before-delete,
and rollback-on-failure. Once someone confirms the real FacultyConfig
field names (see the `uv run python -c "..."` command in
commands.py's docstring), add a second, library-backed test file that
exercises the real CombinedConfig directly.
"""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import app.commands as commands
import app.crud as crud
from app.session import Session


class FakeValidationError(Exception):
    """Stand-in for scheduler.config.ValidationError. Tests monkeypatch
    app.crud.ValidationError to this class so apply_edit()'s
    `except ValidationError` clause catches it -- Python looks up that
    name from app.crud's module globals at call time, so patching it
    there is enough; nothing else needs to change."""


class FakeFacultyConfig:
    """Stand-in for scheduler.config.FacultyConfig. Just holds whatever
    kwargs commands.py builds it with."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeCourse:
    """Minimal stand-in for a course record -- just enough for
    delete_faculty()'s reference scan (c.course_id, c.faculty) and
    _prompt_faculty_fields()'s existing-course lookup."""

    def __init__(self, course_id, faculty=None):
        self.course_id = course_id
        self.faculty = list(faculty or [])


class FakeRoom:
    """Minimal stand-in for a room/lab record -- just needs .name for
    _prompt_faculty_fields()'s existing-room/lab lookup."""

    def __init__(self, name):
        self.name = name


class FakeCombinedConfig:
    """Stand-in for scheduler.config.CombinedConfig. Mirrors the
    documented edit_mode() contract quoted in app/crud.py: yields an
    independently-editable draft; on a clean exit, copies the draft
    back onto self; if the `with` block raises, self is left
    completely untouched."""

    def __init__(self, faculty=None, courses=None, rooms=None, labs=None, reject=False):
        self.config = SimpleNamespace(
            faculty=list(faculty or []),
            courses=list(courses or []),
            rooms=list(rooms or []),
            labs=list(labs or []),
        )
        # Test hook: when True, this config's NEXT edit_mode() block
        # raises FakeValidationError on exit instead of committing --
        # mirroring what a real Pydantic validation failure would do.
        self.reject = reject

    @contextmanager
    def edit_mode(self):
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


@pytest.fixture(autouse=True)
def patch_library_types(monkeypatch):
    """Swap the library types app/commands.py and app/crud.py reference
    for our fakes, for every test in this file."""
    monkeypatch.setattr(commands, "FacultyConfig", FakeFacultyConfig)
    monkeypatch.setattr(crud, "ValidationError", FakeValidationError)


def make_session(faculty=None, courses=None, rooms=None, labs=None, reject=False):
    session = Session()
    session.config = FakeCombinedConfig(faculty=faculty, courses=courses, rooms=rooms, labs=labs, reject=reject)
    return session


def feed_inputs(monkeypatch, answers):
    it = iter(answers)

    def fake_input(prompt=""):
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
    """Input sequence for _prompt_faculty_times() + the three
    preference loops, for tests that don't care about their content:
    'n/a' for all 5 weekdays, then a blank line to stop each of the
    three preference loops (course/room/lab)."""
    return _skip_times() + ["", "", ""]


# ---------- add_faculty ----------

def test_add_faculty_happy_path(monkeypatch, capsys):
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
    assert "faculty added" in capsys.readouterr().out.lower()


def test_add_faculty_captures_times_and_preferences(monkeypatch):
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
    assert added.course_preferences == {"CMSC 420": 8, "CMSC 350": 5}
    assert added.room_preferences == {"Roddy 136": 7}
    assert added.lab_preferences == {}


def test_add_faculty_rejects_unknown_preference_name_and_retries(monkeypatch):
    session = make_session(faculty=[], courses=[FakeCourse("CMSC 420")])
    feed_inputs(monkeypatch, [
        "Dr. Full", "full",
    ] + _skip_times() + [
        "CS999", "CMSC 420", "6", "",   # bad name, then the real one, then stop
        "",                              # no rooms exist -> stop immediately
        "",                              # no labs exist -> stop immediately
    ])

    commands.add_faculty(session)

    added = session.config.config.faculty[0]
    assert added.course_preferences == {"CMSC 420": 6}


def test_add_faculty_adjunct_defaults(monkeypatch):
    session = make_session(faculty=[])
    feed_inputs(monkeypatch, ["Dr. Adjunct", "adjunct"] + _skip_times_and_prefs())

    commands.add_faculty(session)

    added = session.config.config.faculty[0]
    assert added.maximum_credits == 4
    assert added.unique_course_limit == 1


def test_add_faculty_rejects_blank_name(monkeypatch, capsys):
    session = make_session(faculty=[])
    feed_inputs(monkeypatch, ["", "full"] + _skip_times_and_prefs())

    commands.add_faculty(session)

    assert session.config.config.faculty == []
    assert "blank name" in capsys.readouterr().out.lower()


def test_add_faculty_rejects_duplicate_name(monkeypatch, capsys):
    existing = FakeFacultyConfig(name="Dr. Test")
    session = make_session(faculty=[existing])
    feed_inputs(monkeypatch, ["Dr. Test", "full"] + _skip_times_and_prefs())

    commands.add_faculty(session)

    assert len(session.config.config.faculty) == 1  # nothing new added
    assert "already in the system" in capsys.readouterr().out.lower()


def test_add_faculty_rolls_back_on_validation_failure(monkeypatch, capsys):
    session = make_session(faculty=[], reject=True)
    feed_inputs(monkeypatch, ["Dr. Test", "full"] + _skip_times_and_prefs())

    commands.add_faculty(session)

    # ValidationFailure means edit_mode() rolled back -- the faculty
    # list must be exactly what it was before the attempted add.
    assert session.config.config.faculty == []
    assert "could not add faculty" in capsys.readouterr().out.lower()


# ---------- modify_faculty ----------

def test_modify_faculty_applies_valid_change(monkeypatch):
    existing = FakeFacultyConfig(name="Dr. Test", maximum_credits=12, unique_course_limit=2)
    session = make_session(faculty=[existing])
    feed_inputs(monkeypatch, ["Dr. Test", "Dr. Test", "adjunct"] + _skip_times_and_prefs())

    commands.modify_faculty(session)

    faculty = session.config.config.faculty
    assert len(faculty) == 1
    assert faculty[0].maximum_credits == 4
    assert faculty[0].unique_course_limit == 1


def test_modify_faculty_nonexistent_name_is_a_no_op(monkeypatch, capsys):
    existing = FakeFacultyConfig(name="Dr. Test")
    session = make_session(faculty=[existing])
    feed_inputs(monkeypatch, ["Nobody"])

    commands.modify_faculty(session)

    assert session.config.config.faculty == [existing]
    assert "does not exist" in capsys.readouterr().out.lower()


def test_modify_faculty_restores_previous_state_on_invalid_edit(monkeypatch, capsys):
    existing = FakeFacultyConfig(name="Dr. Test", maximum_credits=12)
    session = make_session(faculty=[existing], reject=True)
    feed_inputs(monkeypatch, ["Dr. Test", "Dr. Test", "adjunct"] + _skip_times_and_prefs())

    commands.modify_faculty(session)

    # edit_mode() rolled back -- the ORIGINAL record object should
    # still be the one in the list, untouched.
    faculty = session.config.config.faculty
    assert faculty == [existing]
    assert faculty[0].maximum_credits == 12
    assert "previous version kept" in capsys.readouterr().out.lower()


# ---------- delete_faculty ----------

def test_delete_faculty_removes_confirmed_record(monkeypatch):
    existing = FakeFacultyConfig(name="Dr. Test")
    session = make_session(faculty=[existing], courses=[])
    feed_inputs(monkeypatch, ["Dr. Test", "y"])

    commands.delete_faculty(session)

    assert session.config.config.faculty == []


def test_delete_faculty_cancel_keeps_record(monkeypatch):
    existing = FakeFacultyConfig(name="Dr. Test")
    session = make_session(faculty=[existing], courses=[])
    feed_inputs(monkeypatch, ["Dr. Test", "n"])

    commands.delete_faculty(session)

    assert session.config.config.faculty == [existing]


def test_delete_faculty_nonexistent_name_is_a_no_op(monkeypatch, capsys):
    existing = FakeFacultyConfig(name="Dr. Test")
    session = make_session(faculty=[existing])
    feed_inputs(monkeypatch, ["Nobody"])

    commands.delete_faculty(session)

    assert session.config.config.faculty == [existing]
    assert "does not exist" in capsys.readouterr().out.lower()


def test_delete_faculty_blocked_by_referencing_course(monkeypatch, capsys):
    existing = FakeFacultyConfig(name="Dr. Test")
    referencing_course = FakeCourse(course_id="CMSC 999", faculty=["Dr. Test"])
    session = make_session(faculty=[existing], courses=[referencing_course])
    feed_inputs(monkeypatch, ["Dr. Test"])  # returns before the y/n confirm

    commands.delete_faculty(session)

    # Req #7: a referenced faculty member must NOT be removed
    assert session.config.config.faculty == [existing]
    assert "CMSC 999" in capsys.readouterr().out


def test_delete_faculty_ignores_courses_with_faculty_set_to_none(monkeypatch):
    """Regression test: a course's `faculty` field can be explicitly
    None (unassigned) in the real schema, not just an empty list.
    getattr(c, "faculty", []) does NOT catch this -- the default only
    applies when the attribute is missing entirely, not when it's
    present but None -- so `name in None` used to crash the whole app.
    This confirms a None-faculty course is skipped cleanly instead."""
    existing = FakeFacultyConfig(name="Dr. Test")
    unassigned_course = FakeCourse(course_id="CMSC 140")
    unassigned_course.faculty = None  # bypass FakeCourse's own "or []" coercion
    session = make_session(faculty=[existing], courses=[unassigned_course])
    feed_inputs(monkeypatch, ["Dr. Test", "y"])

    commands.delete_faculty(session)  # must not raise

    assert session.config.config.faculty == []


def test_delete_faculty_rolls_back_on_validation_failure(monkeypatch, capsys):
    existing = FakeFacultyConfig(name="Dr. Test")
    session = make_session(faculty=[existing], courses=[], reject=True)
    feed_inputs(monkeypatch, ["Dr. Test", "y"])

    commands.delete_faculty(session)

    assert session.config.config.faculty == [existing]
    assert "could not remove faculty" in capsys.readouterr().out.lower()