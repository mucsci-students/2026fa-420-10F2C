"""
Saved chats, "New chat" and live page updates for the AI assistant (Sprint 3).

  * the conversation is kept on the server for each browser (gui/ai/chats.py), so the chat panel can
    draw it again after a page change or reload
  * "New chat" starts a fresh conversation (and a fresh memory for the AI); the older ones stay in a list
    and can be opened again or deleted; anything waiting for a "yes" is forgotten when the chat changes
  * a request that is still running is visible to the panel, and the chats cannot be changed meanwhile
  * the scripts keep the page in step with what the assistant changed, without a reload (the swap itself
    is exercised in a real browser; here the pieces it depends on are checked)

The tools run for real (the AI is replaced by a small scripted stand-in), so no key and no network.
"""

import re
from pathlib import Path

import pytest

from gui import session_store
from gui.ai import changes, chats, generation, service
from gui.ai.tools import ToolBox

ROOT = Path(__file__).resolve().parent.parent
ASK_URL = "/assistant/ask/"
CHAT_URL = "/assistant/chat/"
NEW_URL = "/assistant/chat/new/"
SWITCH_URL = "/assistant/chat/switch/"
DELETE_URL = "/assistant/chat/delete/"


class FakeRequest:
    def __init__(self, session=None):
        self.session = {} if session is None else dict(session)


class ScriptedRunner:
    """Stands in for the AI: runs the scripted tool calls for each message, or answers with text."""

    def __init__(self, script=None, during=None):
        self.script = script or {}
        self.during = during
        self.seen = []  # what the AI was given as earlier messages, for each request

    def run(self, text, toolbox):
        self.seen.append(list(toolbox.history))
        if self.during:
            self.during(toolbox)
        for name, args in self.script.get(text, []):
            toolbox.call(name, args)
        return "" if text in self.script else f"You said: {text}"


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    service._BUSY.clear()
    yield
    session_store._SESSIONS.clear()
    service._BUSY.clear()


@pytest.fixture
def runner(monkeypatch):
    stand_in = ScriptedRunner(
        {
            "add a room": [("add_room", {"name": "RODDY150", "capacity": 35})],
            "generate": [("prepare_schedule_generation", {"limit": 2})],
            "delete a room": [("delete_room", {"name": "Roddy 136"})],
        }
    )
    monkeypatch.setattr(service, "get_runner", lambda: stand_in)
    return stand_in


@pytest.fixture
def request_():
    request = FakeRequest()
    session_store.get_session(request)
    return request


def session(request):
    return session_store.get_session(request)


def ask(request, text):
    return service.handle_request(request, text)


def lines(request):
    return [(message["kind"], message["text"]) for message in chats.state(session(request))["messages"]]


# ---------------------------------------------------------------------- #
#  The store
# ---------------------------------------------------------------------- #
def test_a_browser_starts_with_one_empty_chat(request_):
    state = chats.state(session(request_))
    assert len(state["chats"]) == 1 and state["messages"] == [] and state["busy"] is False
    first = state["chats"][0]
    assert {key: first[key] for key in ("id", "title", "count", "active")} == {
        "id": state["active"],
        "title": "New chat",
        "count": 0,
        "active": True,
    }
    assert isinstance(first["updated"], int) and first["updated"] > 0  # when it was last used: the sidebar groups by day


def test_lines_are_kept_in_order_and_the_first_message_gives_the_title(request_):
    chats.record(session(request_), "user", "Add a room called Roddy 150 with room for 40 students please")
    chats.record(session(request_), "assistant", "Done.", suggestions=["Cancel"], generated=True)
    state = chats.state(session(request_))
    assert state["chats"][0]["title"] == "Add a room called Roddy 150 with room f…"
    assert len(state["chats"][0]["title"]) <= chats.TITLE_LENGTH
    assert [m["kind"] for m in state["messages"]] == ["user", "assistant"]
    assert state["messages"][1]["suggestions"] == ["Cancel"] and state["messages"][1]["generated"] is True
    chats.record(session(request_), "user", "A later message")
    assert chats.state(session(request_))["chats"][0]["title"].startswith("Add a room")  # the title stays


def test_new_chat_keeps_the_old_one_and_starts_empty(request_):
    chats.record(session(request_), "user", "first chat message")
    first = chats.state(session(request_))["active"]
    fresh = chats.new_chat(session(request_))
    state = chats.state(session(request_))
    assert state["active"] == fresh["id"] != first and state["messages"] == []
    assert [chat["id"] for chat in state["chats"]] == [fresh["id"], first]  # newest first
    assert [chat["count"] for chat in state["chats"]] == [0, 1]


