"""
Tests for the AI assistant's tools (Sprint 3 user stories 7, 8 and 9).

The tools are called directly, the way the AI calls them, against the real
scheduler library and the shipped example configuration. No AI is involved:
these check what each tool really does to the configuration and what it
reports back.

    ToolBox(request).call("add_room", {"name": "RODDY150", "capacity": 35})
"""

import pytest
from scheduler.config import TimeBlock

from app.crud import apply_edit
from gui import session_store
from gui.ai import service
from gui.ai.prompt import AREAS, CAPABILITIES
from gui.ai.tools import NO_CONFIG_MESSAGE, TOOLS, TOOLS_BY_NAME, ToolBox, find_name
from gui.controllers import rooms


class FakeRequest:
    """Enough of a Django request for get_session(): just a session dict."""

    def __init__(self):
        self.session = {}


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


@pytest.fixture
def request_():
    return FakeRequest()


@pytest.fixture
def box(request_):
    return ToolBox(request_)


@pytest.fixture
def no_config(monkeypatch):
    monkeypatch.setattr(session_store, "AUTO_LOAD_EXAMPLE", False)


def config(request_):
    return session_store.get_session(request_).config


def room(request_, name):
    return next((r for r in config(request_).config.rooms if r.name == name), None)


def snapshot(request_):
    return config(request_).model_dump_json()


@pytest.fixture
def roddy(request_):
    """The story data: RODDY140 (capacity 30) and RODDY141 (capacity 25)."""
    rooms.add_room(request_, {"name": "RODDY140", "capacity": 30})
    rooms.add_room(request_, {"name": "RODDY141", "capacity": 25})
    session_store.get_session(request_).dirty = False
    return request_


# ---------------------------------------------------------------------- #
#  Registry
# ---------------------------------------------------------------------- #
def test_every_tool_has_a_unique_name_a_description_and_an_argument_schema():
    names = [tool.name for tool in TOOLS]
    assert len(names) == len(set(names))
    for tool in TOOLS:
        assert tool.description.strip()
        assert "properties" in tool.args.model_json_schema()


def test_read_and_add_tools_are_registered():
    for name in (
        "describe_capabilities",
        "show_configuration",
        "list_rooms",
        "get_room",
        "list_labs",
        "get_lab",
        "list_courses",
        "get_course",
        "list_faculty",
        "get_faculty",
        "list_time_slots",
        "list_class_patterns",
        "get_global_settings",
        "add_room",
        "add_lab",
        "add_course",
        "add_faculty",
        "add_time_slot",
        "add_class_pattern",
    ):
        assert name in TOOLS_BY_NAME
    assert not any(tool.write for tool in TOOLS if tool.name.startswith(("list_", "get_", "show_", "describe_")))
    assert all(tool.write for tool in TOOLS if tool.name.startswith("add_"))


def test_add_room_schema_requires_name_and_capacity():
    schema = TOOLS_BY_NAME["add_room"].args.model_json_schema()
    assert set(schema["required"]) == {"name", "capacity"}
    assert schema["properties"]["capacity"]["type"] == "integer"


def test_unknown_tool_is_refused(box, request_):
    before = snapshot(request_)
    result = box.call("run_shell", {"command": "rm -rf /"})
    assert not result.ok and "no 'run_shell' action" in result.message
    assert snapshot(request_) == before


def test_malformed_arguments_are_rejected_before_anything_runs(box, request_):
    before = snapshot(request_)
    result = box.call("add_room", {"name": "RODDY150", "capacity": "lots"})
    assert not result.ok and result.write and not result.changed
    assert "capacity" in result.message
    assert room(request_, "RODDY150") is None
    assert snapshot(request_) == before


def test_missing_arguments_are_named(box):
    result = box.call("add_room", {})
    assert not result.ok
    assert "name" in result.message and "capacity" in result.message


