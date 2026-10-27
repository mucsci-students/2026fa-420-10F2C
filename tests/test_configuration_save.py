import json
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from gui import session_store
from gui.ai import service
from gui.controllers import config_controller as controller
from gui.controllers import rooms

PREPARE = "/configuration/save/"
COMPLETE = "/configuration/save/complete/"
BEGIN = "/configuration/save/begin/"
CANCEL = "/configuration/save/cancel/"


@pytest.fixture(autouse=True)
def clear_sessions():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


def current_session():
    return next(iter(session_store._SESSIONS.values()))


def test_prepare_includes_complete_snapshot_without_marking_saved(client):
    client.get("/configuration/")
    session = current_session()
    request = type("Request", (), {"session": client.session})()
    rooms.add_room(request, {"name": "BEFORE SAVE", "capacity": 30})
    response = client.post(PREPARE, {"filename": "fall"})
    assert response.status_code == 200
    prepared = response.json()
    assert prepared["filename"] == "fall.json"
    assert json.loads(prepared["content"]) == json.loads(session.dumps())
    assert "BEFORE SAVE" in prepared["content"]
    assert session.dirty
    assert "Content-Disposition" not in response


def test_completion_is_idempotent_and_records_actual_picker_name(client):
    client.get("/configuration/")
    session = current_session()
    session.dirty = True
    prepared = client.post(PREPARE).json()
    data = {"token": prepared["token"], "filename": "chosen.json"}
    assert client.post(BEGIN, data).status_code == 200
    assert client.post(BEGIN, data).status_code == 400
    first = client.post(COMPLETE, data)
    assert first.status_code == 200
    assert first.json()["dirty"] is False
    assert first.json()["filename"] == "chosen.json"
    assert session.config_name == "chosen.json"
    assert session.saved_configs["chosen.json"] == prepared["content"]
    assert client.post(COMPLETE, data).json() == first.json()
    assert client.post(COMPLETE, {**data, "filename": "other.json"}).status_code == 400


def test_newer_edits_remain_unsaved_after_snapshot_completion(client):
    client.get("/configuration/")
    session = current_session()
    prepared = client.post(PREPARE).json()
    request = type("Request", (), {"session": client.session})()
    rooms.add_room(request, {"name": "NEW ROOM", "capacity": 30})
    client.post(BEGIN, {"token": prepared["token"], "filename": "snapshot.json"})
    result = client.post(COMPLETE, {"token": prepared["token"], "filename": "snapshot.json"})
    assert result.status_code == 200
    assert result.json()["dirty"] is True
    assert session.dirty
    assert session.saved_configs["snapshot.json"] == prepared["content"]
    assert "NEW ROOM" not in prepared["content"]
    assert "NEW ROOM" in session.dumps()


def test_replacing_configuration_does_not_mark_new_configuration_saved(client):
    client.get("/configuration/")
    prepared = client.post(PREPARE).json()
    session = current_session()
    session.new_config()
    session.dirty = True
    client.post(BEGIN, {"token": prepared["token"], "filename": "old.json"})
    result = client.post(COMPLETE, {"token": prepared["token"], "filename": "old.json"})
    assert result.status_code == 200
    assert result.json()["dirty"] is True
    assert session.dirty


def test_cancel_invalidates_snapshot_without_clearing_dirty(client):
    client.get("/configuration/")
    current_session().dirty = True
    prepared = client.post(PREPARE).json()
    assert client.post(CANCEL, {"token": prepared["token"]}).status_code == 200
    assert client.post(COMPLETE, {"token": prepared["token"], "filename": "fall.json"}).status_code == 400
    assert current_session().dirty


def test_completion_requires_explicit_target_authorization(client):
    client.get("/configuration/")
    current_session().dirty = True
    prepared = client.post(PREPARE).json()
    data = {"token": prepared["token"], "filename": "unconfirmed.json"}
    assert client.post(COMPLETE, data).status_code == 400
    assert current_session().dirty
    assert "unconfirmed.json" not in current_session().saved_configs


def test_repeated_completion_does_not_clear_a_later_edit(client):
    client.get("/configuration/")
    prepared = client.post(PREPARE).json()
    data = {"token": prepared["token"], "filename": "saved.json"}
    client.post(BEGIN, data)
    client.post(COMPLETE, data)
    request = type("Request", (), {"session": client.session})()
    rooms.add_room(request, {"name": "LATER", "capacity": 30})
    assert client.post(COMPLETE, data).json()["dirty"]
    assert current_session().dirty


