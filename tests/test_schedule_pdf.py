"""
Tests for gui/schedule_pdf.py: a schedule export as a print-friendly PDF
(Sprint 4 Sections 5.3 and 7).

These read the generated PDF back with pypdf and check the text on its pages,
so they fail if the document is unreadable or leaves content out -- not just
if rendering was skipped. Pagination and visual layout are checked by eye
(see the README).
"""

import inspect
from io import BytesIO

import pytest
from pypdf import PdfReader

from app.schedule_export import (
    BY_FACULTY,
    BY_ROOM_OR_LAB,
    EMPTY_EXPORT_LABEL,
    EXPORT_ORIENTATIONS,
    NO_MEETING_TIMES_LABEL,
    build_export,
)
from app.schedule_io import Assignment, MeetingTime
from app.schedule_view import LAB, NO_FACULTY_LABEL, NO_LOCATION_LABEL
from gui.constants import TIME_FORMAT_12, TIME_FORMAT_24
from gui.schedule_pdf import (
    DOCUMENTS,
    PAGE_SIZE,
    FacultyDocument,
    RoomLabDocument,
    ScheduleDocument,
    fit,
    render_pdf,
)

LONG_FACULTY = (
    "Dr. Bartholomew Featherstonehaugh-Worthington III, Visiting Distinguished"
    " Professor of Computational Linguistics & Data <Science>"
)
LONG_ROOM = (
    "Caputo Hall Interdisciplinary Collaborative Computing Laboratory West Annex 214B"
)


