"""Unit tests for course CRUD (Req #5, #7, #12).

Mirrors tests/test_crud_room.py: monkeypatch the _prompt_* helper, call the
command, assert on config state, session.dirty, and captured output.

The seed config from Session.new_config() is:
  rooms    = ["Placeholder Room" (cap 30)]
  labs     = []
  courses  = ["PLACEHOLDER 000" (3 credits, cap 30)]
  faculty  = ["Placeholder Faculty"]
  patterns = [3 credits, one MON 150-minute non-lab meeting]
"""

from app import commands
from app.session import Session


def make_session():
    session = Session()
    session.new_config()
    return session


def course_fields(**overrides):
    """A valid-against-the-seed-config course, with per-test overrides."""
    fields = {
        "course_id": "CS 101",
        "section_id": None,
        "credits": 3,
        "capacity": 30,
        "room": ["Placeholder Room"],
        "lab": [],
        "conflicts": [],
        "faculty": ["Placeholder Faculty"],
        "modality": "in_person",
        "required_room_features": set(),
        "required_lab_features": set(),
        "reserve_room_during_lab": True,
    }
    fields.update(overrides)
    return fields


def add_course_to_config(session, monkeypatch, **overrides):
    monkeypatch.setattr(commands, "_prompt_course_fields", lambda config: course_fields(**overrides))
    commands.add_course(session)


# --------------------------------------------------------------------------- #
#  Create
# --------------------------------------------------------------------------- #

def test_add_course_appends_new_course(monkeypatch, capsys):
    session = make_session()

    add_course_to_config(session, monkeypatch)

    courses = session.require_config().config.courses
    course = next(c for c in courses if c.course_id == "CS 101")

    assert course.credits == 3
    assert course.capacity == 30
    assert course.room == ["Placeholder Room"]
    assert course.faculty == ["Placeholder Faculty"]
    assert session.dirty is True
    assert "Course added." in capsys.readouterr().out


def test_add_course_allows_a_second_section_of_the_same_id(monkeypatch, capsys):
    """Repeated course_id values are legal -- they create separate sections."""
    session = make_session()

    add_course_to_config(session, monkeypatch, section_id="A")
    add_course_to_config(session, monkeypatch, section_id="B")

    sections = [c.section_id for c in session.require_config().config.courses if c.course_id == "CS 101"]

    assert sections == ["A", "B"]
    assert "Course added." in capsys.readouterr().out


def test_add_course_with_unmatched_credits_is_rejected(monkeypatch, capsys):
    """CombinedConfig._validate_course_patterns requires an ENABLED pattern
    with matching credits. The seed config only has a 3-credit pattern."""
    session = make_session()
    before = session.require_config().model_dump()

    add_course_to_config(session, monkeypatch, credits=4)

    assert session.require_config().model_dump() == before
    assert len(session.require_config().config.courses) == 1
    assert "Could not add course" in capsys.readouterr().out


def test_add_online_course_with_a_room_is_rejected(monkeypatch, capsys):
    """CourseConfig._validate_delivery_requirements forbids an online course
    from carrying rooms, labs, or required room features."""
    session = make_session()

    add_course_to_config(session, monkeypatch, modality="online", room=["Placeholder Room"])

    assert len(session.require_config().config.courses) == 1
    assert "Could not add course" in capsys.readouterr().out


def test_add_course_with_unknown_faculty_is_rejected(monkeypatch, capsys):
    session = make_session()

    add_course_to_config(session, monkeypatch, faculty=["Nobody"])

    assert len(session.require_config().config.courses) == 1
    assert "Could not add course" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
#  Read
# --------------------------------------------------------------------------- #

def test_view_course_lists_every_course(monkeypatch, capsys):
    session = make_session()
    add_course_to_config(session, monkeypatch)
    capsys.readouterr()

    commands.view_course(session)

    out = capsys.readouterr().out
    assert "PLACEHOLDER 000" in out
    assert "CS 101" in out


