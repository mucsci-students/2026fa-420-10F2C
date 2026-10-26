"""
The real LangChain runner against a mocked OpenAI endpoint (no key, no cost).

Like the course's LangChain example tests, an httpx.MockTransport answers in
the shape of OpenAI's Responses API, so these check the real wiring: the
model name and base prompt that are sent, the tool list, a tool call being
carried out, that earlier chat messages are sent only as help (story 6), that
lookups let the model look before it acts (and stop after MAX_STEPS), and that
service failures stop after a fixed number of attempts.
"""

import json

import pytest

pytest.importorskip("langchain_openai")
httpx = pytest.importorskip("httpx")

from gui import session_store  # noqa: E402
from gui.ai import service  # noqa: E402
from gui.ai.runner import MAX_RETRIES, MAX_STEPS, LangChainRunner  # noqa: E402
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


def sent_messages(payload):
    """The chat messages in a request body, without the system prompt."""
    return [item for item in payload["input"] if item.get("role") in ("user", "assistant")]


def test_story_6_earlier_messages_are_sent_only_to_help_understand_the_newest(monkeypatch):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        name = "RODDY140" if len(requests) == 1 else "RODDY141"
        return response(len(requests), tool_calls(("add_room", {"name": name, "capacity": 30})))

    use(monkeypatch, respond)
    request = FakeRequest()
    service.handle_request(request, "Add a room named RODDY140 with capacity 30")
    service.handle_request(request, "Make it 25 instead")

    sent = sent_messages(requests[1])
    assert [item["role"] for item in sent] == ["user", "assistant", "user"]
    assert "RODDY140" in json.dumps(sent[0]) and "RODDY140" in json.dumps(sent[1])
    assert "Make it 25 instead" in json.dumps(sent[2])  # the newest message is last
    assert len(sent_messages(requests[0])) == 1


def test_history_can_be_turned_off(monkeypatch):
    monkeypatch.setenv(service.HISTORY_ENV, "0")
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return response(len(requests), tool_calls(("describe_capabilities", {})))

    use(monkeypatch, respond)
    request = FakeRequest()
    service.handle_request(request, "What can you do?")
    service.handle_request(request, "And now?")
    sent = sent_messages(requests[1])
    assert len(sent) == 1 and "And now?" in json.dumps(sent)


def test_history_is_limited_to_the_last_few_messages(monkeypatch):
    monkeypatch.setenv(service.HISTORY_ENV, "4")
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return response(len(requests), tool_calls(("describe_capabilities", {})))

    use(monkeypatch, respond)
    request = FakeRequest()
    for number in range(1, 6):
        service.handle_request(request, f"question number {number}")
    sent = sent_messages(requests[-1])
    assert len(sent) == 5  # 4 earlier messages (2 questions and 2 replies) + the newest
    assert "question number 3" in json.dumps(sent[0]) and "question number 1" not in json.dumps(sent)


def test_the_model_can_look_first_and_then_act(monkeypatch):
    """"Delete the room with the smallest number": list the rooms, then describe the delete."""
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        looked = any(item.get("type") == "function_call_output" for item in payload["input"])
        if not looked:
            return response(len(requests), tool_calls(("list_rooms", {})))
        return response(len(requests), tool_calls(("delete_room", {"name": "Roddy 136"})))

    use(monkeypatch, respond)
    request = FakeRequest()
    reply = service.handle_request(request, "Delete the room with the smallest room number")

    assert len(requests) == 2
    assert reply.ok and not reply.changed
    assert "Deleting room 'Roddy 136' would do this" in reply.message
    assert "Rooms (" not in reply.message  # the lookup was only for the model
    assert any(room.name == "Roddy 136" for room in session_store.get_session(request).config.config.rooms)


def test_a_lookup_answer_is_the_models_own_words(monkeypatch):
    def respond(request):
        payload = json.loads(request.content)
        if not any(item.get("type") == "function_call_output" for item in payload["input"]):
            return response(1, tool_calls(("list_rooms", {})))
        return response(2, text_output("You have 3 rooms: Roddy 136, Roddy 140 and Roddy 147."))

    use(monkeypatch, respond)
    reply = service.handle_request(FakeRequest(), "How many rooms do I have?")
    assert reply.ok and not reply.changed
    assert reply.message == "You have 3 rooms: Roddy 136, Roddy 140 and Roddy 147."


def test_looking_forever_is_stopped(monkeypatch):
    requests = []

    def respond(request):
        requests.append(1)
        return response(len(requests), tool_calls(("list_rooms", {})))

    use(monkeypatch, respond)
    request = FakeRequest()
    before = session_store.get_session(request).config.model_dump_json()
    reply = service.handle_request(request, "List rooms again and again")
    assert not reply.ok and "couldn't finish" in reply.message
    assert len(requests) <= 2 * MAX_STEPS
    assert session_store.get_session(request).config.model_dump_json() == before


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
        return response(1, tool_calls(("describe_capabilities", {})), model="gpt-test-mini")

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
