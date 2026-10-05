"""
Tests for the Rooms and Labs pages (Sprint 2 Section 7) and the forms behind
them (gui/forms.py, gui/views_rooms.py, gui/views_labs.py).

Rooms and labs behave the same, so every page test runs once for each. They run
against the REAL scheduler library and the shipped example configuration, where
every room and lab is used by a course: that is what makes "cannot delete" and
"cannot rename" testable. To test a delete that works, a test adds a new,
unused room/lab first.
"""

from urllib.parse import quote

import pytest

from gui import session_store
from gui.forms import availability_to_text, parse_availability

KINDS = {
    "room": {"base": "/configuration/rooms/", "collection": "rooms", "existing": "Roddy 136"},
    "lab": {"base": "/configuration/labs/", "collection": "labs", "existing": "Linux"},
}


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


@pytest.fixture(params=list(KINDS))
def kind(request):
    return {"key": request.param, **KINDS[request.param]}


def browser_session():
    """The single Session the current test client created."""
    return next(iter(session_store._SESSIONS.values()))


def page(response):
    return response.content.decode()


def items(kind):
    return getattr(browser_session().config.config, kind["collection"])


def find(kind, name):
    return next((item for item in items(kind) if item.name == name), None)


def edit_url(kind, name):
    return f"{kind['base']}{quote(name)}/edit/"


def delete_url(kind, name):
    return f"{kind['base']}{quote(name)}/delete/"


def rename_confirm_url(kind, name):
    return f"{kind['base']}{quote(name)}/rename/confirm/"


def new_item(**overrides):
    data = {"name": "Annex 1", "capacity": "20", "features": "projector, whiteboard", "times": ""}
    data.update(overrides)
    return data


# ---------------------------------------------------------------------- #
#  The availability text helpers
# ---------------------------------------------------------------------- #
def test_blank_availability_means_any_time():
    assert parse_availability("  \n ") == (None, [])


def test_availability_lines_are_read_and_padded():
    times, problems = parse_availability("mon 9:00-17:00\nMON 18:00 - 19:00\nTUE 08:30-10:00")
    assert problems == []
    assert times == {
        "MON": [{"start": "09:00", "end": "17:00"}, {"start": "18:00", "end": "19:00"}],
        "TUE": [{"start": "08:30", "end": "10:00"}],
    }


def test_availability_problems_name_the_line():
    _, problems = parse_availability("MON 09:00-17:00\nSUN 09:00-17:00\nMON 9-5\nTUE 25:00-26:00")
    assert len(problems) == 3
    assert "Line 2" in problems[0] and "not a weekday" in problems[0]
    assert "Line 3" in problems[1] and "MON 09:00-17:00" in problems[1]
    assert "Line 4" in problems[2] and "24-hour" in problems[2]


def test_availability_text_round_trips():
    text = "MON 09:00-17:00\nMON 18:00-19:00\nWED 08:00-12:00"
    times, _ = parse_availability(text)
    assert availability_to_text(times) == text
    assert availability_to_text(None) == ""


# ---------------------------------------------------------------------- #
#  Pages (through Django's test client)
# ---------------------------------------------------------------------- #
def test_editor_home_links_to_the_page(client, kind):
    text = page(client.get("/configuration/"))
    assert f'href="{kind["base"]}"' in text


def test_list_page_shows_the_existing_items(client, kind):
    response = client.get(kind["base"])
    assert response.status_code == 200
    text = page(response)
    assert kind["existing"] in text
    assert "Unsaved changes" not in text


def test_list_page_shows_the_empty_state_without_a_configuration(client, kind, monkeypatch):
    monkeypatch.setattr(session_store, "AUTO_LOAD_EXAMPLE", False)
    response = client.get(kind["base"])
    assert response.status_code == 200
    assert "No configuration is loaded" in page(response)


def test_adding_confirms_lists_it_and_flags_unsaved_changes(client, kind):
    data = new_item(times="MON 09:00-17:00")
    response = client.post(kind["base"] + "add/", data, follow=True)
    text = page(response)
    assert "Annex 1" in text and "added" in text
    assert "MON 09:00-17:00" in text
    assert "Unsaved changes" in text
    added = find(kind, "Annex 1")
    assert added.capacity == 20
    assert sorted(added.features) == ["projector", "whiteboard"]
    assert browser_session().dirty is True


