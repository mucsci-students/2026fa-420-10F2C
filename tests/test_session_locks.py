"""Tests for the lock hooks in app/session.py.

Locks belong to the Session. Starting a New configuration and restoring the
previous one both clear them. Like tests/test_session.py, these replace the
scheduler library's types with small fakes.
"""

import pytest

import app.session as session_module
from app.locks import LockSet
from app.schedule_io import Assignment
from app.session import Session
from tests.fakes import FakeConfig


class FakeValidationError(Exception):
    """Stand-in for scheduler.config.ValidationError."""


class FakeCombinedConfig(FakeConfig):
    """Stand-in for scheduler.config.CombinedConfig."""

    def __init__(self, **kwargs):
        """Initialize the test double with the supplied values."""
        super().__init__()
        self.__dict__.update(kwargs)


@pytest.fixture(autouse=True)
def patch_library_types(monkeypatch):
    """Replace scheduler-library types with controlled test doubles."""
    monkeypatch.setattr(session_module, "CombinedConfig", FakeCombinedConfig)
    monkeypatch.setattr(session_module, "ValidationError", FakeValidationError)


def a_lock_target():
    """Any placement will do for these tests."""
    return Assignment("CMSC 140.01", "Hogg", "Roddy 140", None, ())


def test_a_new_session_has_no_locks():
    """Every session starts with an empty LockSet."""
    session = Session()
    assert isinstance(session.locks, LockSet)
    assert len(session.locks) == 0


def test_each_session_has_its_own_locks():
    """Locks are per session, never shared between browsers."""
    one, other = Session(), Session()
    one.locks.lock(a_lock_target())
    assert len(other.locks) == 0


def test_new_config_clears_the_locks():
    """Starting a new configuration drops every lock."""
    session = Session()
    session.new_config()
    session.locks.lock(a_lock_target())

    session.new_config()

    assert len(session.locks) == 0


def test_restore_previous_clears_the_locks():
    """Restoring the previous configuration also drops every lock."""
    session = Session()
    session.new_config()
    session.new_config()  # the first one is now the "previous" configuration
    session.locks.lock(a_lock_target())

    session.restore_previous()

    assert len(session.locks) == 0


def test_locking_does_not_touch_the_unsaved_changes_flag():
    """Locks are not configuration: they never mark it as changed."""
    session = Session()
    session.new_config()
    history_version = session.history.version

    session.locks.lock(a_lock_target())
    session.locks.unlock("CMSC 140.01")

    assert session.dirty is False
    assert session.history.version == history_version
