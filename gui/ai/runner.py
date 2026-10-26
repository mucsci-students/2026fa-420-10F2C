"""
The LangChain agent that turns a request into tool calls (Sprint 3).

Same setup as the course's LangChain example: create_agent() with OpenAI's
Responses API. Action tools (add, update, delete, confirm, capabilities) are
marked return_direct, so once the model picks one the app's own result is the
answer: no second model call re-words it, and the model cannot claim something
happened that a tool did not do. Lookup tools (list_*, get_*, show_*) are not
direct: the model reads them and goes on, so "delete the smallest room" can
look first and then act. The number of steps is bounded (MAX_STEPS).

Settings come from environment variables only:
    OPENAI_API_KEY   required; never written to a file, a page, or a log
    OPENAI_MODEL     optional, defaults to gpt-6-luna

Each request carries the base prompt, the newest message and the last few chat
messages (see gui/ai/service.py, AI_HISTORY_MESSAGES), which only help the model
understand "yes" or "that one". The data itself always comes from the tools
(user story 6). Retries are bounded (MAX_RETRIES), the steps are bounded
(MAX_STEPS) and every call has a timeout, so a slow or failing service cannot
hang the page or run up the bill.

LangChain is imported inside build() so the rest of the app (and the tests
that use a fake runner) still work where it isn't installed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

from gui.ai.prompt import BASE_PROMPT, tool_overview
from gui.ai.tools import ToolBox

DEFAULT_MODEL = "gpt-6-luna"
TIMEOUT_SECONDS = 60
MAX_RETRIES = 2
MAX_STEPS = 6  # model calls per request: look, look, act, ...


class NotConfigured(Exception):
    """The AI can't run here (no API key, or LangChain isn't installed)."""


class Runner(Protocol):
    """Anything that can answer one request using the tools in `toolbox`.

    Returns the model's own text, or "" when it only called tools. Tests pass
    a fake runner that calls toolbox.call() directly, so no AI is used.
    """

    def run(self, text: str, toolbox: ToolBox) -> str: ...


def model_name() -> str:
    return os.environ.get("OPENAI_MODEL", "").strip() or DEFAULT_MODEL


@dataclass
class LangChainRunner:
    model: str = DEFAULT_MODEL
    http_client: Any = None  # tests pass an httpx client with a mocked OpenAI

    @classmethod
    def from_environment(cls) -> LangChainRunner:
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            raise NotConfigured(
                "The AI assistant isn't set up: set the OPENAI_API_KEY environment variable and restart the server."
            )
        return cls(model=model_name())

    def chat_model(self):
        from langchain_openai import ChatOpenAI

        options: dict[str, Any] = {"http_client": self.http_client} if self.http_client is not None else {}
        return ChatOpenAI(
            model=self.model,
            use_responses_api=True,
            reasoning={"effort": "medium"},
            timeout=TIMEOUT_SECONDS,
            max_retries=MAX_RETRIES,
            **options,
        )

    def build(self, toolbox: ToolBox):
        try:
            from langchain.agents import create_agent
            from langchain_core.tools import StructuredTool
        except ImportError as error:  # pragma: no cover - depends on the install
            raise NotConfigured("The AI assistant isn't installed. Run `uv sync` and restart.") from error

        def bind(name: str):
            def run_tool(**arguments) -> str:
                return toolbox.call(name, arguments).message

            return run_tool

        tools = [
            StructuredTool.from_function(
                name=tool.name,
                func=bind(tool.name),
                description=tool.description,
                args_schema=tool.args,
                return_direct=tool.final,
                # Bad arguments come back as a normal failed result, not a crash.
                handle_validation_error=lambda error, name=tool.name: toolbox.invalid(name, error).message,
            )
            for tool in toolbox.tools.values()
        ]
        prompt = BASE_PROMPT + "\n" + tool_overview(toolbox.tools.values())
        return create_agent(model=self.chat_model(), tools=tools, system_prompt=prompt)

    def run(self, text: str, toolbox: ToolBox) -> str:
        agent = self.build(toolbox)
        messages = [*toolbox.history, {"role": "user", "content": text}]
        result = agent.invoke({"messages": messages}, config={"recursion_limit": 2 * MAX_STEPS + 1})
        if any(item.final for item in toolbox.results):
            return ""  # an action's own result is the answer
        # Only lookups (or nothing): the model's last message is the answer.
        replies = [m for m in result["messages"] if getattr(m, "type", "") == "ai" and getattr(m, "text", "")]
        return replies[-1].text.strip() if replies else ""
