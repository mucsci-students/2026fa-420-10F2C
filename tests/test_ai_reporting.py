"""
Tests for accurate AI action reporting (issue #116, user story 5).

The chat may only say something was done when the application really did it:

  * AI text alone never counts as an action. If the AI's own words claim a change
    ("Room RODDY150 has been added") but no action tool ran, the reply is replaced.
  * A write tool's report is checked against the configuration itself: a "success"
    that left the configuration exactly as it was is reported as a failure, and a
    change that did happen is always reported.
  * A failed action explains why and leaves the configuration unchanged.

No AI is used: a fake runner plays the model's part, everything after it is real.
"""

import pytest

from gui import session_store
from gui.ai import service
from gui.ai.base import AiTool
from gui.ai.tools import TOOLS, NameArgs, ToolBox
from gui.controllers import rooms


class FakeRequest:
    def __init__(self):
        self.session = {}


class Scripted:
    """Plays the model: calls the given tools, then answers with `text`."""

    def __init__(self, calls=(), text=""):
        self.calls = list(calls)
        self.text = text

    def run(self, text, toolbox):
        for name, args in self.calls:
            toolbox.call(name, args)
        return self.text


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


@pytest.fixture
def request_():
    return FakeRequest()


def config(request):
    return session_store.get_session(request).config


def snapshot(request):
    return config(request).model_dump_json()


def room_names(request):
    return [room.name for room in config(request).config.rooms]


def ask(monkeypatch, request, runner, text="request"):
    monkeypatch.setattr(service, "get_runner", lambda: runner)
    return service.handle_request(request, text)


# ---------------------------------------------------------------------- #
#  AI text alone is not an action
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "claim",
    [
        "Room RODDY150 has been added.",
        "Room RODDY150 was added successfully.",
        "I've deleted course CMSC 999.",
        "I added the room for you.",
        "The capacity of Roddy 140 is now updated to 40.",
        "Done!",
        "Saved the configuration successfully.",
    ],
)
def test_story_5_text_claiming_an_action_is_not_reported_as_done(
    monkeypatch, request_, claim
):
    before = snapshot(request_)
    reply = ask(
        monkeypatch, request_, Scripted(text=claim), "Add a room named RODDY150"
    )
    assert reply.ok is False
    assert reply.message == service.NOT_DONE
    assert claim not in reply.message
    assert "RODDY150" not in room_names(request_)
    assert snapshot(request_) == before
    assert reply.changed is False
    assert not session_store.get_session(request_).dirty


def test_text_claim_after_only_lookups_is_also_replaced(monkeypatch, request_):
    runner = Scripted(calls=[("list_rooms", {})], text="Room RODDY150 has been added.")
    reply = ask(monkeypatch, request_, runner)
    assert reply.ok is False and reply.message == service.NOT_DONE
    assert "RODDY150" not in room_names(request_)


@pytest.mark.parametrize(
    "answer",
    [
        "You have 3 rooms: Roddy 136, Roddy 140 and Roddy 147.",
        "CMSC 420 has 4 credits.",
        "Nothing was added: I need the room's capacity. What should it be?",
        "Should I add a room named RODDY150 with capacity 35?",
        "That room wasn't changed.",
        "I can add, change and delete rooms, labs and courses.",
    ],
)
def test_ordinary_answers_and_questions_are_shown_as_they_are(
    monkeypatch, request_, answer
):
    reply = ask(monkeypatch, request_, Scripted(text=answer))
    assert reply.ok is True
    assert reply.message == answer


def test_claims_action_ignores_questions_and_negative_sentences():
    assert service.claims_action("The room has been added.")
    assert not service.claims_action("Has the room been added?")
    assert not service.claims_action("Nothing was deleted.")
    assert not service.claims_action(
        "I couldn't add that room because it already exists."
    )
    assert service.claims_action("Here you go. Room X was removed.")


# ---------------------------------------------------------------------- #
#  Success only when the application confirms it, and it shows in the config
# ---------------------------------------------------------------------- #
def test_story_5_a_reported_success_matches_the_real_state(monkeypatch, request_):
    runner = Scripted(calls=[("add_room", {"name": "RODDY140", "capacity": 30})])
    reply = ask(monkeypatch, request_, runner)
    assert reply.ok and reply.changed
    assert "Room 'RODDY140' added with capacity 30." in reply.message
    listed = {
        row["name"]: row["capacity"] for row in rooms.describe_rooms(request_)["rooms"]
    }
    assert listed["RODDY140"] == 30  # what the Rooms section shows


