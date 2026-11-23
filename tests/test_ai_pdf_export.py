"""
Tests for exporting a schedule as a PDF through the AI chat (Sprint 4 Section 5, gui/ai/exports.py).

The real AI is replaced by FakeRunner, which calls the tool a model would have picked. Everything else
is real: the chat endpoint, gui.ai.service, the tool, the controllers, the session and the PDF export.
What these cover:
  * "Export the schedule as a PDF" offers an Export PDF button (an action), for every room and lab or
    every faculty member, and the reply never says the file was saved
  * one room, lab or faculty member, found the way every tool finds a name ("136", "hogg")
  * a name that is both a room and a lab is asked about, with one suggestion for each
  * an unknown name, a schedule that does not exist, and no schedules at all give a clear reply and no
    button
  * the button's target is the Schedule Viewer's own PDF export and downloads the PDF that was offered
  * nothing in the session changes
"""

from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from pypdf import PdfReader

from app import schedule_io
from app.schedule_io import Assignment, MeetingTime
from gui import session_store
from gui.ai import exports, service
from gui.ai.prompt import CAPABILITIES
from gui.ai.tools import TOOLS_BY_NAME

ASK_URL = "/assistant/ask/"
VIEWER_URL = "/schedules/"
IMPORT_URL = "/schedules/import/"
EXPORT_URL = "/schedules/export/"
PDF_URL = "/schedules/export/pdf/"

SCRIPT = {
    "Export the schedule as a PDF by room": [
        ("export_schedule_pdf", {"orientation": "rooms"})
    ],
    "Print the faculty schedules": [
        ("export_schedule_pdf", {"orientation": "faculty"})
    ],
    "PDF of schedule 2 by faculty": [
        ("export_schedule_pdf", {"orientation": "faculty", "schedule": 2})
    ],
    "PDF for hogg": [
        ("export_schedule_pdf", {"orientation": "faculty", "name": "hogg"})
    ],
    "PDF for Dr. Hogg in schedule 2": [
        (
            "export_schedule_pdf",
            {"orientation": "faculty", "name": "Dr. Hogg", "schedule": 2},
        )
    ],
    "PDF for room 136": [
        ("export_schedule_pdf", {"orientation": "rooms", "name": "136"})
    ],
    "PDF for Roddy 147": [
        ("export_schedule_pdf", {"orientation": "rooms", "name": "Roddy 147"})
    ],
    "PDF for the lab Roddy 147": [
        (
            "export_schedule_pdf",
            {"orientation": "rooms", "name": "Roddy 147", "kind": "lab"},
        )
    ],
    "PDF for Nobody": [
        ("export_schedule_pdf", {"orientation": "faculty", "name": "Nobody"})
    ],
    "PDF of schedule 9": [
        ("export_schedule_pdf", {"orientation": "rooms", "schedule": 9})
    ],
}


class FakeRunner:
    def run(self, text, toolbox):
        for name, args in SCRIPT[text]:
            toolbox.call(name, args)
        return ""


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    monkeypatch.setattr(service, "get_runner", lambda: FakeRunner())


