"""
Tests for asking follow-up questions before changing the configuration (Sprint 3: AI request clarification).

The tools are called the way the AI calls them, against the real scheduler library, the real session and
the shipped example configuration. No AI is involved: these check what the application does with an
incomplete or ambiguous request.

    ToolBox(request).call("add_room", {"name": "RODDY150"})                 # capacity is missing: a question
    ToolBox(later(request)).call("provide_details", {"details": {"capacity": 35}})   # the answer: the room is added

What these cover:
  * a request that lacks a required value (or names something that matches several items) is NOT run: the
    reply asks only for what is missing or unclear, lists the matching items, and says nothing changed
  * the application stores the unfinished request and merges the answer itself (provide_details), reusing the
    tool's own argument schema and checks, so nothing is asked twice and nothing is repeated by the user
  * a skipped recommended detail ("none") is remembered as answered; an invalid answer is asked again
  * an answer may also correct a value given earlier; a fresh request of the same tool replaces the waiting one
  * while a request waits, actions are refused (lookups are not); cancelling or waiting too long drops it
  * a combined change (apply_changes) waits as a whole and is resumed with the step the details belong to
  * the application tells the AI what is waiting, so it can answer with provide_details
"""

import pytest
from pydantic import ValidationError

from gui import session_store
from gui.ai import chats, clarify, generation, runner, service
from gui.ai.tools import TOOLS, TOOLS_BY_NAME, AddPlaceArgs, ToolBox
from gui.controllers import rooms
from tests.canonical import canonical


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
    request = FakeRequest()
    session_store.get_session(
        request
    )  # opens the example, so later messages share the session
    return request


def session(request_):
    return session_store.get_session(request_)


def snapshot(request_):
    return session(request_).config.model_dump_json()


def call(request_, name, args=None):
    return ToolBox(later(request_)).call(name, args)


def provide(request_, details, step=None):
    arguments = {"details": details}
    if step is not None:
        arguments["step"] = step
    return call(request_, "provide_details", arguments)


def room_named(request_, name):
    return next(
        (r for r in session(request_).config.config.rooms if r.name == name), None
    )


def waiting(request_):
    return clarify.current(session(request_))


@pytest.fixture
def incomplete_room(request_):
    """Add a room with no capacity: the request that waits in most of these tests."""
    result = call(request_, "add_room", {"name": "RODDY150"})
    assert result.ok and result.questions
    return request_


# ---------------------------------------------------------------------- #
#  A missing required value is asked for, not guessed or failed
# ---------------------------------------------------------------------- #
def test_a_missing_required_value_is_asked_for_and_nothing_changes(request_):
    before = snapshot(request_)
    result = call(request_, "add_room", {"name": "RODDY150"})

    assert result.ok is True and result.changed is False
    assert [question.field for question in result.questions] == ["capacity"]
    assert "I need a bit more before I can add room 'RODDY150'" in result.message
    assert "Nothing has been changed yet" in result.message
    assert (
        "capacity" in result.message
        and "name:" not in result.message.split("Already noted")[0]
    )
    assert "Already noted: name: RODDY150" in result.message
    assert 'say "cancel"' in result.message
    assert snapshot(request_) == before and session(request_).dirty is False
    assert room_named(request_, "RODDY150") is None


def test_the_question_comes_from_the_tools_own_schema(request_):
    result = call(request_, "add_room", {"name": "RODDY150"})
    assert AddPlaceArgs.model_fields["capacity"].description in result.message


def test_the_unfinished_request_is_stored_with_what_was_given(request_):
    call(request_, "add_room", {"name": "RODDY150", "features": ["projector"]})
    held = waiting(request_)
    assert held.tool == "add_room"
    assert held.details == {"name": "RODDY150", "features": ["projector"]}


def test_the_answer_completes_the_original_request(incomplete_room):
    result = provide(incomplete_room, {"capacity": 35})

    assert result.ok, result.message
    assert result.changed is True and result.tool == "provide_details"
    assert "RODDY150" in result.message and "35" in result.message
    assert room_named(incomplete_room, "RODDY150").capacity == 35
    assert session(incomplete_room).dirty is True
    assert waiting(incomplete_room) is None


