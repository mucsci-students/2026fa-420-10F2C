"""
Tests for the AI assistant's update and delete tools (Sprint 3 Section 4, Section 10.1).

The tools are called the way the AI calls them, against the real scheduler library and the
shipped example configuration (rooms Roddy 136/140/147, labs Linux/Mac, faculty such as Hogg,
Schwartz and sam, and course sections such as CMSC 140 x2 and CMSC 420). No AI is involved.

    ToolBox(request).call("update_room", {"name": "Roddy 140", "capacity": 20})
    ToolBox(request).call("delete_room", {"name": "Roddy 136"})   # only describes the delete
    ToolBox(later(request)).call("confirm_delete")                # a LATER message does it

What these cover, from the Sprint 3 requirements:
  * every area can be updated and deleted through the tools (Section 4)
  * arguments are validated before anything runs, and a rejected edit leaves the last valid
    configuration untouched (Section 4)
  * deletes use the same safeguard as the Delete pages: they are shown first, need a separate
    confirmation, and are undoable (Section 4, "same deletion ... safeguards")
  * the reply says what really happened, and whether it is applied or also saved (Section 4)
"""

import pytest

from gui import session_store
from gui.ai import changes
from gui.ai.tools import TOOLS_BY_NAME, ToolBox
from gui.controllers import meetings as meeting_ctrl
from gui.controllers import patterns as pattern_ctrl


class FakeRequest:
    """Enough of a Django request for get_session(): just a session dict."""

    def __init__(self, session=None):
        self.session = {} if session is None else dict(session)


def later(request):
    """The NEXT message from the same browser: a new request that shares the browser's session."""
    return FakeRequest(request.session)


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


def session(request_):
    return session_store.get_session(request_)


def config(request_):
    return session(request_).config


def snapshot(request_):
    return config(request_).model_dump_json()


def fresh(request_):
    """Open the configuration and mark it as saved, so the next change is easy to spot."""
    session(request_).dirty = False
    return request_


def room(request_, name):
    return next(
        (item for item in config(request_).config.rooms if item.name == name), None
    )


def lab(request_, name):
    return next(
        (item for item in config(request_).config.labs if item.name == name), None
    )


def person(request_, name):
    return next(
        (item for item in config(request_).config.faculty if item.name == name), None
    )


def sections(request_, course_id):
    return [
        item for item in config(request_).config.courses if item.course_id == course_id
    ]


def course_ids(request_):
    return {item.course_id for item in config(request_).config.courses}


def confirm(request_):
    """Confirm in a later message, the way a user answers "confirm"."""
    return ToolBox(later(request_)).call("confirm_delete")


# ---------------------------------------------------------------------- #
#  Registry
# ---------------------------------------------------------------------- #
UPDATE_TOOLS = (
    "update_room",
    "update_lab",
    "update_course",
    "update_faculty",
    "update_time_slot",
    "update_timing_options",
    "update_class_pattern",
    "update_meeting",
    "update_global_settings",
)
DELETE_TOOLS = (
    "delete_room",
    "delete_lab",
    "delete_course",
    "delete_faculty",
    "delete_time_slot",
    "delete_class_pattern",
    "delete_meeting",
)


def test_every_area_can_be_updated_and_deleted():
    for name in (
        UPDATE_TOOLS
        + DELETE_TOOLS
        + ("confirm_delete", "cancel_delete", "add_meeting", "list_meetings")
    ):
        assert name in TOOLS_BY_NAME, name


def test_updates_write_and_delete_requests_only_describe():
    assert all(TOOLS_BY_NAME[name].write for name in UPDATE_TOOLS)
    assert not any(
        TOOLS_BY_NAME[name].write for name in DELETE_TOOLS
    )  # they delete nothing
    assert (
        TOOLS_BY_NAME["confirm_delete"].write
        and not TOOLS_BY_NAME["cancel_delete"].write
    )


