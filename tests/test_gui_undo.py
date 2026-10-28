"""
Tests for Undo / Redo through the web pages (Sprint 2 Sections 11, 12, 23).

They run against the REAL scheduler library and the shipped example
configuration (3 rooms, 2 labs, 17 course sections, 10 faculty).
"""

from urllib.parse import quote

import pytest

from gui import session_store
from tests.canonical import canonical

ROOMS = "/configuration/rooms/"
LABS = "/configuration/labs/"
UNDO = "/configuration/history/undo/"
REDO = "/configuration/history/redo/"


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


def browser_session():
    return next(iter(session_store._SESSIONS.values()))


def page(response):
    return response.content.decode()


def config_json():
    """The whole current configuration, exactly as the library serializes it."""
    return canonical(browser_session().config.model_dump_json())


def delete_big_room(client):
    """Delete Roddy 136 (used everywhere); the sections that could only use it go too."""
    client.get(ROOMS)
    return client.post(
        f"{ROOMS}{quote('Roddy 136')}/delete/",
        {"action": "confirm"},
        follow=True,
    )


def add_room(client, name="Annex 1"):
    client.get(ROOMS)
    return client.post(
        ROOMS + "add/",
        {"name": name, "capacity": "20", "features": "", "times": ""},
        follow=True,
    )


def test_the_undo_bar_stays_out_of_the_way_until_there_is_something_to_undo(client):
    text = page(client.get(ROOMS))
    assert "Nothing to undo yet" not in text
    assert 'data-history-action="undo"' not in text
    add_room(client)
    assert 'data-history-action="undo"' in page(client.get(ROOMS))


def test_a_cascading_delete_can_be_undone_exactly(client):
    client.get(ROOMS)
    before = config_json()
    response = delete_big_room(client)
    assert "Undo: Delete room" in page(response)
    assert config_json() != before

    response = client.post(UNDO, follow=True)
    assert "Undid: Delete room" in page(response)
    assert (
        config_json() == before
    )  # rooms, course lists and faculty preferences all back
    assert browser_session().dirty is False  # back to the loaded state


def test_redo_reapplies_the_delete_and_undo_again_restores_it(client):
    client.get(ROOMS)
    before = config_json()
    delete_big_room(client)
    after = config_json()
    client.post(UNDO)
    response = client.post(REDO, follow=True)
    assert "Redid: Delete room" in page(response)
    assert config_json() == after
    client.post(UNDO)
    assert config_json() == before


def test_a_new_change_after_undo_clears_redo(client):
    delete_big_room(client)
    client.post(UNDO)
    add_room(client)
    history = browser_session().history
    assert history.can_undo and not history.can_redo


def test_undo_covers_other_kinds_of_edits_too(client):
    client.get(ROOMS)
    before = config_json()
    add_room(client)
    assert config_json() != before
    response = client.post(UNDO, follow=True)
    assert "Undid: Add room" in page(response)
    assert config_json() == before


def test_a_rejected_edit_leaves_nothing_to_undo(client):
    client.get(ROOMS)
    client.post(
        ROOMS + "add/",
        {"name": "Roddy 136", "capacity": "20", "features": "", "times": ""},
    )
    assert not browser_session().history.can_undo


def test_undoing_with_nothing_to_undo_explains_instead_of_failing(client):
    client.get(ROOMS)
    response = client.post(UNDO, follow=True)
    assert response.status_code == 200
    assert "nothing to undo" in page(response).lower()


def test_undo_only_acts_on_post(client):
    client.get(ROOMS)
    add_room(client)
    after = config_json()
    response = client.get(UNDO)
    assert response.status_code == 302
    assert config_json() == after


def test_after_a_save_undoing_marks_the_configuration_unsaved(client):
    client.get(ROOMS)
    add_room(client)
    client.post("/configuration/save/")
    assert browser_session().dirty is False
    client.post(UNDO)
    assert browser_session().dirty is True


def test_starting_a_new_configuration_clears_the_history(client):
    delete_big_room(client)
    client.post(UNDO)
    assert browser_session().history.can_redo
    client.post("/configuration/new/", {})
    history = browser_session().history
    assert not history.can_undo and not history.can_redo


def test_the_return_address_must_stay_on_this_site(client):
    client.get(ROOMS)
    add_room(client)
    response = client.post(UNDO, {"next": "https://evil.example/phish"})
    assert response.status_code == 302
    assert "evil.example" not in response["Location"]
    response = client.post(REDO, {"next": ROOMS})
    assert response["Location"] == ROOMS