def test_only_what_is_still_missing_is_asked_again(request_):
    first = call(request_, "add_time_slot", {"day": "Friday"})
    assert [q.field for q in first.questions] == [
        "start",
        "end",
        "spacing",
    ]  # everything missing, in one message

    second = provide(request_, {"start": "09:00"})
    assert [q.field for q in second.questions] == ["end", "spacing"]
    assert "start:" not in second.message.split("Already noted")[0]
    assert "Already noted" in second.message and "09:00" in second.message
    assert waiting(request_).details["day"] == "Friday"


def test_structured_answers_are_validated_by_the_tools_schema(request_):
    first = call(request_, "add_class_pattern", {"credits": 3})
    assert [q.field for q in first.questions] == ["meetings"]

    result = provide(
        request_,
        {"meetings": [{"day": "MON", "duration": 50}, {"day": "WED", "duration": 50}]},
    )
    assert result.ok, result.message
    patterns = session(request_).config.time_slot_config.classes
    assert any(p.credits == 3 and len(p.meetings) == 2 for p in patterns)


def test_the_ai_framework_path_asks_too(request_):
    """LangChain rejects missing values before the tool runs and reports them through ToolBox.invalid()."""
    with pytest.raises(ValidationError) as info:
        AddPlaceArgs.model_validate({"name": "RODDY150"})
    result = ToolBox(later(request_)).invalid("add_room", info.value)

    assert result.ok and [q.field for q in result.questions] == ["capacity"]
    assert waiting(request_).details == {"name": "RODDY150"}
    assert room_named(request_, "RODDY150") is None


def test_a_wrong_value_is_still_a_plain_failure_with_nothing_stored(request_):
    result = call(request_, "add_room", {"name": "RODDY150", "capacity": "lots"})
    assert not result.ok and not result.questions
    assert waiting(request_) is None


def test_lookups_never_start_a_question(request_):
    result = call(request_, "get_room", {})
    assert not result.ok and not result.questions and waiting(request_) is None


# ---------------------------------------------------------------------- #
#  Recommended details of a new course: asked unless already given; "none" counts as an answer
# ---------------------------------------------------------------------- #
COURSE = {"course_id": "CMSC 421", "credits": 3, "capacity": 20}


def test_add_course_asks_for_faculty_and_rooms_when_not_given(request_):
    before = snapshot(request_)
    result = call(request_, "add_course", COURSE)

    assert result.ok and result.changed is False
    assert [q.field for q in result.questions] == ["faculty", "rooms"]
    assert (
        "Hogg" in result.message and "Roddy 140" in result.message
    )  # relevant options
    assert 'say "none"' in result.message.lower() or "none" in result.message.lower()
    assert snapshot(request_) == before


def test_add_course_only_asks_for_what_was_not_supplied(request_):
    result = call(request_, "add_course", {**COURSE, "rooms": ["Roddy 140"]})
    assert [q.field for q in result.questions] == ["faculty"]

    done = provide(request_, {"faculty": ["Hogg"]})
    assert done.ok and "CMSC 421" in done.message
    assert any(
        c.course_id == "CMSC 421" and c.room == ["Roddy 140"]
        for c in session(request_).config.config.courses
    )


def test_a_skipped_detail_is_not_asked_again(request_):
    call(
        request_, "add_course", {"course_id": "CMSC 420", "credits": 3, "capacity": 20}
    )
    result = provide(
        request_, {"faculty": []}
    )  # "none": a faculty member already prefers CMSC 420
    assert [q.field for q in result.questions] == ["rooms"]
    assert waiting(request_).details["faculty"] == []

    done = provide(request_, {"rooms": ["Roddy 140"]})
    assert done.ok and "chosen from faculty preferences" in done.message


def test_a_skip_the_library_rejects_asks_again_with_the_reason(request_):
    call(request_, "add_course", COURSE)
    result = provide(
        request_, {"faculty": [], "rooms": ["Roddy 140"]}
    )  # nobody prefers CMSC 421

    assert result.ok and [q.field for q in result.questions] == ["faculty"]
    assert (
        "preferences" in result.message.lower() or "required" in result.message.lower()
    )
    assert waiting(request_).details["rooms"] == ["Roddy 140"]  # answered fields stay
    assert all(
        c.course_id != "CMSC 421" for c in session(request_).config.config.courses
    )


