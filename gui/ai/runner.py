"""
The LangChain agent that turns a request into tool calls (Sprint 3).

Same setup as the course's LangChain example: create_agent() with OpenAI's
Responses API, and every tool marked return_direct, so after the model picks
its tool calls the app's own results are the answer. No second model call
re-words them, and the model cannot claim something happened that a tool
did not do.

Settings come from environment variables only:
    OPENAI_API_KEY   required; never written to a file, a page, or a log
    OPENAI_MODEL     optional, defaults to gpt-6-luna

Each request is sent alone: the base prompt and this one message, never
earlier chat text (user story 6). Retries are bounded (MAX_RETRIES) and every
call has a timeout, so a slow or failing service cannot hang the page or run
up the bill.

LangChain is imported inside build() so the rest of the app (and the tests
that use a fake runner) still work where it isn't installed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

from gui.ai.prompt import BASE_PROMPT
from gui.ai.tools import ToolBox

DEFAULT_MODEL = "gpt-6-luna"
TIMEOUT_SECONDS = 60
MAX_RETRIES = 2


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
                return_direct=True,
                # Bad arguments come back as a normal failed result, not a crash.
                handle_validation_error=lambda error, name=tool.name: toolbox.invalid(name, error).message,
            )
            for tool in toolbox.tools.values()
        ]
        return create_agent(model=self.chat_model(), tools=tools, system_prompt=BASE_PROMPT)

    def run(self, text: str, toolbox: ToolBox) -> str:
        agent = self.build(toolbox)
        # Only this request: no earlier chat text is sent (user story 6).
        result = agent.invoke({"messages": [{"role": "user", "content": text}]})
        if toolbox.results:
            return ""  # the tools' own results are the answer
        replies = [message.text for message in result["messages"][1:] if getattr(message, "text", "")]
        return "\n".join(replies).strip()
