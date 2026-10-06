"""
Tests for the Courses slice of the Configuration Editor: the controller
(gui/controllers/courses.py) called directly, then the pages
(gui/views_courses.py, CourseForm) through Django's test client.

Covers the Section 7 Courses row and Sprint 2 Sections 10, 11, 12, 19 and
23.2/23.6. Runs against the REAL scheduler library and the shipped example config.
Facts from that config the tests rely on (indexes are list positions):
    0, 1   CMSC 140 (two sections)      2   CMSC 152 (only Hardy prefers it)
    3      CMSC 161.01, faculty ["Zoppetti"], conflicts ["CMSC 140"]
    6      CMSC 162, the only section; CMSC 140's sections conflict with it,
           and Hogg prefers it
    Enabled class patterns exist for 3 and 4 credits, none for online delivery.
"""

import re

import pytest

from app.session import Session
from gui import session_store
from gui.controllers import courses as ctrl
from gui.controllers.errors import ControllerError

EXAMPLE = "app/examples/config_example.json"


@pytest.fixture
def session(monkeypatch):
    loaded = Session()
    loaded.load(EXAMPLE)
    monkeypatch.setattr(ctrl, "get_session", lambda request: loaded)
    return loaded


@pytest.fixture
def empty_session(monkeypatch):
    blank = Session()
    monkeypatch.setattr(ctrl, "get_session", lambda request: blank)
    return blank


def courses(session):
    return session.config.config.courses


def ids(session):
    return [course.course_id for course in courses(session)]


def valid_form(**overrides):
    form = {
        "course_id": "CMSC 500",
        "section_id": "",
        "credits": 4,
        "capacity": 24,
        "modality": "in_person",
        "room": ["Roddy 136", "Roddy 140"],
        "lab": ["Linux"],
        "conflicts": ["CMSC 140"],
        "faculty": ["Hardy"],
        "required_room_features": "",
        "required_lab_features": "",
        "reserve_room_during_lab": True,
    }
    form.update(overrides)
    return form


def fields_of(info):
    return {item.field for item in info.value.errors}


# ---------------------------------------------------------------------- #
#  Reads
# ---------------------------------------------------------------------- #
class TestReads:
    def test_list_numbers_sections_like_the_scheduler(self, session):
        rows = ctrl.describe_courses(None)["courses"]
        assert [row["display"] for row in rows[:3]] == ["CMSC 140.01", "CMSC 140.02", "CMSC 152.01"]
        assert rows[3]["faculty"] == ["Zoppetti"]

    def test_list_shows_who_a_preference_based_course_draws_from(self, session):
        row = ctrl.describe_courses(None)["courses"][2]
        assert row["faculty"] is None
        assert row["derived_faculty"] == ["Hardy"]

    def test_list_marks_which_sections_can_be_deleted(self, session):
        rows = ctrl.describe_courses(None)["courses"]
        assert rows[0]["can_delete"] is True  # another CMSC 140 section remains
        assert rows[6]["can_delete"] is False

    def test_list_without_a_config_reports_the_empty_state(self, empty_session):
        assert ctrl.describe_courses(None) == {"has_config": False}

    def test_get_course_round_trips_through_update_unchanged(self, session):
        before = courses(session)[3].model_dump()
        ctrl.update_course(None, 3, ctrl.get_course(None, 3))
        assert courses(session)[3].model_dump() == before

    def test_get_course_includes_its_display_name(self, session):
        assert ctrl.get_course(None, 1)["display"] == "CMSC 140.02"

    def test_choices_include_only_enabled_pattern_credits(self, session):
        choices = ctrl.form_choices(None)
        assert choices["credit_choices"] == [3, 4]