def test_a_fully_specified_course_is_added_without_questions(request_):
    result = call(
        request_, "add_course", {**COURSE, "faculty": ["Hogg"], "rooms": ["Roddy 140"]}
    )
    assert result.ok and not result.questions and result.changed
    assert waiting(request_) is None


# ---------------------------------------------------------------------- #
#  Ambiguous names: the options are listed, the rest of the request is kept
# ---------------------------------------------------------------------- #
def test_an_ambiguous_name_lists_the_options_and_changes_nothing(request_):
    rooms.add_room(
        request_, {"name": "RODDY140", "capacity": 30}
    )  # next to "Roddy 140"
    session(request_).dirty = False
    before = snapshot(request_)

    result = call(request_, "update_room", {"name": "roddy 140", "capacity": 40})

    assert result.ok and result.changed is False
    assert [q.field for q in result.questions] == ["name"]
    assert "RODDY140" in result.message and "Roddy 140" in result.message
    assert "could mean" in result.message
    assert snapshot(request_) == before
    assert waiting(request_).details == {"name": "roddy 140", "capacity": 40}


def test_the_answer_picks_the_item_and_the_rest_is_remembered(request_):
    rooms.add_room(request_, {"name": "RODDY140", "capacity": 30})
    call(request_, "update_room", {"name": "roddy 140", "capacity": 40})

    result = provide(request_, {"name": "RODDY140"})

    assert result.ok and result.changed, result.message
    assert room_named(request_, "RODDY140").capacity == 40
    assert room_named(request_, "Roddy 140").capacity != 40


def test_an_ambiguous_room_in_a_list_is_asked_about_too(request_):
    rooms.add_room(request_, {"name": "RODDY140", "capacity": 30})
    result = call(
        request_, "add_course", {**COURSE, "faculty": ["Hogg"], "rooms": ["roddy 140"]}
    )
    assert [q.field for q in result.questions] == ["rooms"]

    done = provide(request_, {"rooms": ["RODDY140"]})
    assert done.ok and any(
        c.course_id == "CMSC 421" and c.room == ["RODDY140"]
        for c in session(request_).config.config.courses
    )


def test_an_ambiguous_delete_asks_first_and_still_needs_its_own_confirmation(request_):
    rooms.add_room(request_, {"name": "RODDY140", "capacity": 30})
    result = call(request_, "delete_room", {"name": "roddy 140"})
    assert result.questions and room_named(request_, "RODDY140") is not None

    review = provide(request_, {"name": "RODDY140"})
    assert review.ok and "Nothing has been deleted yet" in review.message
    assert room_named(request_, "RODDY140") is not None


def test_an_ambiguous_lookup_is_still_just_a_message(request_):
    result = call(request_, "get_room", {"name": "roddy"})
    assert "could mean" in result.message and not result.questions
    assert waiting(request_) is None


# ---------------------------------------------------------------------- #
#  Corrections, bad answers and unknown details
# ---------------------------------------------------------------------- #
def test_an_answer_can_correct_a_value_given_earlier(incomplete_room):
    result = provide(incomplete_room, {"name": "RODDY151", "capacity": 20})

    assert result.ok, result.message
    assert "name: RODDY150 -> RODDY151" in result.message
    assert (
        room_named(incomplete_room, "RODDY151")
        and room_named(incomplete_room, "RODDY150") is None
    )


def test_an_invalid_answer_is_asked_again_and_other_details_are_kept(incomplete_room):
    before = snapshot(incomplete_room)
    result = provide(incomplete_room, {"capacity": "lots"})

    assert result.ok and [q.field for q in result.questions] == ["capacity"]
    assert "capacity" in result.message and snapshot(incomplete_room) == before
    assert waiting(incomplete_room).details == {
        "name": "RODDY150"
    }  # the bad value was not kept

    assert provide(incomplete_room, {"capacity": 25}).ok
    assert room_named(incomplete_room, "RODDY150").capacity == 25


def test_a_detail_the_tool_does_not_have_is_refused_and_the_request_keeps_waiting(
    incomplete_room,
):
    result = provide(incomplete_room, {"colour": "red"})
    assert not result.ok and "'colour'" in result.message
    assert "name, capacity, features" in result.message
    assert waiting(incomplete_room).tool == "add_room"


def test_empty_details_are_refused(incomplete_room):
    result = provide(incomplete_room, {})
    assert not result.ok and waiting(incomplete_room) is not None


