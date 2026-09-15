import pytest

from app.model.facultyModel import Faculty, FacultyValidationError, validate_faculty


def sample_faculty(**overrides):
    """A minimal valid faculty record; pass overrides to tweak one field."""
    record = {
        "name": "Dr. Smith",
        "maximum_credits": 12,
        "minimum_credits": 6,
        "unique_course_limit": 2,
        "times": {"MON": ["09:00-17:00"], "WED": ["09:00-12:00"]},
        "course_preferences": {"CMSC 420": 5},
        "room_preferences": {},
        "lab_preferences": {},
    }
    record.update(overrides)
    return record


# ---------- validate_faculty ----------

def test_validate_faculty_accepts_valid_record():
    record = sample_faculty()
    assert validate_faculty(record) == record


def test_validate_faculty_rejects_blank_name():
    with pytest.raises(FacultyValidationError):
        validate_faculty(sample_faculty(name=""))


def test_validate_faculty_rejects_min_greater_than_max():
    with pytest.raises(FacultyValidationError):
        validate_faculty(sample_faculty(minimum_credits=10, maximum_credits=4))


def test_validate_faculty_rejects_invalid_unique_course_limit():
    with pytest.raises(FacultyValidationError):
        validate_faculty(sample_faculty(unique_course_limit=0))


def test_validate_faculty_rejects_invalid_day():
    with pytest.raises(FacultyValidationError):
        validate_faculty(sample_faculty(times={"FUNDAY": ["09:00-17:00"]}))


def test_validate_faculty_rejects_bad_time_format():
    with pytest.raises(FacultyValidationError):
        validate_faculty(sample_faculty(times={"MON": ["9am-5pm"]}))


def test_validate_faculty_rejects_out_of_range_preference_weight():
    with pytest.raises(FacultyValidationError):
        validate_faculty(sample_faculty(course_preferences={"CMSC 420": 15}))


def test_validate_faculty_allows_preference_for_course_that_does_not_exist_yet():
    # Deliberate design choice noted in facultyModel.py: cross-record
    # existence checks happen later, not here.
    record = sample_faculty(course_preferences={"CMSC 999": 7})
    assert validate_faculty(record) == record


# ---------- Faculty.facCheck / getFaculty (EXACT match, not substring) ----------

def test_facCheck_true_on_exact_match():
    faculty_list = [sample_faculty(name="Bob")]
    assert Faculty.facCheck(faculty_list, "Bob") is True


def test_facCheck_false_on_substring_match():
    # "Bobby" existing should NOT block/match a search for "Bob"
    faculty_list = [sample_faculty(name="Bobby")]
    assert Faculty.facCheck(faculty_list, "Bob") is False


def test_getFaculty_returns_none_when_not_found():
    assert Faculty.getFaculty([], "Nobody") is None


# ---------- Faculty.addFaculty ----------

def test_addFaculty_appends_valid_record():
    faculty_list = []
    Faculty.addFaculty(faculty_list, sample_faculty())
    assert len(faculty_list) == 1
    assert faculty_list[0]["name"] == "Dr. Smith"


def test_addFaculty_raises_and_does_not_append_invalid_record():
    faculty_list = []
    with pytest.raises(FacultyValidationError):
        Faculty.addFaculty(faculty_list, sample_faculty(name=""))
    assert faculty_list == []  # nothing was added


# ---------- Faculty.removeFaculty ----------

def test_removeFaculty_removes_and_returns_matching_record():
    faculty_list = [sample_faculty(name="Bob"), sample_faculty(name="Bobby")]
    removed = Faculty.removeFaculty(faculty_list, "Bob")
    assert removed["name"] == "Bob"
    assert [f["name"] for f in faculty_list] == ["Bobby"]  # "Bobby" untouched


def test_removeFaculty_returns_none_when_not_found():
    faculty_list = [sample_faculty(name="Bob")]
    assert Faculty.removeFaculty(faculty_list, "Nobody") is None
    assert len(faculty_list) == 1  # unchanged