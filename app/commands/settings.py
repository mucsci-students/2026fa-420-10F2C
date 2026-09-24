"""Commands for scheduler-wide settings."""

from scheduler.config import OptimizerFlags

from app.crud import ValidationFailure

from .common import VALID_OPTIMIZER_FLAGS, apply_session_edit


def set_generation_limit(session, value):
    """Set the maximum number of schedules to generate."""
    config = session.require_config()
    if value <= 0:
        print("Error: generation limit needs to be positive.")
        return

    def mutate(draft):
        draft.limit = value

    try:
        apply_session_edit(session, config, "global_settings", mutate)
        print(f"Generation limit set to {value}.")
    except ValidationFailure as error:
        print(f"Could not set limit: {error}")


def reset_generation_limit(session):
    """Restore the default schedule-generation limit."""
    config = session.require_config()

    def mutate(draft):
        draft.limit = 10

    try:
        apply_session_edit(session, config, "global_settings", mutate)
        print("Generation limit reset to default (10).")
    except ValidationFailure as error:
        print(f"Could not reset limit: {error}")


def enable_optimizer_flag(session, flag):
    """Enable a supported optimizer flag."""
    config = session.require_config()
    if flag not in VALID_OPTIMIZER_FLAGS:
        print(f"Error: '{flag}' is not a valid optimizer flag.")
        return
    if flag in config.optimizer_flags:
        print(f"'{flag}' is already enabled.")
        return

    def mutate(draft):
        draft.optimizer_flags.append(OptimizerFlags(flag))

    try:
        apply_session_edit(session, config, "global_settings", mutate)
        print(f"Optimizer flag '{flag}' added.")
    except ValidationFailure as error:
        print(f"Could not add flag: {error}")


def disable_optimizer_flag(session, flag):
    """Disable a supported optimizer flag."""
    config = session.require_config()
    if flag not in config.optimizer_flags:
        print(f"'{flag}' is not currently enabled.")
        return

    def mutate(draft):
        draft.optimizer_flags.remove(flag)

    try:
        apply_session_edit(session, config, "global_settings", mutate)
        print(f"Optimizer flag '{flag}' removed.")
    except ValidationFailure as error:
        print(f"Could not remove flag: {error}")