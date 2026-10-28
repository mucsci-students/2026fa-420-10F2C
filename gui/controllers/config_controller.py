"""
Controller for Configuration Editor lifecycle actions (Sections 8-10):
New, Load, Save and Validate, plus the summary the editor home page shows.

Every function gets this browser's Session through
gui.session_store.get_session(request) and calls the same app/ code the CLI
uses (Session.new_config, Session.load_bytes, Session.dumps and
app.commands.configuration.revalidate). Validation is NOT reimplemented here
(Section 3). Anything the user can fix raises ControllerError; nothing in this
module builds an HttpResponse or touches a template (Section 20).

State safety (Sections 8 and 10): Session.load_bytes() swaps the new
configuration in only after the whole file has been read and validated, so
every failure leaves the previous valid configuration exactly as it was.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass

from scheduler.config import ValidationError

from app.commands.configuration import revalidate
from app.session import ConfigError
from gui import constants
from gui.controllers.common import require_config
from gui.controllers.errors import ControllerError, FieldError, describe_problems
from gui.controllers.uploads import read_upload
from gui.session_store import get_session

LOAD_FIELD = "config_file"
DEFAULT_FILENAME = "scheduler_config.json"
MAX_PROBLEMS = 8  # how many validation problems to list before "...and N more"
KEPT = "Your current configuration was kept."
FILENAME_PATTERN = (
    constants.FILENAME_PATTERN
)  # what _download_name keeps; every file name box uses it
MAX_FILENAME_LENGTH = constants.MAX_FILENAME_LENGTH
STARTED_NEW = (
    "Started a new configuration. It begins with one placeholder room, course, "
    "faculty member and class pattern; edit or replace them."
)
RESTORE_HINT = "Restore previous configuration in the Configuration Editor brings back the one you have now."
PENDING_NEW_ATTR = (
    "pending_new_configuration"  # token of a New waiting for the user's choice
)


# ---------------------------------------------------------------------- #
#  Page summary
# ---------------------------------------------------------------------- #
def _size(items) -> int:
    try:
        return len(items)
    except TypeError:
        return 0


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def discard_note(dirty: bool, schedule_count: int) -> str:
    """Plain-language list of what New/Load would throw away ('' if nothing).

    Starting or loading a configuration clears the schedules in the session
    too (Session.new_config / Session.load), so they are part of the warning.
    """
    parts = []
    if dirty:
        parts.append("your unsaved changes")
    if schedule_count:
        parts.append(f"the {_plural(schedule_count, 'schedule')} loaded now")
    return " and ".join(parts)


def describe_configuration(request) -> dict:
    """Everything the Configuration Editor home page needs, as plain data.

    "counts" has one entry per configuration area (None when the area has no
    meaningful count), keyed the same way as _CONFIG_AREAS in gui/views.py.
    "discard_note" is non-empty when New/Load must ask for confirmation.
    """
    session = get_session(request)
    config = session.config
    schedule_count = len(session.schedules)
    dirty = bool(session.dirty)
    state = {
        "has_config": config is not None,
        "dirty": dirty,
        "name": getattr(session, "config_name", None),
        "save_name": _download_name(getattr(session, "config_name", None)),
        "schedule_count": schedule_count,
        "counts": {},
        "discard_note": discard_note(dirty, schedule_count),
    }
    if config is None:
        return state

    entities = config.config
    slots = config.time_slot_config
    patterns = list(getattr(slots, "classes", None) or [])
    state["counts"] = {
        "rooms": _size(getattr(entities, "rooms", None)),
        "labs": _size(getattr(entities, "labs", None)),
        "courses": _size(getattr(entities, "courses", None)),
        "faculty": _size(getattr(entities, "faculty", None)),
        "time_blocks": sum(_size(blocks) for blocks in slots.times.values()),
        "patterns": len(patterns),
        "meetings": sum(
            _size(getattr(pattern, "meetings", None)) for pattern in patterns
        ),
        "settings": None,
    }
    return state


# ---------------------------------------------------------------------- #
#  New / Load (Section 8)
# ---------------------------------------------------------------------- #
def new_configuration(request) -> None:
    """Start a fresh configuration (it holds placeholder items, because the
    library does not accept a completely empty one). The view asks for
    confirmation first when there are unsaved changes."""
    session = get_session(request)
    try:
        session.new_config()
    except ConfigError as error:
        raise ControllerError(
            f"A new configuration could not be created. {KEPT}"
        ) from error


@dataclass(frozen=True)
class NewRequest:
    """What asking for a new configuration did.

    started: it was started at once (nothing would have been lost).
    Otherwise `dirty`, `schedule_count` say what a new one would discard, `token`
    identifies this warning (confirm_new_configuration needs it) and `export_name`
    is the file name Save JSON offers.
    """

    started: bool
    dirty: bool = False
    schedule_count: int = 0
    token: str = ""
    export_name: str = DEFAULT_FILENAME


def request_new_configuration(request) -> NewRequest:
    """Start a new configuration only when that loses nothing; otherwise change
    nothing and remember the warning, so confirm_new_configuration can be
    refused for anything that was not warned about."""
    session = get_session(request)
    dirty = bool(session.dirty) and session.config is not None
    schedule_count = len(session.schedules) if session.config is not None else 0
    if not discard_note(dirty, schedule_count):
        setattr(session, PENDING_NEW_ATTR, None)
        new_configuration(request)
        return NewRequest(started=True)
    token = secrets.token_urlsafe(8)
    setattr(session, PENDING_NEW_ATTR, token)
    return NewRequest(
        started=False,
        dirty=dirty,
        schedule_count=schedule_count,
        token=token,
        export_name=_download_name(getattr(session, "config_name", None)),
    )


def confirm_new_configuration(request, token: str) -> None:
    """Discard and Continue: start the new configuration the user was warned about."""
    session = get_session(request)
    waiting = getattr(session, PENDING_NEW_ATTR, None)
    if not waiting or not secrets.compare_digest(waiting, str(token or "")):
        raise ControllerError(
            f"That choice is no longer current, so nothing was discarded. {KEPT} "
            "Ask me to start a new configuration again if you still want one."
        )
    setattr(session, PENDING_NEW_ATTR, None)
    new_configuration(request)


def cancel_new_configuration(request, token: str) -> bool:
    """Cancel: forget the warning and change nothing. True when one was waiting."""
    session = get_session(request)
    waiting = getattr(session, PENDING_NEW_ATTR, None)
    setattr(session, PENDING_NEW_ATTR, None)
    return bool(waiting) and secrets.compare_digest(waiting, str(token or ""))


def load_configuration(request, uploaded_file) -> str:
    """Load and validate an uploaded JSON configuration; return its file name.

    The whole file is read (read_upload) and validated (the scheduler library,
    via Session.load_bytes) before anything changes. On any problem this
    raises ControllerError on the file field and the current configuration is
    untouched.
    """
    raw = read_upload(uploaded_file, LOAD_FIELD)
    name = getattr(uploaded_file, "name", None) or "the uploaded file"
    session = get_session(request)
    try:
        session.load_bytes(raw, name)
        session.remember_config(name)
    except ConfigError as error:
        raise ControllerError(_load_problems(error)) from error
    except Exception as error:
        raise ControllerError(
            [
                FieldError(
                    LOAD_FIELD,
                    f"'{name}' could not be loaded as a configuration. {KEPT}",
                )
            ]
        ) from error
    return name


def _load_problems(error: ConfigError) -> list[FieldError]:
    items = [FieldError(LOAD_FIELD, f"{error} {KEPT}")]
    cause = error.__cause__
    if isinstance(cause, ValidationError):
        items += [
            FieldError(LOAD_FIELD, text)
            for text in describe_problems(cause, MAX_PROBLEMS)
        ]
    return items


# ---------------------------------------------------------------------- #
#  Save (Section 9)
# ---------------------------------------------------------------------- #
def _download_name(name: str | None) -> str:
    """A safe download file name: no path or quote characters, ends in .json."""
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", (name or "").strip()) or DEFAULT_FILENAME
    return cleaned if cleaned.lower().endswith(".json") else f"{cleaned}.json"


def _chosen_name(session, filename: str | None) -> str:
    """The name the user typed (checked for length), else the configuration's own name."""
    typed = (filename or "").strip()
    if len(typed) > MAX_FILENAME_LENGTH:
        raise ControllerError(
            f"That file name is too long. Use at most {MAX_FILENAME_LENGTH} characters."
        )
    return _download_name(typed or getattr(session, "config_name", None))


