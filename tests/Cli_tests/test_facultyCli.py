import json

import pytest

import app.Cli.facultyComm as facultyComm


def feed_inputs(monkeypatch, answers):
    """Makes input() return each string in `answers` in order, one call
    at a time. Raises a clear error if the code under test asks for
    more input than the test provided."""
    it = iter(answers)

    def fake_input(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise AssertionError("input() was called more times than the test expected")

    monkeypatch.setattr("builtins.input", fake_input)


def write_config(faculty_list):
    """Writes config.json (in the current directory) with the given
    faculty list already in it."""
    data = {"config": {"rooms": [], "labs": [], "courses": [], "faculty": faculty_list}}
    with open("config.json", "w") as f:
        json.dump(data, f)
    return data


def read_config():
    with open("config.json") as f:
        return json.load(f)


def sample_faculty(**overrides):
    record = {
        "name": "Dr. Test",
        "maximum_credits": 12,
        "minimum_credits": 6,
        "unique_course_limit": 2,
        "times": {"MON": ["09:00-17:00"]},
        "course_preferences": {},
        "room_preferences": {},
        "lab_preferences": {},
    }
    record.update(overrides)
    return record


# All these tests run inside a tmp_path so config.json never touches
# the real repo, and CONFIG_PATH ("config.json") resolves relative to
# whatever the current directory is.
@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


# ---------- add_faculty ----------

def test_add_faculty_happy_path(monkeypatch):
    feed_inputs(monkeypatch, [
        "Dr. Test",   # name
        "full",       # full-time
        "",           # min credits -> default 0
        "",           # max credits -> default 12
        "",           # MON -> default 09:00-17:00
        "n/a", "n/a", "n/a", "n/a",  # TUE-FRI unavailable
        "",           # course preferences -> none
        "",           # room preferences -> none
        "",           # lab preferences -> none
    ])

    facultyComm.add_faculty()

    data = read_config()
    faculty = data["config"]["faculty"]
    assert len(faculty) == 1
    assert faculty[0]["name"] == "Dr. Test"
    assert faculty[0]["unique_course_limit"] == 2
    assert faculty[0]["maximum_credits"] == 12
    assert faculty[0]["minimum_credits"] == 0
    assert faculty[0]["times"] == {"MON": ["09:00-17:00"]}


def test_add_faculty_adjunct_defaults(monkeypatch):
    feed_inputs(monkeypatch, [
        "Dr. Adjunct",
        "adjunct",
        "", "",                        # min/max credits -> defaults (0, 4)
        "n/a", "n/a", "n/a", "n/a", "n/a",  # unavailable all week
        "", "", "",                    # no preferences
    ])

    facultyComm.add_faculty()

    faculty = read_config()["config"]["faculty"][0]
    assert faculty["unique_course_limit"] == 1
    assert faculty["maximum_credits"] == 4


def test_add_faculty_rejects_duplicate_name(monkeypatch):
    write_config([sample_faculty(name="Dr. Test")])
    feed_inputs(monkeypatch, ["Dr. Test"])  # returns early, no further prompts

    facultyComm.add_faculty()

    faculty = read_config()["config"]["faculty"]
    assert len(faculty) == 1  # nothing new was added


def test_add_faculty_rejects_blank_name(monkeypatch):
    feed_inputs(monkeypatch, [""])

    facultyComm.add_faculty()

    # add_faculty() returns before ever calling save_config() on a blank
    # name, so no config.json gets written at all -- nothing to check
    # inside it, just confirm the early-return path was taken.
    import os
    assert not os.path.exists("config.json")


# ---------- delete_faculty ----------

def test_delete_faculty_removes_confirmed_record(monkeypatch):
    write_config([sample_faculty(name="Dr. Test")])
    feed_inputs(monkeypatch, ["Dr. Test", "y"])

    facultyComm.delete_faculty()

    faculty = read_config()["config"]["faculty"]
    assert faculty == []


def test_delete_faculty_cancel_keeps_record(monkeypatch):
    write_config([sample_faculty(name="Dr. Test")])
    feed_inputs(monkeypatch, ["Dr. Test", "n"])

    facultyComm.delete_faculty()

    faculty = read_config()["config"]["faculty"]
    assert len(faculty) == 1
    assert faculty[0]["name"] == "Dr. Test"


def test_delete_faculty_nonexistent_name_is_a_no_op(monkeypatch):
    write_config([sample_faculty(name="Dr. Test")])
    feed_inputs(monkeypatch, ["Nobody"])

    facultyComm.delete_faculty()

    faculty = read_config()["config"]["faculty"]
    assert len(faculty) == 1  # unchanged


# ---------- modify_faculty ----------

def test_modify_faculty_applies_valid_change(monkeypatch):
    write_config([sample_faculty(name="Dr. Test")])
    feed_inputs(monkeypatch, [
        "Dr. Test",     # who to edit
        "credits",      # what to edit
        "adjunct",      # switch to adjunct
        "", "",         # min/max credits -> defaults (0, 4)
    ])

    facultyComm.modify_faculty()

    faculty = read_config()["config"]["faculty"][0]
    assert faculty["unique_course_limit"] == 1
    assert faculty["maximum_credits"] == 4
    assert faculty["minimum_credits"] == 0


def test_modify_faculty_restores_previous_state_on_invalid_edit(monkeypatch, capsys):
    original = sample_faculty(name="Dr. Test", times={"MON": ["09:00-17:00"]})
    write_config([original])
    feed_inputs(monkeypatch, [
        "Dr. Test",       # who to edit
        "availability",   # what to edit
        "badtime",        # MON -> not a valid HH:MM-HH:MM range
        "n/a", "n/a", "n/a", "n/a",  # TUE-FRI unavailable
    ])

    facultyComm.modify_faculty()

    faculty = read_config()["config"]["faculty"]
    assert len(faculty) == 1
    # the record should be exactly what it was before the failed edit
    assert faculty[0]["times"] == {"MON": ["09:00-17:00"]}

    output = capsys.readouterr().out
    assert "restored previous version" in output


def test_modify_faculty_nonexistent_name_is_a_no_op(monkeypatch):
    write_config([sample_faculty(name="Dr. Test")])
    feed_inputs(monkeypatch, ["Nobody"])

    facultyComm.modify_faculty()

    faculty = read_config()["config"]["faculty"]
    assert len(faculty) == 1
    assert faculty[0]["name"] == "Dr. Test"  # unchanged