# ---------------------------------------------------------------------- #
#  Add
# ---------------------------------------------------------------------- #
class TestAdd:
    def test_adds_a_course_and_marks_the_session_dirty(self, session):
        count = len(courses(session))
        assert ctrl.add_course(None, valid_form()) == []
        added = courses(session)[-1]
        assert len(courses(session)) == count + 1
        assert (added.course_id, added.section_id, added.faculty) == ("CMSC 500", None, ["Hardy"])
        assert session.dirty is True

    def test_repeated_course_id_adds_another_section(self, session):
        ctrl.add_course(None, valid_form(course_id="CMSC 152", conflicts=[]))
        rows = ctrl.describe_courses(None)["courses"]
        assert rows[-1]["display"] == "CMSC 152.02"

    def test_text_values_are_accepted(self, session):
        ctrl.add_course(
            None,
            valid_form(room="Roddy 136, Roddy 147", lab="", conflicts="", required_room_features="projector"),
        )
        added = courses(session)[-1]
        assert added.room == ["Roddy 136", "Roddy 147"]
        assert added.required_room_features == {"projector"}

    def test_unknown_names_and_self_conflict_land_on_their_fields(self, session):
        with pytest.raises(ControllerError) as info:
            ctrl.add_course(
                None,
                valid_form(room=["Roddy 136", "Nope"], faculty=["Ghost"], conflicts=["CMSC 500"]),
            )
        assert fields_of(info) == {"room", "faculty", "conflicts"}
        assert session.dirty is False

    def test_credits_without_an_enabled_pattern_are_explained(self, session):
        with pytest.raises(ControllerError) as info:
            ctrl.add_course(None, valid_form(credits=7))
        assert fields_of(info) == {"credits"}
        assert "Enabled patterns have: 3, 4" in info.value.message

    def test_bad_numbers_and_modality_are_all_reported(self, session):
        with pytest.raises(ControllerError) as info:
            ctrl.add_course(None, valid_form(course_id=" ", capacity=0, modality="remote"))
        assert fields_of(info) == {"course_id", "capacity", "modality"}

    def test_no_faculty_and_no_preferences_is_rejected_on_the_faculty_field(self, session):
        count = len(courses(session))
        with pytest.raises(ControllerError) as info:
            ctrl.add_course(None, valid_form(faculty=[]))
        assert fields_of(info) == {"faculty"}
        assert len(courses(session)) == count

    def test_online_course_is_rejected_when_no_pattern_supports_it(self, session):
        with pytest.raises(ControllerError) as info:
            ctrl.add_course(None, valid_form(modality="online"))
        assert fields_of(info) == {"modality"}

    def test_duplicate_section_id_is_rejected(self, session):
        with pytest.raises(ControllerError):
            ctrl.add_course(None, valid_form(course_id="CMSC 140", section_id="01", conflicts=[]))

    def test_without_a_config_says_so(self, empty_session):
        with pytest.raises(ControllerError, match="No configuration is loaded"):
            ctrl.add_course(None, valid_form())


# ---------------------------------------------------------------------- #
#  Update
# ---------------------------------------------------------------------- #
class TestUpdate:
    def test_updates_the_section_in_place(self, session):
        form = ctrl.get_course(None, 3)
        ctrl.update_course(None, 3, {**form, "capacity": 40}, expected_course_id="CMSC 161")
        assert courses(session)[3].capacity == 40
        assert ids(session)[3] == "CMSC 161"

    def test_failed_update_keeps_the_previous_valid_record(self, session):
        before = courses(session)[3].model_dump()
        form = ctrl.get_course(None, 3)
        with pytest.raises(ControllerError):
            ctrl.update_course(None, 3, {**form, "faculty": ["Ghost"]})
        assert courses(session)[3].model_dump() == before
        assert session.dirty is False

    def test_stale_index_is_refused(self, session):
        form = ctrl.get_course(None, 3)
        with pytest.raises(ControllerError, match="course list changed"):
            ctrl.update_course(None, 3, form, expected_course_id="CMSC 999")

    def test_renaming_the_last_section_carries_references_along(self, session):
        form = ctrl.get_course(None, 6)
        notices = ctrl.update_course(None, 6, {**form, "course_id": "CMSC 262"}, expected_course_id="CMSC 162")
        assert ids(session)[6] == "CMSC 262"
        assert courses(session)[0].conflicts == ["CMSC 161", "CMSC 262"]
        hogg = next(f for f in session.config.config.faculty if f.name == "Hogg")
        assert "CMSC 262" in hogg.course_preferences and "CMSC 162" not in hogg.course_preferences
        assert notices == ["Renamed 'CMSC 162' to 'CMSC 262' in 2 course conflict lists and 1 faculty course preference."]

    def test_renaming_one_of_several_sections_leaves_references_alone(self, session):
        form = ctrl.get_course(None, 0)
        notices = ctrl.update_course(None, 0, {**form, "course_id": "CMSC 141", "conflicts": [], "faculty": ["Hardy"]})
        assert notices == []
        assert courses(session)[3].conflicts == ["CMSC 140"]  # still valid: 140.02 remains