def test_update_tools_only_require_what_names_the_item():
    required = lambda name: set(
        TOOLS_BY_NAME[name].args.model_json_schema()["required"]
    )
    assert required("update_room") == {"name"}
    assert required("update_course") == {"course_id"}
    assert required("update_class_pattern") == {"pattern_number"}
    assert required("update_meeting") == {"pattern_number", "meeting_number"}
    assert required("update_time_slot") == {"day", "start"}


# ---------------------------------------------------------------------- #
#  Rooms and labs
# ---------------------------------------------------------------------- #
def test_update_room_changes_only_what_was_asked(box, request_):
    fresh(request_)
    result = box.call("update_room", {"name": "roddy 140", "capacity": 40})
    assert result.ok and result.changed and result.write
    assert "capacity 28 -> 40" in result.message
    assert room(request_, "Roddy 140").capacity == 40
    assert room(request_, "Roddy 136").capacity == 28  # nothing else moved
    assert session(request_).dirty is True  # applied, not saved
    assert session(request_).history.can_undo  # and undoable like any other edit


def test_update_room_rename_follows_every_reference(box, request_):
    result = box.call("update_room", {"name": "Roddy 147", "new_name": "Roddy 150"})
    assert result.ok and result.changed
    assert room(request_, "Roddy 147") is None and room(request_, "Roddy 150")
    assert all("Roddy 147" not in item.room for item in config(request_).config.courses)
    assert any("Roddy 150" in item.room for item in config(request_).config.courses)
    assert (
        "Roddy 150" in person(request_, "Hardy").room_preferences
    )  # faculty preference moved too


def test_update_room_adds_and_removes_features(box, request_):
    box.call(
        "update_room",
        {"name": "Roddy 136", "features": {"add": ["projector", "whiteboard"]}},
    )
    assert sorted(room(request_, "Roddy 136").features) == ["projector", "whiteboard"]
    result = ToolBox(request_).call(
        "update_room", {"name": "Roddy 136", "features": {"remove": ["projector"]}}
    )
    assert result.ok and "features removed: projector" in result.message
    assert sorted(room(request_, "Roddy 136").features) == ["whiteboard"]


def test_update_room_with_the_same_values_changes_nothing(box, request_):
    fresh(request_)
    before = snapshot(request_)
    result = box.call("update_room", {"name": "Roddy 140", "capacity": 28})
    assert result.ok and not result.changed
    assert "nothing was changed" in result.message
    assert snapshot(request_) == before
    assert session(request_).dirty is False and not session(request_).history.can_undo


def test_update_room_without_any_change_asks_what_to_change(box, request_):
    before = snapshot(request_)
    result = box.call("update_room", {"name": "Roddy 140"})
    assert not result.ok and result.write and not result.changed
    assert "what to change" in result.message
    assert snapshot(request_) == before


def test_update_room_for_a_room_that_does_not_exist(box, request_):
    before = snapshot(request_)
    result = box.call("update_room", {"name": "Atlantis", "capacity": 10})
    assert not result.ok and "No room named 'Atlantis'" in result.message
    assert snapshot(request_) == before


def test_a_rejected_room_edit_leaves_the_last_valid_configuration(box, request_):
    fresh(request_)
    before = snapshot(request_)
    result = box.call("update_room", {"name": "Roddy 140", "capacity": 0})
    assert not result.ok and result.write and not result.changed
    assert snapshot(request_) == before
    assert session(request_).dirty is False and not session(request_).history.can_undo


def test_malformed_update_arguments_are_rejected_before_anything_runs(box, request_):
    before = snapshot(request_)
    result = box.call("update_room", {"name": "Roddy 140", "capacity": "lots"})
    assert not result.ok and "capacity" in result.message
    result = box.call(
        "update_room",
        {
            "name": "Roddy 140",
            "availability": [{"day": "someday", "start": "09:00", "end": "10:00"}],
        },
    )
    assert not result.ok and "weekday" in result.message.lower()
    assert snapshot(request_) == before


def test_update_lab_changes_capacity(box, request_):
    result = box.call("update_lab", {"name": "mac", "capacity": 30})
    assert result.ok and result.changed
    assert lab(request_, "Mac").capacity == 30 and lab(request_, "Linux").capacity == 28