def schedule() -> list[Assignment]:
    return [
        Assignment(
            "CMSC 140.01",
            "Hogg",
            "Roddy 136",
            None,
            (
                MeetingTime("MON", "09:00", "09:50", 50),
                MeetingTime("WED", "09:00", "09:50", 50),
                MeetingTime("FRI", "09:00", "09:50", 50),
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
            "CMSC 390.01", None, None, None, (MeetingTime("MON", "08:00", "08:50", 50),)
        ),
        Assignment("CMSC 999.01", "Online Person", None, None, ()),
    ]


def long_schedule(count: int = 70) -> list[Assignment]:
    """Enough sections, with long names, to run over several pages."""
    people = [LONG_FACULTY, "Hogg", "Killen", "Zoppetti"]
    rooms = ["Roddy 136", "Roddy 140", LONG_ROOM]
    days = ["MON", "TUE", "WED", "THU", "FRI"]
    assignments = []
    for index in range(count):
        hour = 8 + index % 9
        assignments.append(
            Assignment(
                f"CMSC {100 + index}.{1 + index % 3:02d}",
                people[index % 4],
                rooms[index % 3],
                None,
                (MeetingTime(days[index % 5], f"{hour:02d}:00", f"{hour:02d}:50", 50),),
            )
        )
    return assignments


def pages(pdf: bytes) -> list[str]:
    """The text of each page, with line breaks and repeated spaces flattened."""
    reader = PdfReader(BytesIO(pdf))
    return [" ".join((page.extract_text() or "").split()) for page in reader.pages]


def text(pdf: bytes) -> str:
    return " ".join(pages(pdf))


def pdf_for(orientation, selected=None, records=None, time_format=TIME_FORMAT_24):
    export = build_export(
        schedule() if records is None else records, orientation, selected
    )
    return render_pdf(export, "Schedule 2 of 5", time_format)


# ---------------------------------------------------------------------- #
#  A readable PDF
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize("orientation", EXPORT_ORIENTATIONS)
def test_the_result_is_a_pdf_that_can_be_read_back(orientation):
    pdf = pdf_for(orientation)
    assert pdf.startswith(b"%PDF-")
    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 1
    assert "CMSC 140" in text(pdf)


@pytest.mark.parametrize("orientation", EXPORT_ORIENTATIONS)
def test_every_page_is_us_letter_portrait(orientation):
    reader = PdfReader(BytesIO(pdf_for(orientation, records=long_schedule())))
    assert len(reader.pages) > 1
    for page in reader.pages:
        assert (float(page.mediabox.width), float(page.mediabox.height)) == PAGE_SIZE
    assert PAGE_SIZE == (612.0, 792.0)


def test_the_same_export_always_gives_the_same_bytes():
    assert pdf_for(BY_FACULTY) == pdf_for(BY_FACULTY)


# ---------------------------------------------------------------------- #
#  Identifying the schedule and the grouping (Section 5.3)
# ---------------------------------------------------------------------- #
def test_the_room_export_names_the_schedule_and_the_grouping():
    pdf = pdf_for(BY_ROOM_OR_LAB)
    assert "Schedule 2 of 5 — By room or lab" in text(pdf)
    assert "All rooms and labs" in text(pdf)
    metadata = PdfReader(BytesIO(pdf)).metadata
    assert metadata is not None
    assert metadata.title == "Schedule 2 of 5 — By room or lab"


def test_the_faculty_export_names_the_schedule_and_the_grouping():
    pdf = pdf_for(BY_FACULTY)
    assert "Schedule 2 of 5 — By faculty" in text(pdf)
    assert "All faculty" in text(pdf)


def test_an_export_of_one_group_says_which():
    assert "Roddy 147 (lab)" in text(pdf_for(BY_ROOM_OR_LAB, (LAB, "Roddy 147")))
    assert "Hogg (faculty)" in text(pdf_for(BY_FACULTY, ("faculty", "Hogg")))


# ---------------------------------------------------------------------- #
#  By room or lab (Section 5.1)
# ---------------------------------------------------------------------- #
def test_room_export_heads_each_section_with_its_name_and_kind():
    found = text(pdf_for(BY_ROOM_OR_LAB))
    for heading in ("Room: Roddy 136", "Room: Roddy 140", "Lab: Roddy 147"):
        assert heading in found
    assert found.index("Room: Roddy 136") < found.index("Room: Roddy 140")
    assert found.index("Room: Roddy 140") < found.index("Lab: Roddy 147")


def test_room_export_lists_course_section_faculty_days_and_times():
    found = text(pdf_for(BY_ROOM_OR_LAB))
    assert "Course Section Faculty Days Time" in found
    assert "CMSC 140 01 Hogg Mon, Wed, Fri 09:00–09:50" in found
    assert "CMSC 162 01 Killen Thu 13:00–14:50" in found  # under the lab


def test_room_export_puts_meetings_with_no_room_last_and_labels_them():
    found = text(pdf_for(BY_ROOM_OR_LAB))
    assert found.index(NO_LOCATION_LABEL) > found.index("Lab: Roddy 147")
    assert f"CMSC 390 01 {NO_FACULTY_LABEL} Mon 08:00–08:50" in found
    assert f"CMSC 999 01 Online Person {NO_MEETING_TIMES_LABEL}" in found


def test_exporting_one_room_leaves_the_others_out():
    found = text(pdf_for(BY_ROOM_OR_LAB, ("room", "Roddy 136")))
    assert "Room: Roddy 136" in found and "CMSC 140" in found
    assert "Roddy 140" not in found and "CMSC 162" not in found


# ---------------------------------------------------------------------- #
#  By faculty (Section 5.2)
# ---------------------------------------------------------------------- #
def test_faculty_export_heads_each_section_with_the_faculty_member():
    found = text(pdf_for(BY_FACULTY))
    for heading in ("Faculty: Hogg", "Faculty: Killen", "Faculty: Online Person"):
        assert heading in found
    assert found.rindex(NO_FACULTY_LABEL) > found.index("Faculty: Online Person")


def test_faculty_export_lists_course_section_room_or_lab_days_and_times():
    found = text(pdf_for(BY_FACULTY))
    assert "Course Section Room or lab Days Time" in found
    assert "CMSC 140 01 Roddy 136 (room) Mon, Wed, Fri 09:00–09:50" in found
    assert "CMSC 162 01 Roddy 147 (lab) Thu 13:00–14:50" in found


def test_faculty_export_labels_a_meeting_with_no_room_instead_of_inventing_one():
    found = text(pdf_for(BY_FACULTY))
    assert f"CMSC 390 01 {NO_LOCATION_LABEL} Mon 08:00–08:50" in found
    assert f"CMSC 999 01 {NO_LOCATION_LABEL} {NO_MEETING_TIMES_LABEL}" in found


def test_exporting_one_faculty_member_leaves_the_others_out():
    found = text(pdf_for(BY_FACULTY, ("faculty", "Killen")))
    assert "Faculty: Killen" in found and "CMSC 162" in found
    assert "Hogg" not in found and "CMSC 140" not in found


# ---------------------------------------------------------------------- #
#  Times
# ---------------------------------------------------------------------- #
def test_times_follow_the_chosen_clock_throughout():
    twelve = text(pdf_for(BY_FACULTY, time_format=TIME_FORMAT_12))
    assert "9:00–9:50 AM" in twelve and "1:00–2:50 PM" in twelve
    assert "13:00" not in twelve and "09:00" not in twelve
    twenty_four = text(pdf_for(BY_FACULTY))
    assert "13:00–14:50" in twenty_four
    assert " AM" not in twenty_four and " PM" not in twenty_four


# ---------------------------------------------------------------------- #
#  Long names and several pages
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize("orientation", EXPORT_ORIENTATIONS)
def test_a_long_schedule_runs_over_pages_without_losing_any_course(orientation):
    records = long_schedule()
    pdf = pdf_for(orientation, records=records)
    assert len(pages(pdf)) > 2
    found = text(pdf)
    for assignment in records:
        course_name, section = assignment.course.split(".")
        assert f"{course_name} {section}" in found


def squeezed(value: str) -> str:
    """Without any whitespace: a name too wide for its column wraps, even in
    the middle of a long word, so its characters are compared, not its lines."""
    return "".join(value.split())


def test_long_names_are_printed_in_full_not_clipped():
    by_faculty = squeezed(text(pdf_for(BY_FACULTY, records=long_schedule())))
    assert squeezed(f"Faculty: {LONG_FACULTY}") in by_faculty
    assert squeezed(f"{LONG_ROOM} (room)") in by_faculty
    by_room = squeezed(text(pdf_for(BY_ROOM_OR_LAB, records=long_schedule())))
    assert squeezed(f"Room: {LONG_ROOM}") in by_room
    assert squeezed(f"CMSC 100 01 {LONG_FACULTY} Mon 08:00\u201308:50") in by_room


def test_section_and_column_headings_repeat_on_continuation_pages():
    one_person = [
        Assignment(
            f"CMSC {100 + index}.01",
            "Hogg",
            "Roddy 136",
            None,
            (MeetingTime("MON", "09:00", "09:50", 50),),
        )
        for index in range(90)
    ]
    each = pages(pdf_for(BY_FACULTY, records=one_person))
    assert len(each) > 1
    for page in each:
        assert "Faculty: Hogg" in page
        assert "Course Section Room or lab Days Time" in page


def test_every_page_carries_the_schedule_the_grouping_and_its_number():
    each = pages(pdf_for(BY_ROOM_OR_LAB, records=long_schedule()))
    for number, page in enumerate(each, start=1):
        assert "Schedule 2 of 5 — By room or lab" in page
        assert "All rooms and labs" in page
        assert f"Page {number}" in page


def test_a_running_header_too_long_for_its_line_is_cut_with_an_ellipsis():
    assert fit("Hogg (faculty)", 200) == "Hogg (faculty)"
    cut = fit(f"{LONG_FACULTY} (faculty)", 200)
    assert cut.endswith("…") and len(cut) < len(LONG_FACULTY)
    assert LONG_FACULTY.startswith(cut[:-1].rstrip())
    # the full name is still on the page, in the title block and the heading
    one = pdf_for(BY_FACULTY, ("faculty", LONG_FACULTY), records=long_schedule())
    assert squeezed(f"Faculty: {LONG_FACULTY}") in squeezed(text(one))


# ---------------------------------------------------------------------- #
#  Empty exports (Section 5.4)
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize("orientation", EXPORT_ORIENTATIONS)
def test_an_empty_schedule_gives_a_readable_pdf_that_says_so(orientation):
    pdf = pdf_for(orientation, records=[])
    assert len(pages(pdf)) == 1
    found = text(pdf)
    assert EMPTY_EXPORT_LABEL in found
    assert "Schedule 2 of 5" in found
    assert "Course Section" not in found


# ---------------------------------------------------------------------- #
#  Template Method
# ---------------------------------------------------------------------- #
def test_there_is_one_document_class_per_export_orientation():
    assert set(DOCUMENTS) == set(EXPORT_ORIENTATIONS)
    assert DOCUMENTS[BY_ROOM_OR_LAB] is RoomLabDocument
    assert DOCUMENTS[BY_FACULTY] is FacultyDocument


def test_the_base_document_is_abstract_and_owns_the_build_steps():
    assert inspect.isabstract(ScheduleDocument)
    for document in DOCUMENTS.values():
        assert issubclass(document, ScheduleDocument)
        assert not inspect.isabstract(document)
        # subclasses fill in the steps; none of them replaces the skeleton
        for shared in ("build", "title_block", "section_block", "page_furniture"):
            assert shared not in vars(document)
        for step in ("section_heading", "columns", "name"):
            assert step in vars(document)


def test_rendering_does_not_change_the_export_or_the_schedule():
    records = schedule()
    export = build_export(records, BY_FACULTY)
    render_pdf(export, "Schedule 1 of 1")
    assert records == schedule()
    assert export == build_export(schedule(), BY_FACULTY)
