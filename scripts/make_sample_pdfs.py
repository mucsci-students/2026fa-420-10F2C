"""
Write the sample PDF exports in docs/samples/ (Sprint 4 Sections 7 and 8).

    uv run python scripts/make_sample_pdfs.py

Makes one PDF per export orientation from invented demonstration data (no real
people, rooms or courses), using the same code the application uses:
app.schedule_export.build_export arranges the schedule and
gui.schedule_pdf.render_pdf draws it. The data is chosen to exercise the print
layout on purpose:

* enough sections that both PDFs run onto a second page, and the busiest room
  continues across a page break, so the repeated headings can be checked;
* a very long faculty name and a very long room name, to check wrapping;
* a lab meeting, an online section with no room or meeting times, and a section
  with no faculty member, to check how each is labelled.

The output is deterministic: running the script again gives the same bytes.
"""

from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

# Run as a script from anywhere: make the project root importable.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.schedule_export import BY_FACULTY, BY_ROOM_OR_LAB, build_export
from app.schedule_io import Assignment, MeetingTime
from gui.schedule_pdf import render_pdf

SAMPLES_DIR = ROOT / "docs" / "samples"
SCHEDULE_LABEL = "Sample schedule 1 of 1"

FILE_NAMES = {
    BY_ROOM_OR_LAB: "sample-by-room-or-lab.pdf",
    BY_FACULTY: "sample-by-faculty.pdf",
}

LONG_FACULTY = "Dr. Alexandra Montgomery-Okonkwo-Vasquez, Visiting Professor"
LONG_ROOM = "Thornton Interdisciplinary Learning Commons, Room 310 (West Wing)"

FACULTY = ["Avery", "Brooks", "Chen", "Delgado", "Evans", LONG_FACULTY]
ROOMS = ["Science Hall 101", "Science Hall 204", LONG_ROOM]
DAY_PAIRS = [("MON", "WED"), ("TUE", "THU")]
TIMES = [
    ("08:00", "09:50"),
    ("10:00", "11:50"),
    ("12:00", "13:50"),
    ("14:00", "15:50"),
    ("16:00", "17:50"),
]
LENGTH = 110  # minutes


def _meetings(days: tuple[str, ...], start: str, end: str) -> tuple[MeetingTime, ...]:
    return tuple(MeetingTime(day, start, end, LENGTH) for day in days)


def demo_schedule() -> list[Assignment]:
    """Invented sections: every room is busy at every time slot, no instructor
    teaches two sections at once, plus the special cases listed above."""
    schedule: list[Assignment] = []
    number = 100
    for (r, room), (p, days), (t, (start, end)) in product(
        enumerate(ROOMS), enumerate(DAY_PAIRS), enumerate(TIMES)
    ):
        number += 1
        # Rooms at the same time get different instructors.
        faculty = FACULTY[(r + 2 * p + t) % len(FACULTY)]
        schedule.append(
            Assignment(
                f"CMSC {number}.01", faculty, room, None, _meetings(days, start, end)
            )
        )

    # A lecture in a room and a lab meeting in a lab, both on Friday.
    schedule.append(
        Assignment(
            "CMSC 380.01",
            "Brooks",
            "Science Hall 204",
            "Linux Lab",
            (
                MeetingTime("FRI", "08:00", "09:50", LENGTH),
                MeetingTime("FRI", "14:00", "15:50", LENGTH, lab=True),
            ),
        )
    )
    # Meets only in a lab.
    schedule.append(
        Assignment(
            "CMSC 381.01",
            "Chen",
            None,
            "Mac Lab",
            (MeetingTime("FRI", "10:00", "11:50", LENGTH, lab=True),),
        )
    )

    # Online: no room and no meeting times.
    schedule.append(Assignment("CMSC 495.01", "Delgado", None, None, ()))
    # Not yet assigned to a faculty member.
    schedule.append(
        Assignment(
            "CMSC 101.05",
            None,
            "Science Hall 101",
            None,
            (MeetingTime("FRI", "08:00", "09:50", LENGTH),),
        )
    )
    return schedule


def write_samples(out_dir: Path = SAMPLES_DIR) -> list[Path]:
    """Write both sample PDFs into `out_dir` and return their paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    schedule = demo_schedule()
    written = []
    for orientation, name in FILE_NAMES.items():
        path = out_dir / name
        path.write_bytes(
            render_pdf(build_export(schedule, orientation), SCHEDULE_LABEL)
        )
        written.append(path)
    return written


def main() -> None:
    for path in write_samples():
        print(f"Wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