def test_find_name_matches_loosely_only_when_unambiguous():
    names = ["RODDY140", "Roddy 136", "Hogg", "Xie"]
    assert find_name("RODDY140", names) == "RODDY140"
    assert find_name("roddy 140", names) == "RODDY140"
    assert find_name("Dr. Hogg", names) == "Hogg"
    assert find_name("Dr. Nobody", names) is None
    assert find_name("roddy", names) is None


# ---------------------------------------------------------------------- #
#  Story 7: capability discovery
# ---------------------------------------------------------------------- #
def test_story_7_capabilities_list_every_area_and_action(box, request_):
    before = snapshot(request_)
    result = box.call("describe_capabilities")
    assert result.ok and not result.changed
    text = result.message.lower()
    for verb in ("view", "add", "change", "delete"):
        assert verb in text
    for area in AREAS:
        assert area in text
    for action in ("validate", "save", "generat"):
        assert action in text
    assert result.message == CAPABILITIES
    assert snapshot(request_) == before


def test_capabilities_work_with_no_configuration(no_config, box):
    result = box.call("describe_capabilities")
    assert result.ok and result.message == CAPABILITIES


# ---------------------------------------------------------------------- #
#  Story 8: inspect the configuration
# ---------------------------------------------------------------------- #
def test_story_8_list_all_rooms_shows_capacities(roddy, box):
    before = snapshot(roddy)
    result = box.call("list_rooms")
    assert result.ok and not result.changed
    assert "RODDY140: capacity 30" in result.message
    assert "RODDY141: capacity 25" in result.message
    assert snapshot(roddy) == before


def test_story_8_how_many_credits_is_cmsc_420(request_, box):
    def three_credits(draft):
        for course in draft.config.courses:
            if course.course_id == "CMSC 420":
                course.credits = 3
                course.lab = []  # the example's 3-credit patterns have no lab meeting

    apply_edit(config(request_), "course", three_credits)
    before = snapshot(request_)
    result = box.call("get_course", {"course_id": "CMSC 420"})
    assert result.ok
    assert "CMSC 420" in result.message and "3 credits" in result.message
    assert snapshot(request_) == before


def test_story_8_unknown_faculty_member(box, request_):
    before = snapshot(request_)
    result = box.call("get_faculty", {"name": "Dr. Nobody"})
    assert result.message == "No faculty member named 'Dr. Nobody' exists."
    assert snapshot(request_) == before


def test_story_8_no_configuration_loaded(no_config, box):
    result = box.call("list_rooms")
    assert not result.ok
    assert result.message == NO_CONFIG_MESSAGE
    assert "no configuration yet" in result.message.lower()
    assert "load or create" in result.message.lower()


@pytest.mark.parametrize(
    ("tool", "args", "expected"),
    [
        ("show_configuration", {}, "3 rooms"),
        ("get_room", {"name": "roddy 136"}, "Room Roddy 136: capacity 28"),
        ("list_labs", {}, "Linux: capacity 28"),
        ("get_lab", {"name": "Mac"}, "Lab Mac: capacity 28"),
        ("list_courses", {}, "CMSC 140.01: 4 credits, capacity 28"),
        ("get_course", {"course_id": "CMSC 140"}, "CMSC 140 has 2 sections"),
        ("list_faculty", {}, "Zoppetti: 12-12 credits"),
        ("get_faculty", {"name": "Dr. Zoppetti"}, "Faculty member Zoppetti"),
        ("list_time_slots", {}, "MON: 08:00-19:00 (every 60 min)"),
        ("list_class_patterns", {}, "3 credits"),
        ("get_global_settings", {}, "Generation limit: 100"),
    ],
)
def test_every_read_tool_reports_current_data_without_changing_it(box, request_, tool, args, expected):
    before = snapshot(request_)
    result = box.call(tool, args)
    assert result.ok, result.message
    assert expected in result.message
    assert not result.changed
    assert snapshot(request_) == before
    assert not session_store.get_session(request_).dirty


def test_unknown_room_lab_and_course(box):
    assert box.call("get_room", {"name": "NOPE100"}).message == "No room named 'NOPE100' exists."
    assert box.call("get_lab", {"name": "NOPE"}).message == "No lab named 'NOPE' exists."
    assert box.call("get_course", {"course_id": "CMSC 999"}).message == "No course 'CMSC 999' exists."


