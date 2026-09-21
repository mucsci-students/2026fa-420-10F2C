"""Unit tests for the schedule-export command interface."""

import pytest

from app import commands
from app.session import Session


class _FakeCourseInstance:
    """Same fake used in test_schedule_export.py -- satisfies both
    CSVWriter and JSONWriter's needs (as_csv() / model_dump())."""

    def __init__(self, course_id="FAKE 101"):
        """Initialize the test double with the supplied values."""
        self.course_id = course_id

    def as_csv(self):
        """Return the CSV representation expected by the export writer."""
        return f"{self.course_id},Faculty,Room,None,MON 09:00-09:50"

    def model_dump(self, by_alias=True, exclude_none=True):
        """Return serializable fields expected by the JSON writer."""
        return {"course_id": self.course_id, "faculty": "Faculty"}


@pytest.fixture
def session_with_schedules():
    """Two distinct schedules, so index-based tests can tell them apart
    by course_id."""
    s = Session()
    s.schedules = [
        [_FakeCourseInstance("SCHED0 A"), _FakeCourseInstance("SCHED0 B")],
        [_FakeCourseInstance("SCHED1 A")],
    ]
    return s


@pytest.fixture
def empty_session():
    """Provide a session with no generated schedules."""
    return Session()  # schedules == [] from __init__


def test_export_with_no_schedules_prints_guard_message(empty_session, tmp_path, capsys):
    """Verify that export with no schedules prints guard message."""
    target = tmp_path / "out.json"
    commands.export_schedule(empty_session, "json", str(target))

    captured = capsys.readouterr()
    assert "No generated schedules to export. Run 'schedule generate' first." in captured.out
    assert not target.exists()


def test_export_whole_set_when_index_is_none(session_with_schedules, tmp_path, capsys):
    """Verify that export whole set when index is none."""
    target = tmp_path / "out.json"
    commands.export_schedule(session_with_schedules, "json", str(target))

    captured = capsys.readouterr()
    assert f"Exported to '{target.resolve()}'." in captured.out

    content = target.read_text(encoding="utf-8")
    assert "SCHED0 A" in content
    assert "SCHED1 A" in content  # both schedules present


def test_export_single_schedule_by_index(session_with_schedules, tmp_path, capsys):
    """Verify that export single schedule by index."""
    target = tmp_path / "single.csv"
    commands.export_schedule(session_with_schedules, "csv", str(target), index=0)

    captured = capsys.readouterr()
    assert f"Exported to '{target.resolve()}'." in captured.out

    content = target.read_text(encoding="utf-8")
    assert "SCHED0 A" in content
    assert "SCHED1 A" not in content  # only schedule 0, not schedule 1


def test_export_rejects_out_of_range_index(session_with_schedules, tmp_path, capsys):
    """Verify that export rejects out of range index."""
    target = tmp_path / "bad.csv"
    commands.export_schedule(session_with_schedules, "csv", str(target), index=99)

    captured = capsys.readouterr()
    assert "No schedule at index 99. Valid range: 0-1." in captured.out
    assert not target.exists()  # never even reached schedule_ops


def test_export_refuses_existing_file_without_overwrite(session_with_schedules, tmp_path, capsys):
    """Verify that export refuses existing file without overwrite."""
    target = tmp_path / "out.csv"
    target.write_text("pre-existing", encoding="utf-8")

    commands.export_schedule(session_with_schedules, "csv", str(target), overwrite=False)

    captured = capsys.readouterr()
    assert "already exists" in captured.out
    assert "(pass --overwrite to replace it)." in captured.out
    assert target.read_text(encoding="utf-8") == "pre-existing"  # untouched


def test_export_overwrites_when_flag_set(session_with_schedules, tmp_path, capsys):
    """Verify that export overwrites when flag set."""
    target = tmp_path / "out.csv"
    target.write_text("stale", encoding="utf-8")

    commands.export_schedule(session_with_schedules, "csv", str(target), overwrite=True)

    captured = capsys.readouterr()
    assert f"Exported to '{target.resolve()}'." in captured.out
    assert "stale" not in target.read_text(encoding="utf-8")
