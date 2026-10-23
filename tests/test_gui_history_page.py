"""
Tests for the History page, the inline Undo, Restore previous, stale-schedule
notices and the smarter delete pages, through the web pages (Sprint 2 Sections
8, 11, 12, 13, 23).

They run against the REAL scheduler library and the shipped example
configuration (3 rooms, 2 labs, 17 course sections, 10 faculty).
"""

from urllib.parse import quote

import pytest

from app.schedule_io import Assignment, MeetingTime
from gui import session_store
from tests.canonical import canonical

ROOMS = "/configuration/rooms/"
UNDO = "/configuration/history/undo/"
REDO = "/configuration/history/redo/"
HISTORY = "/configuration/history/"
GOTO = "/configuration/history/goto/"
RESTORE = "/configuration/restore-previous/"
RESTORE_BUTTON = ">Restore previous configuration</button>"     # the card's button, not the help text
EDITOR = "/configuration/"
NEW = "/configuration/new/"
VIEWER = "/schedules/"
GENERATOR = "/generate/"


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
    return canonical(browser_session().config.model_dump_json())


def add_room(client, name="Annex 1"):
    client.get(ROOMS)
    return client.post(ROOMS + "add/", {"name": name, "capacity": "20", "features": "", "times": ""}, follow=True)


def delete_room(client, name="Roddy 136", **fields):
    client.get(ROOMS)
    data = {"action": "confirm", **fields}
    return client.post(f"{ROOMS}{quote(name)}/delete/", data, follow=True)


def a_schedule():
    return [Assignment("CMSC 140.01", "Hardy", "Roddy 136", None, (MeetingTime("MON", "09:00", "09:50", 50),))]


# ---------------------------------------------------------------------- #
#  Inline Undo
# ---------------------------------------------------------------------- #
def test_the_saved_message_carries_an_undo_button_once(client):
    client.get(ROOMS)
    before = config_json()
    response = add_room(client)
    text = page(response)
    assert 'class="alert__undo"' in text and 'name="token"' in text
    assert 'class="alert__undo"' not in page(client.get(ROOMS))   # offered once, on the page right after

    assert config_json() != before


def test_the_inline_undo_undoes_exactly_that_change(client):
    client.get(ROOMS)
    before = config_json()
    page(add_room(client))
    token = browser_session().history.version
    response = client.post(UNDO, {"token": str(token), "next": ROOMS}, follow=True)
    assert "Undid: Add room" in page(response)
    assert config_json() == before


def test_a_stale_undo_is_refused_instead_of_undoing_the_wrong_thing(client):
    add_room(client, "Annex 1")
    old_token = browser_session().history.version
    add_room(client, "Annex 2")                       # the page the user clicked from is now out of date
    after = config_json()
    response = client.post(UNDO, {"token": str(old_token)}, follow=True)
    assert "changed since that page was shown" in page(response)
    assert config_json() == after


# ---------------------------------------------------------------------- #
#  History page
# ---------------------------------------------------------------------- #
def test_the_history_page_is_empty_at_first(client):
    client.get(ROOMS)
    text = page(client.get(HISTORY))
    assert "No changes yet" in text


def test_the_history_page_lists_changes_newest_first_with_what_changed(client):
    add_room(client, "Annex 1")
    delete_room(client, "Annex 1")
    text = page(client.get(HISTORY))
    assert text.index("Delete room &#x27;Annex 1&#x27;") < text.index("Add room &#x27;Annex 1&#x27;")
    assert "Removed room Annex 1" in text
    assert "Go back to before this" in text


def test_going_back_to_an_entry_undoes_it_and_everything_after(client):
    client.get(ROOMS)
    original = config_json()
    add_room(client, "Annex 1")
    add_room(client, "Annex 2")
    add_room(client, "Annex 3")
    state = browser_session().history.state()
    oldest = state["undo_entries"][-1]                    # the "Annex 1" change
    response = client.post(
        GOTO,
        {"entry": oldest["id"], "token": state["token"], "direction": "back", "next": HISTORY},
        follow=True,
    )
    assert "Went back 3 changes" in page(response)
    assert config_json() == original
    assert browser_session().history.can_redo

    redo = browser_session().history.state()["redo_entries"][-1]
    response = client.post(
        GOTO,
        {"entry": redo["id"], "token": browser_session().history.version, "direction": "forward"},
        follow=True,
    )
    assert "Re-applied 3 changes" in page(response)
    assert "Annex 3" in str(config_json())


