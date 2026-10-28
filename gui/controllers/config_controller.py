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
from time import monotonic

from scheduler.config import CombinedConfig, ValidationError

from app.commands.configuration import revalidate
from app.session import ConfigError
from gui.controllers.common import require_config
from gui.controllers.errors import ControllerError, FieldError, describe_problems
from gui.controllers.uploads import read_upload
from gui.session_store import get_session

LOAD_FIELD = "config_file"
DEFAULT_FILENAME = "scheduler_config.json"
MAX_PROBLEMS = 8  # how many validation problems to list before "...and N more"
KEPT = "Your current configuration was kept."


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
        "export_name": _download_name(
            getattr(session, "config_name", None)
        ),  # what Save would call the file
        "filename_pattern": FILENAME_PATTERN,
        "max_filename_length": MAX_FILENAME_LENGTH,
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


# What a file name may hold. The same pattern is put on both file name fields (the editor's and the
# chat's) so the browser stops a path before anything is sent; the server checks it again.
FILENAME_PATTERN = r"[^\\\/\x00-\x1f]*"
MAX_FILENAME_LENGTH = 100


def _requested_filename(filename: str | None) -> str | None:
    """The file name the user typed ("fall"), or None for the default.

    A path is refused rather than quietly rewritten: only the browser decides where a download goes."""
    name = (filename or "").strip()
    if not name:
        return None
    if name in (".", "..") or not re.fullmatch(FILENAME_PATTERN, name):
        raise ControllerError(
            "Give a file name, not a path. Your browser decides where a download is saved."
        )
    if len(name) > MAX_FILENAME_LENGTH:
        raise ControllerError(
            f"That file name is too long. Use at most {MAX_FILENAME_LENGTH} characters."
        )
    return _download_name(name)


def _validated_session(request):
    """The session, once its configuration is loaded and valid. Nothing is changed."""
    session = get_session(request)
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
    return session


def _export_name(session, filename: str | None) -> str:
    return _requested_filename(filename) or _download_name(
        getattr(session, "config_name", None)
    )


def check_export(request, filename: str | None = None) -> str:
    """The file name an export would use, or a ControllerError saying why it could not happen.

    Changes nothing, so the chat can check a save request before offering its Save JSON button."""
    return _export_name(_validated_session(request), filename)


def save_configuration(request, filename: str | None = None) -> tuple[str, str]:
    """Validate the configuration, then return (file name, JSON text).

    The one export behind the Configuration Editor's Save button and the chat's Save JSON button.
    The text comes from the library's own Pydantic serialization. The view sends it as a standard
    download, so the browser decides where it goes and whether to ask before replacing a file.
    The app cannot see whether the download finished, so the unsaved-changes flag is cleared once
    the text is handed over and the pages say that the download was only started.
    """
    session = _validated_session(request)
    name = _export_name(session, filename)
    content = session.dumps()
    session.mark_saved(name)
    session.remember_config(name, content)
    return name, content


# ---------------------------------------------------------------------- #
#  Starting a new configuration from the chat: warn first, replace only on an explicit click
# ---------------------------------------------------------------------- #
STARTED_NEW = (
    "Started a new configuration. It begins with one placeholder room, course, "
    "faculty member and class pattern; edit or replace them."
)
RESTORE_HINT = (
    "The configuration you had is kept for this session: use Restore previous configuration "
    "in the Configuration Editor to bring it back, with its schedules."
)
NEW_CONFIRM_SECONDS = 600  # a warning stops being confirmable after this long
_PENDING_NEW_ATTR = "pending_new_configuration"
NOTHING_WAITING = "Nothing is waiting for confirmation, so nothing was changed. Ask me to start a new configuration again."


@dataclass(frozen=True)
class PendingReplacement:
    """What the user was warned about; the confirmation only counts while that is still true."""

    token: str
    config: CombinedConfig
    version: int  # the edit-history version of that configuration
    schedule_count: int
    created: float


@dataclass(frozen=True)
class NewConfigurationOutcome:
    started: bool  # True: the new configuration already exists, because nothing would be lost
    token: str | None = None
    dirty: bool = False
    schedule_count: int = 0
    name: str | None = None
    export_name: str = (
        DEFAULT_FILENAME  # what Save JSON would call the current configuration's file
    )


def request_new_configuration(request) -> NewConfigurationOutcome:
    """Start a new configuration now when nothing would be lost; otherwise remember what would be
    lost and return a single-use token. The caller must ask the user before confirming."""
    state = describe_configuration(request)
    if not state["discard_note"]:
        new_configuration(request)
        return NewConfigurationOutcome(started=True)
    session = get_session(request)
    pending = PendingReplacement(
        token=secrets.token_urlsafe(32),
        config=session.config,
        version=session.history.version,
        schedule_count=state["schedule_count"],
        created=monotonic(),
    )
    setattr(
        session, _PENDING_NEW_ATTR, pending
    )  # one at a time: a newer warning replaces an older one
    return NewConfigurationOutcome(
        started=False,
        token=pending.token,
        dirty=state["dirty"],
        schedule_count=state["schedule_count"],
        name=state["name"],
        export_name=state["export_name"],
    )


def _waiting(session, token: str) -> PendingReplacement:
    pending = getattr(session, _PENDING_NEW_ATTR, None)
    if pending is None or not secrets.compare_digest(pending.token, str(token)):
        raise ControllerError(NOTHING_WAITING)
    return pending


def confirm_new_configuration(request, token: str) -> None:
    """Replace the configuration the user was warned about.

    Single use, and refused when the configuration or the number of schedules is no longer what
    the warning described. Saving a download in between does not matter: it changes neither."""
    session = get_session(request)
    pending = _waiting(session, token)
    setattr(session, _PENDING_NEW_ATTR, None)  # used up, whatever happens next
    if monotonic() - pending.created > NEW_CONFIRM_SECONDS:
        raise ControllerError(
            "That warning is too old, so nothing was changed. Ask me to start a new configuration again."
        )
    if (
        session.config is not pending.config
        or session.history.version != pending.version
        or len(session.schedules) != pending.schedule_count
    ):
        raise ControllerError(
            "The configuration or schedules changed after I warned you, so nothing was replaced. "
            "Ask me to start a new configuration again."
        )
    new_configuration(request)


def cancel_new_configuration(request, token: str) -> None:
    """Forget the warning. The configuration and the schedules are not touched."""
    session = get_session(request)
    _waiting(session, token)
    setattr(session, _PENDING_NEW_ATTR, None)


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
