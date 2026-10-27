"""
Tests for loading states (Sprint 2 Sections 13, 19, 24; user story 48,
board card #76 "UI States: Loading").

The visible part (banner, button says "Loading…", spinner) lives in
gui/static/gui/js/loading.js and was checked in a browser (Section 23 allows
manual checks for visual behaviour). These tests cover everything the server
is responsible for:

* every page loads loading.js and has the #loading-status banner;
* the file load/save/import/export forms opt in with data-loading="Loading…",
  downloads also with data-loading-download, and Validate says "Validating…";
* a download sent with a download_token echoes it back in a cookie, which is
  how the page knows a download finished, and junk tokens are never echoed;
* a failed save or export still answers with a normal page or redirect (with
  its error message), which replaces the loading state.
"""

import re
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory

from app import schedule_io
from app.schedule_io import Assignment, MeetingTime
from gui import session_store, views

EDITOR_URL = "/configuration/"
SAVE_URL = "/configuration/save/"
VIEWER_URL = "/schedules/"
IMPORT_URL = "/schedules/import/"
EXPORT_URL = "/schedules/export/"
LOADING_JS = Path("gui/static/gui/js/loading.js")


def page(response) -> str:
    return response.content.decode()


def form_tag(html: str, action: str) -> str:
    """The opening <form ...> tag whose action is `action` (first match)."""
    match = re.search(rf'<form[^>]*action="{re.escape(action)}"[^>]*>', html)
    assert match, f"no form posting to {action}"
    return match.group(0)


def load_schedules(client, *faculty):
    schedules = [
        [Assignment("CMSC 140.01", name, "Roddy 136", None, (MeetingTime("MON", "09:00", "09:50", 50),))]
        for name in faculty
    ]
    raw = schedule_io.schedules_to_json(schedules).encode("utf-8")
    upload = SimpleUploadedFile("fall.json", raw, content_type="application/json")
    client.post(IMPORT_URL, {"schedule_file": upload}, follow=True)


# ---------------------------------------------------------------------- #
#  The script is on every page
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize("url", ["/", EDITOR_URL, "/generate/", VIEWER_URL])
def test_every_mode_loads_the_loading_script_and_banner(client, url):
    html = page(client.get(url))
    assert '<script src="/static/gui/js/loading.js" defer></script>' in html
    assert 'id="loading-status"' in html


def test_loading_script_handles_downloads():
    source = LOADING_JS.read_text(encoding="utf-8")
    assert "loadingDownload" in source and "download_token" in source


# ---------------------------------------------------------------------- #
#  Which forms opt in
# ---------------------------------------------------------------------- #
def test_configuration_save_shows_loading_until_the_download_arrives(client):
    tag = form_tag(page(client.get(EDITOR_URL)), SAVE_URL)
    assert 'data-loading="Loading…"' in tag and "data-loading-download" in tag


def test_configuration_load_and_new_show_loading(client):
    html = page(client.get(EDITOR_URL))
    for action in ("/configuration/load/", "/configuration/new/"):
        tag = form_tag(html, action)
        assert 'data-loading="Loading…"' in tag and "data-loading-download" not in tag


def test_validate_says_validating(client):
    tag = form_tag(page(client.get(EDITOR_URL)), "/configuration/validate/")
    assert 'data-loading="Validating…"' in tag


def test_schedule_import_shows_loading(client):
    tag = form_tag(page(client.get(VIEWER_URL)), IMPORT_URL)
    assert 'data-loading="Loading…"' in tag and "data-loading-download" not in tag


def test_both_schedule_export_forms_wait_for_the_download(client):
    load_schedules(client, "A", "B")
    tags = re.findall(r'<form[^>]*action="/schedules/export/"[^>]*>', page(client.get(VIEWER_URL)))
    assert len(tags) == 2
    assert all('data-loading="Loading…"' in tag and "data-loading-download" in tag for tag in tags)


# ---------------------------------------------------------------------- #
#  download_token / download_response
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize("token", ["abc123", "muw1evpf-t3ekissj", "A_b-9", "x" * 64])
def test_well_formed_tokens_are_accepted(token):
    request = RequestFactory().get("/", {"download_token": token})
    assert views.download_token(request) == token


@pytest.mark.parametrize("token", ["", "x" * 65, "has space", "semi;colon", "<script>", "a=b"])
def test_odd_tokens_are_ignored(token):
    request = RequestFactory().get("/", {"download_token": token})
    assert views.download_token(request) is None


def test_token_can_come_from_a_post_form():
    request = RequestFactory().post("/", {"download_token": "abc123"})
    assert views.download_token(request) == "abc123"


def test_download_response_echoes_the_token_in_a_short_lived_cookie():
    response = views.download_response("x.json", "{}", "application/json; charset=utf-8", "abc123")
    cookie = response.cookies["download_token"]
    assert cookie.value == "abc123"
    assert cookie["max-age"] == 120
    assert cookie["samesite"] == "Lax"
    assert response["Content-Disposition"] == 'attachment; filename="x.json"'


@pytest.mark.parametrize("token", [None, "", "bad token"])
def test_download_response_without_a_good_token_sets_no_cookie(token):
    response = views.download_response("x.json", "{}", "application/json; charset=utf-8", token)
    assert "download_token" not in response.cookies


# ---------------------------------------------------------------------- #
#  End to end through the real views
# ---------------------------------------------------------------------- #
def test_configuration_save_with_a_token_sets_the_cookie(client):
    client.get(EDITOR_URL)
    response = client.post(SAVE_URL, {"download_token": "save-1"})
    assert "attachment" in response["Content-Disposition"]
    assert response.cookies["download_token"].value == "save-1"


def test_schedule_export_with_a_token_sets_the_cookie(client):
    load_schedules(client, "A", "B")
    response = client.get(EXPORT_URL, {"schedule": "all", "file_format": "csv", "download_token": "exp-1"})
    assert response["Content-Disposition"] == 'attachment; filename="schedules-all-2.csv"'
    assert response.cookies["download_token"].value == "exp-1"


def test_export_without_a_token_still_works_and_sets_no_cookie(client):
    load_schedules(client, "A")
    response = client.get(EXPORT_URL, {"schedule": "1"})
    assert response.status_code == 200
    assert "download_token" not in response.cookies


def test_failed_export_answers_with_a_page_and_message_not_a_cookie(client):
    response = client.get(EXPORT_URL, {"schedule": "1", "download_token": "exp-2"}, follow=True)
    assert response.redirect_chain[-1][0].endswith(VIEWER_URL)
    assert "There are no schedules yet." in page(response)
    assert "download_token" not in response.cookies


def test_failed_save_answers_with_a_page_and_message_not_a_cookie(client, monkeypatch):
    monkeypatch.setattr(session_store, "AUTO_LOAD_EXAMPLE", False)
    response = client.post(SAVE_URL, {"download_token": "save-2"}, follow=True)
    assert "No configuration is loaded" in page(response)
    assert "download_token" not in response.cookies