# --------------------------------------------------------------------------- #
#  Update
# --------------------------------------------------------------------------- #

def test_modify_course_replaces_in_place(monkeypatch, capsys):
    session = make_session()
    add_course_to_config(session, monkeypatch)

    monkeypatch.setattr("builtins.input", lambda prompt="": "1")
    monkeypatch.setattr(
        commands,
        "_prompt_course_fields",
        lambda config: course_fields(capacity=25),
    )

    commands.modify_course(session)

    courses = session.require_config().config.courses

    assert len(courses) == 2
    # index 1 still holds the edited course -- position must not change,
    # because section auto-numbering is derived from list order.
    assert courses[1].course_id == "CS 101"
    assert courses[1].capacity == 25
    assert session.dirty is True
    assert "Course updated." in capsys.readouterr().out


def test_modify_course_rejects_out_of_range_index(monkeypatch, capsys):
    session = make_session()

    monkeypatch.setattr("builtins.input", lambda prompt="": "7")

    commands.modify_course(session)

    assert session.dirty is False
    assert "No course at index 7" in capsys.readouterr().out


def test_failed_modify_keeps_previous_valid_state(monkeypatch, capsys):
    """Req #12: 'preservation of the previous valid state after a failed
    change'. edit_mode() rebuilds and revalidates the whole config, so a
    rejected edit must leave the in-memory config byte-identical."""
    session = make_session()
    add_course_to_config(session, monkeypatch)
    before = session.require_config().model_dump()

    monkeypatch.setattr("builtins.input", lambda prompt="": "1")
    monkeypatch.setattr(
        commands,
        "_prompt_course_fields",
        lambda config: course_fields(credits=4),
    )

    commands.modify_course(session)

    assert session.require_config().model_dump() == before
    assert "previous version kept" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
#  Delete
# --------------------------------------------------------------------------- #

def test_delete_course_removes_unreferenced_course(monkeypatch, capsys):
    session = make_session()
    add_course_to_config(session, monkeypatch)

    inputs = iter(["1", "yes"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    commands.delete_course(session)

    courses = session.require_config().config.courses

    assert [c.course_id for c in courses] == ["PLACEHOLDER 000"]
    assert session.dirty is True
    assert "Course removed." in capsys.readouterr().out


def test_delete_course_blocked_when_another_course_conflicts_with_it(monkeypatch, capsys):
    session = make_session()
    add_course_to_config(session, monkeypatch, conflicts=["PLACEHOLDER 000"])
    session.dirty = False 

    inputs = iter(["0", "yes"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    commands.delete_course(session)

    courses = session.require_config().config.courses

    assert [c.course_id for c in courses] == ["PLACEHOLDER 000", "CS 101"]
    assert session.dirty is False
    assert "Cannot delete 'PLACEHOLDER 000'" in capsys.readouterr().out


def test_delete_one_section_is_allowed_while_another_remains(monkeypatch, capsys):
    """References point at a course_id, not at a section, so they only dangle
    when the LAST section carrying that id goes away."""
    session = make_session()
    add_course_to_config(session, monkeypatch, section_id="A")
    add_course_to_config(session, monkeypatch, section_id="B")
    add_course_to_config(session, monkeypatch, course_id="CS 200", conflicts=["CS 101"])

    inputs = iter(["1", "yes"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    commands.delete_course(session)

    remaining = [(c.course_id, c.section_id) for c in session.require_config().config.courses]

    assert ("CS 101", "A") not in remaining
    assert ("CS 101", "B") in remaining
    assert "Course removed." in capsys.readouterr().out


def test_delete_course_cancelled_leaves_config_untouched(monkeypatch, capsys):
    session = make_session()
    add_course_to_config(session, monkeypatch)
    session.dirty = False

    inputs = iter(["1", "n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    commands.delete_course(session)

    assert len(session.require_config().config.courses) == 2
    assert session.dirty is False
    assert "Removal cancelled" in capsys.readouterr().out