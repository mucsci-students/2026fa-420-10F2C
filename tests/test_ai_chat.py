"""
Tests for the AI chat button's endpoint and one request from start to finish
(Sprint 3 user stories 2, 3 and 6). The button and panel themselves are covered in test_gui_chat.py.

The real AI is replaced by FakeRunner, which calls the tools a model would
have picked for each request (or just answers with text). Everything after
that is real: the endpoint, gui.ai.service, the tools, the controllers and the
scheduler library. No OpenAI connection or API key is used.
"""

import logging
import threading

import pytest

from gui import session_store
from gui.ai import runner as runner_module
from gui.ai import service

ASK_URL = "/assistant/ask/"
PAGE_URL = "/"

ADD_140 = "Add a room named RODDY140 with capacity 30"
ADD_141 = "Add a room named RODDY141 with capacity 25"
WHAT_140 = "What is the capacity of RODDY140?"

SCRIPT = {
    ADD_140: [("add_room", {"name": "RODDY140", "capacity": 30})],
    ADD_141: [("add_room", {"name": "RODDY141", "capacity": 25})],
    WHAT_140: [("get_room", {"name": "RODDY140"})],
    "List all rooms": [("list_rooms", {})],
    "What can you do?": [("describe_capabilities", {})],
    "Add two rooms": [
        ("add_room", {"name": "RODDY150", "capacity": 35}),
        ("add_room", {"name": "RODDY151", "capacity": 40}),
    ],
    "Hello": "Hi! Ask me about rooms, labs, courses and more.",
    "Add a room named RODDY150": "Room RODDY150 has been added.",  # text only, no tool
}


class FakeRequest:
    """Enough of a request for gui.ai.service: just a session dict."""

    def __init__(self):
        self.session = {}


class FakeRunner:
    """Stands in for the AI: calls the scripted tools for each request."""

    def __init__(self, script=SCRIPT, during=None):
        self.script = script
        self.during = during  # optional hook run while the "AI" is working
        self.requests = []

    def run(self, text, toolbox):
        self.requests.append(text)
        if self.during:
            self.during(toolbox)
        step = self.script[text]
        if isinstance(step, str):
            return step
        for name, args in step:
            toolbox.call(name, args)
        return ""


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


@pytest.fixture
def fake(monkeypatch):
    runner = FakeRunner()
    monkeypatch.setattr(service, "get_runner", lambda: runner)
    return runner


def ask(client, text):
    response = client.post(ASK_URL, {"message": text})
    return response.status_code, response.json()


def browser_session():
    return next(iter(session_store._SESSIONS.values()))


def rooms_named(name):
    return [room for room in browser_session().config.config.rooms if room.name == name]


def capacity(name):
    (room,) = rooms_named(name)
    return room.capacity


# ---------------------------------------------------------------------- #
#  The endpoint
# ---------------------------------------------------------------------- #
def test_the_endpoint_only_accepts_post(client):
    assert client.get(ASK_URL).status_code == 405


def test_a_post_from_another_site_is_refused():
    from django.test import Client

    strict = Client(enforce_csrf_checks=True)
    assert strict.post(ASK_URL, {"message": "List all rooms"}).status_code == 403


def test_the_separate_assistant_page_is_gone(client):
    assert client.get("/assistant/").status_code == 404
    assert (
        "AI Assistant</a>" not in client.get("/").content.decode()
    )  # no tab; the button replaces it


def test_the_page_never_contains_the_api_key(client, monkeypatch, fake):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    assert "sk-test" not in client.get(PAGE_URL).content.decode()
    _, body = ask(client, "List all rooms")
    assert "sk-test" not in str(body)


# ---------------------------------------------------------------------- #
#  Story 2: a result always replaces the processing status
# ---------------------------------------------------------------------- #
def test_story_2_success_comes_back_as_a_result_message(client, fake):
    status, body = ask(client, ADD_140)
    assert status == 200
    assert body["ok"] is True and body["changed"] is True
    assert "Room 'RODDY140' added with capacity 30." in body["reply"]
    assert "applied but not yet saved" in body["reply"]
    assert body["dirty"] is True


