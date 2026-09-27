"""
Controller for Configuration Editor lifecycle actions (Sections 8-10).

Each function should: get this browser's Session via
gui.session_store.get_session(request), call the matching function in
app/commands/configuration.py (do NOT reimplement validation here --
Section 3 forbids alternative configuration representations), and return
a plain result gui/views.py can pass to a template. Never touch
HttpResponse or templates directly from here -- that's the View's job.
"""

from gui.session_store import get_session


def new_configuration(request):
    """TODO (Section 8): start a fresh configuration.
    Should call something equivalent to app.commands.configuration.new_config()
    against get_session(request)."""
    raise NotImplementedError


def load_configuration(request, uploaded_file):
    """TODO (Section 8): parse + validate an uploaded JSON config file.
    On any failure (bad JSON, unreadable file, schema validation failure),
    the previous valid in-memory config must be left untouched -- mirror
    app.session.Session.load()'s "only swap state in on success" behavior."""
    raise NotImplementedError


def save_configuration(request):
    """TODO (Section 9): validate + serialize the current config via
    CombinedConfig's own Pydantic serialization, and return it in a form
    views.py can offer as a file download. Must guard against silently
    overwriting an existing file (Section 9's overwrite-protection requirement)."""
    raise NotImplementedError


def validate_configuration(request):
    """TODO (Section 10): re-run full CombinedConfig validation on the
    current session config and report pass/fail with a plain-language
    explanation (no raw tracebacks) that names the affected area when possible."""
    raise NotImplementedError