# ---------------------------------------------------------------------- #
#  Delete (Section 12)
# ---------------------------------------------------------------------- #
class TestDelete:
    def test_one_of_several_sections_is_deleted(self, session):
        count = len(courses(session))
        ctrl.delete_course(None, 0, expected_course_id="CMSC 140")
        assert len(courses(session)) == count - 1
        assert ids(session)[0] == "CMSC 140"
        assert session.dirty is True

    def test_last_referenced_section_is_blocked_with_the_reasons(self, session):
        references = ctrl.get_course(None, 6)["referenced_by"]
        assert references == [
            "course CMSC 140.01 (conflicts)",
            "course CMSC 140.02 (conflicts)",
            "faculty Hogg (course preference)",
        ]
        with pytest.raises(ControllerError, match="Cannot delete 'CMSC 162'"):
            ctrl.delete_course(None, 6)
        assert "CMSC 162" in ids(session)
        assert session.dirty is False

    def test_stale_index_is_refused(self, session):
        with pytest.raises(ControllerError, match="course list changed"):
            ctrl.delete_course(None, 0, expected_course_id="CMSC 152")
        assert ids(session)[0] == "CMSC 140"

    def test_out_of_range_index_is_a_controller_error(self, session):
        with pytest.raises(ControllerError, match="no longer exists"):
            ctrl.delete_course(None, 999)


# ---------------------------------------------------------------------- #
#  Pages (through Django's test client)
# ---------------------------------------------------------------------- #
COURSES_URL = "/configuration/courses/"


@pytest.fixture
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


def browser_session():
    """The one Session the current test client created."""
    return next(iter(session_store._SESSIONS.values()))


def page(response):
    return response.content.decode()


def post_data(**overrides):
    data = {
        "course_id": "CMSC 500",
        "section_id": "",
        "credits": "4",
        "capacity": "24",
        "modality": "in_person",
        "room": ["Roddy 136"],
        "lab": ["Linux"],
        "faculty": ["Hardy"],
        "conflicts": [],
        "required_room_features": "",
        "required_lab_features": "",
        "reserve_room_during_lab": "on",
    }
    data.update(overrides)
    return data


