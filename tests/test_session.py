"""
Unit tests for app/session.py's Session class: the new/load/save
lifecycle (Req #4) and the dirty flag that drives shell.py's
unsaved-changes warning.

These tests isolate Session's OWN control flow -- does state only swap
in on success, is the prior valid config left completely untouched on
any kind of failure (missing file, bad JSON, invalid schema), does
dirty get reset at the right points -- from whether the real library's
seed data / a loaded file actually validates. That's a separate,
already-confirmed concern (app/examples/config_example.json has been
verified directly against the real CombinedConfig.model_validate()).
Here, scheduler.config's CombinedConfig/ValidationError and
scheduler.load_config_from_file are replaced with simple fakes the
tests fully control, so a failure can be simulated on demand without
needing to know the real schema's exact rejection rules.
"""
import pytest

import app.session as session_module
from app.session import ConfigError, Session


class FakeValidationError(Exception):
    """Stand-in for scheduler.config.ValidationError."""


class FakeCombinedConfig:
    """Stand-in for scheduler.config.CombinedConfig."""

    def __init__(self, **kwargs):
        """Initialize the test double with the supplied values."""
        self.__dict__.update(kwargs)

    def model_dump_json(self, indent=2):
        """Serialize the fake configuration for save tests."""
        # Just needs to return *something* writable -- save()'s job is
        # to get bytes onto disk and manage config_path/dirty, not to
        # produce a byte-perfect JSON document (that's the real
        # library's serialization, already exercised elsewhere).
        return "{}"


@pytest.fixture(autouse=True)
def patch_library_types(monkeypatch):
    """Replace scheduler-library types with controlled test doubles."""
    monkeypatch.setattr(session_module, "CombinedConfig", FakeCombinedConfig)
    monkeypatch.setattr(session_module, "ValidationError", FakeValidationError)


def fake_loader_success(cls, path):
    """Return a valid fake configuration for a successful load."""
    return cls(name=f"loaded-from-{path}")


def fake_loader_invalid_schema(cls, path):
    """Simulate schema validation failure while loading."""
    raise FakeValidationError(f"'{path}' failed schema validation")


def fake_loader_bad_json(cls, path):
    """Simulate malformed JSON while loading."""
    raise ValueError(f"'{path}' is not valid JSON")


# ---------- new_config ----------

def test_new_config_sets_a_config_and_resets_state():
    """Verify that new config sets a config and resets state."""
    session = Session()
    session.schedules = ["stale"]
    session.dirty = True

    session.new_config()

    assert session.config is not None
    assert session.config_path is None
    assert session.schedules == []
    assert session.dirty is False


def test_new_config_raises_config_error_on_validation_failure(monkeypatch):
    """Verify that new config raises config error on validation failure."""
    def bad_constructor(**kwargs):
        """Simulate validation failure during configuration creation."""
        raise FakeValidationError("seed data rejected")
    monkeypatch.setattr(session_module, "CombinedConfig", bad_constructor)

    session = Session()
    with pytest.raises(ConfigError):
        session.new_config()


# ---------- load ----------

def test_load_missing_file_raises_and_leaves_prior_config_untouched(tmp_path):
    """Verify that load missing file raises and leaves prior config untouched."""
    session = Session()
    session.new_config()
    original_config = session.config

    with pytest.raises(ConfigError):
        session.load(str(tmp_path / "does_not_exist.json"))

    assert session.config is original_config  # untouched, same object


def test_load_invalid_schema_raises_and_leaves_prior_config_untouched(monkeypatch, tmp_path):
    """Verify that load invalid schema raises and leaves prior config untouched."""
    session = Session()
    session.new_config()
    original_config = session.config

    fake_file = tmp_path / "bad.json"
    fake_file.write_text("{}")
    monkeypatch.setattr(session_module, "load_config_from_file", fake_loader_invalid_schema)

    with pytest.raises(ConfigError):
        session.load(str(fake_file))

    assert session.config is original_config


def test_load_bad_json_raises_and_leaves_prior_config_untouched(monkeypatch, tmp_path):
    """Verify that load bad json raises and leaves prior config untouched."""
    session = Session()
    session.new_config()
    original_config = session.config

    fake_file = tmp_path / "malformed.json"
    fake_file.write_text("not json")
    monkeypatch.setattr(session_module, "load_config_from_file", fake_loader_bad_json)

    with pytest.raises(ConfigError):
        session.load(str(fake_file))

    assert session.config is original_config


def test_load_success_swaps_in_new_config_and_resets_dirty(monkeypatch, tmp_path):
    """Verify that load success swaps in new config and resets dirty."""
    session = Session()
    session.new_config()
    session.dirty = True
    session.schedules = ["stale"]

    fake_file = tmp_path / "good.json"
    fake_file.write_text("{}")
    monkeypatch.setattr(session_module, "load_config_from_file", fake_loader_success)

    session.load(str(fake_file))

    assert session.config.name == f"loaded-from-{fake_file}"
    assert session.config_path == fake_file
    assert session.dirty is False
    assert session.schedules == []


# ---------- save ----------

def test_save_with_no_config_raises_config_error():
    """Verify that save with no config raises config error."""
    session = Session()
    with pytest.raises(ConfigError):
        session.save("somewhere.json")


def test_save_with_no_path_and_no_prior_path_raises_config_error():
    """Verify that save with no path and no prior path raises config error."""
    session = Session()
    session.new_config()  # config_path stays None until a load/save
    with pytest.raises(ConfigError):
        session.save()


def test_save_writes_file_and_resets_dirty(tmp_path):
    """Verify that save writes file and resets dirty."""
    session = Session()
    session.new_config()
    session.dirty = True

    target = tmp_path / "out.json"
    result_path = session.save(str(target))

    assert result_path == target
    assert target.exists()
    assert session.dirty is False
    assert session.config_path == target


def test_save_reuses_last_path_when_none_given(tmp_path):
    """Verify that save reuses last path when none given."""
    session = Session()
    session.new_config()
    target = tmp_path / "out.json"
    session.save(str(target))  # first save -- sets config_path

    session.dirty = True  # simulate another edit happening after
    result_path = session.save()  # no path this time -- should reuse target

    assert result_path == target


# ---------- require_config ----------

def test_require_config_raises_when_nothing_loaded():
    """Verify that require config raises when nothing loaded."""
    session = Session()
    with pytest.raises(ConfigError):
        session.require_config()


def test_require_config_returns_config_when_present():
    """Verify that require config returns config when present."""
    session = Session()
    session.new_config()
    assert session.require_config() is session.config
