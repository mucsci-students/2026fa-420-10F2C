"""Focused form and controller tests for Course Configuration Editor CRUD."""

import pytest

from app.session import Session
from gui import session_store
from gui.controllers import courses as course_controller
from gui.controllers.errors import ControllerError
from gui.forms import CourseForm

EXAMPLE = "app/examples/config_example.json"
COURSES_URL = "/configuration/courses/"


def new_course_data(**overrides):
    """Return data for a standalone section that fits the example config."""
    data = {
        "course_id": "CMSC 499",
        "section_id": "01",
        "credits": 4,
        "capacity": 20,
        "room": ["Roddy 136"],
        "lab": [],
        "conflicts": [],
        "faculty": ["Zoppetti"],
        "modality": "in_person",
        "required_room_features": [],
        "required_lab_features": [],
        "reserve_room_during_lab": True,
    }
    data.update(overrides)
    return data


@pytest.fixture
def session(monkeypatch):
    """Provide a real scheduler configuration to each controller test."""
    loaded = Session()
    loaded.load(EXAMPLE)
    monkeypatch.setattr(course_controller, "get_session", lambda request: loaded)
    return loaded


class TestCourseForm:
    def test_maps_resource_choices_and_blank_faculty_to_course_data(self):
        """The form keeps selected names as lists and blanks as derived faculty."""
        form = CourseForm(
            data={
                "course_id": "CMSC 499",
                "section_id": "01",
                "credits": "4",
                "capacity": "20",
                "modality": "in_person",
                "room": ["Roddy 136"],
                "lab": ["Linux"],
                "conflicts": ["CMSC 140"],
                "required_room_features": "projector, whiteboard",
                "required_lab_features": "computers",
                "reserve_room_during_lab": "on",
            },
            course_names=["CMSC 140"],
            room_names=["Roddy 136"],
            lab_names=["Linux"],
            faculty_names=["Zoppetti"],
        )

        assert form.is_valid()
        assert form.cleaned_data["room"] == ["Roddy 136"]
        assert form.cleaned_data["lab"] == ["Linux"]
        assert form.cleaned_data["faculty"] is None
        assert form.cleaned_data["section_id"] == "01"


class TestCourseController:
    def test_adds_a_course_and_marks_the_session_dirty(self, session):
        """A valid CourseConfig is appended through the atomic edit helper."""
        course_controller.add_course(None, new_course_data())

        added = session.config.config.courses[-1]
        assert added.course_id == "CMSC 499"
        assert added.section_id == "01"
        assert added.room == ["Roddy 136"]
        assert added.faculty == ["Zoppetti"]
        assert session.dirty is True

    def test_invalid_course_keeps_the_previous_configuration(self, session):
        """Local validation failures leave the serialized config untouched."""
        before = session.dumps()

        with pytest.raises(ControllerError) as info:
            course_controller.add_course(None, new_course_data(capacity=0))

        assert "positive whole number" in info.value.message
        assert session.dumps() == before
        assert session.dirty is False

    def test_last_referenced_course_section_cannot_be_renamed_or_deleted(self, session):
        """Changing a final ID cannot leave conflicts or preferences dangling."""
        index = next(index for index, course in enumerate(session.config.config.courses) if course.course_id == "CMSC 162")
        renamed = new_course_data(course_id="CMSC 999")

        with pytest.raises(ControllerError) as rename_error:
            course_controller.update_course(None, index, renamed)
        with pytest.raises(ControllerError) as delete_error:
            course_controller.delete_course(None, index)

        assert "CMSC 162" in rename_error.value.message
        assert "CMSC 162" in delete_error.value.message
        assert session.config.config.courses[index].course_id == "CMSC 162"
        assert session.dirty is False

    def test_nonfinal_section_can_be_deleted_and_unreferenced_section_can_change(self, session):
        """References protect course IDs, not individual sections with siblings."""
        first_cmsc_140 = next(index for index, course in enumerate(session.config.config.courses) if course.course_id == "CMSC 140")
        course_controller.delete_course(None, first_cmsc_140)
        assert sum(course.course_id == "CMSC 140" for course in session.config.config.courses) == 1

        course_controller.add_course(None, new_course_data())
        added_index = len(session.config.config.courses) - 1
        course_controller.update_course(None, added_index, new_course_data(course_id="CMSC 498", section_id=None))
        course_controller.delete_course(None, added_index)

        assert not any(course.course_id == "CMSC 498" for course in session.config.config.courses)

    def test_confirmed_final_course_rename_updates_conflicts_and_preferences(self, session):
        """A final course ID renames all references in one atomic edit."""
        index = next(index for index, course in enumerate(session.config.config.courses) if course.course_id == "CMSC 162")
        fields = session.config.config.courses[index].model_dump(mode="json")
        fields["course_id"] = "CMSC 163"
        fields["faculty"] = ["Hogg"]

        course_controller.rename_course_and_update_references(None, index, fields)

        assert session.config.config.courses[index].course_id == "CMSC 163"
        assert all("CMSC 162" not in (course.conflicts or []) for course in session.config.config.courses)
        hogg = next(person for person in session.config.config.faculty if person.name == "Hogg")
        assert "CMSC 162" not in hogg.course_preferences
        assert hogg.course_preferences["CMSC 163"] == 5
        assert session.dirty is True

    def test_course_rename_does_not_overwrite_an_existing_preference_key(self, session):
        """Faculty preference weights must be resolved manually before a key collision."""
        index = next(index for index, course in enumerate(session.config.config.courses) if course.course_id == "CMSC 162")
        fields = session.config.config.courses[index].model_dump(mode="json")
        fields["course_id"] = "CMSC 380"
        fields["faculty"] = ["Hogg"]

        with pytest.raises(ControllerError) as info:
            course_controller.rename_impact(None, index, fields)

        assert "already has a preference" in info.value.message
        assert session.config.config.courses[index].course_id == "CMSC 162"
        assert session.dirty is False


