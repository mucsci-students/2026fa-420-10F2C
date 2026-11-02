"""
The Adapter between the app's AI tools and LangChain (gui/ai/runner.py).

Each half of the adapter is checked without a key or a network: our tools become
LangChain tools that forward to the tool box (the request half), and LangChain's
answer becomes plain text (the reply half). The whole agent against a mocked
OpenAI is in tests/test_ai_langchain.py.
"""

from types import SimpleNamespace

import pytest

from gui import session_store
from gui.ai import runner as runner_module
from gui.ai.base import ToolResult
from gui.ai.runner import LangChainRunner, Runner, load_api_key
from gui.ai.tools import ToolBox


class FakeRequest:
    def __init__(self):
        self.session = {}


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


@pytest.fixture
def toolbox():
    return ToolBox(FakeRequest())


@pytest.fixture
def adapter():
    return LangChainRunner(model="test-model", api_key="test-key")


def langchain_tools_by_name(adapter, toolbox):
    pytest.importorskip("langchain_core")
    return {tool.name: tool for tool in adapter.langchain_tools(toolbox)}


def message(kind, text):
    return SimpleNamespace(type=kind, text=text)


# ---------------------------------------------------------------------- #
#  The target interface
# ---------------------------------------------------------------------- #
def test_the_adapter_provides_the_runner_interface(adapter):
    as_runner: Runner = (
        adapter  # the type checker verifies that the adapter fits the target
    )
    assert callable(as_runner.run)


# ---------------------------------------------------------------------- #
#  Request half: our tools -> LangChain tools
# ---------------------------------------------------------------------- #
def test_every_app_tool_becomes_one_langchain_tool(adapter, toolbox):
    tools = langchain_tools_by_name(adapter, toolbox)

    assert list(tools) == list(toolbox.tools)
    for name, app_tool in toolbox.tools.items():
        langchain_tool = tools[name]
        assert app_tool.description in langchain_tool.description
        assert langchain_tool.args_schema is app_tool.args
        # an action's own result is the answer; a lookup is only read by the model
        assert langchain_tool.return_direct == app_tool.final


def test_a_langchain_tool_call_is_forwarded_to_the_tool_box(
    adapter, toolbox, monkeypatch
):
    calls = []

    def spy(name, arguments=None):
        calls.append((name, arguments))
        return ToolResult(name, True, "forwarded")

    monkeypatch.setattr(toolbox, "call", spy)
    tools = langchain_tools_by_name(adapter, toolbox)

    text = tools["add_room"].invoke({"name": "RODDY150", "capacity": 35})

    assert text == "forwarded"
    # only what the model sent is passed on: "features" has a default but was not sent
    assert calls == [("add_room", {"name": "RODDY150", "capacity": 35})]


def test_arguments_langchain_rejects_come_back_as_a_failed_result(adapter, toolbox):
    tools = langchain_tools_by_name(adapter, toolbox)

    text = tools["add_room"].invoke({"name": "RODDY150", "capacity": "lots"})

    assert text  # a message for the user, not an exception
    assert toolbox.results[-1].message == text
    assert not toolbox.results[-1].ok


# ---------------------------------------------------------------------- #
#  Reply half: LangChain's answer -> plain text
# ---------------------------------------------------------------------- #
def test_an_actions_own_result_is_the_reply(toolbox):
    toolbox.results.append(ToolResult("add_room", True, "Room added."))
    result = {"messages": [message("ai", "I added it!")]}

    assert LangChainRunner.reply_from(result, toolbox) == ""


def test_after_only_lookups_the_models_last_message_is_the_reply(toolbox):
    toolbox.results.append(ToolResult("list_rooms", True, "3 rooms", final=False))
    result = {
        "messages": [
            message("human", "How many rooms are there?"),
            message("ai", "Let me look."),
            message("ai", "  There are 3 rooms.  "),
        ]
    }

    assert LangChainRunner.reply_from(result, toolbox) == "There are 3 rooms."


def test_no_model_text_gives_an_empty_reply(toolbox):
    result = {"messages": [message("human", "hello"), message("ai", "")]}

    assert LangChainRunner.reply_from(result, toolbox) == ""


# ---------------------------------------------------------------------- #
#  Where the key comes from
# ---------------------------------------------------------------------- #
def test_load_api_key_is_empty_when_there_is_no_key(monkeypatch, tmp_path):
    monkeypatch.setattr(runner_module, "API_KEY_FILE", tmp_path / "missing.txt")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert load_api_key() == ""


def test_a_blank_environment_key_falls_back_to_the_key_file(monkeypatch, tmp_path):
    key_file = tmp_path / "openai_api_key.txt"
    key_file.write_text("key-from-file\n", encoding="utf-8")
    monkeypatch.setattr(runner_module, "API_KEY_FILE", key_file)
    monkeypatch.setenv("OPENAI_API_KEY", "   ")

    assert load_api_key() == "key-from-file"
