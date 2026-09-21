"""Unit tests for lab create, update, delete, and prompt behavior."""

from app import commands
from app.crud import apply_edit
from app.session import Session
from scheduler.config import LabConfig, Meeting


def make_session():
    """Create an initialized session for a test."""
    session = Session()
    session.new_config()
    return session


def add_lab_to_config(session, name="Linux Lab", capacity=28):
    """Insert a lab directly so another operation can be tested."""
    lab = LabConfig(name=name, capacity=capacity)

    def mutate(config):
        """Apply the test-specific change to the editable configuration."""
        config.config.labs.append(lab)

    apply_edit(session.require_config(), "lab", mutate)


def test_add_lab_adds_new_lab(monkeypatch, capsys):
    """Verify that add lab adds new lab."""
    session = make_session()

    monkeypatch.setattr(
        commands,
        "_prompt_lab_fields",
        lambda: {"name": "Linux Lab", "capacity": 28},
    )

    commands.add_lab(session)

    labs = session.require_config().config.labs

    assert len(labs) == 1
    assert labs[0].name == "Linux Lab"
    assert labs[0].capacity == 28
    assert "Lab added." in capsys.readouterr().out


def test_add_lab_rejects_duplicate_name(monkeypatch, capsys):
    """Verify that add lab rejects duplicate name."""
    session = make_session()
    add_lab_to_config(session)

    monkeypatch.setattr(
        commands,
        "_prompt_lab_fields",
        lambda: {"name": "Linux Lab", "capacity": 28},
    )

    commands.add_lab(session)

    assert len(session.require_config().config.labs) == 1
    assert "Lab is already in the system!" in capsys.readouterr().out


def test_modify_lab_replaces_existing_lab(monkeypatch, capsys):
    """Verify that modify lab replaces existing lab."""
    session = make_session()
    add_lab_to_config(session, name="Linux Lab", capacity=28)

    inputs = iter(["Linux Lab"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr(
        commands,
        "_prompt_lab_fields",
        lambda: {"name": "Updated Linux Lab", "capacity": 35},
    )

    commands.modify_lab(session)

    labs = session.require_config().config.labs

    assert len(labs) == 1
    assert labs[0].name == "Updated Linux Lab"
    assert labs[0].capacity == 35
    assert "Lab updated." in capsys.readouterr().out


def test_delete_lab_removes_unreferenced_lab(monkeypatch, capsys):
    """Verify that delete lab removes unreferenced lab."""
    session = make_session()
    add_lab_to_config(session, name="Linux Lab", capacity=28)

    inputs = iter(["Linux Lab", "yes"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    commands.delete_lab(session)

    assert session.require_config().config.labs == []
    assert "Lab removed." in capsys.readouterr().out


def test_delete_lab_does_not_remove_referenced_lab(monkeypatch, capsys):
    """Verify that delete lab does not remove referenced lab."""
    session = make_session()

    def mutate(config):
        """Apply the test-specific change to the editable configuration."""
        config.config.labs.append(LabConfig(name="Linux Lab", capacity=28))
        config.config.courses[0].lab.append("Linux Lab")
        meeting = config.time_slot_config.classes[0].meetings[0]
        config.time_slot_config.classes[0].meetings[0] = Meeting(
            day=meeting.day,
            duration=meeting.duration,
            lab=True,
        )

    apply_edit(session.require_config(), "lab", mutate)

    monkeypatch.setattr("builtins.input", lambda prompt="": "Linux Lab")

    commands.delete_lab(session)

    labs = session.require_config().config.labs

    assert len(labs) == 1
    assert labs[0].name == "Linux Lab"
    assert "Cannot delete 'Linux Lab'" in capsys.readouterr().out


def test_prompt_lab_fields_retries_after_bad_input(monkeypatch):
    """Verify that prompt lab fields retries after bad input."""
    inputs = iter(["", "Linux Lab", "zero", "0", "-5", "28", "", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    fields = commands._prompt_lab_fields()

    assert fields["name"] == "Linux Lab"
    assert fields["capacity"] == 28
    assert fields["features"] == []
    assert "times" not in fields


def test_modify_lab_rejects_missing_lab(monkeypatch, capsys):
    """Verify that modify lab rejects missing lab."""
    session = make_session()

    monkeypatch.setattr("builtins.input", lambda prompt="": "Missing Lab")

    commands.modify_lab(session)

    assert session.require_config().config.labs == []
    assert "Lab does not exist!" in capsys.readouterr().out


def test_modify_lab_rejects_duplicate_name(monkeypatch, capsys):
    """Verify that modify lab rejects duplicate name."""
    session = make_session()
    add_lab_to_config(session, name="Linux Lab", capacity=28)
    add_lab_to_config(session, name="Mac Lab", capacity=30)

    monkeypatch.setattr("builtins.input", lambda prompt="": "Linux Lab")
    monkeypatch.setattr(
        commands,
        "_prompt_lab_fields",
        lambda: {"name": "Mac Lab", "capacity": 40},
    )

    commands.modify_lab(session)

    labs = session.require_config().config.labs

    assert [(lab.name, lab.capacity) for lab in labs] == [
        ("Linux Lab", 28),
        ("Mac Lab", 30),
    ]
    assert "Lab name is already in the system!" in capsys.readouterr().out


def test_delete_lab_cancellation_keeps_lab(monkeypatch, capsys):
    """Verify that delete lab cancellation keeps lab."""
    session = make_session()
    add_lab_to_config(session)

    inputs = iter(["Linux Lab", "no"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    commands.delete_lab(session)

    labs = session.require_config().config.labs

    assert len(labs) == 1
    assert labs[0].name == "Linux Lab"
    assert "Removal cancelled" in capsys.readouterr().out


def test_delete_lab_rejects_missing_lab(monkeypatch, capsys):
    """Verify that delete lab rejects missing lab."""
    session = make_session()

    monkeypatch.setattr("builtins.input", lambda prompt="": "Missing Lab")

    commands.delete_lab(session)

    assert session.require_config().config.labs == []
    assert "Lab does not exist!" in capsys.readouterr().out
