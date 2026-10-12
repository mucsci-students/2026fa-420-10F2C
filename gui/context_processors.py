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
    return {
        "config_loaded": session.config is not None,
        "config_dirty": bool(session.dirty),
    }