def test_story_2_failure_also_comes_back_as_a_result_message(client, fake):
    ask(client, ADD_140)
    status, body = ask(client, ADD_140)  # duplicate name this time
    assert status == 200
    assert body["ok"] is False and body["changed"] is False
    assert "already exists" in body["reply"] and "not changed" in body["reply"]


def test_story_2_the_next_request_is_accepted_after_a_failure(client, fake):
    ask(client, ADD_140)
    ask(client, ADD_140)
    status, body = ask(client, ADD_141)
    assert status == 200 and body["ok"] is True
    assert fake.requests == [ADD_140, ADD_140, ADD_141]


def test_story_2_the_next_request_is_accepted_after_the_ai_service_fails(
    client, monkeypatch
):
    class Broken:
        def run(self, text, toolbox):
            raise ConnectionError("network down")

    monkeypatch.setattr(service, "get_runner", lambda: Broken())
    _, body = ask(client, ADD_140)
    assert body["ok"] is False
    assert "couldn't finish" in body["reply"] and "not changed" in body["reply"]
    assert rooms_named("RODDY140") == []

    monkeypatch.setattr(service, "get_runner", lambda: FakeRunner())
    _, body = ask(client, ADD_140)
    assert body["ok"] is True


def test_empty_request_is_not_sent_to_the_ai(client, fake):
    status, body = ask(client, "   ")
    assert status == 200 and body["ok"] is False
    assert body["reply"] == "Type a request first."
    assert fake.requests == []


def test_the_script_shows_working_status_and_guards_resubmits():
    """The browser half of stories 2 and 3 lives in chat.js; check the
    pieces the tests in this file cannot run are really there."""
    from pathlib import Path

    script = (
        Path(__file__).resolve().parent.parent / "gui/static/gui/js/chat.js"
    ).read_text()
    assert "Working on it" in script
    assert "if (pending) {" in script
    assert "sendButton.classList.toggle" in script
    assert "thinking.remove()" in script


# ---------------------------------------------------------------------- #
#  Story 3: a second submit while one is running is refused
# ---------------------------------------------------------------------- #
def test_story_3_double_submit_reaches_the_ai_once(client, monkeypatch):
    second = {}

    def submit_again(toolbox):
        # The user presses Enter again while the first request is still running.
        second["reply"] = service.handle_request(toolbox.request, ADD_140)

    runner = FakeRunner(during=submit_again)
    monkeypatch.setattr(service, "get_runner", lambda: runner)
    _, body = ask(client, ADD_140)

    assert body["ok"] is True
    assert second["reply"].busy and not second["reply"].ok
    assert second["reply"].message == service.BUSY_MESSAGE
    assert runner.requests == [ADD_140]  # only one request was sent to the AI
    assert len(rooms_named("RODDY140")) == 1


def test_story_3_busy_reply_from_the_endpoint(client, monkeypatch, fake):
    client.get(PAGE_URL)
    key = id(browser_session())
    service._BUSY.add(key)
    try:
        status, body = ask(client, ADD_140)
    finally:
        service._BUSY.discard(key)
    assert status == 409 and body["busy"] is True
    assert fake.requests == []
    assert rooms_named("RODDY140") == []


