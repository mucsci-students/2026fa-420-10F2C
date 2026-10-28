"""
One AI request from start to finish (Sprint 3 user stories 2, 3 and 6).

    reply = service.handle_request(request, "Add a room named RODDY150 with capacity 35")

  * Empty text is refused before anything is sent.
  * Only one request per browser runs at a time. A second submit that
    arrives while the first is still running (a double click, Enter pressed
    twice) is refused with BUSY_MESSAGE and never reaches the AI, so a change
    can't be applied twice (story 3). The page blocks it too; this is the
    server-side half, for anything that gets past the page.
  * A fresh ToolBox is made for every request, and every tool reads the
    session's configuration when it runs, so the AI always sees the current
    state, manual edits included (story 6).
  * The AI also gets the last few chat messages (AI_HISTORY_MESSAGES, default
    6, 0 turns it off), only so it can understand "yes", "that one" or "make
    it 40 instead". They are never a source of data: the tools are.
  * Every request and reply is kept in the browser's chat (gui/ai/chats.py), so the panel
    shows the conversation again after a page change or reload.
  * The reply is built from the tool results, so it only says something
    happened when the application really did it, and it says whether the
    configuration was changed. Plain lookups are for the AI to read; when a
    request ends after only lookups, the AI's own words are the answer.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field, replace

from gui.ai import chats
from gui.ai.runner import LangChainRunner, NotConfigured, Runner
from gui.ai.tools import ToolBox, ToolResult
from gui.session_store import get_session

logger = logging.getLogger("gui.ai")

MAX_REQUEST_LENGTH = 2000
EMPTY_MESSAGE = "Type a request first."
TOO_LONG_MESSAGE = (
    f"That request is too long. Keep it under {MAX_REQUEST_LENGTH} characters."
)
BUSY_MESSAGE = "Your previous request is still being processed. Wait for it to finish, then try again."
SERVICE_FAILED = "The AI service couldn't finish that request. Try again in a moment."
NO_ANSWER = "The AI didn't give an answer. Try asking in a different way."
SAVED_NOTE = "The change is applied but not yet saved to a file."
SAVED_NOTE_MANY = "The changes are applied but not yet saved to a file."
PARTLY_SAVED_NOTE = "The changes that worked are applied but not yet saved to a file."
UNCHANGED_NOTE = "The configuration was not changed."

HISTORY_ENV = "AI_HISTORY_MESSAGES"
DEFAULT_HISTORY = 6
MAX_HISTORY = 20
HISTORY_ATTR = "ai_history"
HISTORY_TEXT_LIMIT = 1500

_BUSY: set[int] = set()
_BUSY_LOCK = threading.Lock()  # the dev server is threaded


@dataclass(frozen=True)
class Reply:
    ok: bool
    message: str
    changed: bool = False
    busy: bool = False
    results: list[ToolResult] = field(default_factory=list)
    schedules_changed: bool = (
        False  # the schedules in the Schedule Viewer were replaced or cleared
    )
    refresh: bool = False  # the page behind the chat is out of date (a different configuration or schedules)
    suggestions: tuple[str, ...] = ()  # short replies the chat offers as buttons


def get_runner() -> Runner:
    """The real AI. Tests replace this with a fake runner."""
    return LangChainRunner.from_environment()


def history_limit() -> int:
    """How many earlier chat messages go to the AI (0 = none, every request on its own)."""
    raw = os.environ.get(HISTORY_ENV, "").strip()
    try:
        value = int(raw) if raw else DEFAULT_HISTORY
    except ValueError:
        value = DEFAULT_HISTORY
    return max(0, min(value, MAX_HISTORY))


def compose(results: list[ToolResult], model_text: str = "") -> Reply:
    """Turn what the tools really did into one plain-language reply, plus what the chat should do next:
    offer quick replies, and say whether the schedules or configuration behind the page were replaced."""
    reply = _compose(results, model_text)
    shown = [result for result in results if result.final] or list(results)
    offered = next(
        (result.suggestions for result in reversed(shown) if result.suggestions), ()
    )
    schedules_changed = any(result.schedules_changed for result in results)
    replaced = any(result.config_replaced for result in results)
    return replace(
        reply,
        schedules_changed=schedules_changed,
        refresh=schedules_changed or replaced,
        suggestions=offered,
    )


def _compose(results: list[ToolResult], model_text: str = "") -> Reply:
    if not results:
        return Reply(ok=bool(model_text), message=model_text or NO_ANSWER)

    # Actions end the request with the application's own words. Lookups are only for the AI to
    # read, so they are shown only when nothing else happened and the AI said nothing itself.
    shown = [result for result in results if result.final]
    if not shown:
        if model_text:
            return Reply(ok=True, message=model_text, results=list(results))
        shown = list(results)

    lines = [result.message for result in shown]
    changed = [result for result in shown if result.changed]
    failed_writes = [result for result in shown if result.write and not result.ok]
    unsaved = [
        result for result in changed if result.note
    ]  # undo and redo say what they did themselves
    if unsaved and failed_writes:
        lines.append(PARTLY_SAVED_NOTE)
    elif unsaved:
        lines.append(SAVED_NOTE if len(unsaved) == 1 else SAVED_NOTE_MANY)
    elif failed_writes and not changed:
        lines.append(UNCHANGED_NOTE)
    return Reply(
        ok=all(result.ok for result in shown),
        message="\n".join(lines),
        changed=bool(changed),
        results=list(results),
    )


def _remember(request, text: str, reply: Reply, limit: int) -> None:
    """Keep the last few chat messages for this browser, so the next request can build on them."""
    session = get_session(request)
    if limit <= 0:
        setattr(session, HISTORY_ATTR, [])
        return
    kept = list(getattr(session, HISTORY_ATTR, None) or [])
    kept.append({"role": "user", "content": text})
    kept.append({"role": "assistant", "content": reply.message[:HISTORY_TEXT_LIMIT]})
    setattr(session, HISTORY_ATTR, kept[-limit:])


def is_busy(request) -> bool:
    """True while a request of this browser is still running (the chat panel shows it after a page change)."""
    with _BUSY_LOCK:
        return id(get_session(request)) in _BUSY


def handle_request(request, text: str) -> Reply:
    text = (text or "").strip()
    if not text:
        return Reply(ok=False, message=EMPTY_MESSAGE)
    if len(text) > MAX_REQUEST_LENGTH:
        return Reply(ok=False, message=TOO_LONG_MESSAGE)

    key = id(get_session(request))
    with _BUSY_LOCK:
        if key in _BUSY:
            return Reply(ok=False, message=BUSY_MESSAGE, busy=True)
        _BUSY.add(key)
    try:
        session = get_session(request)
        chats.record(
            session, "user", text
        )  # kept at once, so a page change while it runs still shows it
        reply = _run(request, text)
        chats.record(
            session,
            "assistant" if reply.ok else "error",
            reply.message,
            suggestions=reply.suggestions,
            generated=reply.ok and reply.schedules_changed,
        )
        return reply
    finally:
        with _BUSY_LOCK:
            _BUSY.discard(key)


def _run(request, text: str) -> Reply:
    limit = history_limit()
    earlier = (
        (list(getattr(get_session(request), HISTORY_ATTR, None) or []))[-limit:]
        if limit
        else []
    )
    toolbox = ToolBox(request, history=earlier)
    try:
        runner = get_runner()
        model_text = runner.run(text, toolbox)
    except NotConfigured as error:
        return Reply(ok=False, message=f"{error} Nothing was changed.")
    except Exception as error:  # noqa: BLE001
        # Only the error's type is logged: provider messages can echo request
        # details, and the API key must never reach a log.
        logger.warning("AI request failed: %s", type(error).__name__)
        if toolbox.results:
            reply = compose(toolbox.results)
            return replace(
                reply, ok=False, message=f"{reply.message}\n{SERVICE_FAILED}"
            )
        return Reply(ok=False, message=f"{SERVICE_FAILED} {UNCHANGED_NOTE}")
    reply = compose(toolbox.results, model_text)
    _remember(request, text, reply, limit)
    return reply
