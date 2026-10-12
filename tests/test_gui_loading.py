import pytest
from app.session import Session
from gui.controllers import schedule_controller as ctrl
from gui.controllers.errors import ControllerError


@pytest.fixture
def session(monkeypatch):
    fresh = Session()
    monkeypatch.setattr(ctrl, "get_session", lambda request: fresh)
    return fresh


def test_flag_is_set_during_generation_and_cleared_after(session):
    with ctrl.generation_in_progress(None):
        assert ctrl.is_generating(None) is True
    assert ctrl.is_generating(None) is False


def test_overlapping_generation_is_refused(session):
    with ctrl.generation_in_progress(None):
        with pytest.raises(ControllerError) as info:
            with ctrl.generation_in_progress(None):
                pass
    assert info.value.message == ctrl.BUSY_MESSAGE


def test_flag_is_cleared_when_generation_crashes(session):
    with pytest.raises(RuntimeError):
        with ctrl.generation_in_progress(None):
            raise RuntimeError("solver crashed")
    assert ctrl.is_generating(None) is False