# ---------------------------------------------------------------------- #
#  Courses
# ---------------------------------------------------------------------- #
def test_update_course_with_several_sections_asks_which_one(box, request_):
    before = snapshot(request_)
    result = box.call("update_course", {"course_id": "CMSC 140", "capacity": 20})
    assert (
        not result.ok
        and "has 2 sections" in result.message
        and "CMSC 140.01" in result.message
    )
    assert snapshot(request_) == before


def test_update_course_changes_just_the_chosen_section(box, request_):
    result = box.call(
        "update_course", {"course_id": "CMSC 140", "section": "02", "capacity": 20}
    )
    assert result.ok and result.changed and "capacity 28 -> 20" in result.message
    first, second = sections(request_, "CMSC 140")
    assert (first.capacity, second.capacity) == (28, 20)


def test_update_course_edits_lists_by_adding_and_removing(box, request_):
    result = box.call(
        "update_course",
        {
            "course_id": "cmsc420",
            "conflicts": {"add": ["CMSC 162"]},
            "labs": {"replace": ["Linux"]},
        },
    )
    assert result.ok and result.changed, result.message
    (course,) = sections(request_, "CMSC 420")
    assert (
        "CMSC 162" in course.conflicts and "CMSC 380" in course.conflicts
    )  # added, the rest kept
    assert list(course.lab) == ["Linux"]


def test_update_course_can_hand_staffing_back_to_the_scheduler(box, request_):
    result = box.call(
        "update_course",
        {"course_id": "CMSC 161", "section": "01", "faculty": {"replace": []}},
    )
    assert result.ok and result.changed, result.message
    assert not sections(request_, "CMSC 161")[
        0
    ].faculty  # "chosen from faculty preferences"


def test_renaming_a_course_updates_what_points_at_it(box, request_):
    result = box.call(
        "update_course", {"course_id": "CMSC 420", "new_course_id": "CMSC 421"}
    )
    assert result.ok and result.changed, result.message
    assert "CMSC 420" not in course_ids(request_) and "CMSC 421" in course_ids(request_)
    assert "CMSC 421" in person(request_, "Hobbs").course_preferences
    assert "CMSC 420" not in person(request_, "Hobbs").course_preferences


def test_update_course_with_an_unknown_room_changes_nothing(box, request_):
    fresh(request_)
    before = snapshot(request_)
    result = box.call(
        "update_course", {"course_id": "CMSC 420", "rooms": {"add": ["Atlantis"]}}
    )
    assert not result.ok and result.write and "Atlantis" in result.message
    assert snapshot(request_) == before and session(request_).dirty is False


# ---------------------------------------------------------------------- #
#  Faculty
# ---------------------------------------------------------------------- #
def test_update_faculty_changes_limits_and_preferences(box, request_):
    result = box.call(
        "update_faculty",
        {
            "name": "dr. schwartz",
            "maximum_credits": 4,
            "preferences": [
                {"kind": "course", "name": "cmsc420", "weight": 7},
                {"kind": "room", "name": "Roddy 140"},  # no weight: remove it
            ],
        },
    )
    assert result.ok and result.changed, result.message
    schwartz = person(request_, "Schwartz")
    assert schwartz.maximum_credits == 4
    assert schwartz.course_preferences["CMSC 420"] == 7
    assert (
        "Roddy 140" not in schwartz.room_preferences
        and "Roddy 136" in schwartz.room_preferences
    )


def test_update_faculty_rejects_a_preference_for_something_that_does_not_exist(
    box, request_
):
    before = snapshot(request_)
    result = box.call(
        "update_faculty",
        {
            "name": "Hogg",
            "preferences": [{"kind": "course", "name": "CMSC 999", "weight": 5}],
        },
    )
    assert not result.ok and "CMSC 999" in result.message
    result = box.call(
        "update_faculty",
        {
            "name": "Hogg",
            "preferences": [{"kind": "room", "name": "Roddy 140", "weight": 99}],
        },
    )
    assert not result.ok
    assert snapshot(request_) == before


