"""Schedule file format: loading, validating, and exporting schedules.

Model layer (Sprint 2, Section 20). No Django imports -- views and
controllers call into this module, and it is tested directly.

Every schedule the GUI shows, imports, or exports goes through the same
plain record types defined here (``Assignment`` and ``MeetingTime``), no
matter where the schedule came from:

* Generated schedules (lists of the scheduler library's CourseInstance
  objects) are converted with ``to_assignments()``, which reads the
  library's own JSON output (``CourseInstance.as_json()`` or, failing
  that, ``scheduler.writers.JSONWriter``).
* Imported files are parsed and validated with ``parse_schedule_file()``.

Supported schedule JSON (documented in the README):

    {
      "format": "course-scheduler-schedules",
      "version": 1,
      "schedule_count": 2,
      "schedules": [
        [
          {
            "course": "CMSC 140.01",
            "faculty": "Hogg",
            "room": "Roddy 136",
            "lab": null,
            "meetings": [
              {"day": "MON", "start": "09:00", "end": "09:50",
               "duration": 50, "lab": false}
            ]
          }
        ]
      ]
    }

For import, the wrapper object is optional: a bare list of schedules (the
scheduler library's JSONWriter output) and a single schedule (a list of
course assignments) are accepted too.
"""

from __future__ import annotations

import csv
import io
import json
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

FORMAT_NAME = "course-scheduler-schedules"
FORMAT_VERSION = 1
MAX_IMPORT_BYTES = 5 * 1024 * 1024  # a real schedule set is a few hundred KB
MAX_REPORTED_PROBLEMS = 5

DAYS = ("MON", "TUE", "WED", "THU", "FRI")
DAY_NAMES = {"MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday", "THU": "Thursday", "FRI": "Friday"}
_LIBRARY_DAY_NAMES = {number: day for number, day in enumerate(DAYS, start=1)}

CSV_COLUMNS = (
    "schedule", "course", "faculty", "room", "lab",
    "day", "start", "end", "duration_minutes", "lab_meeting",
)

_HHMM_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_MEETING_STR_RE = re.compile(r"^\s*([A-Za-z]+)\s+(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*$")


class ScheduleFileError(Exception):
    """A schedule file (or schedule data) could not be used.

    ``message`` is one plain-language sentence for the user. ``problems``
    lists specific issues (at most MAX_REPORTED_PROBLEMS) for a details
    list under the message.
    """

    def __init__(self, message: str, problems: Iterable[str] = ()):
        super().__init__(message)
        self.message = message
        self.problems = list(problems)


# --------------------------------------------------------------------------- #
#  Record types
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class MeetingTime:
    """One weekly meeting of a scheduled section."""

    day: str          # MON..FRI
    start: str        # "HH:MM", 24-hour
    end: str          # "HH:MM", 24-hour
    duration: int     # minutes
    lab: bool = False

    @property
    def day_name(self) -> str:
        return DAY_NAMES.get(self.day, self.day)

    def to_dict(self) -> dict[str, Any]:
        return {"day": self.day, "start": self.start, "end": self.end,
                "duration": self.duration, "lab": self.lab}


@dataclass(frozen=True)
class Assignment:
    """One course section's placement in a schedule."""

    course: str
    faculty: str | None = None
    room: str | None = None
    lab: str | None = None
    meetings: tuple[MeetingTime, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "course": self.course,
            "faculty": self.faculty,
            "room": self.room,
            "lab": self.lab,
            "meetings": [m.to_dict() for m in self.meetings],
        }


# --------------------------------------------------------------------------- #
#  Import
# --------------------------------------------------------------------------- #

