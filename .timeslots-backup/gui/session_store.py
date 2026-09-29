"""
Option B session storage.

Django's own session framework (SESSION_ENGINE = signed_cookies, see
config/settings.py) gives every browser a stable, unguessable session key
with no database behind it. The actual mutable state -- one
app.session.Session per browser, holding its CombinedConfig and any
generated schedules -- lives in this plain in-process dict, keyed by that
session key. This is the same Session class main.py's CLI already uses
unmodified, so a Django view and the CLI shell can both drive the exact
same object shape.

Tradeoff, accepted deliberately: state is lost on server restart and isn't
shared across multiple worker processes. Section 25 rules out database
persistence and multi-user requirements, and this project runs as a single
dev-server process, so that tradeoff costs nothing here.
"""

from __future__ import annotations

from app.session import Session

_SESSIONS: dict[str, Session] = {}


def get_session(request) -> Session:
    """Return this browser's Session, creating one on first use."""
    if not request.session.session_key:
        request.session.save()  # forces Django to allocate a session_key
    key = request.session.session_key
    if key not in _SESSIONS:
        _SESSIONS[key] = Session()
    return _SESSIONS[key]
