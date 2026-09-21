"""Unit tests for exporting generated schedules to JSON and CSV."""

import pytest
from pathlib import Path

from app import schedule_ops


class _FakeCourseInstance:
    """Stand-in for scheduler.models.course.CourseInstance. Confirmed via a
    real pytest failure that the two writers want different things from
    each course instance:
      - CSVWriter.add_schedule() works with the bare original fake (calls
        something CSV-shaped internally -- likely as_csv(), unconfirmed
        beyond "it didn't need model_dump").
      - JSONWriter.add_schedule() calls course_instance.model_dump(
        by_alias=True, exclude_none=True) -- real Pydantic model
        serialization -- so the fake needs a same-named method too.
    Neither writer inspects the *contents* past what these return, so a
    minimal fake satisfying both call shapes is enough for a unit test."""

    def __init__(self, course_id="FAKE 101"):
        """Create a minimal course instance with a stable identifier."""
        self.course_id = course_id

    def as_csv(self):
        """Return the CSV representation expected by the CSV writer."""
        return f"{self.course_id},Faculty,Room,None,MON 09:00-09:50"

    def model_dump(self, by_alias=True, exclude_none=True):
        """Return serializable fields expected by the JSON writer."""
        return {"course_id": self.course_id, "faculty": "Faculty"}


@pytest.fixture
def one_schedule():
    """Provide one schedule containing two fake course instances."""
    return [_FakeCourseInstance(), _FakeCourseInstance()]


@pytest.fixture
def two_schedules(one_schedule):
    """Provide two schedules containing three courses in total."""
    return [one_schedule, [_FakeCourseInstance()]]


def test_export_json_creates_valid_utf8_file(tmp_path, one_schedule):
    """Export JSON to the requested path using UTF-8 encoding."""
    target = tmp_path / "out.json"
    result = schedule_ops.export_schedule([one_schedule], "json", str(target))

    assert result == target.resolve()
    assert target.exists()
    # round-trips as UTF-8 without error
    target.read_text(encoding="utf-8")


def test_export_csv_creates_valid_utf8_file(tmp_path, one_schedule):
    """Export CSV to the requested path using UTF-8 encoding."""
    target = tmp_path / "out.csv"
    result = schedule_ops.export_schedule([one_schedule], "csv", str(target))

    assert result == target.resolve()
    assert target.exists()
    target.read_text(encoding="utf-8")


def test_export_whole_set_writes_every_schedule(tmp_path, two_schedules):
    """Include every course from every schedule in the output."""
    target = tmp_path / "out.json"
    schedule_ops.export_schedule(two_schedules, "json", str(target))
    # Both schedules' course instances should show up somewhere in the
    # output -- exact structure is the library's concern, not ours.
    content = target.read_text(encoding="utf-8")
    assert content.count("FAKE 101") == 3  # 2 in schedule 1, 1 in schedule 2


def test_export_refuses_existing_file_without_overwrite(tmp_path, one_schedule):
    """Protect an existing file when overwrite is disabled."""
    target = tmp_path / "out.csv"
    target.write_text("pre-existing content", encoding="utf-8")

    with pytest.raises(FileExistsError):
        schedule_ops.export_schedule([one_schedule], "csv", str(target), overwrite=False)

    # refusal must not touch the existing file
    assert target.read_text(encoding="utf-8") == "pre-existing content"


def test_export_overwrites_when_flag_set(tmp_path, one_schedule):
    """Replace an existing file when overwrite is enabled."""
    target = tmp_path / "out.csv"
    target.write_text("stale content", encoding="utf-8")

    schedule_ops.export_schedule([one_schedule], "csv", str(target), overwrite=True)

    assert "stale content" not in target.read_text(encoding="utf-8")


def test_export_rejects_unknown_format(tmp_path, one_schedule):
    """Reject an unsupported format without creating a file."""
    target = tmp_path / "out.txt"
    with pytest.raises(ValueError):
        schedule_ops.export_schedule([one_schedule], "xml", str(target))

    assert not target.exists()
