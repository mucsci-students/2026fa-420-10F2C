"""
Tests for exporting a PDF from the Schedule Viewer (Sprint 4 Sections 5, 5.4
and 7).

Covers the "Print-friendly PDF" form on the viewer, the /schedules/export/pdf/
download (gui/views.schedule_export_pdf), and the list of choices behind it
(gui/controllers/pdf_export.export_choices and parse_choice). The downloads
are real PDFs from gui/schedule_pdf.py, read back with pypdf, so these tests
fail if the wrong schedule, orientation or group ends up on the page.
"""

from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from pypdf import PdfReader

from app import schedule_io
from app.schedule_io import Assignment, MeetingTime
from app.session import Session
from gui import views
from gui.controllers import pdf_export
from gui.controllers import schedule_controller as ctrl
from gui.controllers.errors import ControllerError

VIEWER_URL = "/schedules/"
IMPORT_URL = "/schedules/import/"
EXPORT_URL = "/schedules/export/"
PDF_URL = "/schedules/export/pdf/"


def schedule(faculty="Hogg"):
    """`faculty` teaches CMSC 140.01 in Roddy 136; Killen teaches CMSC 162.01
    with a lecture in Roddy 140 and a lab in Roddy 147; CMSC 201.01 meets in a
    room that is also called Roddy 147; CMSC 999.01 is online."""
    return [
        Assignment(
            "CMSC 140.01",
            faculty,
            "Roddy 136",
            None,
            (
                MeetingTime("MON", "09:00", "09:50", 50),
                MeetingTime("WED", "09:00", "09:50", 50),
            ),
        ),
        Assignment(
            "CMSC 162.01",
            "Killen",
            "Roddy 140",
            "Roddy 147",
            (
                MeetingTime("TUE", "10:00", "10:50", 50),
                MeetingTime("THU", "13:00", "14:50", 110, lab=True),
            ),
        ),
        Assignment(
            "CMSC 201.01",
            "Zoppetti",
            "Roddy 147",
            None,
            (MeetingTime("FRI", "08:00", "08:50", 50),),
        ),
        Assignment("CMSC 999.01", "Online Person", None, None, ()),
    ]


def load(client, *faculty):
    """Load one schedule per name into the client's session, through the
    viewer's import form, as a user would."""
    raw = schedule_io.schedules_to_json([schedule(name) for name in faculty])
    upload = SimpleUploadedFile(
        "fall.json", raw.encode("utf-8"), content_type="application/json"
    )
    return client.post(IMPORT_URL, {"schedule_file": upload}, follow=True)