def _require_valid(session) -> None:
    """Raise unless a configuration is open and passes the library's validation."""
    require_config(session, "saving it")
    error = revalidate(session)
    if error is not None:
        raise ControllerError(
            [FieldError(None, "Not saved: the configuration is not valid.")]
            + [
                FieldError(None, text)
                for text in describe_problems(error, MAX_PROBLEMS)
            ]
        )


def export_name(request, filename: str | None = None) -> str:
    """The file name a save would offer, after the same checks as saving.

    Changes nothing: the AI chat uses it to show the file name box before the
    user clicks Save JSON, which then goes through save_configuration.
    """
    session = get_session(request)
    _require_valid(session)
    return _chosen_name(session, filename)


def save_configuration(request, filename: str | None = None) -> tuple[str, str]:
    """Validate the configuration, then return (file name, JSON text).

    `filename` is what the user typed in the file name box (blank = the name
    the configuration was loaded from or last saved as). The text comes from
    the library's own Pydantic serialization. The view sends it as a download,
    so the browser decides where it goes and what happens to an existing file
    -- the app never writes or overwrites anything on disk (Section 9). The
    unsaved-changes flag is cleared once the text is handed over.
    """
    session = get_session(request)
    _require_valid(session)
    name = _chosen_name(session, filename)
    content = session.dumps()
    session.mark_saved(name)
    session.remember_config(name, content)
    return name, content


def saved_config_choices(request) -> list[tuple[str, str]]:
    """Return the saved configurations available to the current browser."""
    session = get_session(request)
    return [(name, name) for name in session.saved_config_names()]


def select_saved_configuration(request, name: str) -> str:
    """Make a saved configuration active for subsequent scheduler runs."""
    session = get_session(request)
    try:
        session.select_saved_config(name)
    except ConfigError as error:
        raise ControllerError(str(error)) from error
    return session.config_name or name


# ---------------------------------------------------------------------- #
#  Validate (Section 10)
# ---------------------------------------------------------------------- #
def validate_configuration(request) -> list[str]:
    """Re-validate the complete configuration.

    Returns [] when it is valid, otherwise plain-language problems that name
    where each one is. Raises ControllerError when nothing is loaded.
    """
    session = get_session(request)
    require_config(session, "validating it")
    error = revalidate(session)
    if error is None:
        return []
    return describe_problems(error, MAX_PROBLEMS) or ["The configuration is not valid."]
