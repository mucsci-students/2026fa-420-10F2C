"""Tests for the Faculty Configuration Editor MVC slice.

The controller tests use the real example configuration and scheduler model.
The browser tests verify the same add/edit/delete shape already used by Rooms
and Labs, including blocked deletes when a course explicitly assigns faculty.
"""

import pytest

from app.session import Session
from gui import session_store
from gui.controllers import faculty as faculty_controller
from gui.controllers.errors import ControllerError
from gui.forms import FacultyForm

EXAMPLE = "app/examples/config_example.json"
FACULTY_URL = "/configuration/faculty/"


def new_faculty_data(**overrides):
    """Return form/controller data that is valid against the example config."""
    data = {
        "name": "Taylor",
        "minimum_credits": 0,
        "maximum_credits": 4,
        "unique_course_limit": 1,
        "maximum_days": 2,
        "times": {"MON": [{"start": "09:00", "end": "12:00"}]},
        "mandatory_days": ["MON"],
        "course_preferences": {"CMSC 140": 0},
        "room_preferences": {"Roddy 136": 5},
        "lab_preferences": {"Linux": 5},
    }
    data.update(overrides)
    return data


def find_faculty(session, name):
    """Find a faculty model by its unique name."""
    return next((person for person in session.config.config.faculty if person.name == name), None)


@pytest.fixture
def session(monkeypatch):
    """Provide the real example configuration to controller calls."""
    loaded = Session()
    loaded.load(EXAMPLE)
    monkeypatch.setattr(faculty_controller, "get_session", lambda request: loaded)
    return loaded


class TestFacultyForm:
    def test_collects_weighted_preferences_and_keeps_zero(self):
        """A blank preference is omitted while zero remains an explicit weight."""
        form = FacultyForm(
            data={
                "name": "Taylor",
                "minimum_credits": "0",
                "maximum_credits": "4",
                "unique_course_limit": "1",
                "maximum_days": "2",
                "times": "MON 09:00-12:00",
                "mandatory_days": ["MON"],
                "course_preference_0": "0",
                "room_preference_0": "5",
            },
            course_names=["CMSC 140"],
            room_names=["Roddy 136"],
            lab_names=["Linux"],
        )

        assert form.is_valid()
        assert form.cleaned_data["course_preferences"] == {"CMSC 140": 0}
        assert form.cleaned_data["room_preferences"] == {"Roddy 136": 5}
        assert form.cleaned_data["lab_preferences"] == {}


class TestFacultyController:
    def test_adds_a_faculty_member_and_marks_the_session_dirty(self, session):
        faculty_controller.add_faculty(None, new_faculty_data())

        added = find_faculty(session, "Taylor")
        assert added is not None
        assert added.minimum_credits == 0
        assert added.maximum_credits == 4
        assert added.course_preferences == {"CMSC 140": 0}
        assert session.dirty is True

    def test_invalid_workload_keeps_the_previous_configuration(self, session):
        before = session.dumps()

        with pytest.raises(ControllerError) as info:
            faculty_controller.add_faculty(None, new_faculty_data(minimum_credits=5, maximum_credits=4))

        assert "Maximum credits must be at least minimum credits" in info.value.message
        assert session.dumps() == before
        assert session.dirty is False

    def test_referenced_faculty_cannot_be_renamed_or_deleted(self, session):
        renamed = new_faculty_data(name="Zoppetti Renamed")

        with pytest.raises(ControllerError) as rename_error:
            faculty_controller.update_faculty(None, "Zoppetti", renamed)
        with pytest.raises(ControllerError) as delete_error:
            faculty_controller.delete_faculty(None, "Zoppetti")

        assert "still referenced" in rename_error.value.message
        assert "CMSC 161" in delete_error.value.message
        assert find_faculty(session, "Zoppetti") is not None
        assert session.dirty is False

    def test_unreferenced_faculty_can_be_updated_and_deleted(self, session):
        faculty_controller.add_faculty(None, new_faculty_data())
        faculty_controller.update_faculty(None, "Taylor", new_faculty_data(name="Taylor Updated", maximum_credits=6))
        faculty_controller.delete_faculty(None, "Taylor Updated")

        assert find_faculty(session, "Taylor") is None
        assert find_faculty(session, "Taylor Updated") is None
        assert session.dirty is True


@pytest.fixture(autouse=True)
def fresh_session_store():
    """Keep each browser test bound to a separate in-memory Session."""
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


def browser_session():
    """Return the one Session created by the current Django test client."""
    return next(iter(session_store._SESSIONS.values()))


def page(response):
    """Decode a Django test response for text assertions."""
    return response.content.decode()


def browser_form_data(**overrides):
    """Return POST values for an unreferenced FacultyForm submission."""
    data = {
        "name": "Taylor",
        "minimum_credits": "0",
        "maximum_credits": "4",
        "unique_course_limit": "1",
        "maximum_days": "2",
        "times": "MON 09:00-12:00",
        "mandatory_days": ["MON"],
    }
    data.update(overrides)
    return data


class TestFacultyPages:
    def test_editor_links_to_faculty_and_the_list_shows_example_data(self, client):
        editor = page(client.get("/configuration/"))
        response = client.get(FACULTY_URL)

        assert f'href="{FACULTY_URL}"' in editor
        assert response.status_code == 200
        assert "Zoppetti" in page(response)

    def test_add_edit_and_delete_unreferenced_faculty(self, client):
        client.get(FACULTY_URL)
        added = client.post(FACULTY_URL + "add/", browser_form_data(), follow=True)
        assert "Taylor" in page(added) and "added" in page(added)
        assert find_faculty(browser_session(), "Taylor") is not None

        edited = client.post(
            FACULTY_URL + "Taylor/edit/",
            browser_form_data(name="Taylor Updated", maximum_credits="6"),
            follow=True,
        )
        assert "Taylor Updated" in page(edited) and "updated" in page(edited)
        assert find_faculty(browser_session(), "Taylor Updated").maximum_credits == 6

        deleted = client.post(FACULTY_URL + "Taylor%20Updated/delete/", {"action": "confirm"}, follow=True)
        assert "Taylor Updated" in page(deleted) and "deleted" in page(deleted)
        assert find_faculty(browser_session(), "Taylor Updated") is None

    def test_referenced_faculty_has_no_delete_confirmation(self, client):
        client.get(FACULTY_URL)
        response = client.get(FACULTY_URL + "Zoppetti/delete/")

        assert "Cannot delete" in page(response)
        assert 'value="confirm"' not in page(response)