# ---------------------------------------------------------------------- #
#  Story 6: tools read the state as it is now
# ---------------------------------------------------------------------- #
def test_story_6_tools_see_a_manual_edit(roddy, box):
    rooms.update_room(roddy, "RODDY140", {"name": "RODDY140", "capacity": 40})  # what the edit page calls
    result = box.call("get_room", {"name": "RODDY140"})
    assert "capacity 40" in result.message


# ---------------------------------------------------------------------- #
#  Story 9: add items
# ---------------------------------------------------------------------- #
def test_story_9_add_a_room(box, request_):
    result = box.call("add_room", {"name": "RODDY150", "capacity": 35})
    assert result.ok and result.changed
    assert result.message == "Room 'RODDY150' added with capacity 35."
    assert room(request_, "RODDY150").capacity == 35
    assert session_store.get_session(request_).dirty
    rows = rooms.describe_rooms(request_)["rooms"]  # what the Rooms page shows
    assert {"RODDY150": 35}.items() <= {r["name"]: r["capacity"] for r in rows}.items()


def test_story_9_add_a_course_that_uses_existing_items(roddy, box):
    assert box.call("add_faculty", {"name": "Dr. Hogg"}).ok
    result = box.call(
        "add_course", {"course_id": "CMSC 421", "credits": 3, "faculty": ["Dr. Hogg"], "rooms": ["RODDY140"]}
    )
    assert result.ok, result.message
    course = next(c for c in config(roddy).config.courses if c.course_id == "CMSC 421")
    assert course.faculty == ["Dr. Hogg"]
    assert course.room == ["RODDY140"]
    assert course.credits == 3
    assert course.capacity == 30  # not given, so the room's capacity is used
    assert "capacity 30 (from room RODDY140)" in result.message


def test_add_course_finds_existing_names_loosely(roddy, box):
    result = box.call(
        "add_course", {"course_id": "CMSC 422", "credits": 3, "faculty": ["Dr. Hogg"], "rooms": ["roddy 141"]}
    )
    assert result.ok, result.message
    course = next(c for c in config(roddy).config.courses if c.course_id == "CMSC 422")
    assert course.faculty == ["Hogg"] and course.room == ["RODDY141"]


def test_an_ambiguous_name_asks_which_one(roddy, box):
    # The example already has "Roddy 140", so "roddy 140" could mean either room.
    before = snapshot(roddy)
    result = box.call("add_course", {"course_id": "CMSC 422", "credits": 3, "rooms": ["roddy 140"]})
    assert not result.ok
    assert "could mean" in result.message
    assert "RODDY140" in result.message and "Roddy 140" in result.message
    assert snapshot(roddy) == before
    asked = box.call("get_room", {"name": "roddy 140"})
    assert "could mean" in asked.message


def test_add_course_with_no_capacity_and_no_room_asks_for_it(box, request_):
    before = snapshot(request_)
    result = box.call("add_course", {"course_id": "CMSC 423", "credits": 3})
    assert not result.ok and "Capacity is required" in result.message
    assert snapshot(request_) == before


def test_add_course_with_an_unknown_room_is_rejected(box, request_):
    before = snapshot(request_)
    result = box.call("add_course", {"course_id": "CMSC 424", "credits": 3, "capacity": 20, "rooms": ["NOPE100"]})
    assert not result.ok and "NOPE100" in result.message
    assert snapshot(request_) == before


def test_story_9_add_a_lab(box, request_):
    result = box.call("add_lab", {"name": "BIO147L", "capacity": 20})
    assert result.ok
    lab = next(lab for lab in config(request_).config.labs if lab.name == "BIO147L")
    assert lab.capacity == 20


