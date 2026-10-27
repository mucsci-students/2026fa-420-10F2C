"""
Controller for Undo / Redo / History and "Restore previous" (Sprint 2 Sections 8, 11, 12, 20).

The history itself is Model code (app/history.py, held on the Session). This
controller only translates "the user pressed Undo / Redo / went back to here /
restore previous" into calls on it and turns problems into a ControllerError the
View can show. It never touches HttpResponse or templates.

Every action accepts the `token` the page was rendered with. If the
configuration has moved on since (another tab, a double click), the request is
refused instead of undoing something the user did not see.
"""

from __future__ import annotations

from app.history import HistoryError
from app.session import ConfigError
from gui.controllers.errors import ControllerError
from gui.session_store import get_session


def describe_history(request) -> dict:
    """Plain data for the Undo / Redo bar and the History page."""
    return get_session(request).history.state()


def undo(request, token=None) -> str:
    """Undo the latest configuration change; returns a description of it."""
    session = get_session(request)
    return _run(session, lambda: session.history.undo(session, token))


def redo(request, token=None) -> str:
    """Re-apply the change that was last undone."""
    session = get_session(request)
    return _run(session, lambda: session.history.redo(session, token))


def go_to(request, entry_id, token=None) -> list[str]:
    """Jump to just before (or, for undone changes, just after) one history entry.
    Returns the labels of the changes that were undone or redone."""
    session = get_session(request)
    return _run(session, lambda: session.history.go_to(session, entry_id, token))


def describe_previous(request) -> dict | None:
    """What "Restore previous" would bring back (None when nothing can be)."""
    return get_session(request).previous_info()


def restore_previous(request) -> str:
    """Bring back the configuration that New / Load replaced (swapping, so this
    can itself be reversed). Returns its name."""
    session = get_session(request)
    if getattr(session, "generating", False):
        raise ControllerError(
            "Schedules are being generated right now. Wait for that to finish (or cancel it) before "
            "restoring the previous configuration."
        )
    try:
        return session.restore_previous()
    except ConfigError as error:
        raise ControllerError(str(error)) from error


def _run(session, action):
    if session.config is None:
        raise ControllerError(
            "No configuration is loaded, so there is nothing to undo or redo."
        )
    try:
        return action()
    except HistoryError as error:
        raise ControllerError(str(error)) from error