def test_a_rejection_when_it_finally_runs_keeps_the_request_waiting(incomplete_room):
    rooms.add_room(
        incomplete_room, {"name": "RODDY150", "capacity": 10}
    )  # edited in the meantime

    result = provide(incomplete_room, {"capacity": 25})

    assert not result.ok and "already exists" in result.message
    assert waiting(incomplete_room).details == {"name": "RODDY150", "capacity": 25}
    assert provide(incomplete_room, {"name": "RODDY152"}).ok  # a correction finishes it


def test_providing_details_with_nothing_waiting_is_refused(request_):
    before = snapshot(request_)
    result = provide(request_, {"capacity": 5})
    assert not result.ok and "Nothing is waiting for details" in result.message
    assert snapshot(request_) == before


# ---------------------------------------------------------------------- #
#  Cancel
# ---------------------------------------------------------------------- #
def test_cancel_drops_the_request_without_touching_the_configuration(incomplete_room):
    before = snapshot(incomplete_room)
    result = call(incomplete_room, "cancel_pending_request")

    assert result.ok and result.changed is False
    assert "Cancelled" in result.message and "RODDY150" in result.message
    assert snapshot(incomplete_room) == before and waiting(incomplete_room) is None
    assert not provide(incomplete_room, {"capacity": 5}).ok


def test_cancel_with_nothing_waiting_says_so(request_):
    result = call(request_, "cancel_pending_request")
    assert result.ok and "Nothing was waiting" in result.message


# ---------------------------------------------------------------------- #
#  While a request waits: actions are refused, lookups are not
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name, args",
    [
        ("add_course", {**COURSE, "faculty": ["Hogg"], "rooms": ["Roddy 140"]}),
        ("update_room", {"name": "Roddy 140", "capacity": 40}),
        ("delete_room", {"name": "Roddy 140"}),
        ("confirm_delete", {}),
        ("undo_changes", {}),
        ("redo_changes", {}),
        ("prepare_schedule_generation", {}),
        ("confirm_schedule_generation", {}),
        ("create_new_configuration", {}),
        ("save_configuration", {}),
        ("load_saved_configuration", {"name": "config_example.json"}),
        (
            "apply_changes",
            {
                "operations": [
                    {"tool": "add_room", "arguments": {"name": "X1", "capacity": 5}}
                ]
            },
        ),
    ],
)
def test_other_actions_are_refused_until_the_request_is_finished_or_cancelled(
    incomplete_room, name, args
):
    before = snapshot(incomplete_room)
    result = call(incomplete_room, name, args)

    assert not result.ok and not result.questions
    assert (
        "still waiting for details" in result.message and "RODDY150" in result.message
    )
    assert 'say "cancel"' in result.message
    assert snapshot(incomplete_room) == before
    assert waiting(incomplete_room).tool == "add_room"  # still waiting


@pytest.mark.parametrize(
    "name, args",
    [
        ("list_rooms", {}),
        ("get_room", {"name": "Roddy 140"}),
        ("list_faculty", {}),
        ("describe_capabilities", {}),
        ("validate_configuration", {}),
        ("show_change_history", {}),
        ("check_generation_status", {}),
        ("list_saved_configurations", {}),
        ("cancel_delete", {}),
        ("open_load_configuration_form", {}),
    ],
)
def test_reading_is_allowed_while_a_request_waits(incomplete_room, name, args):
    result = call(incomplete_room, name, args)
    assert result.ok, result.message
    assert waiting(incomplete_room).tool == "add_room"


def test_the_same_tool_called_afresh_replaces_the_waiting_request(incomplete_room):
    result = call(incomplete_room, "add_room", {"name": "RODDY151", "capacity": 20})

    assert result.ok and result.changed and room_named(incomplete_room, "RODDY151")
    assert room_named(incomplete_room, "RODDY150") is None
    assert (
        "I dropped the earlier unfinished request to add room 'RODDY150'"
        in result.message
    )
    assert waiting(incomplete_room) is None


def test_a_fresh_incomplete_request_of_the_same_tool_replaces_it_too(incomplete_room):
    result = call(incomplete_room, "add_room", {"name": "RODDY151"})
    assert (
        result.questions and "dropped the earlier unfinished request" in result.message
    )
    assert waiting(incomplete_room).details == {"name": "RODDY151"}


