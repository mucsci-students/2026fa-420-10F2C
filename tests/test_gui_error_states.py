"""
Tests for error states (Sprint 2 Sections 4, 19, 23.6; user story 49, board
card #77 "UI States: Error").

Story 49:
  * Failed import: an error message appears in the Viewer and the old
    schedules stay.
  * Unexpected error: a friendly message, not a traceback, and the app can
    still be used.

The crash tests make a controller raise a plain RuntimeError, the kind of
bug nobody planned for, and check what the user sees, what is logged, and
that the next request works normally.
"""

import logging

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory

from app import schedule_io
from app.schedule_io import Assignment, MeetingTime
from gui import views_errors
from gui.controllers import config_controller, schedule_controller

VIEWER_URL = "/schedules/"
IMPORT_URL = "/schedules/import/"
EDITOR_URL = "/configuration/"
LOAD_URL = "/configuration/load/"


def page(response) -> str:
    return response.content.decode()


def load_schedules(client, *faculty, **extra):
    schedules = [
        [Assignment("CMSC 140.01", name, "Roddy 136", None, (MeetingTime("MON", "09:00", "09:50", 50),))]
        for name in faculty
    ]
    raw = schedule_io.schedules_to_json(schedules).encode("utf-8")
    upload = SimpleUploadedFile("fall.json", raw, content_type="application/json")
    return client.post(IMPORT_URL, {"schedule_file": upload, **extra}, follow=True)


def explode(*args, **kwargs):
    raise RuntimeError("database melted: secret internal detail")


# ---------------------------------------------------------------------- #
#  Scenario 1: failed import shows an error and keeps the old schedules
# ---------------------------------------------------------------------- #
def test_story_49_failed_import_shows_error_in_viewer_and_keeps_schedules(client):
    load_schedules(client, "A", "B", "C")
    bad = SimpleUploadedFile("bad.json", b"{not json", content_type="application/json")
    response = client.post(IMPORT_URL, {"schedule_file": bad, "confirm_replace": "on"}, follow=True)

    html = page(response)
    assert response.status_code == 200
    assert "<strong>Error:</strong>" in html and "not valid JSON" in html
    assert "<strong>3</strong> schedules available." in html
    assert "Traceback" not in html


# ---------------------------------------------------------------------- #
#  Scenario 2: unexpected error -> friendly page, not a traceback
# ---------------------------------------------------------------------- #
def test_unexpected_crash_shows_a_friendly_page(client, monkeypatch):
    monkeypatch.setattr(schedule_controller, "schedule_count", explode)
    response = client.get(VIEWER_URL)

    html = page(response)
    assert response.status_code == 500
    assert "Something went wrong" in html
    assert "<strong>Error:</strong>" in html  # labelled, not colour alone (Section 24)
    assert "couldn&#x27;t finish that action" in html or "couldn't finish that action" in html
    assert "Traceback" not in html
    assert "secret internal detail" not in html  # no internals unless DEBUG
    for mode in ("/configuration/", "/generate/", "/schedules/"):
        assert f'href="{mode}"' in html  # links back into the app


def test_crash_page_shows_a_reference_that_matches_the_log(client, monkeypatch, caplog):
    monkeypatch.setattr(schedule_controller, "schedule_count", explode)
    with caplog.at_level(logging.ERROR, logger="gui.errors"):
        html = page(client.get(VIEWER_URL))

    records = [r for r in caplog.records if r.name == "gui.errors"]
    assert len(records) == 1
    record = records[0]
    assert record.exc_info and record.exc_info[0] is RuntimeError  # full traceback goes to the log
    reference = html.split('id="error-reference">')[1].split("<")[0]
    assert len(reference) == 8
    assert reference in record.getMessage()
    assert "GET /schedules/" in record.getMessage()


def test_app_keeps_working_after_a_crash_and_nothing_is_lost(client, monkeypatch):
    load_schedules(client, "A", "B")
    with monkeypatch.context() as patch:
        patch.setattr(schedule_controller, "schedule_count", explode)
        assert client.get(VIEWER_URL).status_code == 500

    after = client.get(VIEWER_URL)
    assert after.status_code == 200
    assert "<strong>2</strong> schedules available." in page(after)


def test_crash_during_a_form_post_is_also_friendly(client, monkeypatch):
    client.get(EDITOR_URL)
    monkeypatch.setattr(config_controller, "load_configuration", explode)
    upload = SimpleUploadedFile("fall.json", b"{}", content_type="application/json")
    response = client.post(LOAD_URL, {"load-config_file": upload, "load-confirm_replace": "on"})
    assert response.status_code == 500
    assert "Something went wrong" in page(response)


def test_technical_details_only_in_development_mode(client, monkeypatch, settings):
    monkeypatch.setattr(schedule_controller, "schedule_count", explode)

    settings.DEBUG = False
    assert "Technical details" not in page(client.get(VIEWER_URL))

    settings.DEBUG = True
    html = page(client.get(VIEWER_URL))
    assert "Technical details" in html
    assert "RuntimeError: database melted" in html
    assert "Traceback" not in html  # a one-line summary, never the stack


def test_error_page_that_cannot_render_still_answers_in_plain_language(monkeypatch):
    def broken_render(*args, **kwargs):
        raise RuntimeError("templates are broken too")

    monkeypatch.setattr(views_errors, "render", broken_render)
    response = views_errors.friendly_error_response(RequestFactory().get("/"), "abcd1234")
    html = page(response)
    assert response.status_code == 500
    assert "Something went wrong" in html and "abcd1234" in html


# ---------------------------------------------------------------------- #
#  Page not found
# ---------------------------------------------------------------------- #
def test_unknown_address_gets_a_friendly_not_found_page(client):
    response = client.get("/no-such-page/")
    html = page(response)
    assert response.status_code == 404
    assert "Page not found" in html and "/no-such-page/" in html
    assert 'href="/configuration/"' in html


def test_missing_item_inside_the_app_gets_the_friendly_not_found_page(client, settings):
    settings.DEBUG = True  # even in development mode, not Django's debug page
    response = client.get("/configuration/timeslots/XYZ/0/edit/")
    assert response.status_code == 404
    assert "Page not found" in page(response)


# ---------------------------------------------------------------------- #
#  Wiring
# ---------------------------------------------------------------------- #
def test_middleware_and_handlers_are_configured(settings):
    from config import urls

    assert "gui.middleware.FriendlyErrorMiddleware" in settings.MIDDLEWARE
    assert urls.handler404 == "gui.views_errors.page_not_found"
    assert urls.handler500 == "gui.views_errors.server_error"


def test_server_error_handler_renders_the_friendly_page():
    response = views_errors.server_error(RequestFactory().get("/"))
    assert response.status_code == 500
    assert "Something went wrong" in page(response)
