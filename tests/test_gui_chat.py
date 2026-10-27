"""
Tests for the AI chat button and panel (Sprint 3 Section 3).

What the AI answers is covered in test_ai_chat.py. These cover the screen: the button and panel
are on every page, the form posts to the AI endpoint, the button can be hidden and brought back,
and it is pinned to the corner of the screen.
"""

from pathlib import Path

import pytest

ASK = "/assistant/ask/"
PAGES = ["/", "/configuration/", "/generate/", "/schedules/"]
ROOT = Path(__file__).resolve().parent.parent


# -- the button and panel are on every page ------------------------------------ #
@pytest.mark.parametrize("path", PAGES)
def test_every_page_carries_the_chat_button_and_panel(client, path):
    text = client.get(path).content.decode()
    assert 'id="chat-launcher"' in text
    assert "data-chat-form" in text
    assert f'action="{ASK}"' in text


def test_the_chat_script_is_loaded_and_the_button_starts_hidden(client):
    text = client.get("/").content.decode()
    assert "gui/js/chat.js" in text
    launcher = text.split('id="chat-launcher"', 1)[1].split(">", 1)[0]
    assert "hidden" in launcher  # revealed by chat.js, so it never shows without JavaScript


def test_the_request_box_is_labelled_and_limited_to_the_server_limit(client):
    text = client.get("/").content.decode()
    assert 'for="chat-input"' in text and 'id="chat-input"' in text
    assert 'maxlength="2000"' in text


# -- the button can be hidden and brought back ---------------------------------- #
@pytest.mark.parametrize("path", PAGES)
def test_every_page_has_the_hide_arrow_and_the_show_tab(client, path):
    text = client.get(path).content.decode()
    assert "data-chat-hide" in text   # the arrow beside the button that slides it away
    assert "data-chat-show" in text   # the tab that stays at the screen edge to bring it back


def test_the_hide_arrow_and_show_tab_start_hidden_and_are_labelled(client):
    text = client.get("/").content.decode()
    arrow = text.split("data-chat-hide", 1)[1].split(">", 1)[0]
    tab = text.split("data-chat-show", 1)[1].split(">", 1)[0]
    assert "hidden" in arrow and "hidden" in tab   # chat.js reveals them, so no-JavaScript pages stay clean
    assert 'aria-label="Hide AI assistant button"' in arrow
    assert 'aria-label="Show AI assistant button"' in tab


def test_the_button_is_pinned_to_the_screen_corner_and_can_slide_away():
    css = (ROOT / "gui/static/gui/css/style.css").read_text(encoding="utf-8")
    widget = css.split(".chat-widget {", 1)[1].split("}", 1)[0]
    assert "position: fixed" in widget and "bottom:" in widget and "right:" in widget
    assert ".chat-widget--tucked .chat-dock" in css   # the slid-away state exists


# -- the script's side of a reply ----------------------------------------------- #
def test_the_script_updates_the_top_bar_and_offers_a_refresh_after_a_change():
    script = (ROOT / "gui/static/gui/js/chat.js").read_text(encoding="utf-8")
    assert "if (body.dirty)" in script and "Unsaved changes" in script
    assert "if (body.changed)" in script and "window.location.reload()" in script
    assert "body.busy" in script   # a refused duplicate is shown as a note, not as a failure
    assert "innerHTML" not in script   # messages are inserted as text, never as HTML

def test_the_script_prompts_instead_of_silently_ignoring_an_empty_request():
    script = (ROOT / "gui/static/gui/js/chat.js").read_text(encoding="utf-8")
    assert 'EMPTY_PROMPT = "Type a request first."' in script
    assert 'addMessage("notice", EMPTY_PROMPT)' in script
