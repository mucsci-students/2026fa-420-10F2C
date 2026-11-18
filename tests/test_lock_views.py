"""
Tests for the lock buttons and cards on the Schedule Viewer and the Schedule Generator
(Django test client; nothing here runs the solver).

What is covered:
  * the viewer: a padlock on every calendar block, the "Keep sections you like" card, the banner
  * lock / unlock a section, lock / unlock all of an instructor's sections, and Unlock all (with its
    confirmation), each returning to the page the user was on
  * refusals are shown as messages and change nothing; "next" only ever points back at this site
  * a section locked to a different placement in another schedule says so
  * the generator lists the same locks and lets the user remove them
"""

import pytest

from app.schedule_io import Assignment, MeetingTime
from gui import session_store

VIEWER = "/schedules/"
GENERATOR = "/generate/"
LOCK = "/schedules/locks/lock/"
UNLOCK = "/schedules/locks/unlock/"
CLEAR = "/schedules/locks/clear/"


def section(course, faculty, room, day, start="09:00", end="09:50"):
    return Assignment(course, faculty, room, None, (MeetingTime(day, start, end, 50),))


A1 = section("CMSC 141.01", "Hogg", "Roddy 136", "MON")
A2 = section("CMSC 141.02", "Hogg", "Roddy 140", "TUE", "10:00", "10:50")
B1 = section("CMSC 142.01", "Barr", "Roddy 147", "WED")
A1_MOVED = section(
    "CMSC 141.01", "Hogg", "Roddy 136", "THU"
)  # schedule 2 places it elsewhere
B1_CLASH = section(
    "CMSC 142.01", "Barr", "Roddy 136", "MON"
)  # takes A1's room and time
SCHEDULES = [[A1, A2, B1], [A1_MOVED, A2, B1], [B1_CLASH]]


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


@pytest.fixture
def browser(client):
    """The browser's own session, holding three schedules."""
    client.get(VIEWER)
    (opened,) = session_store._SESSIONS.values()
    opened.set_schedules([list(schedule) for schedule in SCHEDULES])
    return opened


def page(client, url=VIEWER):
    return client.get(url).content.decode()


# ---------------------------------------------------------------------- #
#  The viewer before anything is locked
# ---------------------------------------------------------------------- #
def test_every_block_has_a_padlock_and_the_card_lists_the_sections(client, browser):
    html = page(client)
    assert 'aria-label="Lock CMSC 141.01 in place"' in html
    assert "Keep sections you like" in html
    assert "Lock all 2" in html  # Hogg teaches two sections in schedule 1
    assert 'id="lock-form"' in html
    assert "lock-banner" not in html  # no banner when nothing is locked


def test_the_card_groups_sections_by_instructor(client, browser):
    card = page(client).split('id="lock-sections"')[1]
    assert card.index("Barr") < card.index("Hogg")  # A to Z
    assert "(2 sections)" in card and "(1 section)" in card


def test_without_schedules_there_is_nothing_to_lock(client):
    html = page(client)
    assert "Keep sections you like" not in html
    assert 'id="lock-form"' not in html


# ---------------------------------------------------------------------- #
#  Locking and unlocking a section
# ---------------------------------------------------------------------- #
def test_locking_a_section_returns_to_the_same_view(client, browser):
    response = client.post(
        LOCK,
        {
            "schedule": "1",
            "section": "CMSC 141.01",
            "next": "/schedules/?schedule=1&view=rooms",
        },
    )
    assert response.status_code == 302
    assert response["Location"] == "/schedules/?schedule=1&view=rooms"
    assert browser.locks.get("CMSC 141.01").assignment == A1


def test_a_locked_section_shows_its_lock_everywhere(client, browser):
    client.post(LOCK, {"schedule": "1", "section": "CMSC 141.01", "next": VIEWER})
    html = page(client)
    assert "1 section locked." in html
    assert 'aria-label="Unlock CMSC 141.01 (it is locked in place)"' in html
    assert "schedule-grid__meeting--locked" in html
    assert ", locked in place" in html  # the block's own accessible name
    assert "Generate again" in html


