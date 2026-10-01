"""
Helpers shared by every Configuration Editor controller (Sections 7, 10, 11).

Each configuration area (time slots today; rooms, labs, courses, faculty,
class patterns, meetings and global settings next) needs the same two things
before and after it changes the configuration:

    require_config(session, "adding a room")
        Get the loaded CombinedConfig, or raise a ControllerError that tells
        the user to create or load one first (the Section 19 empty state).

    apply_config_edit(session, config, "room", mutate, form_fields=...)
        Run `mutate(draft)` through app.crud.apply_edit(), which re-validates
        the COMPLETE configuration and leaves the previous valid one untouched
        on failure (Sections 10 and 11), mark the session as having unsaved
        changes on success, and turn any library failure into a
        ControllerError the view can show on the form.

New controllers should call these instead of copying them, so every area
reports problems and tracks unsaved changes the same way.
"""

from __future__ import annotations

from typing import Callable, Iterable

from app.commands.common import apply_session_edit
from app.crud import ValidationFailure
from app.session import ConfigError
from gui.controllers.errors import ControllerError, to_controller_error


def require_config(session, doing: str = "editing"):
    """Return the session's configuration, or raise a ControllerError.

    `doing` completes the sentence "... before <doing>." so each page can say
    what the user was trying to do, e.g. "editing time slots".
    """
    try:
        return session.require_config()
    except ConfigError as error:
        raise ControllerError(
            f"No configuration is loaded. Create or load one before {doing}."
        ) from error


def apply_config_edit(
    session,
    config,
    area: str,
    mutate: Callable[[object], None],
    form_fields: Iterable[str] = (),
) -> None:
    """Apply an atomic, fully validated edit and mark the session dirty.

    `area` is the human label used in error messages ("room", "course", ...).
    `form_fields` names the form fields library errors may be attached to.
    """
    try:
        apply_session_edit(session, config, area, mutate)
    except ValidationFailure as error:
        raise to_controller_error(error, form_fields=form_fields) from error
