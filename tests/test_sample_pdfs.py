"""
Tests for scripts/make_sample_pdfs.py, which writes the sample PDF exports in
docs/samples/ (Sprint 4 Sections 7 and 8, issue #168).

The print layout itself is tested in tests/test_schedule_pdf.py. These check
that the sample script still runs and that its demonstration data really
exercises the cases the samples are meant to show: two pages or more, every
section included, and the special cases present.
"""

import importlib.util
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.schedule_export import BY_FACULTY, BY_ROOM_OR_LAB, build_export

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "make_sample_pdfs.py"


def load_script():
    spec = importlib.util.spec_from_file_location("make_sample_pdfs", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return load_script()


def text_of(path: Path) -> tuple[int, str]:
    reader = PdfReader(BytesIO(path.read_bytes()))
    return len(reader.pages), "\n".join(page.extract_text() for page in reader.pages)


def test_writes_one_readable_pdf_per_orientation(script, tmp_path):
    written = script.write_samples(tmp_path)
    assert [path.name for path in written] == [
        "schedule-by-room-or-lab.pdf",
        "schedule-by-faculty.pdf",
    ]
    for path in written:
        assert path.read_bytes().startswith(b"%PDF-")
        pages, text = text_of(path)
        assert pages >= 2  # the samples show a multi-page export
        assert script.SCHEDULE_LABEL in text


def test_every_section_appears_in_both_samples(script, tmp_path):
    courses = {item.course.split(".")[0] for item in script.demo_schedule()}
    for path in script.write_samples(tmp_path):
        _, text = text_of(path)
        missing = [course for course in courses if course not in text]
        assert missing == []


def test_demo_data_covers_the_special_cases(script):
    schedule = script.demo_schedule()
    assert any(item.faculty == script.LONG_FACULTY for item in schedule)
    assert any(item.room == script.LONG_ROOM for item in schedule)
    assert any(item.lab for item in schedule)  # a lab meeting
    assert any(not item.meetings for item in schedule)  # online, never meets
    assert any(item.faculty is None for item in schedule)  # no faculty member

    rooms = build_export(schedule, BY_ROOM_OR_LAB)
    faculty = build_export(schedule, BY_FACULTY)
    assert {section.kind for section in rooms.sections} >= {"room", "lab"}
    assert len(faculty.sections) == len(script.FACULTY) + 1  # + "No faculty assigned"


def test_the_same_data_gives_the_same_files(script, tmp_path):
    first = [path.read_bytes() for path in script.write_samples(tmp_path / "a")]
    second = [path.read_bytes() for path in script.write_samples(tmp_path / "b")]
    assert first == second
