"""
The LangChain agent that turns a request into tool calls (Sprint 3).

Same setup as the course's LangChain example: create_agent() with OpenAI's
Responses API. Action tools (add, update, delete, confirm, capabilities) are
marked return_direct, so once the model picks one the app's own result is the
answer: no second model call re-words it, and the model cannot claim something
happened that a tool did not do. Lookup tools (list_*, get_*, show_*) are not
direct: the model reads them and goes on, so "delete the smallest room" can
look first and then act. The number of steps is bounded (MAX_STEPS).

Settings come from the environment, with a local key-file fallback:
    OPENAI_API_KEY   required; config/openai_api_key.txt is used if unset
    OPENAI_MODEL     optional, defaults to gpt-6-luna

Each request carries the base prompt, the newest message and the last few chat
messages (see gui/ai/service.py, AI_HISTORY_MESSAGES), which only help the model
understand "yes" or "that one". The data itself always comes from the tools
(user story 6). Retries are bounded (MAX_RETRIES), the steps are bounded
(MAX_STEPS) and every call has a timeout, so a slow or failing service cannot
hang the page or run up the bill.

LangChain is imported only when the AI is used (see _langchain()), so the rest of
the app (and the tests that use a fake runner) still work where it isn't installed.

Design pattern: Adapter (see "Design patterns" in the README).
    Target    Runner, the one interface the app wants: run(text, toolbox) -> text.
    Client    gui/ai/service.py, which only ever calls Runner.run().
    Adaptee   LangChain's agent and tool classes, talking to OpenAI.
    Adapter   LangChainRunner. langchain_tools() turns our tools into LangChain
              tools, and reply_from() turns LangChain's answer back into text.
Nothing else in the app imports LangChain, and the tests' fake runners implement
the same Runner interface, so routine tests need no AI and no key.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from gui.ai.prompt import BASE_PROMPT, tool_overview
from gui.ai.tools import ToolBox

DEFAULT_MODEL = "gpt-6-luna"
TIMEOUT_SECONDS = 60
MAX_RETRIES = 2
MAX_STEPS = 6  # model calls per request: look, look, act, ...
_SENT = (
    threading.local()
)  # the argument names the model sent for the tool call running on this thread
API_KEY_FILE = Path(__file__).resolve().parents[2] / "config" / "openai_api_key.txt"


class NotConfigured(Exception):
    """The AI can't run here (no API key, or LangChain isn't installed)."""


class Runner(Protocol):
    """The Adapter pattern's Target: anything that can answer one request using the tools in `toolbox`.

    Returns the model's own text, or "" when it only called tools. Tests pass
    a fake runner that calls toolbox.call() directly, so no AI is used.
    """

    def run(self, text: str, toolbox: ToolBox) -> str: ...


def model_name() -> str:
    return os.environ.get("OPENAI_MODEL", "").strip() or DEFAULT_MODEL


def load_api_key() -> str:
    """The OpenAI key: the environment variable first, then the local key file ("" when neither has one)."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        try:
            api_key = API_KEY_FILE.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            pass
    return api_key


def _langchain():
    """LangChain's agent builder and tool class, imported only when the AI is really used."""
    try:
        from langchain.agents import create_agent
        from langchain_core.tools import StructuredTool
    except ImportError as error:  # pragma: no cover - depends on the install
        raise NotConfigured(
            "The AI assistant isn't installed. Run `uv sync` and restart."
        ) from error
    return create_agent, StructuredTool


def system_prompt(toolbox: ToolBox) -> str:
    """The base rules, the tools, and (only while one waits) the request that is waiting for details."""
    return (
        BASE_PROMPT
        + "\n"
        + tool_overview(toolbox.tools.values())
        + toolbox.waiting_note()
    )


@dataclass
class LangChainRunner:
    """The Adapter: makes LangChain's agent usable through the app's own Runner interface."""

    model: str = DEFAULT_MODEL
    http_client: Any = None  # tests pass an httpx client with a mocked OpenAI
    api_key: str = field(default="", repr=False)

    @classmethod
    def from_environment(cls) -> LangChainRunner:
        api_key = load_api_key()
        if not api_key:
            raise NotConfigured(
                "The AI assistant isn't set up: set the OPENAI_API_KEY environment variable or add your key to config/openai_api_key.txt, then restart the server."
            )
        return cls(model=model_name(), api_key=api_key)

    def chat_model(self):
        from langchain_openai import ChatOpenAI

        options: dict[str, Any] = (
            {"http_client": self.http_client} if self.http_client is not None else {}
        )
        return ChatOpenAI(
            model=self.model,
            api_key=self.api_key or None,
            use_responses_api=True,
            reasoning={"effort": "medium"},
            timeout=TIMEOUT_SECONDS,
            max_retries=MAX_RETRIES,
            **options,
        )

    def langchain_tools(self, toolbox: ToolBox) -> list[Any]:
        """Our tools as LangChain tools: the request half of the adapter.

        Each AiTool (name, description, argument schema, handler) becomes one LangChain tool, and
        every call the model makes is forwarded to toolbox.call(), which checks the arguments,
        runs the controller and records what really happened."""
        _, StructuredTool = _langchain()

        class SentKeysTool(StructuredTool):
            """LangChain fills in every field that has a default before it calls a tool, so the arguments no
            longer say what the model actually sent. Whether a value was given (even as "none") decides
            whether it is asked for (gui/ai/clarify.py), so the keys it sent are kept for the call."""

            def run(self, tool_input, *args, **kwargs):
                _SENT.keys = set(tool_input) if isinstance(tool_input, dict) else None
                try:
                    return super().run(tool_input, *args, **kwargs)
                finally:
                    _SENT.keys = None

        def bind(name: str):
            def run_tool(**arguments) -> str:
                sent = getattr(_SENT, "keys", None)
                if sent is not None:
                    arguments = {
                        key: value for key, value in arguments.items() if key in sent
                    }
                return toolbox.call(name, arguments).message

            return run_tool

        return [
            SentKeysTool.from_function(
                name=tool.name,
                func=bind(tool.name),
                description=tool.description,
                args_schema=tool.args,
                return_direct=tool.final,
                # Bad arguments come back as a normal failed result, not a crash.
                handle_validation_error=lambda error, name=tool.name: (
                    toolbox.invalid(name, error).message
                ),
            )
            for tool in toolbox.tools.values()
        ]

    def build(self, toolbox: ToolBox):
        create_agent, _ = _langchain()
        tools = self.langchain_tools(toolbox)
        return create_agent(
            model=self.chat_model(), tools=tools, system_prompt=system_prompt(toolbox)
        )

    def run(self, text: str, toolbox: ToolBox) -> str:
        agent = self.build(toolbox)
        messages = [*toolbox.history, {"role": "user", "content": text}]
        result = agent.invoke(
            {"messages": messages}, config={"recursion_limit": 2 * MAX_STEPS + 1}
        )
        return self.reply_from(result, toolbox)

    @staticmethod
    def reply_from(result: Any, toolbox: ToolBox) -> str:
        """LangChain's answer as plain text: the reply half of the adapter.

        "" when an action's own result is the answer; otherwise the model's last message."""
        if any(item.final for item in toolbox.results):
            return ""  # an action's own result is the answer
        # Only lookups (or nothing): the model's last message is the answer.
        replies = [
            m
            for m in result["messages"]
            if getattr(m, "type", "") == "ai" and getattr(m, "text", "")
        ]
        return replies[-1].text.strip() if replies else ""