def test_going_back_with_a_stale_page_changes_nothing(client):
    add_room(client, "Annex 1")
    entry = browser_session().history.state()["undo_entries"][0]
    add_room(client, "Annex 2")
    after = config_json()
    response = client.post(GOTO, {"entry": entry["id"], "token": "0", "direction": "back"}, follow=True)
    assert "changed since that page was shown" in page(response)
    assert config_json() == after


def test_going_back_to_an_unknown_entry_explains(client):
    add_room(client)
    response = client.post(GOTO, {"entry": "999999", "direction": "back"}, follow=True)
    assert "does not exist" in page(response)


def test_history_actions_only_act_on_post(client):
    add_room(client)
    after = config_json()
    assert client.get(GOTO).status_code == 302
    assert client.get(RESTORE).status_code == 302
    assert config_json() == after


# ---------------------------------------------------------------------- #
#  Restore previous
# ---------------------------------------------------------------------- #
def test_restore_previous_brings_back_the_configuration_a_new_one_replaced(client):
    client.get(ROOMS)
    add_room(client)
    edited = config_json()
    assert RESTORE_BUTTON not in page(client.get(EDITOR))

    client.post(NEW, {"new-confirm_replace": "on"}, follow=True)
    assert config_json() != edited
    editor = page(client.get(EDITOR))
    assert RESTORE_BUTTON in editor
    assert "with unsaved changes" in editor

    response = client.post(RESTORE, {"next": EDITOR}, follow=True)
    assert "Restored" in page(response)
    assert config_json() == edited
    assert browser_session().dirty is True
    assert browser_session().history.can_undo                 # the undo history came back too

    client.post(RESTORE, {"next": EDITOR})                    # and it can be reversed
    assert config_json() != edited


def test_restoring_with_nothing_kept_explains(client):
    client.get(ROOMS)
    response = client.post(RESTORE, {"next": EDITOR}, follow=True)
    assert "no previous configuration" in page(response)


# ---------------------------------------------------------------------- #
#  Out-of-date schedules
# ---------------------------------------------------------------------- #
def test_schedules_are_flagged_out_of_date_after_an_edit_and_fresh_again_after_undo(client):
    client.get(ROOMS)
    browser_session().set_schedules([a_schedule()])
    assert "out of date" not in page(client.get(VIEWER))

    add_room(client)
    assert "out of date" in page(client.get(VIEWER))
    assert "out of date" in page(client.get(GENERATOR))
    assert browser_session().schedules                          # kept, not deleted

    client.post(UNDO)
    assert "out of date" not in page(client.get(VIEWER))


def test_imported_schedules_are_never_flagged(client):
    client.get(ROOMS)
    browser_session().set_schedules([a_schedule()], tracked=False)
    add_room(client)
    assert "out of date" not in page(client.get(VIEWER))


# ---------------------------------------------------------------------- #
#  Delete review page
# ---------------------------------------------------------------------- #
def test_the_room_delete_page_lists_the_sections_that_go_too_and_names_no_replacement(client):
    client.get(ROOMS)
    text = page(client.get(f"{ROOMS}{quote('Roddy 136')}/delete/"))
    assert "Course sections that would be deleted" in text
    assert "CMSC 362.01" in text
    assert 'name="confirm_extra"' not in text and 'type="checkbox"' not in text
    assert "Who takes over?" not in text and 'name="choice_' not in text
    assert "(capacity" not in text                      # the page names the room, nothing more


def test_deleting_with_a_single_click_deletes_the_room_and_offers_undo(client):
    client.get(ROOMS)
    response = client.post(f"{ROOMS}{quote('Roddy 136')}/delete/", {"action": "confirm"}, follow=True)
    text = page(response)
    assert response.status_code == 200
    assert "nothing was changed" not in text and "Tick the box" not in text
    assert 'class="alert__undo"' in text
    assert browser_session().history.can_undo


def test_the_room_and_the_sections_only_it_served_go_in_that_one_click(client):
    client.get(ROOMS)
    before = len(browser_session().config.config.courses)
    response = delete_room(client)
    assert "Also deleted 3 course sections" in page(response)
    assert len(browser_session().config.config.courses) == before - 3
    assert all("Roddy 136" not in (c.room or []) for c in browser_session().config.config.courses)


def test_deleting_from_the_page_is_one_undoable_step(client):
    client.get(ROOMS)
    before = config_json()
    response = delete_room(client)
    assert 'class="alert__undo"' in page(response)
    assert browser_session().history.state()["undo_entries"][0]["summary"].startswith("Removed room Roddy 136")
    client.post(UNDO)
    assert config_json() == before


def test_the_keyboard_shortcuts_script_is_loaded_on_configuration_pages(client):
    assert "gui/js/history.js" in page(client.get(ROOMS))
