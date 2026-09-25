"""Configuration lifecycle commands."""

from app.session import ConfigError


def new_config(session):
    """Start a fresh configuration and confirm the action to the user."""
    session.new_config()
    print("Started a new, empty configuration.")


def load_config(session, path):
    """Load and validate a configuration from the supplied path."""
    try:
        session.load(path)
    except ConfigError as error:
        raise error
    print(f"Loaded and validated '{path}'.")


def save_config(session, path=None):
    """Save the active configuration to a path."""
    target = session.save(path)
    print(f"Saved configuration to '{target}'.")


def print_config(session):
    """Print the active configuration as formatted JSON."""
    config = session.require_config()
    print(config.model_dump_json(indent=2))


def validate_config(session):
    """Revalidate the active configuration and report the result."""
    config = session.require_config()
    try:
        type(config).model_validate(config.model_dump())
    except Exception as error:  # noqa: BLE001 -- library validation type is not stable
        print(f"Configuration is INVALID: {error}")
        return
    print("Configuration is valid.")