def test_story_3_two_threads_at_once_only_one_runs(monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls = []

    class Slow:
        def run(self, text, toolbox):
            calls.append(text)
            started.set()
            release.wait(5)
            toolbox.call("add_room", {"name": "RODDY140", "capacity": 30})
            return ""

    monkeypatch.setattr(service, "get_runner", lambda: Slow())
    request = FakeRequest()
    first = {}
    worker = threading.Thread(
        target=lambda: first.setdefault(
            "reply", service.handle_request(request, ADD_140)
        )
    )
    worker.start()
    assert started.wait(5)
    again = service.handle_request(
        request, ADD_140
    )  # same browser, while the first is running
    release.set()
    worker.join(5)

    assert again.busy
    assert first["reply"].ok
    assert calls == [ADD_140]
    names = [
        room.name
        for room in session_store.get_session(request).require_config().config.rooms
    ]
    assert names.count("RODDY140") == 1


def test_one_browser_being_busy_does_not_block_another(client, fake):
    other = FakeRequest()
    key = id(session_store.get_session(other))
    service._BUSY.add(key)
    try:
        status, body = ask(client, ADD_140)
    finally:
        service._BUSY.discard(key)
    assert status == 200 and body["busy"] is False and body["ok"] is True


# ---------------------------------------------------------------------- #
#  Story 6: every request uses the current state, on its own
# ---------------------------------------------------------------------- #
def test_story_6_the_ai_sees_a_manual_edit(client, fake):
    ask(client, ADD_140)
    response = client.post(
        "/configuration/rooms/RODDY140/edit/",
        {"name": "RODDY140", "capacity": "40", "features": "", "times": ""},
        follow=True,
    )
    assert response.status_code == 200 and capacity("RODDY140") == 40

    _, body = ask(client, WHAT_140)
    assert "capacity 40" in body["reply"]


def test_story_6_requests_are_independent(client, fake):
    ask(client, ADD_140)
    _, body = ask(client, ADD_141)
    assert body["ok"] is True
    assert capacity("RODDY141") == 25
    assert capacity("RODDY140") == 30
    assert fake.requests[-1] == ADD_141  # only the new request text is sent


# ---------------------------------------------------------------------- #
#  Replies are built from what really happened
# ---------------------------------------------------------------------- #
def test_text_only_reply_is_shown_but_changes_nothing(client, fake):
    _, body = ask(client, "Add a room named RODDY150")
    assert body["changed"] is False
    assert rooms_named("RODDY150") == []
    assert body["dirty"] is False


def test_plain_answer_without_tools(client, fake):
    _, body = ask(client, "Hello")
    assert body["ok"] is True and body["reply"].startswith("Hi!")


def test_two_changes_in_one_request_are_both_reported(client, fake):
    _, body = ask(client, "Add two rooms")
    assert "RODDY150" in body["reply"] and "RODDY151" in body["reply"]
    assert "The changes are applied but not yet saved to a file." in body["reply"]


def test_what_can_you_do(client, fake):
    client.get(PAGE_URL)
    before = browser_session().config.model_dump_json()
    _, body = ask(client, "What can you do?")
    assert body["ok"] is True and body["changed"] is False
    assert "Delete rooms, labs, courses" in body["reply"]
    assert "Save JSON button" in body["reply"]
    assert "never say it was saved" in body["reply"]
    assert browser_session().config.model_dump_json() == before


def test_list_all_rooms_with_no_configuration(client, fake, monkeypatch):
    monkeypatch.setattr(session_store, "AUTO_LOAD_EXAMPLE", False)
    _, body = ask(client, "List all rooms")
    assert body["ok"] is False
    assert "There is no configuration yet. Load or create one first" in body["reply"]


# ---------------------------------------------------------------------- #
#  Setup problems
# ---------------------------------------------------------------------- #
def test_missing_api_key_explains_how_to_set_it(client, monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        runner_module, "API_KEY_FILE", tmp_path / "missing-openai-api-key.txt"
    )
    _, body = ask(client, "List all rooms")
    assert body["ok"] is False
    assert "OPENAI_API_KEY" in body["reply"] and "Nothing was changed" in body["reply"]
    assert (
        client.get("/configuration/rooms/").status_code == 200
    )  # the rest of the app still works


def test_model_setting_defaults_to_gpt_6_luna(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert runner_module.model_name() == "gpt-6-luna"
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test-mini")
    assert runner_module.model_name() == "gpt-test-mini"


def test_service_failure_is_logged_without_details(client, monkeypatch, caplog):
    class Broken:
        def run(self, text, toolbox):
            raise RuntimeError("Incorrect API key provided: sk-secret-123")

    monkeypatch.setattr(service, "get_runner", lambda: Broken())
    with caplog.at_level(logging.WARNING, logger="gui.ai"):
        _, body = ask(client, "List all rooms")
    assert "sk-secret" not in body["reply"]
    assert "sk-secret" not in caplog.text
    assert "RuntimeError" in caplog.text