# ---------------------------------------------------------------------- #
#  Time slots, class patterns, meetings, global settings
# ---------------------------------------------------------------------- #
def test_update_time_slot_finds_the_slot_by_day_and_start(box, request_):
    result = box.call(
        "update_time_slot", {"day": "monday", "start": "8:00", "new_spacing": 30}
    )
    assert result.ok and result.changed, result.message
    assert config(request_).time_slot_config.times["MON"][0].spacing == 30


def test_update_time_slot_lists_the_real_slots_when_none_matches(box, request_):
    before = snapshot(request_)
    result = box.call(
        "update_time_slot", {"day": "MON", "start": "09:15", "new_spacing": 30}
    )
    assert (
        not result.ok
        and "no time slot starting at 09:15" in result.message
        and "08:00-19:00" in result.message
    )
    assert snapshot(request_) == before


def test_update_timing_options(box, request_):
    result = box.call("update_timing_options", {"max_time_gap": 40})
    assert result.ok and result.changed and "max time gap 30 -> 40" in result.message
    assert config(request_).time_slot_config.max_time_gap == 40
    assert config(request_).time_slot_config.min_time_overlap == 45  # untouched


def test_update_class_pattern_can_disable_it(box, request_):
    result = box.call("update_class_pattern", {"pattern_number": 1, "enabled": False})
    assert result.ok and result.changed, result.message
    assert config(request_).time_slot_config.classes[1].disabled is True
    assert config(request_).time_slot_config.classes[0].disabled is False


def test_update_class_pattern_with_a_number_that_does_not_exist(box, request_):
    result = box.call("update_class_pattern", {"pattern_number": 99, "enabled": False})
    assert not result.ok and "no class pattern 99" in result.message.lower()


def test_update_meeting_is_found_by_pattern_and_meeting_number(box, request_):
    result = box.call(
        "update_meeting", {"pattern_number": 0, "meeting_number": 2, "duration": 60}
    )
    assert result.ok and result.changed, result.message
    meetings = config(request_).time_slot_config.classes[0].meetings
    assert [meeting.duration for meeting in meetings] == [50, 60, 50]
    result = box.call(
        "update_meeting", {"pattern_number": 0, "meeting_number": 9, "duration": 60}
    )
    assert not result.ok and "numbered 1 to 3" in result.message


def test_add_meeting_appends_to_the_pattern(box, request_):
    result = box.call(
        "add_meeting", {"pattern_number": 1, "day": "monday", "duration": 50}
    )
    assert result.ok and result.changed, result.message
    assert len(config(request_).time_slot_config.classes[1].meetings) == 3


def test_list_meetings_shows_numbered_meetings(box):
    result = box.call("list_meetings")
    assert result.ok and not result.write
    assert "Pattern 0" in result.message and "numbered from 1" in result.message


def test_update_global_settings_changes_limit_and_flags_together(box, request_):
    result = box.call(
        "update_global_settings", {"limit": 25, "disable_flags": ["pack_rooms"]}
    )
    assert result.ok and result.changed, result.message
    assert config(request_).limit == 25
    flags = [
        str(getattr(flag, "value", flag)) for flag in config(request_).optimizer_flags
    ]
    assert "pack_rooms" not in flags and "faculty_course" in flags


def test_update_global_settings_can_reset_the_limit(box, request_):
    box.call("update_global_settings", {"limit": 25})
    result = ToolBox(request_).call("update_global_settings", {"reset_limit": True})
    assert result.ok and config(request_).limit == 10


def test_update_global_settings_rejects_nonsense(box, request_):
    before = snapshot(request_)
    assert not box.call("update_global_settings", {"limit": 5, "reset_limit": True}).ok
    assert not box.call("update_global_settings", {"enable_flags": ["warp_drive"]}).ok
    assert not box.call("update_global_settings", {"limit": 0}).ok
    assert snapshot(request_) == before


@pytest.mark.parametrize(
    "tool, args",
    [
        ("update_room", {"name": "Roddy 140", "capacity": 40}),
        ("update_course", {"course_id": "CMSC 420", "capacity": 20}),
        ("update_faculty", {"name": "sam", "maximum_credits": 6}),
        ("update_global_settings", {"limit": 25}),
    ],
)
def test_without_a_configuration_updates_say_so(tool, args, box, monkeypatch, request_):
    monkeypatch.setattr(session_store, "AUTO_LOAD_EXAMPLE", False)
    result = ToolBox(FakeRequest()).call(tool, args)
    assert not result.ok and "no configuration" in result.message.lower()


