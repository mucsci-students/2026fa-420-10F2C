"""
Tests for "Generate again" on the Schedule Viewer (Django test client; nothing here runs the solver).

One click on the banner starts a run in the background and the banner turns into the progress bar. The
progress bar itself is gui/js/generation_progress.js; these tests cover what the server puts on the page for it.

What is covered:
  * nothing locked: no banner and no progress panel, and the page still loads the progress script
  * locked: the banner has the one-click form and a hidden progress panel with its addresses
  * the lock card has its own button, and only while something is locked
  * the finished run comes back to schedule 1 of the same view
  * a run that is already going is picked up when the page loads
  * the way to the Schedule Generator (for the limit and optimizer flags) is still there
"""

import pytest

from app.schedule_io import Assignment, MeetingTime
from gui import session_store

VIEWER = "/schedules/"
LOCK = "/schedules/locks/lock/"


def section(course, faculty, room, day, start="09:00", end="09:50"):
    return Assignment(course, faculty, room, None, (MeetingTime(day, start, end, 50),))


A1 = section("CMSC 141.01", "Hogg", "Roddy 136", "MON")
A2 = section("CMSC 141.02", "Hogg", "Roddy 140", "TUE", "10:00", "10:50")
B1 = section("CMSC 142.01", "Barr", "Roddy 147", "WED")


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


@pytest.fixture
def browser(client):
    """The browser's own session, holding one schedule."""
    client.get(VIEWER)
    (opened,) = session_store._SESSIONS.values()
    opened.set_schedules([[A1, A2, B1]])
    return opened


def lock_one(client):
    client.post(LOCK, {"schedule": "1", "section": "CMSC 141.01", "next": VIEWER})


def page(client, url=VIEWER, **query):
    return client.get(url, query).content.decode()


def test_nothing_locked_means_no_banner_and_no_progress_panel(client, browser):
    html = page(client)
    assert "data-regenerate-form" not in html
    assert 'id="generation-progress"' not in html
    # the script is loaded either way; it does nothing without a panel
    assert "generation_progress.js" in html


def test_the_banner_starts_a_run_in_place(client, browser):
    lock_one(client)
    html = page(client)
    assert "data-regenerate-form" in html
    assert 'action="/generate/"' in html  # without JavaScript the form still generates
    assert 'data-start-url="/generate/start/"' in html
    assert 'id="generation-progress"' in html
    assert 'data-status-url="/generate/status/"' in html
    assert 'data-cancel-url="/generate/cancel/"' in html
    assert "Cancel generation" in html
    assert 'data-active="true"' not in html  # nothing is running yet
    assert "data-hide-while-generating hidden" not in html


def test_the_way_to_the_generator_page_is_still_there(client, browser):
    lock_one(client)
    assert 'href="/generate/"' in page(client)
    assert "Generation options" in page(client)


def test_the_lock_card_has_its_own_button_while_something_is_locked(client, browser):
    card = page(client).split('id="lock-sections"')[1].split("</section>")[0]
    assert "data-regenerate-form" not in card
    lock_one(client)
    card = page(client).split('id="lock-sections"')[1].split("</section>")[0]
    assert "data-regenerate-form" in card
    assert "1 section locked." in card


def test_a_finished_run_comes_back_to_schedule_one_of_the_same_view(client, browser):
    lock_one(client)
    html = page(client, view="faculty", resource=["Hogg"])
    assert (
        'data-return-url="/schedules/?schedule=1&amp;view=faculty&amp;resource=Hogg"'
        in html
    )


def test_the_default_view_comes_back_without_a_view_in_the_address(client, browser):
    lock_one(client)
    assert 'data-return-url="/schedules/?schedule=1"' in page(client)


def test_a_run_that_is_already_going_is_picked_up(client, browser):
    lock_one(client)
    # a run started here, from the generator page, or in another tab
    browser.generation_job = object()
    html = page(client)
    assert 'data-active="true"' in html
    # the banner text and the card button are both hidden
    assert html.count("data-hide-while-generating hidden") == 2
