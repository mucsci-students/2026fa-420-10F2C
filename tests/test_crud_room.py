"""Unit tests for room create, update, and delete commands."""

from app import commands
from app.crud import apply_edit
from app.session import Session
from scheduler.config import RoomConfig


def make_session():
	"""Return a session initialized with the default configuration."""
	session = Session()
	session.new_config()
	return session


def add_room_to_config(session, name="Roddy 136", capacity=28):
	"""Insert a room directly so another operation can be tested."""
	room = RoomConfig(name=name, capacity=capacity)

	def mutate(config):
		"""Append the prepared room to the editable configuration."""
		config.config.rooms.append(room)

	apply_edit(session.require_config(), "room", mutate)


def test_add_room_adds_new_room(monkeypatch, capsys):
	"""Add a unique room and mark the session as dirty."""
	session = make_session()

	monkeypatch.setattr(
		commands,
		"_prompt_room_fields",
		lambda: {"name": "Roddy 136", "capacity": 28},
	)

	commands.add_room(session)

	room = next(room for room in session.require_config().config.rooms if room.name == "Roddy 136")

	assert room.capacity == 28
	assert session.dirty is True
	assert "Room added." in capsys.readouterr().out


def test_add_room_rejects_duplicate_name(monkeypatch, capsys):
	"""Reject a room whose name already exists."""
	session = make_session()

	monkeypatch.setattr(
		commands,
		"_prompt_room_fields",
		lambda: {"name": "Placeholder Room", "capacity": 30},
	)

	commands.add_room(session)

	assert len(session.require_config().config.rooms) == 1
	assert "Room is already in the system!" in capsys.readouterr().out


def test_modify_room_replaces_existing_room(monkeypatch, capsys):
	"""Update the selected room's fields in place."""
	session = make_session()

	monkeypatch.setattr("builtins.input", lambda prompt="": "Placeholder Room")
	monkeypatch.setattr(
		commands,
		"_prompt_room_fields",
		lambda: {"name": "Placeholder Room", "capacity": 35},
	)

	commands.modify_room(session)

	rooms = session.require_config().config.rooms

	assert len(rooms) == 1
	assert rooms[0].name == "Placeholder Room"
	assert rooms[0].capacity == 35
	assert session.dirty is True
	assert "Room updated." in capsys.readouterr().out


def test_modify_room_rejects_missing_room(monkeypatch, capsys):
	"""Report a missing room without changing the configuration."""
	session = make_session()

	monkeypatch.setattr("builtins.input", lambda prompt="": "Missing Room")

	commands.modify_room(session)

	assert session.require_config().config.rooms[0].capacity == 30
	assert "Room does not exist!" in capsys.readouterr().out


def test_modify_room_rejects_duplicate_name(monkeypatch, capsys):
	"""Prevent a room update from duplicating another room's name."""
	session = make_session()
	add_room_to_config(session)

	monkeypatch.setattr("builtins.input", lambda prompt="": "Placeholder Room")
	monkeypatch.setattr(
		commands,
		"_prompt_room_fields",
		lambda: {"name": "Roddy 136", "capacity": 35},
	)

	commands.modify_room(session)

	rooms = session.require_config().config.rooms

	assert [(room.name, room.capacity) for room in rooms] == [
		("Placeholder Room", 30),
		("Roddy 136", 28),
	]
	assert "Room name is already in the system!" in capsys.readouterr().out


def test_delete_room_removes_unreferenced_room(monkeypatch, capsys):
	"""Delete an unreferenced room after user confirmation."""
	session = make_session()
	add_room_to_config(session)

	inputs = iter(["Roddy 136", "yes"])
	monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

	commands.delete_room(session)

	rooms = session.require_config().config.rooms

	assert [(room.name, room.capacity) for room in rooms] == [
		("Placeholder Room", 30),
	]
	assert session.dirty is True
	assert "Room removed." in capsys.readouterr().out


def test_delete_room_does_not_remove_referenced_room(monkeypatch, capsys):
	"""Keep a room that is referenced elsewhere in the configuration."""
	session = make_session()

	monkeypatch.setattr("builtins.input", lambda prompt="": "Placeholder Room")

	commands.delete_room(session)

	rooms = session.require_config().config.rooms

	assert [(room.name, room.capacity) for room in rooms] == [
		("Placeholder Room", 30),
	]
	assert session.dirty is False
	assert "Cannot delete 'Placeholder Room'" in capsys.readouterr().out