def test_adding_a_duplicate_name_is_rejected(client, kind):
    client.get(kind["base"])  # creates the session
    before = len(items(kind))
    response = client.post(kind["base"] + "add/", new_item(name=kind["existing"]))
    assert response.status_code == 200
    assert "already exists" in page(response)
    assert len(items(kind)) == before


def test_bad_capacity_is_reported_on_the_form_and_keeps_what_was_typed(client, kind):
    client.get(kind["base"])
    before = len(items(kind))
    response = client.post(kind["base"] + "add/", new_item(capacity="0"))
    text = page(response)
    assert "greater than or equal to 1" in text
    assert "Annex 1" in text  # the typed name is still in the form
    response = client.post(kind["base"] + "add/", new_item(capacity="lots"))
    assert "Enter a whole number" in page(response)
    assert len(items(kind)) == before


def test_bad_availability_is_reported_and_nothing_is_added(client, kind):
    client.get(kind["base"])
    before = len(items(kind))
    response = client.post(kind["base"] + "add/", new_item(times="SUN 09:00-17:00"))
    assert "is not a weekday" in page(response)
    assert len(items(kind)) == before


def test_get_on_the_add_url_just_redirects(client, kind):
    assert client.get(kind["base"] + "add/").status_code == 302


def test_edit_page_shows_the_current_values_and_changes_nothing_until_submitted(client, kind):
    client.get(kind["base"])
    original = find(kind, kind["existing"]).capacity
    response = client.get(edit_url(kind, kind["existing"]))
    assert response.status_code == 200
    text = page(response)
    assert f'value="{kind["existing"]}"' in text
    assert f'value="{original}"' in text
    assert find(kind, kind["existing"]).capacity == original


def test_editing_applies_on_submit(client, kind):
    client.get(kind["base"])
    data = new_item(name=kind["existing"], capacity="30", features="", times="")
    response = client.post(edit_url(kind, kind["existing"]), data, follow=True)
    assert "updated" in page(response)
    assert find(kind, kind["existing"]).capacity == 30


def test_renaming_something_in_use_confirms_then_updates_all_references(client, kind):
    client.get(kind["base"])
    data = new_item(name="Renamed", capacity="30", features="", times="")
    preview = client.post(edit_url(kind, kind["existing"]), data)
    assert "Confirm" in page(preview)
    assert find(kind, kind["existing"]) is not None
    assert find(kind, "Renamed") is None

    response = client.post(
        rename_confirm_url(kind, kind["existing"]),
        {"confirmation_token": preview.context["confirmation_token"]},
        follow=True,
    )
    assert "associated references updated" in page(response)
    assert find(kind, kind["existing"]) is None
    assert find(kind, "Renamed") is not None

    course_field = kind["key"]
    preference_field = f"{kind['key']}_preferences"
    assert any("Renamed" in (getattr(course, course_field) or []) for course in browser_session().config.config.courses)
    assert all(kind["existing"] not in (getattr(course, course_field) or []) for course in browser_session().config.config.courses)
    assert any(
        "Renamed" in (getattr(person, preference_field) or {})
        for person in browser_session().config.config.faculty
    )


def test_editing_something_that_no_longer_exists_redirects_with_an_error(client, kind):
    response = client.get(edit_url(kind, "Nowhere 9"), follow=True)
    assert "no longer exists" in page(response)


def test_deleting_something_in_use_is_blocked_on_the_page_and_in_the_action(client, kind):
    client.get(kind["base"])
    text = page(client.get(delete_url(kind, kind["existing"])))
    assert "Cannot delete" in text
    assert 'value="confirm"' not in text
    response = client.post(delete_url(kind, kind["existing"]), {"action": "confirm"}, follow=True)
    assert f"Remove this {kind['key']} from those records first" in page(response)
    assert find(kind, kind["existing"]) is not None


def test_delete_asks_first_and_cancel_changes_nothing(client, kind):
    client.post(kind["base"] + "add/", new_item())
    text = page(client.get(delete_url(kind, "Annex 1")))
    assert "Are you sure" in text and "Annex 1" in text
    response = client.post(delete_url(kind, "Annex 1"), {"action": "cancel"}, follow=True)
    assert "Cancelled." in page(response)
    assert find(kind, "Annex 1") is not None


def test_confirming_a_delete_removes_it(client, kind):
    client.post(kind["base"] + "add/", new_item())
    response = client.post(delete_url(kind, "Annex 1"), {"action": "confirm"}, follow=True)
    assert "deleted" in page(response)
    assert find(kind, "Annex 1") is None