def parse_schedule_file(raw: bytes) -> list[list[Assignment]]:
    """Decode, parse, and validate an uploaded schedule file.

    Returns one list of Assignments per schedule. Raises ScheduleFileError
    for anything unusable; callers must not change any state until this
    returns (Section 17: preserve existing schedules on a failed load).
    """
    if not raw or not raw.strip():
        raise ScheduleFileError("The file is empty.")
    if len(raw) > MAX_IMPORT_BYTES:
        raise ScheduleFileError(
            f"The file is too large ({len(raw) // 1024} KB). Schedule files over "
            f"{MAX_IMPORT_BYTES // (1024 * 1024)} MB are not supported."
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ScheduleFileError("The file is not a UTF-8 text file. Choose a .json schedule file.") from None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ScheduleFileError(
            f"The file is not valid JSON (problem at line {e.lineno}, column {e.colno}: {e.msg})."
        ) from None
    return parse_schedule_data(data)


def parse_schedule_data(data: Any) -> list[list[Assignment]]:
    """Validate already-parsed JSON data. See the module docstring for
    the accepted shapes."""
    raw_schedules = _unwrap(data)

    problems: list[str] = []
    schedules: list[list[Assignment]] = []
    for s_idx, raw_schedule in enumerate(raw_schedules, start=1):
        where_schedule = f"Schedule {s_idx}"
        if not isinstance(raw_schedule, list):
            problems.append(f"{where_schedule} is not a list of course assignments.")
            continue
        if not raw_schedule:
            problems.append(f"{where_schedule} has no course assignments.")
            continue
        assignments = []
        for a_idx, raw_assignment in enumerate(raw_schedule, start=1):
            try:
                assignments.append(_assignment_from_data(raw_assignment, f"{where_schedule}, assignment {a_idx}"))
            except ScheduleFileError as e:
                problems.append(e.message)
        schedules.append(assignments)

    if problems:
        shown = problems[:MAX_REPORTED_PROBLEMS]
        if len(problems) > MAX_REPORTED_PROBLEMS:
            shown.append(f"...and {len(problems) - MAX_REPORTED_PROBLEMS} more problem(s).")
        raise ScheduleFileError("The file contains schedule data that is missing or invalid.", shown)
    return schedules


def _unwrap(data: Any) -> list:
    """Return the list of raw schedules from any accepted top-level shape."""
    if isinstance(data, dict):
        if "config" in data and "time_slot_config" in data:
            raise ScheduleFileError(
                "This is not a supported schedule format: it looks like a configuration file. "
                "Load it from the Configuration Editor instead."
            )
        if "format" in data and data["format"] != FORMAT_NAME:
            raise ScheduleFileError(f"This is not a supported schedule format: the file says {data['format']!r}, expected {FORMAT_NAME!r}.")
        version = data.get("version", FORMAT_VERSION)
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ScheduleFileError(f"The file has an invalid format version {version!r}.")
        if version > FORMAT_VERSION:
            raise ScheduleFileError(
                f"The file uses schedule format version {version}, but this application "
                f"supports up to version {FORMAT_VERSION}."
            )
        if "schedules" not in data:
            raise ScheduleFileError("This is not a supported schedule format: it has no \"schedules\" list.")
        data = data["schedules"]
        if not isinstance(data, list):
            raise ScheduleFileError("This is not a supported schedule format: \"schedules\" must be a list.")

    if not isinstance(data, list):
        raise ScheduleFileError("This is not a supported schedule format: expected a list of schedules.")
    if not data:
        raise ScheduleFileError("The file contains no schedules.")

    if all(isinstance(item, dict) for item in data):
        return [data]  # a single schedule: a list of assignments
    if all(isinstance(item, list) for item in data):
        return data    # a set of schedules
    raise ScheduleFileError(
        "This is not a supported schedule format: it mixes schedules and course assignments at the top level."
    )


def _assignment_from_data(obj: Any, where: str) -> Assignment:
    if not isinstance(obj, dict):
        raise ScheduleFileError(f"{where} is not an object with course details.")

    course = obj.get("course")
    if isinstance(course, dict):  # tolerate {"course_id": ..., "section": ...}
        course_id = course.get("course_id") or course.get("id")
        section = course.get("section") or course.get("section_id")
        course = f"{course_id}.{section}" if course_id and section else course_id
    if not isinstance(course, str) or not course.strip():
        raise ScheduleFileError(f"{where} is missing a course name.")
    course = course.strip()
    where = f"{where} ({course})"

    faculty = _optional_name(obj.get("faculty"), "faculty", where)
    room = _optional_name(obj.get("room"), "room", where)
    lab = _optional_name(obj.get("lab"), "lab", where)

    raw_meetings = obj.get("meetings", obj.get("times", []))
    if raw_meetings is None:
        raw_meetings = []
    if not isinstance(raw_meetings, list):
        raise ScheduleFileError(f"{where}: \"meetings\" must be a list.")
    meetings = tuple(
        _meeting_from_data(m, f"{where}, meeting {i}") for i, m in enumerate(raw_meetings, start=1)
    )
    return Assignment(course=course, faculty=faculty, room=room, lab=lab, meetings=meetings)


def _optional_name(value: Any, label: str, where: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    raise ScheduleFileError(f"{where}: {label} must be a name or null, not {type(value).__name__}.")


def _meeting_from_data(obj: Any, where: str) -> MeetingTime:
    lab = False
    if isinstance(obj, str):  # "MON 09:00-09:50"
        match = _MEETING_STR_RE.match(obj)
        if not match:
            raise ScheduleFileError(f"{where}: {obj!r} is not a meeting like \"MON 09:00-09:50\".")
        raw_day, raw_start, raw_end, raw_duration = match.group(1), match.group(2), match.group(3), None
    elif isinstance(obj, dict):
        raw_day, raw_start = obj.get("day"), obj.get("start")
        raw_end, raw_duration = obj.get("end"), obj.get("duration")
        lab_value = obj.get("lab", False)
        if not isinstance(lab_value, bool):
            raise ScheduleFileError(f"{where}: \"lab\" must be true or false.")
        lab = lab_value
    else:
        raise ScheduleFileError(f"{where} is not a meeting object.")

    day = _parse_day(raw_day, where)
    start = _parse_minutes(raw_start, "start", where)

    if raw_duration is not None:
        if isinstance(raw_duration, bool) or not isinstance(raw_duration, int) or raw_duration <= 0:
            raise ScheduleFileError(f"{where}: duration must be a positive whole number of minutes.")
        duration = raw_duration  # when both are given, duration wins (documented)
    elif raw_end is not None:
        duration = _parse_minutes(raw_end, "end", where) - start
        if duration <= 0:
            raise ScheduleFileError(f"{where}: end time must be after the start time.")
    else:
        raise ScheduleFileError(f"{where} needs either a duration or an end time.")

    end = start + duration
    if end > 24 * 60:
        raise ScheduleFileError(f"{where}: the meeting runs past midnight.")
    return MeetingTime(day=day, start=_fmt(start), end=_fmt(end), duration=duration, lab=lab)


def _parse_day(value: Any, where: str) -> str:
    if isinstance(value, str) and value.strip()[:3].upper() in DAYS:
        return value.strip()[:3].upper()
    raise ScheduleFileError(f"{where}: {value!r} is not a weekday (use MON, TUE, WED, THU, or FRI).")


def _parse_minutes(value: Any, label: str, where: str) -> int:
    """'HH:MM' (or minutes after midnight as an int) -> minutes after midnight."""
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 24 * 60:
        return value
    if isinstance(value, str):
        match = _HHMM_RE.match(value.strip())
        if match:
            hours, minutes = int(match.group(1)), int(match.group(2))
            if hours < 24 and minutes < 60:
                return hours * 60 + minutes
    raise ScheduleFileError(f"{where}: {label} time {value!r} is not a valid HH:MM time.")


def _fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


# --------------------------------------------------------------------------- #
#  Generated schedules -> records
# --------------------------------------------------------------------------- #

def to_assignments(schedule: Iterable[Any]) -> list[Assignment]:
    """Return a schedule as Assignments, whatever it currently holds.

    session.schedules can hold either imported schedules (already
    Assignments) or generated ones (the library's CourseInstance lists,
    stored as-is by the generator). Views, exports, and the viewer tables
    call this so they never need to know which.
    """
    items = list(schedule)
    if all(isinstance(item, Assignment) for item in items):
        return items
    if all(isinstance(item, dict) for item in items):
        return parse_schedule_data([items])[0]
    return _library_instances_to_assignments(items)


def _library_instances_to_assignments(instances: list[Any]) -> list[Assignment]:
    """Convert CourseInstance objects using the library's own JSON output,
    so there is exactly one place that knows the library's shape."""
    as_json_items = []
    for instance in instances:
        as_json = getattr(instance, "as_json", None)
        if not callable(as_json):
            break
        value = as_json()
        as_json_items.append(json.loads(value) if isinstance(value, str) else value)
    else:
        return parse_schedule_data([_normalize_library_schedule(as_json_items)])[0]

    # Fallback: the same JSONWriter Sprint 1's export used.
    from scheduler.writers import JSONWriter

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "schedule.json"
        with JSONWriter(str(path)) as writer:
            writer.add_schedule(instances)
        data = json.loads(path.read_text(encoding="utf-8"))
    return parse_schedule_data([_normalize_library_schedule(schedule) for schedule in data])[0]


def _normalize_library_schedule(schedule: list[Any]) -> list[Any]:
    """Translate the scheduler library's JSON conventions into our file format.

    The library serializes weekdays as 1 through 5 and marks the lab meeting
    with the assignment-level ``lab_index``. Imported files stay strict; only
    generated records pass through this adapter.
    """
    normalized = []
    for raw_assignment in schedule:
        if not isinstance(raw_assignment, dict):
            normalized.append(raw_assignment)
            continue

        assignment = dict(raw_assignment)
        lab_index = assignment.pop("lab_index", None)
        times = assignment.get("times")
        if isinstance(times, list):
            normalized_times = []
            for index, raw_time in enumerate(times):
                if not isinstance(raw_time, dict):
                    normalized_times.append(raw_time)
                    continue

                meeting = dict(raw_time)
                day_name = _LIBRARY_DAY_NAMES.get(meeting.get("day"))
                if day_name is not None:
                    meeting["day"] = day_name
                if index == lab_index:
                    meeting["lab"] = True
                normalized_times.append(meeting)
            assignment["times"] = normalized_times
        normalized.append(assignment)
    return normalized


# --------------------------------------------------------------------------- #
#  Export
# --------------------------------------------------------------------------- #

def schedules_to_json(schedules: list[list[Assignment]]) -> str:
    """Serialize schedules in the documented format (reloadable with
    parse_schedule_file)."""
    payload = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "schedule_count": len(schedules),
        "schedules": [[a.to_dict() for a in schedule] for schedule in schedules],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def schedules_to_csv(schedules: list[list[Assignment]], first_number: int = 1) -> str:
    """One row per meeting (one row for a section with no meetings).
    ``schedule`` is the 1-based number shown in the viewer."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for number, schedule in enumerate(schedules, start=first_number):
        for a in schedule:
            base = [number, a.course, a.faculty or "", a.room or "", a.lab or ""]
            if not a.meetings:
                writer.writerow(base + ["", "", "", "", ""])
            for m in a.meetings:
                writer.writerow(base + [m.day, m.start, m.end, m.duration, "yes" if m.lab else "no"])
    return buffer.getvalue()
