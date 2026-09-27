"""
Controller for Schedule Generator + Schedule Viewer actions (Sections 13-18).

Should call app.schedule_ops (generate_schedules, export_schedule) and
store results on the session via gui.session_store.get_session(request),
mirroring how app/commands/schedules.py already drives the same
schedule_ops functions for the CLI.
"""

from gui.session_store import get_session


def generate(request, limit_override=None, optimizer_overrides=None):
    """TODO (Section 13-14): call app.schedule_ops.generate_schedules()
    with the session's valid config, applying limit_override/optimizer_overrides
    for THIS RUN ONLY -- must not mutate the saved config's own settings.
    Must distinguish success / no-feasible-schedule / invalid-config /
    invalid-override / runtime-error outcomes for the view to display."""
    raise NotImplementedError


def clear_schedules(request):
    """TODO (Section 15): clear session.schedules."""
    raise NotImplementedError


def view_schedule(request, index):
    """TODO (Section 15-16): return one schedule's data in a shape the
    room-oriented and faculty-oriented templates can render as tables."""
    raise NotImplementedError


def load_schedule_json(request, uploaded_file):
    """TODO (Section 17): parse + validate uploaded schedule JSON; on
    failure, leave session.schedules untouched."""
    raise NotImplementedError


def export_schedule_json(request, index=None):
    """TODO (Section 18): export one schedule (index given) or the full
    set (index=None) as JSON via app.schedule_ops.export_schedule()."""
    raise NotImplementedError


def export_schedule_csv(request, index=None):
    """TODO (Section 18): same as export_schedule_json but fmt='csv'
    (Sprint 1 CSV export must remain available)."""
    raise NotImplementedError
