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
  * The reply is built from the tool results, so it only says something
    happened when the application really did it, and it says whether the
    configuration was changed.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from gui.ai.runner import LangChainRunner, NotConfigured, Runner
from gui.ai.tools import ToolBox, ToolResult
from gui.session_store import get_session

logger = logging.getLogger("gui.ai")

MAX_REQUEST_LENGTH = 2000
EMPTY_MESSAGE = "Type a request first."
TOO_LONG_MESSAGE = f"That request is too long. Keep it under {MAX_REQUEST_LENGTH} characters."
BUSY_MESSAGE = "Your previous request is still being processed. Wait for it to finish, then try again."
SERVICE_FAILED = "The AI service couldn't finish that request. Try again in a moment."
NO_ANSWER = "The AI didn't give an answer. Try asking in a different way."
SAVED_NOTE = "The change is applied but not yet saved to a file."
SAVED_NOTE_MANY = "The changes are applied but not yet saved to a file."
PARTLY_SAVED_NOTE = "The changes that worked are applied but not yet saved to a file."
UNCHANGED_NOTE = "The configuration was not changed."

_BUSY: set[int] = set()
_BUSY_LOCK = threading.Lock()  # the dev server is threaded


@dataclass(frozen=True)
class Reply:
    ok: bool
    message: str
    changed: bool = False
    busy: bool = False
    results: list[ToolResult] = field(default_factory=list)


def get_runner() -> Runner:
    """The real AI. Tests replace this with a fake runner."""
    return LangChainRunner.from_environment()


def compose(results: list[ToolResult], model_text: str = "") -> Reply:
    """Turn what the tools really did into one plain-language reply."""
    if not results:
        return Reply(ok=bool(model_text), message=model_text or NO_ANSWER)

    lines = [result.message for result in results]
    changed = [result for result in results if result.changed]
    failed_writes = [result for result in results if result.write and not result.ok]
    if changed and failed_writes:
        lines.append(PARTLY_SAVED_NOTE)
    elif changed:
        lines.append(SAVED_NOTE if len(changed) == 1 else SAVED_NOTE_MANY)
    elif failed_writes:
        lines.append(UNCHANGED_NOTE)
    return Reply(
        ok=all(result.ok for result in results),
        message="\n".join(lines),
        changed=bool(changed),
        results=list(results),
    )


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
        return _run(request, text)
    finally:
        with _BUSY_LOCK:
            _BUSY.discard(key)


def _run(request, text: str) -> Reply:
    toolbox = ToolBox(request)
    try:
        runner = get_runner()
        model_text = runner.run(text, toolbox)
    except NotConfigured as error:
        return Reply(ok=False, message=f"{error} Nothing was changed.")
    except Exception as error:
        # Only the error's type is logged: provider messages can echo request
        # details, and the API key must never reach a log.
        logger.warning("AI request failed: %s", type(error).__name__)
        if toolbox.results:
            reply = compose(toolbox.results)
            return Reply(ok=False, message=f"{reply.message}\n{SERVICE_FAILED}", changed=reply.changed)
        return Reply(ok=False, message=f"{SERVICE_FAILED} {UNCHANGED_NOTE}")
    return compose(toolbox.results, model_text)