@pytest.mark.usefixtures("fresh_session_store")
class TestPages:
    def test_editor_links_to_courses_and_the_list_shows_sections(self, client):
        editor = page(client.get("/configuration/"))
        response = client.get(COURSES_URL)
        assert f'href="{COURSES_URL}"' in editor
        assert response.status_code == 200
        assert "CMSC 140.02" in page(response)
        assert "From preferences: Hardy" in page(response)

    def test_list_shows_the_empty_state_without_a_configuration(self, client, monkeypatch):
        monkeypatch.setattr(session_store, "AUTO_LOAD_EXAMPLE", False)
        response = client.get(COURSES_URL)
        assert "No configuration is loaded" in page(response)
        assert client.get(COURSES_URL + "add/").status_code == 302

    def test_add_page_offers_this_configurations_choices(self, client):
        text = page(client.get(COURSES_URL + "add/"))
        assert 'value="Roddy 147"' in text
        assert 'value="Zoppetti"' in text
        assert "Must match an enabled class pattern: 3, 4." in text

    def test_adding_a_course_lists_it_and_flags_unsaved_changes(self, client):
        client.get(COURSES_URL)
        response = client.post(COURSES_URL + "add/", post_data(), follow=True)
        assert "Course &#x27;CMSC 500&#x27; added." in page(response)
        added = browser_session().config.config.courses[-1]
        assert (added.course_id, added.room, added.lab, added.faculty) == (
            "CMSC 500", ["Roddy 136"], ["Linux"], ["Hardy"],
        )
        assert browser_session().dirty is True

    def test_rejected_add_stays_on_the_form_and_keeps_the_input(self, client):
        client.get(COURSES_URL)
        count = len(browser_session().config.config.courses)
        response = client.post(COURSES_URL + "add/", post_data(credits="7", course_id="CMSC 777"))
        text = page(response)
        assert response.status_code == 200
        assert "No enabled class pattern has 7 credits" in text
        assert 'value="CMSC 777"' in text
        assert len(browser_session().config.config.courses) == count

    def test_unchecking_reserve_room_saves_false(self, client):
        client.get(COURSES_URL)
        data = post_data()
        del data["reserve_room_during_lab"]
        client.post(COURSES_URL + "add/", data)
        assert browser_session().config.config.courses[-1].reserve_room_during_lab is False

    def test_edit_page_is_prefilled_and_applies_changes(self, client):
        text = page(client.get(COURSES_URL + "3/edit/"))
        assert "CMSC 161.01" in text
        assert 'name="expected_course_id" value="CMSC 161"' in text
        checked = re.findall(r'<input type="checkbox" name="(\w+)" value="([^"]+)"[^>]*checked>', text)
        assert ("faculty", "Zoppetti") in checked
        assert ("conflicts", "CMSC 140") in checked
        assert ("room", "Roddy 136") in checked
        response = client.post(
            COURSES_URL + "3/edit/",
            post_data(course_id="CMSC 161", capacity="40", faculty=["Zoppetti"], conflicts=["CMSC 140"], expected_course_id="CMSC 161"),
            follow=True,
        )
        assert "updated" in page(response)
        assert browser_session().config.config.courses[3].capacity == 40

    def test_edit_of_a_stale_row_is_refused(self, client):
        client.get(COURSES_URL)
        before = browser_session().config.config.courses[3].model_dump()
        response = client.post(COURSES_URL + "3/edit/", post_data(expected_course_id="CMSC 999"))
        assert "course list changed" in page(response)
        assert browser_session().config.config.courses[3].model_dump() == before

    def test_cancel_on_delete_changes_nothing(self, client):
        client.get(COURSES_URL)
        count = len(browser_session().config.config.courses)
        response = client.post(COURSES_URL + "0/delete/", {"action": "cancel", "expected_course_id": "CMSC 140"}, follow=True)
        assert "Cancelled." in page(response)
        assert len(browser_session().config.config.courses) == count
        assert browser_session().dirty is False

    def test_delete_one_of_several_sections(self, client):
        client.get(COURSES_URL)
        count = len(browser_session().config.config.courses)
        response = client.post(COURSES_URL + "0/delete/", {"action": "confirm", "expected_course_id": "CMSC 140"}, follow=True)
        assert "deleted" in page(response)
        assert len(browser_session().config.config.courses) == count - 1

    def test_referenced_last_section_shows_why_instead_of_a_delete_button(self, client):
        listing = page(client.get(COURSES_URL))
        text = page(client.get(COURSES_URL + "6/delete/"))
        assert "In use by course CMSC 140.01 (conflicts)" in listing
        assert "Cannot delete:" in text
        assert "faculty Hogg (course preference)" in text
        assert 'value="confirm"' not in text

    def test_unknown_row_redirects_with_a_message(self, client):
        response = client.get(COURSES_URL + "999/edit/", follow=True)
        assert "no longer exists" in page(response)
