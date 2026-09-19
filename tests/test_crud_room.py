from app import commands
from app.crud import apply_edit
from app.session import Session
from scheduler.config import RoomConfig


def make_session():
	session = Session()
	session.new_config()
	return session


def add_room_to_config(session, name="Roddy 136", capacity=28):
	room = RoomConfig(name=name, capacity=capacity)

	def mutate(config):
		config.config.rooms.append(room)

	apply_edit(session.require_config(), "room", mutate)


def test_add_room_adds_new_room(monkeypatch, capsys):
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
	session = make_session()

	monkeypatch.setattr("builtins.input", lambda prompt="": "Missing Room")

	commands.modify_room(session)

	assert session.require_config().config.rooms[0].capacity == 30
	assert "Room does not exist!" in capsys.readouterr().out


def test_modify_room_rejects_duplicate_name(monkeypatch, capsys):
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
	session = make_session()

	monkeypatch.setattr("builtins.input", lambda prompt="": "Placeholder Room")

	commands.delete_room(session)

	rooms = session.require_config().config.rooms

	assert [(room.name, room.capacity) for room in rooms] == [
		("Placeholder Room", 30),
	]
	assert session.dirty is False
	assert "Cannot delete 'Placeholder Room'" in capsys.readouterr().out