def test_new_chat_on_an_empty_chat_does_not_pile_up_blank_chats(request_):
    chats.new_chat(session(request_))
    chats.new_chat(session(request_))
    assert len(chats.state(session(request_))["chats"]) == 1


def test_switching_opens_an_older_chat_and_an_unknown_one_changes_nothing(request_):
    chats.record(session(request_), "user", "in the first chat")
    first = chats.state(session(request_))["active"]
    chats.new_chat(session(request_))
    chats.record(session(request_), "user", "in the second chat")
    assert chats.switch_chat(session(request_), first) is True
    assert lines(request_) == [("user", "in the first chat")]
    assert chats.switch_chat(session(request_), "nope") is False
    assert chats.state(session(request_))["active"] == first


def test_each_chat_has_its_own_memory_for_the_ai(request_):
    chats.record(session(request_), "user", "one")  # opens the first chat
    session(request_).ai_history = [{"role": "user", "content": "one"}]
    first = chats.state(session(request_))["active"]
    chats.new_chat(session(request_))
    assert session(request_).ai_history == []  # a new chat starts with no memory
    session(request_).ai_history = [{"role": "user", "content": "two"}]
    chats.record(session(request_), "user", "two")
    chats.switch_chat(session(request_), first)
    assert session(request_).ai_history == [{"role": "user", "content": "one"}]


def test_a_new_chat_or_switch_forgets_anything_that_was_waiting_for_a_yes(request_):
    ToolBox(request_).call("prepare_schedule_generation")  # (preparing drops a waiting delete, so this goes first)
    ToolBox(FakeRequest(request_.session)).call("delete_room", {"name": "Roddy 136"})
    assert getattr(session(request_), generation._PLAN_ATTR) is not None
    assert getattr(session(request_), changes._PENDING_ATTR) is not None
    chats.record(session(request_), "user", "x")
    chats.new_chat(session(request_))
    assert getattr(session(request_), changes._PENDING_ATTR) is None
    assert getattr(session(request_), generation._PLAN_ATTR) is None
    result = ToolBox(FakeRequest(request_.session)).call("confirm_delete")
    assert not result.ok and any(room.name == "Roddy 136" for room in session(request_).config.config.rooms)


def test_deleting_the_open_chat_opens_the_newest_other_one_or_a_blank_one(request_):
    chats.record(session(request_), "user", "oldest")
    oldest = chats.state(session(request_))["active"]
    chats.new_chat(session(request_))
    chats.record(session(request_), "user", "newest")
    newest = chats.state(session(request_))["active"]
    assert chats.delete_chat(session(request_), newest) is True
    assert chats.state(session(request_))["active"] == oldest
    assert chats.delete_chat(session(request_), oldest) is True
    state = chats.state(session(request_))
    assert len(state["chats"]) == 1 and state["messages"] == [] and session(request_).ai_history == []
    assert chats.delete_chat(session(request_), "nope") is False


def test_deleting_another_chat_leaves_the_open_one_alone(request_):
    chats.record(session(request_), "user", "older")
    older = chats.state(session(request_))["active"]
    chats.new_chat(session(request_))
    chats.record(session(request_), "user", "open one")
    assert chats.delete_chat(session(request_), older) is True
    assert lines(request_) == [("user", "open one")]


def test_the_number_of_chats_and_of_lines_is_bounded(request_):
    for number in range(chats.MAX_CHATS + 5):
        chats.record(session(request_), "user", f"chat {number}")
        chats.new_chat(session(request_))
    state = chats.state(session(request_))
    assert len(state["chats"]) <= chats.MAX_CHATS
    assert all(chat["title"] != "chat 0" for chat in state["chats"])  # the oldest went first
    for number in range(chats.MAX_MESSAGES + 10):
        chats.record(session(request_), "user", f"line {number}")
    messages = chats.state(session(request_))["messages"]
    assert len(messages) == chats.MAX_MESSAGES and messages[-1]["text"] == f"line {chats.MAX_MESSAGES + 9}"
    chats.record(session(request_), "assistant", "x" * (chats.TEXT_LIMIT + 50))
    assert len(chats.state(session(request_))["messages"][-1]["text"]) == chats.TEXT_LIMIT


def test_chats_belong_to_one_browser(request_):
    chats.record(session(request_), "user", "mine")
    other = FakeRequest()
    assert chats.state(session_store.get_session(other))["messages"] == []