def test_every_action_tool_is_classified():
    acting = {tool.name for tool in TOOLS if tool.acts_on_state}
    expected = {
        *(t.name for t in TOOLS if t.name.startswith(("add_", "update_", "delete_"))),
        "apply_changes",
        "confirm_delete",
        "undo_changes",
        "redo_changes",
        "create_new_configuration",
        "load_saved_configuration",
        "save_configuration",
        "prepare_schedule_generation",
        "confirm_schedule_generation",
    }
    assert acting == expected
    for name in ("provide_details", "cancel_pending_request"):
        assert TOOLS_BY_NAME[name].final and not TOOLS_BY_NAME[name].acts_on_state


# ---------------------------------------------------------------------- #
#  One thing waits at a time, for a limited time, in one chat
# ---------------------------------------------------------------------- #
def test_a_question_replaces_a_waiting_delete_review(request_):
    assert (
        "Nothing has been deleted yet"
        in call(request_, "delete_room", {"name": "Roddy 140"}).message
    )
    call(request_, "add_room", {"name": "RODDY150"})
    result = provide(request_, {"capacity": 20})
    assert result.ok
    confirmed = call(request_, "confirm_delete")
    assert (
        not confirmed.ok
        and "nothing waiting to be deleted" in confirmed.message.lower()
    )
    assert any(r.name == "Roddy 140" for r in session(request_).config.config.rooms)


def test_a_question_replaces_waiting_generation_settings(request_):
    assert call(request_, "prepare_schedule_generation").ok
    assert getattr(session(request_), generation._PLAN_ATTR) is not None
    call(request_, "add_room", {"name": "RODDY150"})
    assert getattr(session(request_), generation._PLAN_ATTR) is None


