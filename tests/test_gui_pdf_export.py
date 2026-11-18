"""
Tests for exporting one schedule as a PDF: empty selections and failures
(Sprint 4 Section 5.4, issue #169; user stories 5 and 6).

Covers gui/controllers/pdf_export.export_pdf. A fake renderer stands in for
the real one (#165), so these tests check what is exported, the messages for
every way an export can fail, and that nothing in the session changes. They
need no PDF library.
"""

import copy
from typing import cast

import pytest

from app.schedule_export import ScheduleExport
from app.schedule_io import Assignment, MeetingTime
from app.session import Session
from gui.controllers import pdf_export
from gui.controllers import schedule_controller as ctrl
from gui.controllers.errors import ControllerError

FAKE_PDF = b"%PDF-1.7\n% fake renderer output\n%%EOF\n"


def schedule(faculty="Hardy"):
    """Hardy (or `faculty`) teaches CMSC 140.01 in a room; Hogg teaches a
    section with a lecture room and a lab."""
    return [
        Assignment(
            "CMSC 140.01",
            faculty,
            "Roddy 147",
            None,
            (
                MeetingTime("MON", "09:00", "10:50", 110),
                MeetingTime("WED", "09:00", "10:50", 110),
            ),
        ),
        Assignment(
            "CMSC 380.01",
            "Hogg",
            "Roddy 140",
            "Linux",
            (
                MeetingTime("TUE", "10:00", "11:50", 110),
                MeetingTime("THU", "10:00", "11:50", 110, lab=True),
            ),
        ),
    ]


class FakeRenderer:
    """Records what it was asked to draw and returns `result` (or raises it)."""

    def __init__(self, result: object = FAKE_PDF):
        self.result = result
        self.calls: list[tuple[ScheduleExport, str]] = []

    def __call__(self, export: ScheduleExport, title: str) -> bytes:
        self.calls.append((export, title))
        if isinstance(self.result, BaseException):
            raise self.result
        return cast(bytes, self.result)

    @property
    def export(self) -> ScheduleExport:
        return self.calls[-1][0]


@pytest.fixture
def session(monkeypatch):
    fresh = Session()
    monkeypatch.setattr(ctrl, "get_session", lambda request: fresh)
    return fresh


@pytest.fixture
def three_schedules(session):
    session.schedules = [schedule("Hardy"), schedule("Yang"), schedule("Xie")]
    return session


# ---------------------------------------------------------------------- #
#  A successful export
# ---------------------------------------------------------------------- #
class TestExport:
    def test_exports_the_chosen_schedule_by_faculty(self, three_schedules):
        render = FakeRenderer()
        pdf = pdf_export.export_pdf(None, 1, "faculty", None, render)

        assert pdf.content == FAKE_PDF
        assert pdf.content_type == "application/pdf"
        assert pdf.filename == "schedule-2-all-faculty.pdf"
        assert pdf.title == "Schedule 2 of 3"
        export, title = render.calls[0]
        assert title == "Schedule 2 of 3"
        assert [section.title for section in export.sections] == ["Hogg", "Yang"]

    def test_exports_every_room_and_lab(self, three_schedules):
        render = FakeRenderer()
        pdf = pdf_export.export_pdf(None, 0, "rooms", None, render)

        assert pdf.filename == "schedule-1-all-rooms-and-labs.pdf"
        assert [s.title for s in render.export.sections] == [
            "Linux",
            "Roddy 140",
            "Roddy 147",
        ]

    def test_exports_one_faculty_member(self, three_schedules):
        render = FakeRenderer()
        pdf = pdf_export.export_pdf(None, 0, "faculty", ("faculty", "Hogg"), render)

        assert pdf.filename == "schedule-1-faculty-hogg.pdf"
        (section,) = render.export.sections
        assert section.title == "Hogg"
        assert section.courses == ["CMSC 380.01"]

    def test_a_room_and_a_lab_get_different_file_names(self, session):
        session.schedules = [
            [
                Assignment(
                    "CMSC 1.01",
                    "A",
                    "Studio",
                    "Studio",
                    (
                        MeetingTime("MON", "09:00", "09:50", 50),
                        MeetingTime("TUE", "09:00", "09:50", 50, lab=True),
                    ),
                )
            ]
        ]
        room = pdf_export.export_pdf(
            None, 0, "rooms", ("room", "Studio"), FakeRenderer()
        )
        lab = pdf_export.export_pdf(None, 0, "rooms", ("lab", "Studio"), FakeRenderer())
        assert room.filename == "schedule-1-room-studio.pdf"
        assert lab.filename == "schedule-1-lab-studio.pdf"

    def test_names_are_made_safe_for_a_file_name(self):
        assert pdf_export._slug("Roddy 147 / Lab B") == "roddy-147-lab-b"
        assert pdf_export._slug("***") == "export"

    def test_bytearray_from_the_renderer_is_returned_as_bytes(self, three_schedules):
        render = FakeRenderer(bytearray(FAKE_PDF))
        pdf = pdf_export.export_pdf(None, 0, "faculty", None, render)
        assert type(pdf.content) is bytes
        assert pdf.content == FAKE_PDF