# ---------------------------------------------------------------------- #
#  The service keeps the conversation
# ---------------------------------------------------------------------- #
def test_a_request_and_its_reply_are_kept(request_, runner):
    reply = ask(request_, "add a room")
    assert reply.ok and lines(request_) == [("user", "add a room"), ("assistant", reply.message)]
    assert "RODDY150" in reply.message


def test_a_failed_request_is_kept_as_a_problem(request_, monkeypatch):
    failing = ScriptedRunner({"bad": [("add_room", {"name": "RODDY150", "capacity": "lots"})]})
    monkeypatch.setattr(service, "get_runner", lambda: failing)
    reply = ask(request_, "bad")
    assert not reply.ok and lines(request_) == [("user", "bad"), ("error", reply.message)]


def test_empty_too_long_and_refused_requests_are_not_kept(request_, runner):
    ask(request_, "   ")
    ask(request_, "x" * (service.MAX_REQUEST_LENGTH + 1))
    service._BUSY.add(id(session(request_)))
    refused = ask(request_, "add a room")
    service._BUSY.discard(id(session(request_)))
    assert refused.busy and lines(request_) == []


def test_the_question_is_kept_before_the_answer_and_the_request_shows_as_running(request_, monkeypatch):
    seen = {}

    def during(toolbox):
        seen["lines"] = lines(request_)
        seen["busy"] = service.is_busy(request_)

    monkeypatch.setattr(service, "get_runner", lambda: ScriptedRunner(during=during))
    ask(request_, "How many rooms are there?")
    assert seen == {"lines": [("user", "How many rooms are there?")], "busy": True}
    assert service.is_busy(request_) is False and len(lines(request_)) == 2


def test_a_generated_reply_is_marked_so_the_viewer_link_comes_back(request_, runner, monkeypatch):
    from app import schedule_ops
    from app.schedule_io import Assignment, MeetingTime

    class FakeScheduler:
        def __init__(self, config):
            pass

        def get_models(self):
            yield [Assignment("CMSC 140.01", "Hogg", "Roddy 136", None, (MeetingTime("MON", "09:00", "09:50", 50),))]

    monkeypatch.setattr(schedule_ops, "Scheduler", FakeScheduler)
    runner.script["go"] = [("confirm_schedule_generation", {})]
    ask(request_, "generate")
    assert chats.state(session(request_))["messages"][-1]["suggestions"] == ["Go ahead and generate", "Cancel"]
    ask(FakeRequest(request_.session), "go")
    last = chats.state(session(request_))["messages"][-1]
    assert last["generated"] is True and last["text"].startswith("Generated 1 schedule.") and last["suggestions"] == []


def test_a_new_chat_gets_none_of_the_old_chats_messages_as_memory(request_, runner):
    ask(request_, "add a room")
    chats.new_chat(session(request_))
    ask(FakeRequest(request_.session), "What can you do?")
    assert runner.seen[0] == [] and runner.seen[1] == []  # the AI saw no earlier messages in the new chat
    first = chats.state(session(request_))["chats"][1]["id"]
    chats.switch_chat(session(request_), first)
    ask(FakeRequest(request_.session), "and one more")
    assert any("add a room" in str(message) for message in runner.seen[2])  # the old chat has its own back


# ---------------------------------------------------------------------- #
#  The endpoints the panel uses
# ---------------------------------------------------------------------- #
def browser_session():
    return next(iter(session_store._SESSIONS.values()))


def post(client, url, **data):
    response = client.post(url, data)
    return response.status_code, response.json()


def test_the_panel_can_load_the_saved_chat_on_any_page(client, runner):
    client.get("/")
    client.post(ASK_URL, {"message": "add a room"})
    for path in ("/", "/rooms/", "/schedules/"):
        client.get(path)  # a page change
        body = client.get(CHAT_URL).json()
        assert [m["kind"] for m in body["messages"]] == ["user", "assistant"] and body["busy"] is False
        assert body["chats"][0]["active"] is True and body["chats"][0]["title"] == "add a room"
        assert set(body["messages"][0]) == {"kind", "text", "suggestions", "generated"}


def test_new_switch_and_delete_through_the_endpoints(client, runner):
    client.get("/")
    client.post(ASK_URL, {"message": "add a room"})
    first = client.get(CHAT_URL).json()["active"]

    status, body = post(client, NEW_URL)
    assert status == 200 and body["messages"] == [] and body["active"] != first and len(body["chats"]) == 2
    second = body["active"]

    client.post(ASK_URL, {"message": "What can you do?"})
    status, body = post(client, SWITCH_URL, id=first)
    assert status == 200 and body["active"] == first and body["messages"][0]["text"] == "add a room"

    status, body = post(client, DELETE_URL, id=first)
    assert status == 200 and body["active"] == second and [c["id"] for c in body["chats"]] == [second]