def test_the_confirmation_message_is_shown(client, browser):
    client.post(LOCK, {"schedule": "1", "section": "CMSC 141.01", "next": VIEWER})
    assert "stays exactly as it is the next time you generate" in page(client)


def test_unlocking_a_section(client, browser):
    client.post(LOCK, {"schedule": "1", "section": "CMSC 141.01", "next": VIEWER})
    response = client.post(UNLOCK, {"section": "CMSC 141.01", "next": VIEWER})
    assert response.status_code == 302
    assert len(browser.locks) == 0
    assert "lock-banner" not in page(client)


def test_unlocking_a_section_that_is_not_locked_says_so_and_changes_nothing(
    client, browser
):
    client.post(UNLOCK, {"section": "CMSC 141.01", "next": VIEWER})
    assert "is not locked" in page(client)
    assert len(browser.locks) == 0


# ---------------------------------------------------------------------- #
#  Locking an instructor's sections
# ---------------------------------------------------------------------- #
def test_locking_all_of_an_instructors_sections(client, browser):
    client.post(LOCK, {"schedule": "1", "faculty": "Hogg", "next": VIEWER})
    assert browser.locks.sections() == ["CMSC 141.01", "CMSC 141.02"]
    html = page(client)
    assert "2 sections locked." in html
    assert "Unlock all 2" in html  # the instructor's bulk unlock button


def test_unlocking_all_of_an_instructors_sections(client, browser):
    client.post(LOCK, {"schedule": "1", "faculty": "Hogg", "next": VIEWER})
    client.post(LOCK, {"schedule": "1", "section": "CMSC 142.01", "next": VIEWER})
    client.post(UNLOCK, {"faculty": "Hogg", "next": VIEWER})
    assert browser.locks.sections() == ["CMSC 142.01"]


# ---------------------------------------------------------------------- #
#  Refusals
# ---------------------------------------------------------------------- #
def test_a_clashing_lock_is_refused_with_a_message(client, browser):
    client.post(LOCK, {"schedule": "1", "section": "CMSC 141.01", "next": VIEWER})
    client.post(LOCK, {"schedule": "3", "section": "CMSC 142.01", "next": VIEWER})
    assert "Unlock one of them first" in page(client)
    assert browser.locks.sections() == ["CMSC 141.01"]


def test_a_missing_schedule_number_is_explained(client, browser):
    client.post(LOCK, {"section": "CMSC 141.01", "next": VIEWER})
    assert "Open the schedule you want to lock from first" in page(client)
    assert len(browser.locks) == 0


def test_locking_nothing_is_explained(client, browser):
    client.post(LOCK, {"schedule": "1", "next": VIEWER})
    assert "Choose a section to lock" in page(client)
    client.post(UNLOCK, {"next": VIEWER})
    assert "Choose a section to unlock" in page(client)


def test_getting_a_lock_address_changes_nothing_and_goes_to_the_viewer(client, browser):
    for address in (LOCK, UNLOCK):
        response = client.get(address, {"section": "CMSC 141.01"})
        assert response.status_code == 302 and response["Location"] == VIEWER
    assert len(browser.locks) == 0


def test_next_never_leaves_this_site(client, browser):
    response = client.post(
        LOCK,
        {
            "schedule": "1",
            "section": "CMSC 141.01",
            "next": "https://elsewhere.example/phish",
        },
    )
    assert response["Location"] == VIEWER
    response = client.post(
        UNLOCK, {"section": "CMSC 141.01", "next": "//elsewhere.example/phish"}
    )
    assert response["Location"] == VIEWER


# ---------------------------------------------------------------------- #
#  A different placement in another schedule
# ---------------------------------------------------------------------- #
def test_a_section_locked_to_another_placement_says_so(client, browser):
    client.post(LOCK, {"schedule": "1", "section": "CMSC 141.01", "next": VIEWER})
    html = page(client, VIEWER + "?schedule=2")
    assert "Locked elsewhere" in html
    assert "schedule-grid__meeting--different" in html
    assert ", locked to a different placement" in html
    assert "Lock this one" in html


