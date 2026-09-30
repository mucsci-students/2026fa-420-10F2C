"""
Tests for the shared GUI helpers other features build on:

    gui/controllers/uploads.read_upload            (any file upload)
    gui/controllers/schedule_controller            get_schedule / get_schedules /
                                                   replace_schedules / schedule_count
    gui/forms.ConfirmReplaceMixin                  (confirm before replacing data)
    gui/views.download_response                    (config save, schedule export)

Sprint 2 Sections 8, 9, 15, 17, 18, 23.6.
"""

import io
import json

import pytest
from django import forms

from app.schedule_io import Assignment, MeetingTime
from app.session import Session
from gui.controllers import schedule_controller as ctrl
from gui.controllers.errors import ControllerError
from gui.controllers.uploads import read_upload
from gui.forms import ConfirmReplaceMixin
from gui.views import download_response


def record(faculty):
    return Assignment("CMSC 140.01", faculty, "Roddy 136", None, (MeetingTime("MON", "09:00", "09:50", 50),))


# ---------------------------------------------------------------------- #
#  read_upload
# ---------------------------------------------------------------------- #
class TestReadUpload:
    def test_returns_the_bytes(self):
        assert read_upload(io.BytesIO(b'{"a": 1}'), "config_file") == b'{"a": 1}'

    @pytest.mark.parametrize(
        "uploaded, fragment",
        [(None, "Choose a file"), (io.BytesIO(b""), "empty"), (io.BytesIO(b"  \n"), "empty")],
    )
    def test_problems_are_attached_to_the_given_field(self, uploaded, fragment):
        with pytest.raises(ControllerError) as info:
            read_upload(uploaded, "config_file")
        assert info.value.errors[0].field == "config_file"
        assert fragment in info.value.message

    def test_unreadable_file(self):
        class Broken:
            def read(self):
                raise OSError("permission denied")

        with pytest.raises(ControllerError) as info:
            read_upload(Broken(), "f")
        assert "could not be read" in info.value.message

    def test_too_large_by_reported_size_is_rejected_without_reading(self):
        class Huge:
            size = 50 * 1024 * 1024

            def read(self):
                raise AssertionError("should not read a file that is already known to be too large")

        with pytest.raises(ControllerError) as info:
            read_upload(Huge(), "f")
        assert "too large" in info.value.message

    def test_too_large_by_content(self):
        with pytest.raises(ControllerError) as info:
            read_upload(io.BytesIO(b"x" * 20), "f", max_bytes=10)
        assert "too large" in info.value.message


# ---------------------------------------------------------------------- #
#  Schedule helpers
# ---------------------------------------------------------------------- #
@pytest.fixture
def session(monkeypatch):
    fresh = Session()
    monkeypatch.setattr(ctrl, "get_session", lambda request: fresh)
    return fresh


class TestScheduleHelpers:
    def test_count(self, session):
        assert ctrl.schedule_count(None) == 0
        session.schedules = [[record("A")], [record("B")]]
        assert ctrl.schedule_count(None) == 2

    def test_get_schedule_and_get_schedules(self, session):
        session.schedules = [[record("A")], [record("B")]]
        assert ctrl.get_schedule(None, 1) == [record("B")]
        assert ctrl.get_schedules(None) == [[record("A")], [record("B")]]

    def test_generated_schedules_are_returned_as_the_same_records(self, session):
        class FakeCourseInstance:  # what the generator stores: the library's objects
            def as_json(self):
                return {"course": "CMSC 140.01", "faculty": "A", "room": "Roddy 136", "lab": None,
                        "times": [{"day": "MON", "start": "09:00", "duration": 50}]}

        session.schedules = [[FakeCourseInstance()]]
        assert ctrl.get_schedule(None, 0) == [record("A")]

    @pytest.mark.parametrize("call", [lambda: ctrl.get_schedules(None), lambda: ctrl.get_schedule(None, 0)])
    def test_no_schedules(self, session, call):
        with pytest.raises(ControllerError) as info:
            call()
        assert "no schedules yet" in info.value.message

    @pytest.mark.parametrize("index", [-1, 2, 99])
    def test_index_out_of_range(self, session, index):
        session.schedules = [[record("A")], [record("B")]]
        with pytest.raises(ControllerError) as info:
            ctrl.get_schedule(None, index)
        assert "There are 2 schedule(s)." in info.value.message

    def test_unreadable_stored_schedule_is_a_controller_error(self, session):
        session.schedules = [[{"course": ""}]]
        with pytest.raises(ControllerError) as info:
            ctrl.get_schedule(None, 0)
        assert info.value.message.startswith("Schedule 1 could not be read")

    def test_replace_schedules(self, session):
        session.schedules = [[record("Old")]]
        ctrl.replace_schedules(None, [[record("A")], [record("B")]])
        assert ctrl.schedule_count(None) == 2
        ctrl.replace_schedules(None, [])
        assert session.schedules == []

    def test_replace_schedules_does_not_touch_the_configuration(self, session):
        ctrl.replace_schedules(None, [[record("A")]])
        assert session.config is None and session.dirty is False


# ---------------------------------------------------------------------- #
#  ConfirmReplaceMixin
# ---------------------------------------------------------------------- #
class ExampleForm(ConfirmReplaceMixin, forms.Form):
    name = forms.CharField()

    def __init__(self, *args, needed=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.require_confirmation(needed, label="Discard my changes", error="Tick to confirm.")


class TestConfirmReplaceMixin:
    def test_no_checkbox_when_nothing_would_be_replaced(self):
        form = ExampleForm({"name": "x"})
        assert "confirm_replace" not in form.fields
        assert form.is_valid()

    def test_checkbox_is_required_when_something_would_be_replaced(self):
        form = ExampleForm({"name": "x"}, needed=True)
        assert form.fields["confirm_replace"].label == "Discard my changes"
        assert not form.is_valid()
        assert form.errors["confirm_replace"] == ["Tick to confirm."]

    def test_ticked_checkbox_passes(self):
        assert ExampleForm({"name": "x", "confirm_replace": "on"}, needed=True).is_valid()


# ---------------------------------------------------------------------- #
#  download_response
# ---------------------------------------------------------------------- #
def test_download_response_sends_an_attachment():
    response = download_response("schedules-all-2.json", json.dumps({"ok": "é"}), "application/json; charset=utf-8")
    assert response["Content-Disposition"] == 'attachment; filename="schedules-all-2.json"'
    assert response["Content-Type"] == "application/json; charset=utf-8"
    assert json.loads(response.content.decode("utf-8")) == {"ok": "é"}


def test_download_response_accepts_bytes():
    assert download_response("a.csv", b"x,y\n", "text/csv; charset=utf-8").content == b"x,y\n"
