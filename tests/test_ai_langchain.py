"""
The real LangChain runner against a mocked OpenAI endpoint (no key, no cost).

Like the course's LangChain example tests, an httpx.MockTransport answers in
the shape of OpenAI's Responses API, so these check the real wiring: the
model name and base prompt that are sent, the tool list, a tool call being
carried out, that each request is sent on its own (story 6), and that
service failures stop after a fixed number of attempts.
"""

import json

import pytest

pytest.importorskip("langchain_openai")
httpx = pytest.importorskip("httpx")

from gui import session_store  # noqa: E402
from gui.ai import service  # noqa: E402
from gui.ai.runner import MAX_RETRIES, LangChainRunner  # noqa: E402
from gui.ai.tools import TOOLS  # noqa: E402


class FakeRequest:
    def __init__(self):
        self.session = {}


@pytest.fixture(autouse=True)
def fresh_session_store(monkeypatch):
    session_store._SESSIONS.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    yield
    session_store._SESSIONS.clear()


def tool_calls(*calls):
    return [
        {
            "type": "function_call",
            "id": f"fc_{index}",
            "call_id": f"call_{index}",
            "name": name,
            "arguments": json.dumps(args),
            "status": "completed",
        }
        for index, (name, args) in enumerate(calls)
    ]


def text_output(text):
    return [
        {
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        }
    ]


def response(number, output, model="gpt-6-luna"):
    return httpx.Response(
        200,
        json={
            "id": f"resp_{number}",
            "object": "response",
            "created_at": 0,
            "status": "completed",
            "model": model,
            "output": output,
            "parallel_tool_calls": True,
        },
    )


def use(monkeypatch, respond, model="gpt-6-luna"):
    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(service, "get_runner", lambda: LangChainRunner(model=model, http_client=client))
    return client


def test_a_tool_call_is_carried_out_and_its_result_is_the_reply(monkeypatch):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return response(len(requests), tool_calls(("add_room", {"name": "RODDY150", "capacity": 35})))

    use(monkeypatch, respond)
    request = FakeRequest()
    reply = service.handle_request(request, "Add a room named RODDY150 with capacity 35")

    assert reply.ok and reply.changed
    assert "Room 'RODDY150' added with capacity 35." in reply.message
    rooms = {room.name: room.capacity for room in session_store.get_session(request).config.config.rooms}
    assert rooms["RODDY150"] == 35
    assert len(requests) == 1  # tool results are the answer: no second model call

    payload = requests[0]
    assert payload["model"] == "gpt-6-luna"
    assert len(payload["tools"]) == len(TOOLS)
    assert {tool["name"] for tool in payload["tools"]} == {tool.name for tool in TOOLS}
    assert "course-scheduling application" in json.dumps(payload)  # the base prompt
    assert "test-key" not in json.dumps(payload)


def test_story_6_each_request_is_sent_on_its_own(monkeypatch):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        name = "RODDY140" if len(requests) == 1 else "RODDY141"
        return response(len(requests), tool_calls(("add_room", {"name": name, "capacity": 30})))

    use(monkeypatch, respond)
    request = FakeRequest()
    service.handle_request(request, "Add a room named RODDY140 with capacity 30")
    service.handle_request(request, "Add a room named RODDY141 with capacity 25")

    # Only the system prompt and the newest request are sent; nothing from the first request.
    sent = [item for item in requests[1]["input"] if item.get("role") != "system"]
    assert len(sent) == 1
    assert "RODDY141" in json.dumps(sent)
    assert "RODDY140" not in json.dumps(sent)


def test_a_text_only_answer_changes_nothing(monkeypatch):
    def respond(request):
        return response(1, text_output("Room RODDY150 was added."))

    use(monkeypatch, respond)
    request = FakeRequest()
    reply = service.handle_request(request, "Add a room named RODDY150")
    assert not reply.changed
    names = [room.name for room in session_store.get_session(request).config.config.rooms]
    assert "RODDY150" not in names


def test_malformed_tool_arguments_are_reported_not_applied(monkeypatch):
    def respond(request):
        return response(1, tool_calls(("add_room", {"name": "RODDY150", "capacity": "lots"})))

    use(monkeypatch, respond)
    request = FakeRequest()
    reply = service.handle_request(request, "Add RODDY150 with capacity lots")
    assert not reply.ok and not reply.changed
    assert "capacity" in reply.message
    names = [room.name for room in session_store.get_session(request).config.config.rooms]
    assert "RODDY150" not in names


def test_the_model_setting_is_what_gets_sent(monkeypatch):
    seen = []

    def respond(request):
        seen.append(json.loads(request.content)["model"])
        return response(1, tool_calls(("list_rooms", {})), model="gpt-test-mini")

    use(monkeypatch, respond, model="gpt-test-mini")
    service.handle_request(FakeRequest(), "List all rooms")
    assert seen == ["gpt-test-mini"]


def test_service_errors_stop_after_a_fixed_number_of_attempts(monkeypatch):
    attempts = []

    def respond(request):
        attempts.append(1)
        return httpx.Response(500, json={"error": {"message": "server error", "type": "server_error"}})

    use(monkeypatch, respond)
    request = FakeRequest()
    before = session_store.get_session(request).config.model_dump_json()
    reply = service.handle_request(request, "List all rooms")

    assert not reply.ok
    assert "couldn't finish" in reply.message and "not changed" in reply.message
    assert len(attempts) == 1 + MAX_RETRIES
    assert session_store.get_session(request).config.model_dump_json() == before
