"""
Tests for empty-state displays (Sprint 2 Section 19; user story 47).

Story 47:
  * No schedules: the Schedule Viewer says "No schedules yet" with links to
    generate or load.
  * No configuration: the Editor and Generator offer "New Configuration" or
    "Load Configuration".
"""

import pytest

from gui import session_store

EDITOR_URL = "/configuration/"
GENERATOR_URL = "/generate/"
VIEWER_URL = "/schedules/"
NEW_LINK = 'href="/configuration/#new-configuration"'
LOAD_LINK = 'href="/configuration/#load-configuration"'


def page(response) -> str:
    return response.content.decode()


@pytest.fixture
def no_config(monkeypatch):
    """A fresh browser with no configuration loaded (the example is not auto-loaded)."""
    monkeypatch.setattr(session_store, "AUTO_LOAD_EXAMPLE", False)


# ---------------------------------------------------------------------- #
#  No configuration
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize("url", [EDITOR_URL, GENERATOR_URL])
def test_story_47_no_configuration_offers_new_or_load(client, no_config, url):
    html = page(client.get(url))
    assert "No configuration loaded" in html
    assert f'<a class="btn btn-primary" {NEW_LINK}>New Configuration</a>' in html
    assert f'<a class="btn" {LOAD_LINK}>Load Configuration</a>' in html


def test_the_links_point_at_real_sections_of_the_editor(client, no_config):
    html = page(client.get(EDITOR_URL))
    assert 'id="new-configuration"' in html
    assert 'id="load-configuration"' in html


def test_generator_without_a_configuration_still_cannot_generate(client, no_config):
    html = page(client.get(GENERATOR_URL))
    assert "disabled>Generate schedules</button>" in html


@pytest.mark.parametrize("url", [EDITOR_URL, GENERATOR_URL])
def test_buttons_are_not_shown_once_a_configuration_is_loaded(client, url):
    html = page(client.get(url))  # the example configuration is auto-loaded
    assert NEW_LINK not in html and LOAD_LINK not in html
    assert "No configuration loaded" not in html


# ---------------------------------------------------------------------- #
#  No schedules
# ---------------------------------------------------------------------- #
def test_story_47_no_schedules_points_to_generate_or_load(client):
    html = page(client.get(VIEWER_URL))
    assert "No schedules yet" in html
    assert 'href="/generate/"' in html  # generate
    assert 'id="load-schedules"' in html  # load a schedule file, on the same page