def test_an_unknown_chat_is_a_404_with_the_current_state(client):
    client.get("/")
    for url in (SWITCH_URL, DELETE_URL):
        status, body = post(client, url, id="nope")
        assert status == 404 and "no longer exists" in body["error"] and body["chats"]


def test_the_chats_cannot_change_while_a_request_is_running(client, runner):
    client.get("/")
    client.post(ASK_URL, {"message": "add a room"})
    first = client.get(CHAT_URL).json()["active"]
    service._BUSY.add(id(browser_session()))
    assert client.get(CHAT_URL).json()["busy"] is True
    for url, data in ((NEW_URL, {}), (SWITCH_URL, {"id": first}), (DELETE_URL, {"id": first})):
        status, body = post(client, url, **data)
        assert status == 409 and "still running" in body["error"] and body["active"] == first
    service._BUSY.discard(id(browser_session()))
    assert post(client, NEW_URL)[0] == 200


def test_only_the_right_methods_are_allowed(client):
    client.get("/")
    assert client.post(CHAT_URL).status_code == 405
    for url in (NEW_URL, SWITCH_URL, DELETE_URL):
        assert client.get(url).status_code == 405


def test_a_browser_that_never_chatted_gets_one_empty_chat(client):
    body = client.get(CHAT_URL).json()
    assert body["messages"] == [] and len(body["chats"]) == 1 and body["busy"] is False


# ---------------------------------------------------------------------- #
#  The markup and scripts
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize("path", ["/", "/configuration/", "/generate/", "/schedules/"])
def test_every_page_has_the_history_sidebar_and_where_the_chats_live(client, path):
    text = client.get(path).content.decode()
    for needed in (
        f'data-chat-url="{CHAT_URL}"',
        f'data-chat-new-url="{NEW_URL}"',
        f'data-chat-switch-url="{SWITCH_URL}"',
        f'data-chat-delete-url="{DELETE_URL}"',
        "data-chat-sidebar",
        "data-chat-history",
        "data-chat-sidebar-toggle",
        "data-chat-new",
        "data-chat-scrim",
    ):
        assert needed in text, needed
    assert "data-chat-sidebar hidden" in text  # shown by the script, so no-JavaScript pages stay clean
    assert "data-chat-toolbar" not in text and "<select" not in text.split('id="chat-panel"')[1].split("chat-dock")[0]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_the_chat_script_restores_chats_and_updates_the_page_in_place():
    script = read("gui/static/gui/js/chat.js")
    for needed in (
        "loadChats()",
        "renderChat(",
        "resumeRunning()",
        "data-chat-new",
        "chatAction(newUrl",
        "chatAction(switchUrl",
        "chatAction(deleteUrl",
        "setSidebar(",
        "drawHistory()",
        "function updatePage()",
        "scheduler:content-updated",
        "fieldsChanged(",
        "sessionStorage",
    ):
        assert needed in script, needed
    assert "innerHTML" not in script  # replies and swapped content are inserted as nodes, never as HTML strings
    assert "window.confirm" not in script  # no pop-up: the history row asks in place


def test_the_page_scripts_wire_the_new_content_after_an_in_place_update():
    for name in ("app.js", "schedule_viewer.js", "generation_progress.js"):
        assert 'addEventListener("scheduler:content-updated"' in read(f"gui/static/gui/js/{name}"), name
    assert "innerHTML" not in read("gui/static/gui/js/schedule_viewer.js")


def test_the_sidebar_has_light_and_dark_styles():
    css = read("gui/static/gui/css/style.css")
    for needed in (".chat-sidebar", ".chat-history__row", ".chat-icon-button", "@media (max-width: 40rem)"):
        assert needed in css, needed
    for needed in ('html[data-theme="dark"] .chat-sidebar', 'html[data-theme="dark"] .chat-history__row'):
        assert needed in css, needed
    assert ".chat-toolbar" not in css and ".chat-picker" not in css


def test_the_stylesheet_and_chat_script_are_versioned_so_a_browser_never_mixes_old_and_new(client):
    text = client.get("/").content.decode()
    assert re.search(r'href="/static/gui/css/style\.css\?v=\d+"', text)
    assert re.search(r'src="/static/gui/js/chat\.js\?v=\d+"', text)