@pytest.fixture(autouse=True)
def fresh_session_store():
    """Keep each browser test bound to a separate in-memory Session."""
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


def browser_session():
    """Return the Session assigned to the current Django test client."""
    return next(iter(session_store._SESSIONS.values()))


def page(response):
    """Decode a Django test response for concise page assertions."""
    return response.content.decode()


def browser_form_data(**overrides):
    """Return POST values for a CourseForm submission against the example."""
    data = {
        "course_id": "CMSC 499",
        "section_id": "01",
        "credits": "4",
        "capacity": "20",
        "modality": "in_person",
        "room": ["Roddy 136"],
        "lab": [],
        "conflicts": [],
        "faculty": ["Zoppetti"],
        "required_room_features": "",
        "required_lab_features": "",
        "reserve_room_during_lab": "on",
    }
    data.update(overrides)
    return data


class TestCoursePages:
    def test_editor_links_to_courses_and_the_list_shows_example_data(self, client):
        """Courses are reachable from the editor and list the loaded sections."""
        editor = page(client.get("/configuration/"))
        response = client.get(COURSES_URL)

        assert f'href="{COURSES_URL}"' in editor
        assert response.status_code == 200
        assert "CMSC 140" in page(response)
        assert "Zoppetti" in page(response)
        assert "Faculty members:" not in page(response)
        assert "Derived from preferences" not in page(response)
        assert f'href="{COURSES_URL}add/"' in page(response)

    def test_add_page_displays_a_blank_course_form(self, client):
        """The lengthy Course form lives on its own page, not in the list."""
        response = client.get(COURSES_URL + "add/")
        text = page(response)

        assert response.status_code == 200
        assert "Add course section" in text
        assert 'name="course_id"' in text
        assert 'name="required_room_features"' in text
        assert f'href="{COURSES_URL}"' in text

    def test_invalid_add_keeps_values_on_the_add_page(self, client):
        """Form errors keep the browser on the dedicated add page."""
        response = client.post(COURSES_URL + "add/", browser_form_data(capacity="many"))
        text = page(response)

        assert response.status_code == 200
        assert "Add course section" in text
        assert "Enter a whole number" in text
        assert 'value="CMSC 499"' in text
        assert not any(course.course_id == "CMSC 499" for course in browser_session().config.config.courses)

    def test_add_edit_and_delete_unreferenced_course(self, client):
        """A standalone section completes the same HTTP CRUD cycle as Faculty."""
        client.get(COURSES_URL + "add/")
        added = client.post(COURSES_URL + "add/", browser_form_data(), follow=True)
        assert "CMSC 499" in page(added) and "added" in page(added)

        added_index = len(browser_session().config.config.courses) - 1
        edited = client.post(
            f"{COURSES_URL}{added_index}/edit/",
            browser_form_data(course_id="CMSC 498", section_id="02"),
            follow=True,
        )
        assert "CMSC 498" in page(edited) and "updated" in page(edited)
        assert browser_session().config.config.courses[added_index].course_id == "CMSC 498"

        deleted = client.post(f"{COURSES_URL}{added_index}/delete/", {"action": "confirm"}, follow=True)
        assert "CMSC 498" in page(deleted) and "deleted" in page(deleted)
        assert not any(course.course_id == "CMSC 498" for course in browser_session().config.config.courses)

    def test_final_course_rename_confirms_then_updates_all_references(self, client):
        """The shared confirmation page is used before updating a final course ID."""
        client.get(COURSES_URL)
        course_index = next(
            index
            for index, course in enumerate(browser_session().config.config.courses)
            if course.course_id == "CMSC 162"
        )
        preview = client.post(
            f"{COURSES_URL}{course_index}/edit/",
            browser_form_data(course_id="CMSC 163", faculty=["Hogg"]),
        )

        assert preview.status_code == 200
        assert "Confirm course ID rename" in page(preview)
        assert "CMSC 140" in page(preview)
        assert browser_session().config.config.courses[course_index].course_id == "CMSC 162"

        confirmed = client.post(
            f"{COURSES_URL}{course_index}/rename/confirm/",
            {"confirmation_token": preview.context["confirmation_token"]},
            follow=True,
        )
        assert "associated references updated" in page(confirmed)
        assert browser_session().config.config.courses[course_index].course_id == "CMSC 163"
        assert all("CMSC 162" not in (course.conflicts or []) for course in browser_session().config.config.courses)
        hogg = next(person for person in browser_session().config.config.faculty if person.name == "Hogg")
        assert "CMSC 162" not in hogg.course_preferences
        assert "CMSC 163" in hogg.course_preferences

    def test_referenced_final_section_has_no_delete_confirmation(self, client):
        """The delete page blocks records that would leave dangling course IDs."""
        client.get(COURSES_URL)
        protected_index = next(
            index
            for index, course in enumerate(browser_session().config.config.courses)
            if course.course_id == "CMSC 162"
        )
        response = client.get(f"{COURSES_URL}{protected_index}/delete/")

        assert "Cannot delete" in page(response)
        assert 'value="confirm"' not in page(response)