def pdf_text(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    return " ".join(
        " ".join((page.extract_text() or "").split()) for page in reader.pages
    )


def export(client, schedule_number="1", what="rooms", follow=False, **extra):
    """GET the PDF download. `extra` becomes more query parameters (for
    example download_token); `follow` tells the test client to follow a
    redirect back to the viewer."""
    query = {"schedule": schedule_number, "what": what, **extra}
    return client.get(PDF_URL, query, follow=follow)


# ---------------------------------------------------------------------- #
#  The form on the viewer
# ---------------------------------------------------------------------- #
def test_viewer_offers_a_pdf_export_of_the_schedule_shown(client):
    load(client, "Hogg", "Hardy")
    html = client.get(VIEWER_URL, {"schedule": "2"}).content.decode()
    assert 'id="export-pdf"' in html
    assert 'action="/schedules/export/pdf/"' in html
    assert '<input type="hidden" name="schedule" value="2">' in html
    assert "<strong>Schedule 2 of 2</strong>" in html
    assert ">Export PDF</button>" in html


def test_the_list_offers_every_group_and_each_room_lab_and_faculty_member(client):
    load(client, "Hogg")
    html = client.get(VIEWER_URL).content.decode()
    assert '<optgroup label="By room or lab">' in html
    assert '<optgroup label="By faculty">' in html
    for value, label in [
        ("rooms", "All rooms and labs"),
        ("rooms:room:Roddy 136", "Room: Roddy 136"),
        ("rooms:lab:Roddy 147", "Lab: Roddy 147"),
        ("rooms:room:Roddy 147", "Room: Roddy 147"),
        ("faculty", "All faculty"),
        ("faculty:faculty:Hogg", "Hogg"),
        ("faculty:faculty:Online Person", "Online Person"),
    ]:
        assert f'value="{value}"' in html, value
        assert f">{label}</option>" in html, label


def test_the_list_matches_the_schedule_shown(client):
    load(client, "Hogg", "Hardy")
    first = client.get(VIEWER_URL, {"schedule": "1"}).content.decode()
    second = client.get(VIEWER_URL, {"schedule": "2"}).content.decode()
    assert 'value="faculty:faculty:Hogg"' in first
    assert 'value="faculty:faculty:Hogg"' not in second
    assert 'value="faculty:faculty:Hardy"' in second


@pytest.mark.parametrize(
    "view, selected",
    [
        (None, "rooms"),
        ("courses", "rooms"),
        ("rooms", "rooms"),
        ("faculty", "faculty"),
    ],
)
def test_the_list_starts_on_the_orientation_of_the_view(client, view, selected):
    load(client, "Hogg")
    query = {"view": view} if view else {}
    html = client.get(VIEWER_URL, query).content.decode()
    assert f'<option value="{selected}" selected>' in html


def test_pdf_export_is_disabled_when_there_are_no_schedules(client):
    html = client.get(VIEWER_URL).content.decode()
    assert 'action="/schedules/export/pdf/"' not in html
    assert (
        'disabled aria-describedby="export-pdf-unavailable">Export PDF</button>' in html
    )


# ---------------------------------------------------------------------- #
#  Downloads
# ---------------------------------------------------------------------- #
def test_downloads_every_room_and_lab_as_a_pdf(client):
    load(client, "Hogg", "Hardy")
    response = export(client, "1", "rooms")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert (
        response["Content-Disposition"]
        == 'attachment; filename="schedule-1-all-rooms-and-labs.pdf"'
    )
    text = pdf_text(response.content)
    assert "Schedule 1 of 2 — By room or lab" in text
    for heading in ("Room: Roddy 136", "Room: Roddy 140", "Lab: Roddy 147"):
        assert heading in text
    assert "CMSC 140 01 Hogg Mon, Wed 09:00–09:50" in text


def test_downloads_every_faculty_member_as_a_pdf(client):
    load(client, "Hogg")
    response = export(client, "1", "faculty")
    assert response["Content-Type"] == "application/pdf"
    assert 'filename="schedule-1-all-faculty.pdf"' in response["Content-Disposition"]
    text = pdf_text(response.content)
    assert "By faculty" in text and "All faculty" in text
    assert "Faculty: Killen" in text
    assert "CMSC 162 01 Roddy 147 (lab) Thu 13:00–14:50" in text
    assert "CMSC 999 01 No room assigned No meeting times" in text


def test_downloads_one_lab_on_its_own(client):
    load(client, "Hogg")
    response = export(client, "1", "rooms:lab:Roddy 147")
    assert 'filename="schedule-1-lab-roddy-147.pdf"' in response["Content-Disposition"]
    text = pdf_text(response.content)
    assert "Lab: Roddy 147" in text and "CMSC 162" in text
    # the room with the same name is a different export
    assert "Room: Roddy 147" not in text and "CMSC 201" not in text


def test_downloads_one_faculty_member_on_their_own(client):
    load(client, "Hogg")
    response = export(client, "1", "faculty:faculty:Killen")
    assert 'filename="schedule-1-faculty-killen.pdf"' in response["Content-Disposition"]
    text = pdf_text(response.content)
    assert "Faculty: Killen" in text
    assert "Hogg" not in text


def test_exports_the_chosen_schedule_not_the_first(client):
    load(client, "Hogg", "Hardy", "Xie")
    text = pdf_text(export(client, "3", "faculty").content)
    assert "Schedule 3 of 3" in text
    assert "Faculty: Xie" in text and "Hogg" not in text


def test_times_follow_the_viewers_clock(client):
    load(client, "Hogg")
    assert "09:00–09:50" in pdf_text(export(client, "1", "faculty").content)
    client.get(VIEWER_URL, {"time": "12h"})  # the viewer remembers the choice
    twelve = pdf_text(export(client, "1", "faculty").content)
    assert "9:00–9:50 AM" in twelve and "1:00–2:50 PM" in twelve
    assert "13:00" not in twelve


def test_a_download_token_is_echoed_for_the_loading_state(client):
    load(client, "Hogg")
    response = export(client, download_token="abc123")
    assert response.cookies["download_token"].value == "abc123"


# ---------------------------------------------------------------------- #
#  Problems go back to the viewer with a message (Section 5.4)
# ---------------------------------------------------------------------- #
def test_no_schedules_goes_back_to_the_viewer_and_explains_why(client):
    response = export(client, "1", "rooms", follow=True)
    assert response.redirect_chain == [(VIEWER_URL, 302)]
    assert "There are no schedules yet." in response.content.decode()


@pytest.mark.parametrize("value", ["9", "0", "-1", "abc", ""])
def test_a_bad_schedule_number_explains_the_range(client, value):
    load(client, "Hogg", "Hardy")
    response = export(client, value, "rooms", follow=True)
    assert response.redirect_chain[-1][0] == VIEWER_URL
    assert "Choose a schedule from 1 to 2 to export." in response.content.decode()


@pytest.mark.parametrize(
    "what",
    [
        "",
        "courses",
        "rooms:room",
        "rooms:room:",
        "rooms:room:Nowhere",
        "rooms:lab:Roddy 136",  # a room, asked for as a lab
        "faculty:faculty:Nobody",
        "faculty:room:Roddy 136",
    ],
)
def test_a_choice_that_is_not_in_the_list_goes_back_with_a_message(client, what):
    load(client, "Hogg", "Hardy")
    response = export(client, "2", what, follow=True)
    url, status = response.redirect_chain[-1]
    assert (url, status) == ("/schedules/?schedule=2#export-pdf", 302)
    assert pdf_export.CHOOSE_EXPORT_MESSAGE in response.content.decode()


def test_a_drawing_failure_is_a_clear_message(client, monkeypatch):
    load(client, "Hogg")

    def broken(schedule_export, title, time_format="24h"):
        raise RuntimeError("out of paper")

    monkeypatch.setattr(views, "render_pdf", broken)
    response = export(client, "1", "rooms", follow=True)
    assert response.redirect_chain[-1][0] == "/schedules/?schedule=1#export-pdf"
    assert "The PDF could not be created." in response.content.decode()


# ---------------------------------------------------------------------- #
#  Nothing changes (Section 5.4)
# ---------------------------------------------------------------------- #
def test_exporting_does_not_change_the_schedules(client):
    load(client, "Hogg", "Hardy")
    json_before = client.get(EXPORT_URL, {"schedule": "all"}).content
    export(client, "1", "rooms")
    export(client, "2", "faculty:faculty:Killen")
    export(client, "2", "faculty:faculty:Nobody")
    export(client, "9", "rooms")
    assert client.get(EXPORT_URL, {"schedule": "all"}).content == json_before


def test_json_and_csv_export_still_work(client):
    load(client, "Hogg")
    json_response = client.get(EXPORT_URL, {"schedule": "1", "file_format": "json"})
    csv_response = client.get(EXPORT_URL, {"schedule": "1", "file_format": "csv"})
    assert json_response["Content-Type"] == "application/json; charset=utf-8"
    assert csv_response["Content-Type"].startswith("text/csv")


# ---------------------------------------------------------------------- #
#  The list of choices (controller, no Django request cycle)
# ---------------------------------------------------------------------- #
@pytest.fixture
def session(monkeypatch):
    fresh = Session()
    monkeypatch.setattr(ctrl, "get_session", lambda request: fresh)
    return fresh


def test_export_choices_are_grouped_by_orientation(session):
    session.schedules = [schedule("Hogg")]
    assert pdf_export.export_choices(None, 0) == [
        (
            "By room or lab",
            [
                ("rooms", "All rooms and labs"),
                ("rooms:room:Roddy 136", "Room: Roddy 136"),
                ("rooms:room:Roddy 140", "Room: Roddy 140"),
                ("rooms:lab:Roddy 147", "Lab: Roddy 147"),
                ("rooms:room:Roddy 147", "Room: Roddy 147"),
            ],
        ),
        (
            "By faculty",
            [
                ("faculty", "All faculty"),
                ("faculty:faculty:Hogg", "Hogg"),
                ("faculty:faculty:Killen", "Killen"),
                ("faculty:faculty:Online Person", "Online Person"),
                ("faculty:faculty:Zoppetti", "Zoppetti"),
            ],
        ),
    ]


def test_export_choices_of_a_missing_schedule_is_a_controller_error(session):
    with pytest.raises(ControllerError):
        pdf_export.export_choices(None, 0)
    session.schedules = [schedule()]
    with pytest.raises(ControllerError):
        pdf_export.export_choices(None, 5)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("rooms", ("rooms", None)),
        ("faculty", ("faculty", None)),
        ("rooms:lab:Roddy 147", ("rooms", ("lab", "Roddy 147"))),
        ("faculty:faculty:Hogg", ("faculty", ("faculty", "Hogg"))),
        # a colon in a name is kept
        ("rooms:room:Hall A: West", ("rooms", ("room", "Hall A: West"))),
    ],
)
def test_parse_choice_reads_back_every_value_the_list_contains(value, expected):
    assert pdf_export.parse_choice(value) == expected


@pytest.mark.parametrize(
    "value", ["", "courses", "rooms:", "rooms:room", "rooms:room:", "faculty:x"]
)
def test_parse_choice_rejects_anything_else(value):
    with pytest.raises(ControllerError) as raised:
        pdf_export.parse_choice(value)
    assert raised.value.message == pdf_export.CHOOSE_EXPORT_MESSAGE


def test_every_listed_choice_round_trips(session):
    session.schedules = [schedule("Hogg")]
    for _, options in pdf_export.export_choices(None, 0):
        for value, _label in options:
            orientation, selected = pdf_export.parse_choice(value)
            assert (
                pdf_export.choice_value(
                    orientation,
                    None if selected is None else pdf_export.GroupKey(*selected),
                )
                == value
            )