def schedule(faculty="Hogg"):
    """`faculty` teaches CMSC 140.01 in Roddy 136; Killen teaches CMSC 162.01 with a lab in
    Roddy 147; CMSC 201.01 meets in a room that is also called Roddy 147."""
    return [
        Assignment(
            "CMSC 140.01",
            faculty,
            "Roddy 136",
            None,
            (MeetingTime("MON", "09:00", "09:50", 50),),
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
    ]


def load(client, *faculty):
    """One schedule per name, loaded through the Schedule Viewer's import form."""
    raw = schedule_io.schedules_to_json([schedule(name) for name in faculty])
    upload = SimpleUploadedFile(
        "fall.json", raw.encode("utf-8"), content_type="application/json"
    )
    client.post(IMPORT_URL, {"schedule_file": upload}, follow=True)


def ask(client, text, viewed=None):
    """Send a chat message. `viewed` is the schedule number the Schedule Viewer was showing, which
    chat.js sends along; None is any other page."""
    data = {"message": text}
    if viewed is not None:
        data["schedule"] = str(viewed)
    response = client.post(ASK_URL, data)
    assert response.status_code == 200
    return response.json()


def download(client, action):
    return client.get(PDF_URL, {"schedule": action["schedule"], "what": action["what"]})


def pdf_text(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    return " ".join(" ".join((p.extract_text() or "").split()) for p in reader.pages)


# ---------------------------------------------------------------------- #
#  Every group
# ---------------------------------------------------------------------- #
def test_a_pdf_request_offers_an_export_pdf_button_for_every_room_and_lab(client):
    load(client, "Hogg")
    body = ask(client, "Export the schedule as a PDF by room")
    assert body["ok"] is True
    assert body["action"] == {"kind": "pdf", "schedule": 1, "what": "rooms"}
    assert "Schedule 1 of 1, all rooms and labs" in body["reply"]
    assert "Click Export PDF" in body["reply"]


def test_every_faculty_member(client):
    load(client, "Hogg")
    body = ask(client, "Print the faculty schedules")
    assert body["action"] == {"kind": "pdf", "schedule": 1, "what": "faculty"}
    assert "all faculty" in body["reply"]


def test_the_reply_never_says_the_pdf_was_saved(client):
    load(client, "Hogg")
    for text in ("Export the schedule as a PDF by room", "Print the faculty schedules"):
        reply = ask(client, text)["reply"].lower()
        assert "saved" not in reply and "has been downloaded" not in reply
        assert "cannot tell whether the download finished" in reply


def test_away_from_the_viewer_it_uses_schedule_1_and_says_so(client):
    load(client, "Hogg", "Hardy")
    body = ask(client, "Print the faculty schedules")
    assert body["action"]["schedule"] == 1
    assert (
        "Schedule 1 of 2 (no schedule is open in the Schedule Viewer" in body["reply"]
    )


def test_in_the_viewer_it_uses_the_schedule_on_screen(client):
    load(client, "Hogg", "Hardy", "Xie")
    body = ask(client, "Print the faculty schedules", viewed=3)
    assert body["action"] == {"kind": "pdf", "schedule": 3, "what": "faculty"}
    assert "Schedule 3 of 3, all faculty" in body["reply"]
    assert "no schedule is open" not in body["reply"]


def test_a_name_is_looked_up_in_the_schedule_on_screen(client):
    load(client, "Hardy", "Hogg")
    assert ask(client, "PDF for hogg", viewed=2)["action"] == {
        "kind": "pdf",
        "schedule": 2,
        "what": "faculty:faculty:Hogg",
    }
    assert ask(client, "PDF for hogg", viewed=1)["action"] is None


def test_a_named_schedule_beats_the_one_on_screen(client):
    load(client, "Hogg", "Hardy")
    body = ask(client, "PDF of schedule 2 by faculty", viewed=1)
    assert body["action"]["schedule"] == 2


def test_a_viewed_number_out_of_range_falls_back_to_schedule_1(client):
    load(client, "Hogg", "Hardy")
    assert (
        ask(client, "Print the faculty schedules", viewed=7)["action"]["schedule"] == 1
    )


def test_a_named_schedule_is_the_one_offered(client):
    load(client, "Hogg", "Hardy")
    body = ask(client, "PDF of schedule 2 by faculty")
    assert body["action"] == {"kind": "pdf", "schedule": 2, "what": "faculty"}
    assert "Schedule 2 of 2, all faculty" in body["reply"]


# ---------------------------------------------------------------------- #
#  One room, lab or faculty member
# ---------------------------------------------------------------------- #
def test_one_faculty_member_found_by_part_of_the_name(client):
    load(client, "Hogg")
    body = ask(client, "PDF for hogg")
    assert body["action"] == {
        "kind": "pdf",
        "schedule": 1,
        "what": "faculty:faculty:Hogg",
    }
    assert "Hogg only" in body["reply"]


def test_a_title_is_ignored_and_the_named_schedule_is_searched(client):
    load(client, "Hardy", "Hogg")
    body = ask(client, "PDF for Dr. Hogg in schedule 2")
    assert body["action"]["what"] == "faculty:faculty:Hogg"
    assert body["action"]["schedule"] == 2


def test_one_room_found_by_its_number(client):
    load(client, "Hogg")
    body = ask(client, "PDF for room 136")
    assert body["action"]["what"] == "rooms:room:Roddy 136"
    assert "room Roddy 136 only" in body["reply"]


def test_a_name_that_is_both_a_room_and_a_lab_is_asked_about(client):
    load(client, "Hogg")
    body = ask(client, "PDF for Roddy 147")
    assert body["action"] is None
    assert "'Roddy 147' is both a room and a lab in schedule 1" in body["reply"]
    assert body["suggestions"] == [
        "Export room Roddy 147 from schedule 1 as a PDF",
        "Export lab Roddy 147 from schedule 1 as a PDF",
    ]


def test_saying_lab_picks_the_lab(client):
    load(client, "Hogg")
    body = ask(client, "PDF for the lab Roddy 147")
    assert body["action"]["what"] == "rooms:lab:Roddy 147"
    assert "lab Roddy 147 only" in body["reply"]


# ---------------------------------------------------------------------- #
#  Nothing to offer
# ---------------------------------------------------------------------- #
def test_an_unknown_name_gets_a_clear_reply_and_no_button(client):
    load(client, "Hogg")
    body = ask(client, "PDF for Nobody")
    assert body["action"] is None
    assert "No faculty member named 'Nobody' exists." in body["reply"]
    assert "(in schedule 1)" in body["reply"]


def test_a_schedule_that_does_not_exist_gets_a_clear_reply(client):
    load(client, "Hogg", "Hardy")
    body = ask(client, "PDF of schedule 9")
    assert body["action"] is None
    assert "There are 2 schedules, so there is no schedule 9" in body["reply"]


def test_no_schedules_explains_what_to_do(client):
    client.get(VIEWER_URL)
    body = ask(client, "Export the schedule as a PDF by room")
    assert body["action"] is None
    assert body["reply"] == exports.NO_SCHEDULES
    assert exports.GENERATE_CHIP in body["suggestions"]


# ---------------------------------------------------------------------- #
#  The button is the Schedule Viewer's own export
# ---------------------------------------------------------------------- #
def test_the_button_downloads_the_pdf_that_was_offered(client):
    load(client, "Hardy", "Hogg")
    action = ask(client, "PDF for Dr. Hogg in schedule 2")["action"]
    response = download(client, action)
    assert response["Content-Type"] == "application/pdf"
    assert 'filename="schedule-2-faculty-hogg.pdf"' in response["Content-Disposition"]
    text = pdf_text(response.content)
    assert "Schedule 2 of 2" in text and "Faculty: Hogg" in text
    assert "Killen" not in text


def test_the_lab_button_downloads_the_lab_not_the_room(client):
    load(client, "Hogg")
    response = download(client, ask(client, "PDF for the lab Roddy 147")["action"])
    text = pdf_text(response.content)
    assert "Lab: Roddy 147" in text and "Room: Roddy 147" not in text


def test_the_chat_knows_where_the_pdf_export_is(client):
    html = client.get(VIEWER_URL).content.decode()
    assert 'data-pdf-url="/schedules/export/pdf/"' in html


def test_asking_changes_nothing(client):
    load(client, "Hogg", "Hardy")
    before = client.get(EXPORT_URL, {"schedule": "all"}).content
    for text in SCRIPT:
        ask(client, text)
    assert client.get(EXPORT_URL, {"schedule": "all"}).content == before


# ---------------------------------------------------------------------- #
#  The tool itself
# ---------------------------------------------------------------------- #
def test_the_tool_is_registered_and_changes_nothing():
    tool = TOOLS_BY_NAME["export_schedule_pdf"]
    assert tool.final and not tool.acts_on_state and not tool.needs_config


def test_the_capabilities_mention_pdf_export():
    assert "print-friendly PDF" in CAPABILITIES
