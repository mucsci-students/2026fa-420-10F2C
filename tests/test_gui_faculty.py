"""Tests for the Faculty Configuration Editor MVC slice.

The controller tests use the real example configuration and scheduler model.
The browser tests verify the same add/edit/delete shape already used by Rooms
and Labs, including blocked deletes when a course explicitly assigns faculty.
"""

import re
from pathlib import Path
from typing import cast

import pytest
from django.template.loader import render_to_string

from app.session import Session
from gui import session_store
from gui.controllers import faculty as faculty_controller
from gui.controllers.errors import ControllerError
from gui.forms import FacultyForm
from tests.canonical import canonical

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
    return next(
        (person for person in session.config.config.faculty if person.name == name),
        None,
    )


def existing_faculty_data(faculty, name):
    """Copy one scheduler faculty record into controller-ready edit data."""
    data = faculty.model_dump(mode="json")
    data["name"] = name
    return data


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

    def test_grouped_fields_render_shared_inline_errors(self):
        """Faculty add and edit use the same field groups and error markup."""
        form = FacultyForm(
            data={
                "name": "Taylor",
                "minimum_credits": "0",
                "maximum_credits": "many",
                "unique_course_limit": "1",
                "maximum_days": "2",
                "times": "MON 09:00-12:00",
                "mandatory_days": ["MON"],
            }
        )

        assert not form.is_valid()
        markup = render_to_string("gui/components/faculty_fields.html", {"form": form})

        for heading in (
            "Identity and workload",
            "Availability and mandatory days",
            "Course preferences",
            "Room preferences",
            "Lab preferences",
        ):
            assert heading in markup
        assert 'class="field field--error"' in markup
        assert 'role="alert"' in markup
        assert "Enter a whole number" in markup


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
            faculty_controller.add_faculty(
                None, new_faculty_data(minimum_credits=5, maximum_credits=4)
            )

        assert "Maximum credits must be at least minimum credits" in info.value.message
        assert session.dumps() == before
        assert session.dirty is False

    def test_a_referenced_faculty_member_is_deleted_in_one_step_with_the_sections_only_they_could_teach(
        self, session
    ):
        """Zoppetti is the only person who could teach two sections, so deleting them deletes those too."""
        sections = len(session.config.config.courses)
        notices = faculty_controller.delete_faculty(None, "Zoppetti")

        assert find_faculty(session, "Zoppetti") is None
        assert len(session.config.config.courses) == sections - 2
        assert notices[-1].startswith("Also deleted 2 course sections")
        assert session.dirty is True

    def test_deleting_a_referenced_faculty_member_cleans_up_their_courses_in_one_undoable_step(
        self, session
    ):
        before = canonical(session.dumps())

        notices = faculty_controller.delete_faculty(None, "Zoppetti")

        assert find_faculty(session, "Zoppetti") is None
        assert all(
            "Zoppetti" not in (course.faculty or [])
            for course in session.config.config.courses
        )
        assert (
            session.config.config.courses[3].faculty is None
        )  # nobody is named in their place
        assert any(
            "Removed 'Zoppetti' from 1 course section" in note for note in notices
        )
        assert session.history.undo_label == "Delete faculty 'Zoppetti'"
        session.history.undo(session)
        assert canonical(session.dumps()) == before

    def test_referenced_faculty_update_changes_explicit_course_assignments_atomically(
        self, session
    ):
        """A direct update keeps the faculty name and course assignments in sync."""
        original = find_faculty(session, "Zoppetti")
        notices = faculty_controller.update_faculty(
            None,
            "Zoppetti",
            existing_faculty_data(original, "Zoppetti Renamed"),
        )

        assert notices == [
            "Renamed 'Zoppetti' to 'Zoppetti Renamed' in 1 course faculty assignment."
        ]
        assert find_faculty(session, "Zoppetti") is None
        assert find_faculty(session, "Zoppetti Renamed") is not None
        assert all(
            "Zoppetti" not in (course.faculty or [])
            for course in session.config.config.courses
        )
        assert any(
            "Zoppetti Renamed" in (course.faculty or [])
            for course in session.config.config.courses
        )
        assert session.dirty is True

    def test_unreferenced_faculty_can_be_updated_and_deleted(self, session):
        faculty_controller.add_faculty(None, new_faculty_data())
        faculty_controller.update_faculty(
            None, "Taylor", new_faculty_data(name="Taylor Updated", maximum_credits=6)
        )
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
        assert f'href="{FACULTY_URL}add/"' in page(response)
        assert 'name="minimum_credits"' not in page(response)

    def test_add_page_displays_a_blank_grouped_form(self, client):
        response = client.get(FACULTY_URL + "add/")
        text = page(response)

        assert response.status_code == 200
        for heading in (
            "Identity and workload",
            "Availability and mandatory days",
            "Course preferences",
            "Room preferences",
            "Lab preferences",
        ):
            assert heading in text
        assert 'name="name"' in text
        assert 'href="/configuration/faculty/"' in text

    def test_add_without_a_configuration_returns_to_the_faculty_empty_state(
        self, client, monkeypatch
    ):
        """Faculty add follows the Course add flow when no config is loaded."""
        monkeypatch.setattr(session_store, "AUTO_LOAD_EXAMPLE", False)

        response = client.get(FACULTY_URL + "add/")

        assert response.status_code == 302
        assert response["Location"] == FACULTY_URL
        assert "No configuration is loaded" in page(client.get(FACULTY_URL))

    def test_invalid_add_stays_on_the_add_page_and_keeps_its_values(self, client):
        response = client.post(
            FACULTY_URL + "add/", browser_form_data(maximum_credits="many")
        )
        text = page(response)

        assert response.status_code == 200
        assert "Add faculty member" in text
        assert "Enter a whole number" in text
        assert 'value="Taylor"' in text
        assert find_faculty(browser_session(), "Taylor") is None

    def test_canceling_an_add_leaves_the_configuration_unchanged(self, client):
        client.get(FACULTY_URL + "add/")
        response = client.get(FACULTY_URL)

        assert response.status_code == 200
        assert browser_session().dirty is False

    def test_add_edit_and_delete_unreferenced_faculty(self, client):
        client.get(FACULTY_URL + "add/")
        added = client.post(FACULTY_URL + "add/", browser_form_data(), follow=True)
        assert "Taylor" in page(added) and "added" in page(added)
        assert find_faculty(browser_session(), "Taylor") is not None

        refreshed = client.get(FACULTY_URL)
        assert refreshed.status_code == 200
        assert (
            len(
                [
                    person
                    for person in browser_session().config.config.faculty
                    if person.name == "Taylor"
                ]
            )
            == 1
        )

        edited = client.post(
            FACULTY_URL + "Taylor/edit/",
            browser_form_data(name="Taylor Updated", maximum_credits="6"),
            follow=True,
        )
        assert "Taylor Updated" in page(edited) and "updated" in page(edited)
        assert find_faculty(browser_session(), "Taylor Updated").maximum_credits == 6

        deleted = client.post(
            FACULTY_URL + "Taylor%20Updated/delete/", {"action": "confirm"}, follow=True
        )
        assert "Taylor Updated" in page(deleted) and "deleted" in page(deleted)
        assert find_faculty(browser_session(), "Taylor Updated") is None

    def test_referenced_faculty_update_changes_course_assignments(self, client):
        """A direct edit updates references and redirects to the Faculty list."""
        edit_page = client.get(FACULTY_URL + "Zoppetti/edit/")
        form = edit_page.context["form"]
        form_data = {
            field_name: value
            for field_name in form.fields
            if (value := form[field_name].value()) is not None
        }
        form_data["name"] = "Zoppetti Renamed"

        response = client.post(FACULTY_URL + "Zoppetti/edit/", form_data, follow=True)
        assert "updated" in page(response)
        assert "Renamed &#x27;Zoppetti&#x27; to &#x27;Zoppetti Renamed&#x27;" in page(
            response
        )
        assert find_faculty(browser_session(), "Zoppetti") is None
        assert find_faculty(browser_session(), "Zoppetti Renamed") is not None
        assert any(
            "Zoppetti Renamed" in (course.faculty or [])
            for course in browser_session().config.config.courses
        )

    def test_rename_confirmation_page_is_not_available(self, client):
        """Faculty now exposes only its direct edit endpoint."""
        assert client.get(FACULTY_URL + "Zoppetti/rename/confirm/").status_code == 404

    def test_usage_toggle_is_a_small_dropdown_icon_not_a_details_link(self, client):
        text = page(client.get(FACULTY_URL))
        assert '<details class="usage">' in text
        assert "usage__toggle" not in text
        assert ">details<" not in text

    def test_every_faculty_card_in_use_has_exactly_one_icon_after_its_last_chip(
        self, client
    ):
        text = page(client.get(FACULTY_URL))
        icons = re.findall(r'<svg class="usage__icon".*?</svg>', text, flags=re.DOTALL)
        summaries = re.findall(
            r'<details class="usage">\s*<summary>(.*?)</summary>', text, flags=re.DOTALL
        )
        assert summaries and len(icons) == len(summaries)
        for summary in summaries:
            assert summary.count("<svg") == 1
            assert re.search(
                r'<span class="chip[^"]*">[^<]*</span><svg class="usage__icon"', summary
            )
            assert summary.strip().endswith("</span>")
        assert not re.search(
            r'<span class="chip[^"]*">[^<]*<svg', text
        )  # never inside a chip

    def test_faculty_uses_the_identical_icon_as_rooms_and_labs(self, client):
        faculty = re.findall(
            r'<svg class="usage__icon".*?</svg>',
            page(client.get(FACULTY_URL)),
            flags=re.DOTALL,
        )
        others = set()
        for base in ("/configuration/rooms/", "/configuration/labs/"):
            others.update(
                re.findall(
                    r'<svg class="usage__icon".*?</svg>',
                    page(client.get(base)),
                    flags=re.DOTALL,
                )
            )
        assert faculty and len(set(faculty)) == 1
        assert set(faculty) == others and len(others) == 1

    def test_the_icon_is_hidden_from_screen_readers_but_keeps_an_accessible_name(
        self, client
    ):
        text = page(client.get(FACULTY_URL))
        assert 'aria-hidden="true"' in cast(
            "re.Match[str]",
            re.search(r'<svg class="usage__icon".*?</svg>', text, flags=re.DOTALL),
        ).group(0)
        assert '<span class="visually-hidden"> (show details)</span>' in text

    def test_a_member_nobody_uses_shows_no_icon_and_no_note(self, client):
        client.get(FACULTY_URL)
        assert (
            browser_session().config is not None
        )  # the example's 'sam' is used by no course
        text = page(client.get(FACULTY_URL))
        sam = text[text.index('<h3 class="item-card__title">sam</h3>') :]
        sam = sam[: sam.index("</article>")]
        assert "usage__icon" not in sam and "Not in use" not in sam

    def test_the_cards_do_not_need_their_own_icon_styles(self):
        css = Path("gui/static/gui/css/style.css").read_text()
        assert not re.search(
            r"item-card[^{]*usage__icon|usage__icon[^{]*item-card", css
        )
        assert not re.search(r"faculty[^{]*usage__icon|usage__icon[^{]*faculty", css)

    def test_the_icon_does_not_get_clipped_by_the_card_footer(self):
        css = Path("gui/static/gui/css/style.css").read_text()
        blocks = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
        # the footer ELEMENT itself (not its descendants or pseudo-elements, which may clip their own box)
        footer = {".item-card__foot", ".item-card__foot--usage"}
        foot = " ".join(
            body
            for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", blocks)
            if footer & {part.strip() for part in sel.split(",")}
        )
        card = " ".join(
            body
            for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", blocks)
            if sel.strip() == ".item-card"
        )
        assert "overflow" not in foot and not re.search(
            r"overflow:\s*(hidden|clip)", card
        )

    def test_referenced_faculty_delete_page_lists_the_sections_that_go_too_and_names_no_replacement(
        self, client
    ):
        client.get(FACULTY_URL)
        response = client.get(FACULTY_URL + "Zoppetti/delete/")
        text = page(response)

        assert "CMSC 362.01" in text and "CMSC 476.01" in text
        assert 'name="confirm_extra"' not in text and 'type="checkbox"' not in text
        assert "Who takes over?" not in text
        assert 'name="choice_3"' not in text
        assert 'value="confirm"' in text
        assert "Cannot delete" not in text

    def test_referenced_faculty_can_be_deleted_in_one_click_and_the_list_says_what_uses_them(
        self, client
    ):
        listing = page(client.get(FACULTY_URL))
        assert "candidate: 2" in listing

        response = client.post(
            FACULTY_URL + "Zoppetti/delete/", {"action": "confirm"}, follow=True
        )
        assert response.status_code == 200
        assert "deleted" in page(response)
        assert "nothing was changed" not in page(response)
        assert "Also deleted 2 course sections" in page(response)
        assert find_faculty(browser_session(), "Zoppetti") is None
