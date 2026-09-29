"""
Option B session storage.

Django's own session framework (SESSION_ENGINE = signed_cookies, see
config/settings.py) needs no database. The actual mutable state -- one
app.session.Session per browser, holding its CombinedConfig and any
generated schedules -- lives in this plain in-process dict. This is the same
Session class main.py's CLI already uses unmodified, so a Django view and the
CLI shell can both drive the exact same object shape.

The dict is keyed by a random id stored INSIDE the Django session
(_SESSION_ID_KEY), not by request.session.session_key. With signed_cookies
the session key is the signed cookie value itself, which is recomputed
(timestamp included) every time the session is saved -- so it is not a stable
identity. A random id in the session data survives re-signing and any other
writes to the session.

Tradeoff, accepted deliberately: state is lost on server restart and isn't
shared across multiple worker processes. Section 25 rules out database
persistence and multi-user requirements, and this project runs as a single
dev-server process, so that tradeoff costs nothing here.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from app.session import ConfigError, Session

# TEMPORARY development convenience: until the Configuration Editor can
# create or load a configuration (gui/controllers/config_controller.py is
# still a stub), start every new browser session with the same example
# dataset the CLI shell auto-loads, so the editing pages have data to work
# with. Set to False (or delete) once New/Load exist. Pages still handle the
# "no configuration loaded" state (Section 19) either way.
AUTO_LOAD_EXAMPLE = True
EXAMPLE_CONFIG_PATH = Path(__file__).resolve().parent.parent / "app" / "examples" / "config_example.json"

_SESSION_ID_KEY = "scheduler_session_id"
_SESSIONS: dict[str, Session] = {}


def _new_session() -> Session:
    session = Session()
    if AUTO_LOAD_EXAMPLE:
        try:
            session.load(str(EXAMPLE_CONFIG_PATH))
        except ConfigError:
            pass  # leave it empty; pages show the "no configuration" state
        else:
            # Never let a later "save" silently overwrite the shipped example.
            session.config_path = None
    return session


def get_session(request) -> Session:
    """Return this browser's Session, creating one on first use."""
    session_id = request.session.get(_SESSION_ID_KEY)
    if session_id is None:
        session_id = uuid.uuid4().hex
        request.session[_SESSION_ID_KEY] = session_id  # sets the cookie on the response
    if session_id not in _SESSIONS:
        _SESSIONS[session_id] = _new_session()
    return _SESSIONS[session_id]