def test_story_5_a_failed_action_is_not_reported_as_success(monkeypatch, request_):
    before = snapshot(request_)
    runner = Scripted(
        calls=[("add_room", {"name": "Roddy 136", "capacity": 20})]
    )  # already exists
    reply = ask(monkeypatch, request_, runner)
    assert reply.ok is False and reply.changed is False
    assert "already exists" in reply.message
    assert "The configuration was not changed." in reply.message
    assert "added" not in reply.message.replace("Could not add", "")
    assert snapshot(request_) == before


def test_a_failed_action_explains_why(monkeypatch, request_):
    runner = Scripted(calls=[("add_room", {"name": "RODDY150", "capacity": "lots"})])
    reply = ask(monkeypatch, request_, runner)
    assert reply.ok is False
    assert "capacity" in reply.message
    assert "RODDY150" not in room_names(request_)


def test_an_action_that_never_ran_is_never_reported(monkeypatch, request_):
    before = snapshot(request_)
    reply = ask(
        monkeypatch, request_, Scripted(calls=[("run_shell", {"command": "ls"})])
    )
    assert reply.ok is False
    assert "no 'run_shell' action" in reply.message
    assert snapshot(request_) == before


# ---------------------------------------------------------------------- #
#  A write tool's own report is checked against the configuration
# ---------------------------------------------------------------------- #
def _claims_but_does_nothing(request, args):
    return f"Room '{args.name}' added."  # says it worked, changes nothing


def _changes_but_reports_unchanged(request, args):
    from gui.ai.base import Unchanged

    rooms.add_room(request, {"name": args.name, "capacity": 10})
    return Unchanged("Nothing needed changing.")


def test_a_tool_that_claims_success_without_changing_anything_is_a_failure(request_):
    fake = AiTool(
        "fake_add", "Pretends to add.", NameArgs, _claims_but_does_nothing, write=True
    )
    box = ToolBox(request_, tools=[fake])
    before = snapshot(request_)
    result = box.call("fake_add", {"name": "RODDY150"})
    assert result.ok is False and result.changed is False
    assert "could not confirm the change" in result.message
    assert "added" not in result.message
    assert snapshot(request_) == before
    reply = service.compose(box.results)
    assert reply.ok is False and "applied" not in reply.message


def test_a_change_the_tool_did_not_report_is_still_reported(request_):
    sneaky = AiTool(
        "sneaky",
        "Changes without saying.",
        NameArgs,
        _changes_but_reports_unchanged,
        write=True,
    )
    box = ToolBox(request_, tools=[sneaky])
    result = box.call("sneaky", {"name": "RODDY150"})
    assert "RODDY150" in room_names(request_)
    assert result.changed is True
    assert "History page" in result.message
    assert service.compose(box.results).changed is True


def test_every_real_write_tool_passes_the_check_on_success(request_):
    # The real add_room really changes the configuration, so its report stands.
    box = ToolBox(request_, tools=TOOLS)
    result = box.call("add_room", {"name": "RODDY150", "capacity": 35})
    assert result.ok and result.changed
    assert result.message == "Room 'RODDY150' added with capacity 35."


# ---------------------------------------------------------------------- #
#  Story 5 scenario 1: deleting something that does not exist
# ---------------------------------------------------------------------- #
def test_story_5_deleting_a_missing_course_says_it_does_not_exist(
    monkeypatch, request_
):
    before = snapshot(request_)
    runner = Scripted(calls=[("delete_course", {"course_id": "CMSC 999"})])
    reply = ask(monkeypatch, request_, runner, "Delete course CMSC 999")
    assert reply.ok is False and reply.changed is False
    assert "CMSC 999" in reply.message
    assert "deleted" not in reply.message.lower()
    assert snapshot(request_) == before


def test_confirming_when_nothing_is_waiting_is_not_reported_as_done(
    monkeypatch, request_
):
    before = snapshot(request_)
    reply = ask(monkeypatch, request_, Scripted(calls=[("confirm_delete", {})]), "yes")
    assert reply.ok is False and reply.changed is False
    assert "nothing waiting to be deleted" in reply.message
    assert snapshot(request_) == before