# ---------------------------------------------------------------------- #
#  Deletes are described first and only a later message carries them out
# ---------------------------------------------------------------------- #
def test_a_delete_request_only_describes_what_would_happen(box, request_):
    fresh(request_)
    before = snapshot(request_)
    result = box.call("delete_room", {"name": "roddy 136"})
    assert result.ok and not result.changed and not result.write
    assert (
        "Roddy 136" in result.message
        and "Nothing has been deleted yet" in result.message
    )
    assert snapshot(request_) == before
    assert session(request_).dirty is False and not session(request_).history.can_undo


def test_the_description_lists_the_sections_that_would_be_deleted_too(box, request_):
    result = box.call(
        "delete_room", {"name": "Roddy 136"}
    )  # the only room of CMSC 362 and 476
    assert result.ok and "CMSC 476" in result.message
    assert "CMSC 476" in course_ids(request_)  # still here: nothing was deleted


def test_a_delete_cannot_be_confirmed_in_the_same_message(box, request_):
    before = snapshot(request_)
    assert box.call("delete_room", {"name": "Roddy 136"}).ok
    result = box.call("confirm_delete")
    assert not result.ok and "separate message" in result.message
    assert snapshot(request_) == before
    assert confirm(request_).ok  # the next message can


def test_confirming_in_a_later_message_deletes_it_and_it_can_be_undone(box, request_):
    fresh(request_)
    box.call("delete_room", {"name": "Roddy 136"})
    result = confirm(request_)
    assert result.ok and result.changed and result.write
    assert (
        "Deleted room 'Roddy 136'" in result.message
        and "History page" in result.message
    )
    assert room(request_, "Roddy 136") is None
    assert session(request_).dirty is True and session(request_).history.can_undo


def test_deleting_a_room_also_deletes_the_sections_that_cannot_exist_without_it(
    box, request_
):
    box.call("delete_room", {"name": "Roddy 136"})
    assert confirm(request_).ok
    assert room(request_, "Roddy 136") is None
    assert "CMSC 476" not in course_ids(request_)  # its only room was Roddy 136


def test_a_confirmation_works_once(box, request_):
    box.call("delete_lab", {"name": "Mac"})
    assert confirm(request_).ok
    again = confirm(request_)
    assert not again.ok and "nothing waiting" in again.message


def test_confirming_with_nothing_described_deletes_nothing(request_):
    before = snapshot(request_)
    result = ToolBox(request_).call("confirm_delete")
    assert not result.ok and "nothing waiting" in result.message
    assert snapshot(request_) == before


def test_cancel_forgets_the_delete(box, request_):
    before = snapshot(request_)
    box.call("delete_room", {"name": "Roddy 136"})
    result = ToolBox(later(request_)).call("cancel_delete")
    assert result.ok and not result.changed and "Cancelled" in result.message
    assert not confirm(request_).ok
    assert snapshot(request_) == before


def test_a_newer_description_replaces_the_older_one(box, request_):
    box.call("delete_room", {"name": "Roddy 136"})
    ToolBox(later(request_)).call("delete_lab", {"name": "Mac"})
    assert confirm(request_).ok
    assert lab(request_, "Mac") is None and room(request_, "Roddy 147")


def test_a_delete_is_refused_when_the_configuration_changed_after_it_was_described(
    box, request_
):
    box.call("delete_lab", {"name": "Mac"})
    assert (
        ToolBox(later(request_))
        .call("update_room", {"name": "Roddy 136", "capacity": 30})
        .ok
    )
    result = confirm(request_)
    assert not result.ok and "changed after I described" in result.message
    assert lab(request_, "Mac")