def test_locking_the_one_shown_replaces_the_other_placement(client, browser):
    client.post(LOCK, {"schedule": "1", "section": "CMSC 141.01", "next": VIEWER})
    client.post(LOCK, {"schedule": "2", "section": "CMSC 141.01", "next": VIEWER})
    assert browser.locks.get("CMSC 141.01").assignment == A1_MOVED
    assert "Locked elsewhere" not in page(client, VIEWER + "?schedule=2")


# ---------------------------------------------------------------------- #
#  Unlock all
# ---------------------------------------------------------------------- #
def test_unlock_all_asks_first(client, browser):
    client.post(LOCK, {"schedule": "1", "faculty": "Hogg", "next": VIEWER})
    response = client.get(CLEAR, {"next": VIEWER})
    html = response.content.decode()
    assert response.status_code == 200
    assert "Unlock all <strong>2</strong> locked sections?" in html
    assert len(browser.locks) == 2


def test_cancelling_keeps_the_locks(client, browser):
    client.post(LOCK, {"schedule": "1", "faculty": "Hogg", "next": VIEWER})
    client.post(CLEAR, {"action": "cancel", "next": VIEWER})
    assert len(browser.locks) == 2
    assert "stay locked" in page(client)


def test_confirming_unlocks_everything_and_returns(client, browser):
    client.post(LOCK, {"schedule": "1", "faculty": "Hogg", "next": VIEWER})
    response = client.post(CLEAR, {"action": "confirm", "next": GENERATOR})
    assert response["Location"] == GENERATOR
    assert len(browser.locks) == 0
    assert "Unlocked 2 sections" in page(client, GENERATOR)


def test_unlock_all_with_nothing_locked_just_goes_back(client, browser):
    response = client.get(CLEAR, {"next": VIEWER})
    assert response.status_code == 302 and response["Location"] == VIEWER
    assert "Nothing is locked" in page(client)


# ---------------------------------------------------------------------- #
#  The Schedule Generator
# ---------------------------------------------------------------------- #
def test_the_generator_says_nothing_is_locked(client, browser):
    html = page(client, GENERATOR)
    assert "Locked sections" in html
    assert "Nothing is locked" in html
    assert "will be kept exactly" not in html


def test_the_generator_lists_the_same_locks(client, browser):
    client.post(LOCK, {"schedule": "1", "faculty": "Hogg", "next": VIEWER})
    html = page(client, GENERATOR)
    assert "CMSC 141.01" in html and "CMSC 141.02" in html
    assert "Roddy 136" in html and "Mon 09:00" in html
    assert "2 locked sections will be kept exactly as they are" in html
    assert 'aria-label="Unlock CMSC 141.01"' in html


def test_a_lock_can_be_removed_from_the_generator(client, browser):
    client.post(LOCK, {"schedule": "1", "faculty": "Hogg", "next": VIEWER})
    response = client.post(UNLOCK, {"section": "CMSC 141.01", "next": GENERATOR})
    assert response["Location"] == GENERATOR
    assert browser.locks.sections() == ["CMSC 141.02"]
    assert "1 locked section will be kept exactly as it is" in page(client, GENERATOR)


def test_the_viewer_banner_links_to_the_generator(client, browser):
    client.post(LOCK, {"schedule": "1", "section": "CMSC 141.01", "next": VIEWER})
    assert 'href="/generate/"' in page(client)


def test_the_lock_buttons_return_to_the_cleaned_view(client, browser):
    html = client.get(
        VIEWER, {"view": "faculty", "resource": ["Hogg", "Nobody"]}
    ).content.decode()
    assert (
        'name="next" value="/schedules/?schedule=1&amp;view=faculty&amp;resource=Hogg"'
        in html
    )
    assert "Nobody" not in html
