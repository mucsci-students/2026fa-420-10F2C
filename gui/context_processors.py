"""
Template context available on every page.

`config_loaded` / `config_dirty` drive the status text in the navigation bar
so the user can always see whether the in-memory configuration has edits that
have not been saved to a file (Section 11: "the interface must indicate
whether an edit has been applied"; Section 8 builds its unsaved-changes
safeguard on the same flag, Session.dirty).
"""

from gui.session_store import get_session


def config_status(request) -> dict:
    session = get_session(request)
    history = getattr(session, "history", None)
    return {
        "config_loaded": session.config is not None,
        "config_dirty": bool(session.dirty),
        # Drives the Undo / Redo buttons on the configuration pages (app/history.py).
        "history_state": history.state() if history is not None else {},
        # Set once, on the first page shown after a successful edit: drives the
        # inline Undo button inside the "saved" message (app/history.py take_fresh).
        "history_fresh": history.take_fresh() if history is not None else None,
        # Generated schedules that no longer match the configuration (Section 13).
        "schedules_stale": bool(getattr(session, "schedules_stale", False)),
        # The configuration that New / Load replaced, if it can be brought back.
        "previous_config": session.previous_info() if hasattr(session, "previous_info") else None,
    }
