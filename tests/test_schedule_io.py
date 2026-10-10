"""
Unit tests for app/schedule_io.py: the schedule JSON format, import
validation, JSON/CSV export, and converting generated schedules.

Sprint 2 Section 23.4 (loading/export). No Django and no solver needed.
"""
import csv
import io
import json
import sys
import types

import pytest

from app import schedule_io
from app.schedule_io import Assignment, MeetingTime, ScheduleFileError


def _assignment(course="CMSC 140.01", faculty="Hogg", room="Roddy 136", lab=None, meetings=None):
    if meetings is None:
        meetings = [MeetingTime("MON", "09:00", "09:50", 50), MeetingTime("WED", "09:00", "09:50", 50)]
    return Assignment(course=course, faculty=faculty, room=room, lab=lab, meetings=tuple(meetings))


def _two_schedules():
    return [
        [_assignment(), _assignment("CMSC 161.01", "Zoppetti", None, "Roddy 147",
                                    [MeetingTime("TUE", "13:00", "14:50", 110, lab=True)])],
        [_assignment(faculty="Killen")],
    ]


# ---------- round trip ----------

def test_export_json_round_trips_a_schedule_set():
    schedules = _two_schedules()
    text = schedule_io.schedules_to_json(schedules)
    assert schedule_io.parse_schedule_file(text.encode("utf-8")) == schedules


def test_export_json_has_documented_wrapper():
    data = json.loads(schedule_io.schedules_to_json(_two_schedules()))
    assert data["format"] == schedule_io.FORMAT_NAME
    assert data["version"] == schedule_io.FORMAT_VERSION
    assert data["schedule_count"] == 2
    assert data["schedules"][0][1] == {
        "course": "CMSC 161.01", "faculty": "Zoppetti", "room": None, "lab": "Roddy 147",
        "meetings": [{"day": "TUE", "start": "13:00", "end": "14:50", "duration": 110, "lab": True}],
    }


def test_export_json_is_utf8_and_keeps_non_ascii_names():
    schedules = [[_assignment(faculty="Muñoz")]]
    raw = schedule_io.schedules_to_json(schedules).encode("utf-8")
    assert "Muñoz" in raw.decode("utf-8")
    assert schedule_io.parse_schedule_file(raw) == schedules


# ---------- accepted input shapes ----------

def test_accepts_bare_list_of_schedules():
    data = [[{"course": "CMSC 140.01", "faculty": "Hogg", "room": "Roddy 136", "lab": None,
              "meetings": [{"day": "MON", "start": "09:00", "duration": 50}]}]]
    [[a]] = schedule_io.parse_schedule_data(data)
    assert a.meetings == (MeetingTime("MON", "09:00", "09:50", 50, False),)


def test_accepts_single_schedule():
    data = [{"course": "CMSC 140.01", "meetings": [{"day": "MON", "start": "09:00", "end": "09:50"}]},
            {"course": "CMSC 162.01", "meetings": []}]
    schedules = schedule_io.parse_schedule_data(data)
    assert len(schedules) == 1 and len(schedules[0]) == 2


def test_accepts_library_style_times_key_and_string_meetings():
    data = [[{"course": "CMSC 140.01", "faculty": "Hogg", "room": "Roddy 136", "lab": "",
              "times": ["MON 09:00-09:50", {"day": "Friday", "start": 540, "duration": 50, "lab": False}]}]]
    [[a]] = schedule_io.parse_schedule_data(data)
    assert a.lab is None
    assert [m.day for m in a.meetings] == ["MON", "FRI"]
    assert a.meetings[1].start == "09:00" and a.meetings[1].end == "09:50"


def test_duration_wins_when_end_also_given():
    [[a]] = schedule_io.parse_schedule_data(
        [[{"course": "X", "meetings": [{"day": "MON", "start": "09:00", "end": "09:49", "duration": 50}]}]])
    assert a.meetings[0].end == "09:50"