def test_a_described_delete_expires(box, request_, monkeypatch):
    box.call("delete_lab", {"name": "Mac"})
    monkeypatch.setattr(
        changes, "_now", lambda: changes.time.monotonic() + changes.PENDING_SECONDS + 5
    )
    result = confirm(request_)
    assert not result.ok and "too long ago" in result.message
    assert lab(request_, "Mac")


def test_another_browser_cannot_confirm_my_delete(box, request_):
    box.call("delete_lab", {"name": "Mac"})
    other = ToolBox(FakeRequest()).call("confirm_delete")  # a different browser session
    assert not other.ok and "nothing waiting" in other.message
    assert lab(request_, "Mac")


def test_delete_describes_a_missing_item_without_staging_anything(box, request_):
    result = box.call("delete_room", {"name": "Atlantis"})
    assert not result.ok and "No room named 'Atlantis'" in result.message
    assert not confirm(request_).ok


def new_pattern(request_):
    """Add a fresh one-meeting pattern (as the existing pattern tests do) and return its number."""
    pattern_ctrl.add_pattern(
        request_,
        {
            "credits": 3,
            "start_time": None,
            "enabled": True,
            "meeting_day": "TUE",
            "meeting_duration": 50,
            "meeting_lab": False,
            "meeting_delivery": "in_person",
            "meeting_start_time": None,
        },
    )
    return len(config(request_).time_slot_config.classes) - 1


def test_deleting_each_kind_of_item(request_):
    """Only deletes the existing controller tests already prove valid on the example file."""
    number = new_pattern(request_)
    meeting_ctrl.add_meeting(
        request_,
        number,
        {
            "day": "THU",
            "duration": 50,
            "lab": False,
            "delivery": "in_person",
            "start_time": None,
        },
    )
    classes = lambda: config(request_).time_slot_config.classes
    cases = [
        (
            "delete_faculty",
            {"name": "Zoppetti"},
            lambda: person(request_, "Zoppetti") is None,
        ),
        ("delete_lab", {"name": "Mac"}, lambda: lab(request_, "Mac") is None),
        (
            "delete_course",
            {"course_id": "CMSC 162"},
            lambda: "CMSC 162" not in course_ids(request_),
        ),
        (
            "delete_time_slot",
            {"day": "tue", "start": "13:10"},
            lambda: len(config(request_).time_slot_config.times["TUE"]) == 2,
        ),
        (
            "delete_meeting",
            {"pattern_number": number, "meeting_number": 2},
            lambda: len(classes()[number].meetings) == 1,
        ),
        (
            "delete_class_pattern",
            {"pattern_number": number},
            lambda: len(classes()) == number,
        ),
    ]
    for tool, args, deleted in cases:
        described = ToolBox(later(request_)).call(tool, args)
        assert described.ok and not described.changed, (tool, described.message)
        result = confirm(request_)
        assert result.ok and result.changed, (tool, result.message)
        assert deleted(), tool


def test_deleting_a_course_with_several_sections_asks_which(box, request_):
    result = box.call("delete_course", {"course_id": "CMSC 140"})
    assert not result.ok and "has 2 sections" in result.message
    result = box.call("delete_course", {"course_id": "CMSC 140", "section": "09"})
    assert not result.ok and "no section '09'" in result.message


def test_the_only_time_slot_of_a_day_and_the_only_meeting_of_a_pattern_cannot_be_deleted(
    box, request_
):
    friday = box.call("delete_time_slot", {"day": "FRI", "start": "08:00"})
    assert not friday.ok and "only time block on FRI" in friday.message
    number = new_pattern(request_)
    result = box.call("delete_meeting", {"pattern_number": number, "meeting_number": 1})
    assert not result.ok
    assert not confirm(request_).ok  # nothing was staged by the refusals


# ---------------------------------------------------------------------- #
#  Through the chat endpoint, one message at a time
# ---------------------------------------------------------------------- #
SCRIPT = {
    "Delete room Roddy 136": [("delete_room", {"name": "Roddy 136"})],
    "confirm": [("confirm_delete", {})],
    "cancel": [("cancel_delete", {})],
    "Delete it and confirm": [
        ("delete_room", {"name": "Roddy 136"}),
        ("confirm_delete", {}),
    ],
    "Make Roddy 140 bigger": [("update_room", {"name": "Roddy 140", "capacity": 40})],
}