# ---------------------------------------------------------------------- #
#  Nothing to export (user story 5)
# ---------------------------------------------------------------------- #
class TestNothingToExport:
    def test_no_schedules_is_a_clear_message_and_nothing_is_drawn(self, session):
        render = FakeRenderer()
        with pytest.raises(ControllerError) as raised:
            pdf_export.export_pdf(None, 0, "faculty", None, render)
        assert raised.value.message == ctrl.NO_SCHEDULES_MESSAGE
        assert render.calls == []

    def test_a_schedule_number_that_does_not_exist(self, three_schedules):
        render = FakeRenderer()
        with pytest.raises(ControllerError) as raised:
            pdf_export.export_pdf(None, 4, "faculty", None, render)
        assert "Schedule 5 doesn't exist" in raised.value.message
        assert render.calls == []

    def test_a_faculty_member_with_no_meetings(self, three_schedules):
        render = FakeRenderer()
        with pytest.raises(ControllerError) as raised:
            pdf_export.export_pdf(None, 0, "faculty", ("faculty", "Rogers"), render)
        assert "no faculty member named 'Rogers'" in raised.value.message
        assert "Nothing was exported" in raised.value.message
        assert render.calls == []

    def test_a_room_that_is_not_in_the_schedule(self, three_schedules):
        render = FakeRenderer()
        with pytest.raises(ControllerError) as raised:
            pdf_export.export_pdf(None, 0, "rooms", ("room", "Roddy 999"), render)
        assert "Roddy 999" in raised.value.message
        assert render.calls == []

    def test_an_unknown_orientation(self, three_schedules):
        render = FakeRenderer()
        with pytest.raises(ControllerError) as raised:
            pdf_export.export_pdf(None, 0, "courses", None, render)
        assert "Unknown export orientation" in raised.value.message
        assert render.calls == []

    def test_a_schedule_with_no_sections_is_a_labelled_empty_pdf(self, session):
        session.schedules = [[]]
        render = FakeRenderer()
        pdf = pdf_export.export_pdf(None, 0, "faculty", None, render)

        assert pdf.content == FAKE_PDF
        assert render.export.is_empty
        assert render.export.empty_label != ""


# ---------------------------------------------------------------------- #
#  The export fails (user story 5)
# ---------------------------------------------------------------------- #
class TestRendererFails:
    def test_an_error_while_drawing_is_a_clear_message(self, three_schedules):
        render = FakeRenderer(RuntimeError("font not found"))
        with pytest.raises(ControllerError) as raised:
            pdf_export.export_pdf(None, 0, "faculty", None, render)
        assert raised.value.message == pdf_export.PDF_FAILED_MESSAGE
        assert "font not found" not in raised.value.message  # no raw error text

    @pytest.mark.parametrize(
        "result",
        [b"", b"<html>not a pdf</html>", "%PDF-1.7 but a str", None],
        ids=["empty", "not-pdf-bytes", "str", "none"],
    )
    def test_output_that_is_not_a_pdf_is_a_failure(self, three_schedules, result):
        with pytest.raises(ControllerError) as raised:
            pdf_export.export_pdf(None, 0, "faculty", None, FakeRenderer(result))
        assert raised.value.message == pdf_export.PDF_FAILED_MESSAGE


# ---------------------------------------------------------------------- #
#  Exporting changes nothing (user story 6)
# ---------------------------------------------------------------------- #
def snapshot(session: Session):
    return (
        copy.deepcopy(session.schedules),
        session.config,
        session.config_name,
        session.dirty,
        session.schedules_version,
    )


class TestExportChangesNothing:
    def test_a_successful_export(self, three_schedules):
        before = snapshot(three_schedules)
        schedules = three_schedules.schedules
        pdf_export.export_pdf(None, 1, "rooms", None, FakeRenderer())
        assert snapshot(three_schedules) == before
        assert three_schedules.schedules is schedules

    @pytest.mark.parametrize(
        ("orientation", "selected", "result"),
        [
            ("faculty", None, RuntimeError("boom")),
            ("faculty", None, b"not a pdf"),
            ("faculty", ("faculty", "Rogers"), FAKE_PDF),
            ("courses", None, FAKE_PDF),
        ],
        ids=["renderer-raises", "not-a-pdf", "unknown-faculty", "bad-orientation"],
    )
    def test_a_failed_export(self, three_schedules, orientation, selected, result):
        before = snapshot(three_schedules)
        with pytest.raises(ControllerError):
            pdf_export.export_pdf(None, 1, orientation, selected, FakeRenderer(result))
        assert snapshot(three_schedules) == before