def test_expired_and_other_session_tokens_are_rejected(client, monkeypatch):
    client.get("/configuration/")
    prepared = client.post(PREPARE).json()
    other = Client()
    other.get("/configuration/")
    assert other.post(COMPLETE, {"token": prepared["token"], "filename": "fall.json"}).status_code == 400
    monkeypatch.setattr(controller, "monotonic", lambda: float("inf"))
    assert client.post(COMPLETE, {"token": prepared["token"], "filename": "fall.json"}).status_code == 400


@pytest.mark.parametrize("filename", ["../secret.json", "/tmp/file.json", r"C:\temp\file.json", "bad\nname.json"])
def test_destinations_are_selected_by_picker_not_server_paths(client, filename):
    client.get("/configuration/")
    assert client.post(PREPARE, {"filename": filename}).status_code == 400


def test_invalid_config_does_not_prepare_or_mark_saved(client):
    client.get("/configuration/")
    session = current_session()
    session.config.config.rooms.clear()
    session.dirty = True
    response = client.post(PREPARE)
    assert response.status_code == 400
    assert session.dirty
    assert "token" not in response.json()


def test_pending_saves_are_bounded(client):
    client.get("/configuration/")
    for _ in range(controller.MAX_PENDING_SAVES):
        assert client.post(PREPARE).status_code == 200
    assert client.post(PREPARE).status_code == 400


def test_unicode_filename_is_preserved(client):
    client.get("/configuration/")
    assert client.post(PREPARE, {"filename": "automne-\u00e9t\u00e9.json"}).json()["filename"] == "automne-\u00e9t\u00e9.json"


@pytest.mark.parametrize("url", [BEGIN, COMPLETE, CANCEL])
def test_save_endpoints_require_post_and_csrf(client, url):
    assert client.get(url).status_code == 405
    assert Client(enforce_csrf_checks=True).post(url).status_code == 403


@pytest.mark.parametrize("text", ["Save my configuration", "Download my config", "Save as fall.json"])
def test_chat_exposes_real_save_action_without_claiming_completion(client, monkeypatch, text):
    class Runner:
        def run(self, prompt, toolbox):
            assert prompt == text
            toolbox.call("save_configuration", {"filename": "fall.json"})
            return ""

    monkeypatch.setattr(service, "get_runner", lambda: Runner())
    client.get("/configuration/")
    current_session().dirty = True
    response = client.post("/assistant/ask/", {"message": text}).json()
    assert response["ok"]
    action = response["actions"][0]
    assert action["kind"] == "save"
    assert action["filename"] == "fall.json"
    assert action["token"]
    assert "not saved yet" in response["reply"].lower()
    assert current_session().dirty


def test_chat_no_config_offers_existing_new_load_workflows(client, monkeypatch):
    monkeypatch.setattr(session_store, "AUTO_LOAD_EXAMPLE", False)

    class Runner:
        def run(self, prompt, toolbox):
            toolbox.call("save_configuration", {})
            return ""

    monkeypatch.setattr(service, "get_runner", lambda: Runner())
    response = client.post("/assistant/ask/", {"message": "save"}).json()
    assert "nothing to save" in response["reply"].lower()
    assert response["actions"][0]["kind"] == "configuration"
    assert not getattr(current_session(), "_prepared_saves", {})


@pytest.mark.parametrize("workflow", ["new", "load"])
def test_save_after_existing_create_or_load_workflow(client, monkeypatch, workflow):
    monkeypatch.setattr(session_store, "AUTO_LOAD_EXAMPLE", False)
    client.get("/configuration/")
    if workflow == "new":
        response = client.post("/configuration/new/", {})
    else:
        uploaded = SimpleUploadedFile(
            "loaded.json", Path("app/examples/config_example.json").read_bytes(),
            content_type="application/json",
        )
        response = client.post("/configuration/load/", {"load-config_file": uploaded})
    assert response.status_code == 302
    prepared = client.post(PREPARE).json()
    assert json.loads(prepared["content"]) == json.loads(current_session().dumps())


def test_chat_create_load_actions_do_not_bypass_discard_confirmation(client, monkeypatch):
    class Runner:
        def run(self, prompt, toolbox):
            toolbox.call("configuration_actions", {})
            return ""

    monkeypatch.setattr(service, "get_runner", lambda: Runner())
    client.get("/configuration/")
    session = current_session()
    session.dirty = True
    before = session.dumps()
    result = client.post("/assistant/ask/", {"message": "Create a configuration"}).json()
    assert result["actions"] == [{"kind": "configuration"}]
    assert session.dumps() == before and session.dirty