def test_leading_bom_is_accepted():
    raw = "﻿".encode("utf-8") + schedule_io.schedules_to_json(_two_schedules()).encode("utf-8")
    assert len(schedule_io.parse_schedule_file(raw)) == 2


# ---------- rejected input ----------

@pytest.mark.parametrize("raw, fragment", [
    (b"", "empty"),
    (b"   \n", "empty"),
    (b"{not json", "not valid JSON"),
    (b"\xff\xfe\x00", "not a UTF-8"),
    (b"[]", "no schedules"),
    (b"42", "expected a list"),
    (b'{"schedules": 3}', "must be a list"),
    (b'{"hello": 1}', 'no "schedules"'),
    (b'{"format": "something-else", "schedules": []}', "not a supported schedule format"),
    (b'{"format": "course-scheduler-schedules", "version": 99, "schedules": [[]]}', "version 99"),
    (b'[[{"course": "A"}], {"course": "B"}]', "mixes"),
])
def test_rejects_bad_files_with_plain_message(raw, fragment):
    with pytest.raises(ScheduleFileError) as info:
        schedule_io.parse_schedule_file(raw)
    assert fragment in info.value.message


def test_rejects_config_file_with_specific_hint():
    raw = json.dumps({"config": {}, "time_slot_config": {}, "limit": 10}).encode()
    with pytest.raises(ScheduleFileError) as info:
        schedule_io.parse_schedule_file(raw)
    assert "configuration file" in info.value.message


def test_rejects_oversized_file(monkeypatch):
    monkeypatch.setattr(schedule_io, "MAX_IMPORT_BYTES", 10)
    with pytest.raises(ScheduleFileError) as info:
        schedule_io.parse_schedule_file(b"[" + b" " * 20 + b"]")
    assert "too large" in info.value.message


@pytest.mark.parametrize("assignment, fragment", [
    ({"faculty": "Hogg"}, "missing a course name"),
    ({"course": "A", "faculty": 5}, "faculty must be a name"),
    ({"course": "A", "meetings": "MON"}, "must be a list"),
    ({"course": "A", "meetings": [{"day": "SUN", "start": "09:00", "duration": 50}]}, "not a weekday"),
    ({"course": "A", "meetings": [{"day": "MON", "start": "25:00", "duration": 50}]}, "not a valid HH:MM"),
    ({"course": "A", "meetings": [{"day": "MON", "start": "09:00", "duration": 0}]}, "positive whole number"),
    ({"course": "A", "meetings": [{"day": "MON", "start": "09:00", "end": "08:00"}]}, "after the start"),
    ({"course": "A", "meetings": [{"day": "MON", "start": "09:00"}]}, "duration or an end time"),
    ({"course": "A", "meetings": [{"day": "MON", "start": "23:30", "duration": 60}]}, "past midnight"),
    ({"course": "A", "meetings": [{"day": "MON", "start": "09:00", "duration": 50, "lab": "yes"}]}, "true or false"),
])
def test_invalid_assignment_is_reported_with_location(assignment, fragment):
    with pytest.raises(ScheduleFileError) as info:
        schedule_io.parse_schedule_data([[assignment]])
    assert info.value.message == "The file contains schedule data that is missing or invalid."
    assert len(info.value.problems) == 1
    assert info.value.problems[0].startswith("Schedule 1, assignment 1")
    assert fragment in info.value.problems[0]


def test_empty_schedule_inside_set_is_rejected():
    with pytest.raises(ScheduleFileError) as info:
        schedule_io.parse_schedule_data([[{"course": "A"}], []])
    assert info.value.problems == ["Schedule 2 has no course assignments."]


def test_problem_list_is_capped():
    bad = [[{"faculty": "x"} for _ in range(12)]]
    with pytest.raises(ScheduleFileError) as info:
        schedule_io.parse_schedule_data(bad)
    assert len(info.value.problems) == schedule_io.MAX_REPORTED_PROBLEMS + 1
    assert info.value.problems[-1] == "...and 7 more problem(s)."


# ---------- CSV ----------