def test_story_9_add_a_faculty_member(box, request_):
    result = box.call("add_faculty", {"name": "Dr. Smith", "maximum_credits": 12})
    assert result.ok, result.message
    person = next(p for p in config(request_).config.faculty if p.name == "Dr. Smith")
    assert person.maximum_credits == 12
    assert "up to 12 credits" in result.message


def test_story_9_add_a_time_slot_on_friday(box, request_):
    # The example already covers FRI 08:00-17:00, so make room for the new block first.
    session = session_store.get_session(request_)

    def short_friday(draft):
        draft.time_slot_config.times["FRI"] = [TimeBlock(start="08:00", end="09:00", spacing=60)]

    apply_edit(session.config, "timeslot", short_friday)
    result = box.call("add_time_slot", {"day": "Friday", "start": "09:00", "end": "17:00"})
    assert result.ok, result.message
    blocks = [(b.start, b.end) for b in config(request_).time_slot_config.times["FRI"]]
    assert ("09:00", "17:00") in blocks
    assert "Friday: 09:00-17:00" in result.message


def test_overlapping_time_slot_is_rejected(box, request_):
    before = snapshot(request_)
    result = box.call("add_time_slot", {"day": "FRI", "start": "09:00", "end": "17:00"})
    assert not result.ok and "overlaps" in result.message
    assert snapshot(request_) == before


def test_story_9_add_a_class_pattern(box, request_):
    count = len(config(request_).time_slot_config.classes)
    result = box.call("add_class_pattern", {"credits": 3, "meetings": [{"day": "MON", "duration": 150}]})
    assert result.ok, result.message
    patterns = config(request_).time_slot_config.classes
    assert len(patterns) == count + 1
    added = patterns[-1]
    assert added.credits == 3
    assert [(str(getattr(m.day, "value", m.day)), m.duration) for m in added.meetings] == [("MON", 150)]


def test_add_class_pattern_with_several_meetings_is_one_edit(box, request_):
    count = len(config(request_).time_slot_config.classes)
    result = box.call(
        "add_class_pattern",
        {"credits": 3, "meetings": [{"day": "TUE", "duration": 75}, {"day": "THU", "duration": 75}]},
    )
    assert result.ok, result.message
    assert len(config(request_).time_slot_config.classes[-1].meetings) == 2
    assert len(config(request_).time_slot_config.classes) == count + 1


def test_add_class_pattern_with_one_bad_meeting_adds_nothing(box, request_):
    before = snapshot(request_)
    result = box.call(
        "add_class_pattern",
        {"credits": 3, "meetings": [{"day": "TUE", "duration": 75}, {"day": "THU", "duration": -5}]},
    )
    assert not result.ok and "Meeting 2" in result.message
    assert snapshot(request_) == before


def test_story_9_duplicate_room_is_rejected(roddy, box):
    before = snapshot(roddy)
    result = box.call("add_room", {"name": "RODDY140", "capacity": 20})
    assert not result.ok and not result.changed
    assert "'RODDY140' already exists" in result.message
    assert room(roddy, "RODDY140").capacity == 30
    assert snapshot(roddy) == before


def test_adding_with_no_configuration(no_config, box):
    result = box.call("add_room", {"name": "RODDY150", "capacity": 35})
    assert not result.ok and result.message == NO_CONFIG_MESSAGE


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("add_lab", {"name": "BIO147L", "capacity": 20}),
        ("add_faculty", {"name": "Dr. Smith", "maximum_credits": 12}),
        ("add_class_pattern", {"credits": 3, "meetings": [{"day": "MON", "duration": 150}]}),
    ],
)
def test_story_9_each_reply_says_applied_but_not_saved(box, tool, args):
    result = box.call(tool, args)
    assert result.ok, result.message
    reply = service.compose(box.results)
    assert reply.changed
    assert "applied but not yet saved" in reply.message


def test_a_failed_add_says_nothing_was_changed(roddy, box):
    box.call("add_room", {"name": "RODDY140", "capacity": 20})
    reply = service.compose(box.results)
    assert not reply.ok and not reply.changed
    assert "The configuration was not changed." in reply.message
    assert "applied" not in reply.message
