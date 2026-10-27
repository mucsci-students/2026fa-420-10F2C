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

from typing import Any, cast

import pytest

import app.session as session_module
from app.session import ConfigError, Session
from tests.fakes import FakeConfig


class FakeValidationError(Exception):
    """Stand-in for scheduler.config.ValidationError."""


class FakeCombinedConfig(FakeConfig):
    """Stand-in for scheduler.config.CombinedConfig (it has the same shape, so
    the undo history can save and restore it)."""

    def __init__(self, **kwargs):
        """Initialize the test double with the supplied values."""
        super().__init__()
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


def test_load_invalid_schema_raises_and_leaves_prior_config_untouched(
    monkeypatch, tmp_path
):
    """Verify that load invalid schema raises and leaves prior config untouched."""
    session = Session()
    session.new_config()
    original_config = session.config

    fake_file = tmp_path / "bad.json"
    fake_file.write_text("{}")
    monkeypatch.setattr(
        session_module, "load_config_from_file", fake_loader_invalid_schema
    )

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

    assert cast("Any", session.config).name == f"loaded-from-{fake_file}"
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


# ---------- restoring what New / Load replaced, and stale schedules ----------


def _loaded_session(monkeypatch, tmp_path, name="first.json"):
    monkeypatch.setattr(session_module, "load_config_from_file", fake_loader_success)
    path = tmp_path / name
    path.write_text("{}", encoding="utf-8")
    session = Session()
    session.load(str(path))
    return session, path


def test_nothing_is_kept_until_a_configuration_replaces_another(monkeypatch, tmp_path):
    session, _ = _loaded_session(monkeypatch, tmp_path)
    assert session.previous is None and session.previous_info() is None


def test_new_config_keeps_the_replaced_one_and_restoring_swaps_back(
    monkeypatch, tmp_path
):
    session, _ = _loaded_session(monkeypatch, tmp_path)
    first = session.config
    session.dirty = True
    session.schedules = ["s1"]
    first_history = session.history

    session.new_config()
    second = session.config
    assert second is not first and session.schedules == [] and session.dirty is False
    info = session.previous_info()
    assert (
        info["name"] == "first.json"
        and info["dirty"] is True
        and info["schedule_count"] == 1
    )

    assert session.restore_previous() == "first.json"
    assert session.config is first and session.dirty is True
    assert session.schedules == ["s1"] and session.history is first_history
    assert (
        session.previous_info()["dirty"] is False
    )  # the new one is now the "previous"

    session.restore_previous()  # and it can be reversed
    assert session.config is second


def test_loading_a_file_keeps_the_replaced_configuration_too(monkeypatch, tmp_path):
    session, _ = _loaded_session(monkeypatch, tmp_path)
    first = session.config
    other = tmp_path / "second.json"
    other.write_text("{}", encoding="utf-8")
    session.load(str(other))
    assert session.config is not first
    session.restore_previous()
    assert session.config is first and session.config_name == "first.json"


def test_a_failed_load_keeps_nothing_and_changes_nothing(monkeypatch, tmp_path):
    session, _ = _loaded_session(monkeypatch, tmp_path)
    with pytest.raises(ConfigError):
        session.load(str(tmp_path / "missing.json"))
    assert session.previous is None


def test_restoring_with_nothing_kept_explains():
    session = Session()
    with pytest.raises(ConfigError, match="no previous configuration"):
        session.restore_previous()


def test_the_replaced_configurations_undo_history_comes_back_with_it(
    monkeypatch, tmp_path
):
    session, _ = _loaded_session(monkeypatch, tmp_path)
    session.history.record("an edit", session.history.capture(session.config), False)
    session.new_config()
    assert not session.history.can_undo
    session.restore_previous()
    assert session.history.can_undo and session.history.undo_label == "an edit"


def test_schedules_are_stale_once_the_configuration_changes_and_fresh_again_after_undo(
    monkeypatch, tmp_path
):
    session, _ = _loaded_session(monkeypatch, tmp_path)
    assert session.schedules_stale is False  # no schedules at all
    session.set_schedules(["s"])
    assert session.schedules_stale is False

    session.history.record("an edit", session.history.capture(session.config), False)
    session.dirty = True
    assert session.schedules_stale is True  # configuration moved on

    session.history.undo(session)
    assert session.schedules_stale is False  # same configuration they came from

    session.history.redo(session)
    session.set_schedules(["fresh"])  # generated again from the new state
    assert session.schedules_stale is False


def test_schedules_set_directly_are_never_reported_stale(monkeypatch, tmp_path):
    session, _ = _loaded_session(monkeypatch, tmp_path)
    session.schedules = ["from an import or the CLI"]
    session.history.record("an edit", session.history.capture(session.config), False)
    assert session.schedules_stale is False


def test_schedules_can_be_tied_to_the_version_a_run_started_from(monkeypatch, tmp_path):
    session, _ = _loaded_session(monkeypatch, tmp_path)
    started_from = session.history.version
    session.history.record(
        "edited while generating", session.history.capture(session.config), False
    )
    session.set_schedules(["s"], started_from)
    assert session.schedules_stale is True
