"""
Controller for Global Settings (Section 7, Global settings row): the generation
limit and the optimizer flags. These are the SAVED configuration values --
distinct from the Schedule Generator's one-run-only overrides, which live in
gui/controllers/schedule_controller.py (Section 14).

Both values sit on the CombinedConfig itself (config.limit and
config.optimizer_flags), same as app/commands/settings.py. Every edit goes
through app.crud.apply_edit() via apply_config_edit(), so the complete
configuration is re-validated and a failed edit leaves the previous valid one
untouched (Sections 10 and 11).

What the scheduler library enforces (so we do NOT reimplement it): field types
and whole-configuration rules. What this controller adds because the GUI needs a
clear message first:
  * a positive whole-number limit (user story 28 wording),
  * only flags the library knows (user story 28: "'x' is not a valid optimizer flag"),
  * Reset puts the limit back to the default of 10 (user story 30). A limit
    cannot be deleted, because the configuration always has one.

Deletion behaviour (Section 12): nothing refers to these settings, so there is
nothing to block. "Deleting" a setting means disabling a flag or resetting the
limit, and both are always allowed.

Functions raise ControllerError for anything the user can fix; they never touch
HttpResponse or templates (Section 20). The write functions return the list of
change messages to show the user (empty when nothing changed).

form_data keys for update_settings (plain Python values; the View's form
produces them):
    limit            int
    optimizer_flags  iterable of flag names that should be ON; every other known
                     flag is turned off
"""

from __future__ import annotations

from scheduler.config import OptimizerFlags

from app.commands.common import VALID_OPTIMIZER_FLAGS
from gui.controllers.common import apply_config_edit, require_config
from gui.controllers.errors import ControllerError, FieldError
from gui.session_store import get_session

DEFAULT_LIMIT = 10
SETTINGS_FIELDS = ("limit", "optimizer_flags")

LIMIT_MESSAGE = "Generation limit needs to be positive."


# ---------------------------------------------------------------------- #
#  Helpers
# ---------------------------------------------------------------------- #
def _require_config(session):
    return require_config(session, "editing global settings")


def _name(flag) -> str:
    """A flag's plain name, whether it is an enum member or already a string."""
    return str(getattr(flag, "value", flag))


def known_flags() -> list[str]:
    """Every optimizer flag the scheduler library accepts, in a stable order.

    Asks the library's own enum first so the list can't drift from it; falls
    back to the shell's list if the enum can't be iterated.
    """
    try:
        found = [_name(flag) for flag in OptimizerFlags]
    except TypeError:
        found = []
    return found or sorted(VALID_OPTIMIZER_FLAGS)


def _enabled(config) -> list[str]:
    return [_name(flag) for flag in config.optimizer_flags]


def _check_limit(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ControllerError([FieldError("limit", LIMIT_MESSAGE)])
    return value


def _check_flags(flags) -> list[str]:
    allowed = set(known_flags())
    unknown = [flag for flag in flags if flag not in allowed]
    if unknown:
        raise ControllerError(
            [FieldError("optimizer_flags", f"'{flag}' is not a valid optimizer flag.") for flag in unknown]
        )
    return list(flags)


def _apply(session, config, mutate) -> None:
    apply_config_edit(session, config, "global_settings", mutate, form_fields=SETTINGS_FIELDS)


def _change(request, *, limit=None, enable=(), disable=()) -> list[str]:
    """Apply a limit change and/or flag changes in one atomic edit.

    Returns the messages describing what actually changed, which is empty when
    everything asked for was already the case.
    """
    session = get_session(request)
    config = _require_config(session)
    if limit is not None:
        limit = _check_limit(limit)
    enable = _check_flags(enable)
    disable = _check_flags(disable)

    current = _enabled(config)
    to_enable = [flag for flag in enable if flag not in current]
    to_disable = [flag for flag in disable if flag in current]
    change_limit = limit is not None and limit != config.limit
    if not (change_limit or to_enable or to_disable):
        return []

    def mutate(draft):
        if change_limit:
            draft.limit = limit
        for flag in to_disable:
            for member in [m for m in draft.optimizer_flags if _name(m) == flag]:
                draft.optimizer_flags.remove(member)
        for flag in to_enable:
            draft.optimizer_flags.append(OptimizerFlags(flag))

    _apply(session, config, mutate)

    messages: list[str] = []
    if change_limit:
        messages.append(f"Generation limit set to {limit}.")
    messages += [f"Optimizer flag '{flag}' added." for flag in to_enable]
    messages += [f"Optimizer flag '{flag}' removed." for flag in to_disable]
    return messages


# ---------------------------------------------------------------------- #
#  Reads
# ---------------------------------------------------------------------- #
def describe_settings(request) -> dict:
    """Everything the Global Settings page needs, as plain data (no models).

    Returns {"has_config": False} when nothing is loaded so the view can show
    the empty state (Section 19).
    """
    config = get_session(request).config
    if config is None:
        return {"has_config": False}
    enabled = _enabled(config)
    return {
        "has_config": True,
        "limit": config.limit,
        "default_limit": DEFAULT_LIMIT,
        "is_default_limit": config.limit == DEFAULT_LIMIT,
        "enabled_flags": enabled,
        "flags": [{"name": name, "enabled": name in enabled} for name in known_flags()],
        "flag_choices": known_flags(),
    }


# ---------------------------------------------------------------------- #
#  Writes -- each returns the list of change messages ([] = nothing changed)
# ---------------------------------------------------------------------- #
def update_settings(request, form_data) -> list[str]:
    """Set the limit and make the enabled flags exactly `optimizer_flags`."""
    wanted = _check_flags(list(form_data.get("optimizer_flags") or []))
    config = _require_config(get_session(request))
    current = _enabled(config)
    return _change(
        request,
        limit=form_data.get("limit"),
        enable=[flag for flag in known_flags() if flag in wanted],
        disable=[flag for flag in current if flag not in wanted],
    )


def set_generation_limit(request, value) -> list[str]:
    """Set the saved generation limit (must be a positive whole number)."""
    return _change(request, limit=_check_limit(value))


def reset_generation_limit(request) -> list[str]:
    """Put the generation limit back to the default (10)."""
    changed = _change(request, limit=DEFAULT_LIMIT)
    return [f"Generation limit reset to default ({DEFAULT_LIMIT})."] if changed else []


def enable_optimizer_flag(request, flag) -> list[str]:
    """Turn one optimizer flag on (nothing happens if it already is)."""
    return _change(request, enable=[flag])


def disable_optimizer_flag(request, flag) -> list[str]:
    """Turn one optimizer flag off (nothing happens if it already is)."""
    return _change(request, disable=[flag])