class ScriptedRunner:
    """Stands in for the AI: calls the scripted tools for each message."""

    def run(self, text, toolbox):
        for name, args in SCRIPT[text]:
            toolbox.call(name, args)
        return ""


@pytest.fixture
def chat(client, monkeypatch):
    from gui.ai import service

    monkeypatch.setattr(service, "get_runner", lambda: ScriptedRunner())

    def send(text):
        return client.post("/assistant/ask/", {"message": text}).json()

    return send


def test_a_delete_over_two_chat_messages(chat):
    first = chat("Delete room Roddy 136")
    assert (
        first["ok"]
        and first["changed"] is False
        and "Nothing has been deleted yet" in first["reply"]
    )
    second = chat("confirm")
    assert second["ok"] and second["changed"] is True and second["dirty"] is True
    assert "Deleted room 'Roddy 136'" in second["reply"]
    assert "applied but not yet saved" in second["reply"]


def test_a_delete_and_its_confirmation_in_one_chat_message_deletes_nothing(
    chat, client
):
    body = chat("Delete it and confirm")
    assert body["changed"] is False and body["ok"] is False
    assert (
        "separate message" in body["reply"] and "not changed" in body["reply"].lower()
    )
    assert (
        chat("confirm")["changed"] is True
    )  # the description is still waiting for a real confirmation


def test_cancel_over_chat_keeps_everything(chat):
    chat("Delete room Roddy 136")
    assert chat("cancel")["changed"] is False
    again = chat("confirm")
    assert again["ok"] is False and again["changed"] is False


def test_an_update_over_chat_reports_applied_but_not_saved(chat):
    body = chat("Make Roddy 140 bigger")
    assert body["ok"] and body["changed"] and body["dirty"]
    assert (
        "capacity 28 -> 40" in body["reply"]
        and "not yet saved to a file" in body["reply"]
    )


# ---------------------------------------------------------------------- #
#  What is shown: actions are the answer, lookups are for the AI
# ---------------------------------------------------------------------- #
def test_only_lookups_are_not_final():
    lookups = {tool.name for tool in TOOLS_BY_NAME.values() if not tool.final}
    assert lookups and all(
        name.startswith(("list_", "get_", "show_")) for name in lookups
    )
    for name in (
        UPDATE_TOOLS
        + DELETE_TOOLS
        + ("confirm_delete", "cancel_delete", "describe_capabilities", "add_room")
    ):
        assert TOOLS_BY_NAME[name].final, name


def test_a_look_then_a_delete_shows_only_the_delete(box):
    from gui.ai import service

    box.call("list_rooms")
    box.call("delete_room", {"name": "Roddy 136"})
    reply = service.compose(box.results, "I'll look at the rooms first.")
    assert (
        "Roddy 136" in reply.message and "Nothing has been deleted yet" in reply.message
    )
    assert (
        "Rooms (" not in reply.message
        and "look at the rooms first" not in reply.message
    )


def test_lookups_alone_show_the_models_words_or_else_the_lookup(box):
    from gui.ai import service

    box.call("list_rooms")
    assert (
        service.compose(box.results, "You have three rooms.").message
        == "You have three rooms."
    )
    assert "Rooms (" in service.compose(box.results, "").message


def test_chat_history_is_kept_per_browser_and_trimmed(monkeypatch, request_):
    from gui.ai import service

    monkeypatch.setenv(service.HISTORY_ENV, "4")
    seen = []

    class Runner:
        def run(self, text, toolbox):
            seen.append(list(toolbox.history))
            return "ok"

    monkeypatch.setattr(service, "get_runner", lambda: Runner())
    for number in range(4):
        service.handle_request(request_, f"message {number}")
    assert seen[0] == []
    assert [item["content"] for item in seen[-1]] == [
        "message 1",
        "ok",
        "message 2",
        "ok",
    ]
    other = FakeRequest()
    service.handle_request(other, "hello")
    assert seen[-1] == []  # another browser never sees this chat