def test_the_request_expires_after_ten_minutes(incomplete_room, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(clarify, "_now", lambda: clock[0])
    call(
        incomplete_room, "add_room", {"name": "RODDY151"}
    )  # restarts the clock at 1000
    clock[0] += clarify.PENDING_SECONDS + 1
    before = snapshot(incomplete_room)

    result = provide(incomplete_room, {"capacity": 20})

    assert (
        not result.ok and "too long" in result.message and "RODDY151" in result.message
    )
    assert snapshot(incomplete_room) == before and waiting(incomplete_room) is None


def test_an_expired_request_no_longer_blocks_other_actions(
    incomplete_room, monkeypatch
):
    clock = [1000.0]
    monkeypatch.setattr(clarify, "_now", lambda: clock[0])
    call(incomplete_room, "add_room", {"name": "RODDY151"})
    clock[0] += clarify.PENDING_SECONDS + 1
    assert call(
        incomplete_room, "update_room", {"name": "Roddy 140", "capacity": 41}
    ).ok


def test_another_chat_forgets_a_waiting_request(incomplete_room):
    chats.record(session(incomplete_room), "user", "add a room")
    chats.new_chat(session(incomplete_room))
    assert waiting(incomplete_room) is None
    assert not provide(incomplete_room, {"capacity": 20}).ok


def test_a_different_configuration_forgets_a_waiting_request(incomplete_room):
    assert call(incomplete_room, "list_rooms").ok  # reading keeps it
    session(incomplete_room).new_config()
    clarify.forget(session(incomplete_room))
    assert waiting(incomplete_room) is None


def test_edits_made_in_between_do_not_cancel_it(incomplete_room):
    rooms.add_room(incomplete_room, {"name": "RODDY200", "capacity": 10})
    assert waiting(incomplete_room) is not None
    assert provide(incomplete_room, {"capacity": 20}).ok


# ---------------------------------------------------------------------- #
#  A combined change waits as a whole
# ---------------------------------------------------------------------- #
def batch(*steps):
    return {"operations": [{"tool": tool, "arguments": args} for tool, args in steps]}


def test_a_step_that_needs_details_stops_the_whole_batch_and_applies_nothing(request_):
    before = snapshot(request_)
    result = call(
        request_,
        "apply_changes",
        batch(
            ("add_room", {"name": "RODDY150", "capacity": 20}),
            ("add_room", {"name": "RODDY151"}),
        ),
    )

    assert result.ok and result.changed is False
    assert [q.field for q in result.questions] == ["capacity"]
    assert "Step 2" in result.message and "add_room" in result.message
    assert (
        canonical(snapshot(request_)) == canonical(before)
        and session(request_).dirty is False
    )
    assert waiting(request_).tool == "apply_changes"


def test_the_batch_is_resumed_with_the_step_the_details_belong_to(request_):
    call(
        request_,
        "apply_changes",
        batch(
            ("add_room", {"name": "RODDY150", "capacity": 20}),
            ("add_room", {"name": "RODDY151"}),
        ),
    )
    result = provide(request_, {"capacity": 30}, step=2)

    assert result.ok and result.changed, result.message
    assert "All 2 changes were applied together" in result.message
    assert (
        room_named(request_, "RODDY150").capacity == 20
        and room_named(request_, "RODDY151").capacity == 30
    )
    assert waiting(request_) is None


def test_a_combined_change_needs_to_know_which_step(request_):
    call(request_, "apply_changes", batch(("add_room", {"name": "RODDY151"})))
    assert not provide(request_, {"capacity": 30}).ok
    assert not provide(request_, {"capacity": 30}, step=7).ok
    assert waiting(request_).tool == "apply_changes"


def test_details_for_a_single_tool_do_not_need_a_step(incomplete_room):
    assert provide(
        incomplete_room, {"capacity": 30}, step=1
    ).ok  # a step is simply not needed


def test_a_batch_step_that_fails_for_another_reason_is_still_all_or_nothing(request_):
    before = snapshot(request_)
    result = call(
        request_,
        "apply_changes",
        batch(
            ("add_room", {"name": "RODDY150", "capacity": 20}),
            ("update_room", {"name": "Nope", "capacity": 3}),
        ),
    )
    assert not result.ok and "None of the 2 changes were applied" in result.message
    assert (
        canonical(snapshot(request_)) == canonical(before) and waiting(request_) is None
    )


# ---------------------------------------------------------------------- #
#  What the AI is told
# ---------------------------------------------------------------------- #
def test_the_ai_is_told_nothing_when_nothing_waits(request_):
    assert ToolBox(request_).waiting_note() == ""


def test_the_ai_is_told_what_waits_what_is_known_and_what_is_missing(incomplete_room):
    note = ToolBox(later(incomplete_room)).waiting_note()
    assert "add_room" in note and "RODDY150" in note and "capacity" in note
    assert "provide_details" in note and "cancel_pending_request" in note


def test_the_note_reaches_the_prompt_the_ai_gets(incomplete_room):
    toolbox = ToolBox(later(incomplete_room))
    prompt = runner.system_prompt(toolbox)
    assert prompt.startswith(runner.BASE_PROMPT)
    assert toolbox.waiting_note() in prompt


def test_the_base_prompt_explains_the_two_ways_to_answer_and_never_to_guess():
    assert (
        "provide_details" in runner.BASE_PROMPT
        and "cancel_pending_request" in runner.BASE_PROMPT
    )
    assert "never invent missing values" in runner.BASE_PROMPT.lower()


# ---------------------------------------------------------------------- #
#  Through the chat (service + endpoint)
# ---------------------------------------------------------------------- #
SCRIPT = {
    "Add a room named RODDY150": [("add_room", {"name": "RODDY150"})],
    "It holds 35": [("provide_details", {"details": {"capacity": 35}})],
    "Cancel that": [("cancel_pending_request", {})],
    "Add a course": [("add_course", COURSE)],
}


class FakeRunner:
    def run(self, text, toolbox):
        for name, args in SCRIPT[text]:
            toolbox.call(name, args)
        return ""


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(service, "get_runner", lambda: FakeRunner())


def ask(client, text):
    response = client.post("/assistant/ask/", {"message": text})
    return response.status_code, response.json()


def browser_session():
    return next(iter(session_store._SESSIONS.values()))


def test_the_chat_asks_then_completes_and_reports_the_change_and_that_it_is_unsaved(
    client, fake
):
    client.get("/")
    _, question = ask(client, "Add a room named RODDY150")
    assert question["ok"] is True and question["changed"] is False
    assert "Nothing has been changed yet" in question["reply"]
    assert "Cancel" in question["suggestions"]
    assert "not yet saved" not in question["reply"] and question["dirty"] is False

    _, done = ask(client, "It holds 35")
    assert done["ok"] is True and done["changed"] is True and done["dirty"] is True
    assert "RODDY150" in done["reply"] and "not yet saved to a file" in done["reply"]
    assert "Undo the last change" in done["suggestions"]


def test_the_chat_cancel_leaves_everything_as_it_was(client, fake):
    client.get("/")
    before = browser_session().config.model_dump_json()
    ask(client, "Add a room named RODDY150")
    _, body = ask(client, "Cancel that")
    assert body["ok"] and "Cancelled" in body["reply"]
    assert (
        browser_session().config.model_dump_json() == before
        and browser_session().dirty is False
    )


def test_a_refusal_in_the_chat_is_shown_as_a_problem_and_changes_nothing(client, fake):
    client.get("/")
    ask(client, "Add a room named RODDY150")
    before = browser_session().config.model_dump_json()
    _, body = ask(client, "Add a course")
    assert body["ok"] is False and "still waiting for details" in body["reply"]
    assert browser_session().config.model_dump_json() == before


def test_the_question_survives_a_page_reload(client, fake):
    client.get("/")
    ask(client, "Add a room named RODDY150")
    last = client.get("/assistant/chat/").json()["messages"][-1]
    assert "I need a bit more" in last["text"] and "Cancel" in last["suggestions"]


# ---------------------------------------------------------------------- #
#  Values the library requires but the tools used to fill in silently: faculty and time slots
# ---------------------------------------------------------------------- #
FACULTY_DETAILS = [
    "maximum_credits",
    "minimum_credits",
    "unique_course_limit",
    "availability",
]
ALL_DEFAULTS = {
    "maximum_credits": 12,
    "minimum_credits": 0,
    "unique_course_limit": 2,
    "availability": [],
}


def person(request_, name):
    return next(
        (p for p in session(request_).config.config.faculty if p.name == name), None
    )


def test_add_faculty_asks_for_the_values_the_library_requires(request_):
    before = snapshot(request_)
    result = call(request_, "add_faculty", {"name": "Dr. Smith"})

    assert result.ok and result.changed is False
    assert [
        q.field for q in result.questions
    ] == FACULTY_DETAILS  # all of them, in one message
    for default in ("default 12", "default 0", "default 2", "09:00-17:00"):
        assert default in result.message
    assert 'say "default"' in result.message.lower()
    assert "name:" not in result.message.split("Already noted")[0]  # the name was given
    assert snapshot(request_) == before and person(request_, "Dr. Smith") is None


def test_the_faculty_questions_come_from_the_schema_and_leave_optional_values_alone(
    request_,
):
    result = call(request_, "add_faculty", {"name": "Dr. Smith"})
    assert "maximum_days" not in [q.field for q in result.questions]
    assert "mandatory_days" not in result.message
    assert (
        "Most credits they can teach" in result.message
    )  # the schema's own description


def test_add_faculty_asks_only_for_what_is_still_unanswered(request_):
    call(request_, "add_faculty", {"name": "Dr. Smith"})
    second = provide(request_, {"maximum_credits": 9})

    assert [q.field for q in second.questions] == [
        "minimum_credits",
        "unique_course_limit",
        "availability",
    ]
    assert waiting(request_).details == {"name": "Dr. Smith", "maximum_credits": 9}


def test_accepting_the_defaults_passes_them_explicitly_and_adds_the_faculty_member(
    request_,
):
    call(request_, "add_faculty", {"name": "Dr. Smith"})
    result = provide(request_, ALL_DEFAULTS)

    assert result.ok and result.changed, result.message
    smith = person(request_, "Dr. Smith")
    assert (
        smith.maximum_credits,
        smith.minimum_credits,
        smith.unique_course_limit,
    ) == (12, 0, 2)
    assert set(smith.times) == {"MON", "TUE", "WED", "THU", "FRI"}
    assert all(
        blocks[0].start == "09:00" and blocks[0].end == "17:00"
        for blocks in smith.times.values()
    )
    assert waiting(request_) is None


def test_chosen_values_are_used_instead_of_the_defaults(request_):
    call(request_, "add_faculty", {"name": "Dr. Smith"})
    result = provide(
        request_,
        {
            "maximum_credits": 9,
            "minimum_credits": 3,
            "unique_course_limit": 1,
            "availability": [{"day": "MON", "start": "10:00", "end": "14:00"}],
        },
    )
    assert result.ok, result.message
    smith = person(request_, "Dr. Smith")
    assert (
        smith.maximum_credits,
        smith.minimum_credits,
        smith.unique_course_limit,
    ) == (9, 3, 1)
    assert list(smith.times) == ["MON"] or smith.times["MON"][0].start == "10:00"


def test_a_missing_name_is_asked_together_with_the_other_values(request_):
    result = call(request_, "add_faculty", {})
    assert [q.field for q in result.questions] == ["name", *FACULTY_DETAILS]


def test_a_fully_specified_faculty_member_is_added_without_questions(request_):
    result = call(request_, "add_faculty", {"name": "Dr. Smith", **ALL_DEFAULTS})
    assert result.ok and result.changed and not result.questions
    assert (
        person(request_, "Dr. Smith").maximum_days == 5
    )  # not asked: the library's own default


def test_a_value_the_user_did_not_give_is_never_filled_in_by_the_tool(request_):
    for details in (
        {"maximum_credits": 12},
        {"unique_course_limit": 2},
        {"availability": []},
    ):
        assert call(request_, "add_faculty", {"name": "Dr. Smith", **details}).questions
    assert person(request_, "Dr. Smith") is None


def test_faculty_in_a_combined_change_waits_as_a_whole(request_):
    before = snapshot(request_)
    result = call(
        request_,
        "apply_changes",
        batch(
            ("add_room", {"name": "RODDY150", "capacity": 20}),
            ("add_faculty", {"name": "Dr. Smith"}),
        ),
    )
    assert result.ok and [q.field for q in result.questions] == FACULTY_DETAILS
    assert "Step 2" in result.message and canonical(snapshot(request_)) == canonical(
        before
    )

    done = provide(request_, ALL_DEFAULTS, step=2)
    assert (
        done.ok
        and done.changed
        and person(request_, "Dr. Smith")
        and room_named(request_, "RODDY150")
    )


def test_add_time_slot_asks_for_the_spacing_the_library_requires(request_):
    before = snapshot(request_)
    result = call(
        request_, "add_time_slot", {"day": "Friday", "start": "09:00", "end": "17:00"}
    )

    assert result.ok and result.changed is False
    assert [q.field for q in result.questions] == ["spacing"]
    assert "default 60" in result.message and 'say "default"' in result.message.lower()
    assert snapshot(request_) == before


def test_the_time_slot_is_added_once_the_spacing_is_given(request_):
    from scheduler.config import TimeBlock

    from app.crud import apply_edit

    def short_friday(
        draft,
    ):  # make room for the new block, as the other time slot tests do
        draft.time_slot_config.times["FRI"] = [
            TimeBlock(start="08:00", end="09:00", spacing=60)
        ]

    apply_edit(session(request_).config, "timeslot", short_friday)
    call(request_, "add_time_slot", {"day": "Friday", "start": "09:00", "end": "17:00"})

    result = provide(request_, {"spacing": 60})
    assert result.ok and result.changed, result.message
    assert any(
        b.start == "09:00" and b.end == "17:00" and b.spacing == 60
        for b in session(request_).config.time_slot_config.times["FRI"]
    )


def test_everything_the_library_requires_for_patterns_and_meetings_is_already_required_by_the_tools(
    request_,
):
    """Nothing is silently defaulted for these, so they ask for no extra values."""
    pattern = call(
        request_,
        "add_class_pattern",
        {"credits": 3, "meetings": [{"day": "MON", "duration": 50}]},
    )
    assert pattern.ok and not pattern.questions and pattern.changed
    meeting = call(
        request_, "add_meeting", {"pattern_number": 1, "day": "monday", "duration": 50}
    )
    assert meeting.ok and not meeting.questions


def test_rooms_and_labs_ask_only_for_what_the_library_requires(request_):
    for tool in ("add_room", "add_lab"):
        assert [q.field for q in call(request_, tool, {"name": "X1"}).questions] == [
            "capacity"
        ]
        assert [q.field for q in call(request_, tool, {}).questions] == [
            "name",
            "capacity",
        ]
        assert call(request_, tool, {"name": "X1", "capacity": 10}).changed
        waiting_ = waiting(request_)
        assert waiting_ is None
