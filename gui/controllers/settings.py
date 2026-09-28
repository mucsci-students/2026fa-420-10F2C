"""
Controller for Global Settings (Section 7, Global settings row):
generation limit and optimizer flags. These are the SAVED configuration
values -- distinct from the Schedule Generator's one-run-only overrides,
which live in gui/controllers/schedule_controller.py (Section 14).
"""

from gui.session_store import get_session


def set_generation_limit(request, value):
    """TODO: validate value is a positive integer and apply_edit() it
    onto config.limit."""
    raise NotImplementedError


def enable_optimizer_flag(request, flag):
    """TODO: validate flag is a supported OptimizerFlags value and
    apply_edit() it onto config.optimizer_flags."""
    raise NotImplementedError


def disable_optimizer_flag(request, flag):
    """TODO: remove flag from config.optimizer_flags via apply_edit()."""
    raise NotImplementedError
