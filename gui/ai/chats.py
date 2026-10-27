"""
The chats of the AI assistant, kept on the server for each browser (Sprint 3: chat persistence).

    chats.record(session, "user", "Add a room")          # one line of the active chat
    chats.new_chat(session)                              # "New chat": the old one stays in the list
    chats.state(session)                                 # what the chat panel draws after any page load

Why on the server: the page behind the chat is replaced whenever the user moves to another page (and
the assistant can update it in place), so the panel cannot be the only place that remembers. The
transcript lives on the browser's own Session next to the configuration it talks about, so it is
there again on every page and after a reload, and it goes away with the session like the
configuration does (a server restart starts everything fresh).

Each chat has its own memory for the AI too (the few earlier messages that help it understand
"yes" or "make it 40 instead"): a new chat starts with none, and going back to an older chat gets its
own back. A new chat or a switch also forgets anything that was waiting for a "yes" (a delete, the
generation settings), so a confirmation can never carry over from another conversation.

Bounded on purpose: at most MAX_CHATS chats (the oldest is dropped) of at most MAX_MESSAGES lines each.
"""

from __future__ import annotations

import threading
import time
import uuid

from gui.ai.generation import _forget_waiting

CHATS_ATTR = "ai_chats"
ACTIVE_ATTR = "ai_active_chat"
HISTORY_ATTR = "ai_history"  # the AI's memory of the ACTIVE chat (see gui/ai/service.py)

MAX_CHATS = 20
MAX_MESSAGES = 200
TITLE_LENGTH = 40
TEXT_LIMIT = 4000
EMPTY_TITLE = "New chat"

_LOCK = threading.RLock()  # the dev server is threaded; the panel and a request can touch this together


def _chats(session) -> list[dict]:
    chats = getattr(session, CHATS_ATTR, None)
    if chats is None:
        chats = []
        setattr(session, CHATS_ATTR, chats)
    return chats


def _make() -> dict:
    return {"id": uuid.uuid4().hex[:12], "title": EMPTY_TITLE, "messages": [], "history": [], "updated": time.time()}


def _find(session, chat_id) -> dict | None:
    return next((chat for chat in _chats(session) if chat["id"] == chat_id), None)


def active(session) -> dict:
    """The chat new messages go to (a first one is made when there is none yet)."""
    with _LOCK:
        chat = _find(session, getattr(session, ACTIVE_ATTR, None))
        if chat is None:
            chats = _chats(session)
            chat = chats[-1] if chats else _make()
            if not chats:
                chats.append(chat)
            setattr(session, ACTIVE_ATTR, chat["id"])
            setattr(session, HISTORY_ATTR, list(chat["history"]))
        return chat


def _title(text: str) -> str:
    line = " ".join(text.split())
    return line if len(line) <= TITLE_LENGTH else line[: TITLE_LENGTH - 1].rstrip() + "…"


def record(session, kind: str, text: str, suggestions=(), generated: bool = False) -> None:
    """Add one line to the active chat. kind: "user", "assistant" or "error"."""
    with _LOCK:
        chat = active(session)
        if kind == "user" and not any(message["kind"] == "user" for message in chat["messages"]):
            chat["title"] = _title(text)
        chat["messages"].append(
            {
                "kind": kind,
                "text": text[:TEXT_LIMIT],
                "suggestions": list(suggestions),
                "generated": bool(generated),
            }
        )
        del chat["messages"][:-MAX_MESSAGES]
        chat["updated"] = time.time()  # the sidebar lists chats by their last activity


def _save_memory(session) -> None:
    """Park the AI's memory with the chat it belongs to before another chat becomes the active one."""
    chat = _find(session, getattr(session, ACTIVE_ATTR, None))
    if chat is not None:
        chat["history"] = list(getattr(session, HISTORY_ATTR, None) or [])


def _open(session, chat: dict) -> None:
    setattr(session, ACTIVE_ATTR, chat["id"])
    setattr(session, HISTORY_ATTR, list(chat["history"]))
    _forget_waiting(session)


def new_chat(session) -> dict:
    """Start a fresh chat. An empty active chat is reused, so "New chat" twice does not pile up blanks."""
    with _LOCK:
        current = active(session)
        if not current["messages"]:
            return current
        _save_memory(session)
        chats = _chats(session)
        fresh = _make()
        chats.append(fresh)
        del chats[: max(0, len(chats) - MAX_CHATS)]
        _open(session, fresh)
        return fresh


def switch_chat(session, chat_id) -> bool:
    with _LOCK:
        chat = _find(session, chat_id)
        if chat is None:
            return False
        if chat["id"] != active(session)["id"]:
            _save_memory(session)
            _open(session, chat)
        return True


def delete_chat(session, chat_id) -> bool:
    """Remove a chat. When it was the open one, the newest other chat opens (or a blank one)."""
    with _LOCK:
        chat = _find(session, chat_id)
        if chat is None:
            return False
        was_active = chat["id"] == active(session)["id"]
        chats = _chats(session)
        chats.remove(chat)
        if was_active:
            setattr(session, HISTORY_ATTR, [])
            if chats:
                _open(session, chats[-1])
            else:
                _open(session, active_after_empty(session))
        return True


def active_after_empty(session) -> dict:
    fresh = _make()
    _chats(session).append(fresh)
    return fresh


def state(session, busy: bool = False) -> dict:
    """Everything the panel draws: the chat list (newest first) and the open chat's lines."""
    with _LOCK:
        current = active(session)
        return {
            "busy": bool(busy),
            "active": current["id"],
            "chats": [
                {
                    "id": chat["id"],
                    "title": chat["title"],
                    "count": len(chat["messages"]),
                    "active": chat["id"] == current["id"],
                    "updated": int(chat.get("updated", 0)),  # seconds since 1970; the page groups by day
                }
                # Most recent activity first; chats with the same time keep newest-created first.
                for chat in sorted(reversed(_chats(session)), key=lambda chat: -chat.get("updated", 0))
            ],
            "messages": [dict(message) for message in current["messages"]],
        }