def test_csv_has_header_and_one_row_per_meeting():
    rows = list(csv.reader(io.StringIO(schedule_io.schedules_to_csv(_two_schedules()))))
    assert rows[0] == list(schedule_io.CSV_COLUMNS)
    assert rows[1] == ["1", "CMSC 140.01", "Hogg", "Roddy 136", "", "MON", "09:00", "09:50", "50", "no"]
    assert rows[3] == ["1", "CMSC 161.01", "Zoppetti", "", "Roddy 147", "TUE", "13:00", "14:50", "110", "yes"]
    assert [r[0] for r in rows[1:]] == ["1", "1", "1", "2", "2"]


def test_csv_numbers_single_schedule_as_shown_in_viewer():
    rows = list(csv.reader(io.StringIO(schedule_io.schedules_to_csv([_two_schedules()[1]], first_number=2))))
    assert {r[0] for r in rows[1:]} == {"2"}


def test_csv_keeps_section_without_meetings():
    rows = list(csv.reader(io.StringIO(schedule_io.schedules_to_csv([[_assignment(meetings=[])]]))))
    assert rows[1][:2] == ["1", "CMSC 140.01"] and rows[1][5:] == ["", "", "", "", ""]


# ---------- generated schedules -> records ----------

class _FakeInstance:
    """Stand-in for scheduler's CourseInstance with an as_json() method."""

    def __init__(self, payload, as_string=False):
        self._payload = payload
        self._as_string = as_string

    def as_json(self):
        return json.dumps(self._payload) if self._as_string else self._payload


def test_to_assignments_passes_through_records():
    schedule = _two_schedules()[0]
    assert schedule_io.to_assignments(schedule) == schedule


def test_to_assignments_uses_as_json():
    schedule = [
        _FakeInstance({"course": "CMSC 140.01", "faculty": "Hogg", "room": "Roddy 136", "lab": None,
                       "times": [{"day": "MON", "start": "09:00", "duration": 50}]}),
        _FakeInstance({"course": "CMSC 161.01", "faculty": "Zoppetti", "room": None, "lab": "Roddy 147",
                       "times": [{"day": "TUE", "start": "13:00", "duration": 110, "lab": True}]}, as_string=True),
    ]
    records = schedule_io.to_assignments(schedule)
    assert [a.course for a in records] == ["CMSC 140.01", "CMSC 161.01"]
    assert records[1].meetings[0].lab is True


def test_to_assignments_normalizes_library_weekdays_and_lab_index():
    schedule = [
        _FakeInstance(
            {
                "course": "CMSC 152.01",
                "faculty": "Hogg",
                "room": "Roddy 136",
                "lab": "Roddy 147",
                "lab_index": 1,
                "times": [
                    {"day": 1, "start": 540, "duration": 50},
                    {"day": 3, "start": 780, "duration": 110},
                ],
            }
        )
    ]

    [record] = schedule_io.to_assignments(schedule)

    assert record.meetings == (
        MeetingTime("MON", "09:00", "09:50", 50, False),
        MeetingTime("WED", "13:00", "14:50", 110, True),
    )


def test_to_assignments_falls_back_to_library_json_writer(monkeypatch):
    written = {}

    class FakeJSONWriter:
        def __init__(self, path):
            self.path = path
            self.schedules = []

        def __enter__(self):
            return self

        def add_schedule(self, schedule):
            self.schedules.append([{"course": i.name, "times": ["WED 10:00-10:50"]} for i in schedule])

        def __exit__(self, *exc):
            written["path"] = self.path
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.schedules, f)

    fake_writers = types.ModuleType("scheduler.writers")
    fake_writers.JSONWriter = FakeJSONWriter
    monkeypatch.setitem(sys.modules, "scheduler.writers", fake_writers)

    records = schedule_io.to_assignments([types.SimpleNamespace(name="CMSC 330.01")])
    assert records == [Assignment("CMSC 330.01", meetings=(MeetingTime("WED", "10:00", "10:50", 50),))]
    assert written["path"].endswith("schedule.json")
