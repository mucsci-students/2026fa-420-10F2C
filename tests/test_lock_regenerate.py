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
  * the scripts are loaded with a version, so a browser never keeps running an old copy after an update
  * the button still shows it is working, and ignores a second click, if the progress script does not run
  * a box for the number of schedules, filled in with the saved limit, and the saved flags sent along
  * a run started from the page uses the number in the box and leaves the saved limit alone
"""

import re

import pytest
from django.urls import reverse

from app.schedule_io import Assignment, MeetingTime
from gui import session_store
from tests.fakes import FakeConfig

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


def test_scripts_are_versioned_so_an_update_is_never_missed(client, browser):
    # The development server sends no cache instructions, so a browser may keep an old script for days.
    # An address that changes with the file (?v=<time>) makes it fetch the new one.
    lock_one(client)
    html = page(client)
    assert re.search(r"generation_progress\.js\?v=\d+", html)
    assert re.search(r"schedule_viewer\.js\?v=\d+", html)


def test_generator_page_versions_its_progress_script(client):
    assert re.search(r"generation_progress\.js\?v=\d+", page(client, "/generate/"))


def test_buttons_show_busy_without_the_progress_script(client, browser):
    lock_one(client)
    # One for the banner, one for the lock card (gui/js/loading.js does the rest).
    assert page(client).count('data-loading="Generating schedules"') == 2


@pytest.fixture
def configured(browser):
    """The same browser session, now with a configuration: saved limit 7, two saved flags."""
    browser.config = FakeConfig(limit=7, optimizer_flags=["pack_rooms", "same_room"])
    return browser


def test_the_box_starts_at_the_saved_limit(client, configured):
    lock_one(client)
    html = page(client)
    # one in the banner and one in the lock card
    assert html.count('name="limit"') == 2
    assert html.count('value="7"') == 2


def test_each_box_has_its_own_label(client, configured):
    lock_one(client)
    html = page(client)
    for box in ("banner-limit", "card-limit"):
        assert f'for="{box}"' in html
        assert f'id="{box}"' in html


def test_the_saved_flags_go_along_with_each_button(client, configured):
    lock_one(client)
    html = page(client)
    assert html.count('name="optimizer_flags" value="pack_rooms"') == 2
    assert html.count('name="optimizer_flags" value="same_room"') == 2
    assert 'name="optimizer_flags" value="faculty_course"' not in html


def test_there_is_no_box_without_a_configuration(client, browser):
    lock_one(client)
    html = page(client)
    assert "data-regenerate-form" in html
    assert 'name="limit"' not in html


def test_a_run_started_here_uses_the_box_and_flags(client, configured, monkeypatch):
    seen = {}

    def fake_start(request, limit_override=None, optimizer_overrides=None):
        seen["limit"] = limit_override
        seen["flags"] = optimizer_overrides
        return {"state": "running"}

    target = "gui.views_generation.schedule_controller.start_generation"
    monkeypatch.setattr(target, fake_start)
    response = client.post(
        reverse("gui:generation_start"),
        {"limit": "5", "optimizer_flags": ["pack_rooms", "same_room"]},
    )
    assert response.status_code == 200
    assert seen == {"limit": 5, "flags": ["pack_rooms", "same_room"]}
    # this run only: the saved limit is untouched
    assert configured.config.limit == 7


def test_a_limit_that_is_not_a_positive_number_is_refused(client, configured):
    response = client.post(reverse("gui:generation_start"), {"limit": "0"})
    assert response.status_code == 400
    assert response.json()["started"] is False
