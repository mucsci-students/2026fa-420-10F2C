"""
Tests for saving, starting and loading a configuration through the AI chat (Sprint 3: configuration saving).

The real AI is replaced by FakeRunner, which calls the tools a model would have picked. Everything else is
real: the endpoints, gui.ai.service, the tools, the controllers, the session and the scheduler library.

What these cover:
  * "Save my configuration", "Download my config" and "Save as fall.json" offer a file name box and a
    Save JSON button; the reply never says the file was saved, and the configuration is not touched
  * Save JSON is the Configuration Editor's own Save view: same validation, same JSON, a normal browser
    download named by the box, so there is one export and a failed save changes nothing
  * overwriting: the app writes nothing to disk, so it can never replace a file; the browser decides, and
    the chat says so. A save that is repeated under the same name is just another download
  * nothing loaded: the reply explains there is nothing to save, offers Load and New, and after a
    configuration exists the user asks again and gets the Save JSON box
  * "Start a new configuration": immediate when nothing would be lost; otherwise a warning with Save JSON,
    Discard and Continue and Cancel, where only the warning just shown can discard anything and
    Cancel (or any failure) leaves the configuration, its unsaved changes and its schedules alone
"""

import json
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from app.schedule_io import Assignment, MeetingTime
from app.session import Session
from gui import session_store
from gui.ai import chats, service
from gui.ai.prompt import BASE_PROMPT, CAPABILITIES
from gui.ai.tools import TOOLS_BY_NAME, ToolBox
from gui.constants import MAX_FILENAME_LENGTH
from gui.controllers import config_controller as ctrl
from gui.controllers.errors import ControllerError

ASK_URL = "/assistant/ask/"
NEW_URL = "/assistant/new/"
CHAT_URL = "/assistant/chat/"
CHAT_NEW_URL = "/assistant/chat/new/"
EDITOR_URL = "/configuration/"
SAVE_URL = "/configuration/save/"
LOAD_URL = "/configuration/load/"
EXAMPLE = Path("app/examples/config_example.json")

SAVE = "Save my configuration"
DOWNLOAD = "Download my config"
SAVE_AS = "Save as fall.json"
START_NEW = "Start a new configuration"
LOAD = "Load a configuration from a file"

SCRIPT = {
    SAVE: [("save_configuration", {})],
    DOWNLOAD: [("save_configuration", {})],
    SAVE_AS: [("save_configuration", {"filename": "fall.json"})],
    "Save as a/b/../fall": [("save_configuration", {"filename": "a/b/../fall"})],
    "Save as long": [("save_configuration", {"filename": "x" * 150})],
    START_NEW: [("create_new_configuration", {})],
    LOAD: [("open_load_configuration_form", {})],
}


class FakeRunner:
    def run(self, text, toolbox):
        for name, args in SCRIPT[text]:
            toolbox.call(name, args)
        return ""


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    monkeypatch.setattr(service, "get_runner", lambda: FakeRunner())


@pytest.fixture
def no_config(monkeypatch):
    monkeypatch.setattr(session_store, "AUTO_LOAD_EXAMPLE", False)


def ask(client, text):
    response = client.post(ASK_URL, {"message": text})
    return response.status_code, response.json()


def browser_session():
    return next(iter(session_store._SESSIONS.values()))


def open_example(client):
    client.get(EDITOR_URL)  # opens the shipped example for this browser
    return browser_session()


def placed():
    return Assignment(
        "CMSC 140.01",
        "Hogg",
        "Roddy 136",
        None,
        (MeetingTime("MON", "09:00", "09:50", 50),),
    )


def choose(client, choice, token):
    response = client.post(NEW_URL, {"choice": choice, "token": token})
    return response.status_code, response.json()


def warn_about_new(client):
    """Ask for a new configuration while there is something to lose; returns the warning's reply body."""
    _, body = ask(client, START_NEW)
    assert body["ok"] and body["action"]["kind"] == "replace"
    return body


def uploaded(name="loaded.json"):
    return SimpleUploadedFile(
        name, EXAMPLE.read_bytes(), content_type="application/json"
    )


# ---------------------------------------------------------------------- #
#  Save through the chat
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize("request_text", [SAVE, DOWNLOAD])
def test_save_requests_offer_a_file_name_box_and_a_save_json_button(
    client, request_text
):
    session = open_example(client)
    session.config_name = "spring.json"
    _, body = ask(client, request_text)

    assert body["ok"] is True
    assert body["action"] == {
        "kind": "export",
        "filename": "spring.json",
        "pattern": r"[A-Za-z0-9._ \-]+",
        "maxlength": MAX_FILENAME_LENGTH,
    }
    assert "Save JSON" in body["reply"] and "spring.json" in body["reply"]


def test_save_as_uses_the_name_the_user_gave(client):
    open_example(client)
    _, body = ask(client, SAVE_AS)
    assert (
        body["action"]["kind"] == "export" and body["action"]["filename"] == "fall.json"
    )


def test_a_name_without_json_gets_it_and_a_path_is_never_kept(client):
    open_example(client)
    _, body = ask(client, "Save as a/b/../fall")
    name = body["action"]["filename"]
    assert name.endswith(".json") and "/" not in name and "\\" not in name


def test_a_new_configuration_is_offered_the_default_name(client):
    open_example(client).new_config()
    _, body = ask(client, SAVE)
    assert body["action"]["filename"] == "scheduler_config.json"


def test_the_reply_never_says_the_file_was_saved(client):
    open_example(client).dirty = True
    for text in (SAVE, DOWNLOAD, SAVE_AS):
        _, body = ask(client, text)
        reply = body["reply"].lower()
        for claim in (
            "has been saved",
            "was saved",
            "saved successfully",
            "downloaded to",
            "download is complete",
        ):
            assert claim not in reply, (text, claim)
        assert "cannot tell whether the download finished" in reply
        assert "your browser decides where the file goes" in reply
        assert body["changed"] is False


def test_offering_the_download_changes_nothing(client):
    session = open_example(client)
    session.dirty = True
    session.set_schedules([[placed()]])
    config, before = session.config, session.config.model_dump_json()
    for text in (SAVE, SAVE_AS):
        ask(client, text)
    assert session.config is config and session.config.model_dump_json() == before
    assert session.dirty is True and len(session.schedules) == 1


def test_a_name_that_is_too_long_is_refused_without_a_button(client):
    session = open_example(client)
    session.dirty = True
    _, body = ask(client, "Save as long")
    assert body["ok"] is False and "too long" in body["reply"]
    assert body["action"] is None and session.dirty is True


def test_an_invalid_configuration_is_not_offered_for_download(client):
    session = open_example(client)
    session.config.config.rooms.clear()  # bypasses edit mode on purpose
    session.dirty = True
    _, body = ask(client, SAVE)
    assert body["ok"] is False and "not valid" in body["reply"]
    assert body["action"] is None and session.dirty is True


def test_the_offer_is_kept_in_the_chat_so_a_reload_draws_it_again(client):
    open_example(client)
    ask(client, SAVE_AS)
    last = client.get(CHAT_URL).json()["messages"][-1]
    assert (
        last["action"]["kind"] == "export" and last["action"]["filename"] == "fall.json"
    )


# ---------------------------------------------------------------------- #
#  Save JSON is the Configuration Editor's own save
# ---------------------------------------------------------------------- #
def test_save_json_downloads_the_named_file_through_the_editors_save_view(client):
    session = open_example(client)
    session.dirty = True
    response = client.post(SAVE_URL, {"filename": "fall"})

    assert response.status_code == 200
    assert 'attachment; filename="fall.json"' in response["Content-Disposition"]
    assert "config" in json.loads(response.content)
    assert session.dirty is False and session.config_name == "fall.json"


def test_save_json_without_a_name_keeps_the_configurations_own_name(client):
    session = open_example(client)
    session.config_name = "spring.json"
    response = client.post(SAVE_URL, {})
    assert 'filename="spring.json"' in response["Content-Disposition"]


def test_the_chat_and_the_editor_produce_the_same_json(client):
    open_example(client)
    chat_save = client.post(SAVE_URL, {"filename": "a.json"}).content
    editor_save = client.post(SAVE_URL, {"filename": "b.json"}).content
    assert chat_save == editor_save


def test_a_failed_save_changes_nothing_and_says_so(client):
    session = open_example(client)
    session.dirty = True
    config = session.config
    response = client.post(SAVE_URL, {"filename": "x" * 150})
    assert (
        response.status_code == 200
        and "The configuration was not saved" in response.content.decode()
    )
    assert (
        session.dirty is True
        and session.config is config
        and "x" * 150 not in session.saved_configs
    )


def test_the_editor_save_form_has_the_same_file_name_box(client):
    open_example(client).config_name = "spring.json"
    text = client.get(EDITOR_URL).content.decode()
    assert 'name="filename"' in text and 'value="spring.json"' in text
    assert f'maxlength="{MAX_FILENAME_LENGTH}"' in text


# ---------------------------------------------------------------------- #
#  Overwrite protection
# ---------------------------------------------------------------------- #
def test_the_app_never_writes_or_overwrites_a_file_on_disk(
    client, monkeypatch, tmp_path
):
    def refuse(*args, **kwargs):
        raise AssertionError("the app wrote a file")

    monkeypatch.setattr(Session, "save", refuse)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "fall.json").write_text("precious")
    open_example(client)

    ask(client, SAVE_AS)
    first = client.post(SAVE_URL, {"filename": "fall.json"})
    second = client.post(SAVE_URL, {"filename": "fall.json"})

    assert first.status_code == second.status_code == 200
    assert (tmp_path / "fall.json").read_text() == "precious"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["fall.json"]


def test_a_repeated_name_is_left_to_the_browser_and_the_chat_says_so(client):
    open_example(client)
    client.post(SAVE_URL, {"filename": "fall.json"})
    _, body = ask(client, SAVE_AS)
    assert "what happens if a file with that name already exists" in body["reply"]
    assert body["action"]["kind"] == "export"  # nothing was decided for the user


def test_the_download_banner_does_not_claim_where_the_file_was_saved():
    assert (
        "where the file was saved"
        not in Path("gui/static/gui/js/loading.js").read_text()
    )


# ---------------------------------------------------------------------- #
#  No configuration loaded
# ---------------------------------------------------------------------- #
def test_saving_with_nothing_loaded_explains_and_offers_load_and_new(client, no_config):
    _, body = ask(client, SAVE)
    assert body["ok"] is True
    assert (
        "nothing to save" in body["reply"]
        and "no configuration is loaded" in body["reply"]
    )
    assert body["action"] == {"kind": "configuration"}
    assert START_NEW in body["suggestions"]
    assert browser_session().config is None


def test_after_a_configuration_exists_the_user_can_ask_again(client, no_config):
    ask(client, SAVE)
    assert browser_session().config is None

    client.post(LOAD_URL, {"load-config_file": uploaded("fall.json")})
    assert browser_session().config_name == "fall.json"
    _, body = ask(client, SAVE)
    assert (
        body["action"]["kind"] == "export" and body["action"]["filename"] == "fall.json"
    )


def test_after_a_new_configuration_the_user_can_ask_again(client, no_config):
    _, started = ask(client, START_NEW)
    assert (
        started["ok"] is True
        and started["refresh"] is True
        and started["action"] is None
    )
    _, body = ask(client, SAVE)
    assert body["action"]["kind"] == "export"


def test_load_requests_point_to_the_editors_load_form(client, no_config):
    _, body = ask(client, LOAD)
    assert body["ok"] is True and body["action"] == {"kind": "configuration"}
    assert "Load Configuration" in body["reply"] and "confirm" in body["reply"]


def test_loading_keeps_the_editors_discard_confirmation(client):
    session = open_example(client)
    session.dirty = True
    config = session.config
    refused = client.post(LOAD_URL, {"load-config_file": uploaded()})
    assert (
        "Tick this box to confirm discarding your unsaved changes"
        in refused.content.decode()
    )
    assert session.config is config and session.dirty is True


# ---------------------------------------------------------------------- #
#  Starting a new configuration
# ---------------------------------------------------------------------- #
def test_with_nothing_to_lose_a_new_configuration_starts_at_once(client):
    session = open_example(client)
    before = session.config
    _, body = ask(client, START_NEW)
    assert body["ok"] and body["action"] is None and body["refresh"] is True
    assert "Started a new configuration" in body["reply"]
    assert session.config is not before and session.config_name is None


def test_unsaved_changes_are_warned_about_and_nothing_is_replaced(client):
    session = open_example(client)
    session.dirty = True
    config = session.config
    body = warn_about_new(client)

    assert "would discard your unsaved changes" in body["reply"]
    for choice in ("Save JSON", "Discard and Continue", "Cancel"):
        assert choice in body["reply"]
    assert "Nothing changes until you choose" in body["reply"]
    assert body["action"]["token"] and body["action"]["filename"]
    assert body["refresh"] is False
    assert session.config is config and session.dirty is True


def test_schedules_are_warned_about_too(client):
    session = open_example(client)
    session.set_schedules([[placed()], [placed()]])
    body = warn_about_new(client)
    assert "the 2 schedules loaded now" in body["reply"]
    assert len(session.schedules) == 2


def test_the_warning_names_both_when_there_are_both(client):
    session = open_example(client)
    session.dirty = True
    session.set_schedules([[placed()]])
    body = warn_about_new(client)
    assert "your unsaved changes and the 1 schedule loaded now" in body["reply"]


def test_cancel_keeps_the_configuration_exactly_as_it_was(client):
    session = open_example(client)
    session.dirty = True
    session.set_schedules([[placed()]])
    config, before = session.config, session.config.model_dump_json()
    token = warn_about_new(client)["action"]["token"]

    status, body = choose(client, "cancel", token)

    assert status == 200 and body["ok"] is True and body["refresh"] is False
    assert "Cancelled" in body["reply"] and "exactly as they were" in body["reply"]
    assert session.config is config and session.config.model_dump_json() == before
    assert session.dirty is True and len(session.schedules) == 1
    assert session.previous is None


def test_a_cancelled_warning_cannot_be_used_to_discard_later(client):
    session = open_example(client)
    session.dirty = True
    config = session.config
    token = warn_about_new(client)["action"]["token"]
    choose(client, "cancel", token)

    _, body = choose(client, "discard", token)

    assert body["ok"] is False and "no longer current" in body["reply"]
    assert "nothing was discarded" in body["reply"]
    assert session.config is config and session.dirty is True


def test_discard_and_continue_starts_the_new_configuration(client):
    session = open_example(client)
    session.dirty = True
    session.set_schedules([[placed()]])
    old = session.config
    token = warn_about_new(client)["action"]["token"]

    status, body = choose(client, "discard", token)

    assert status == 200 and body["ok"] is True and body["refresh"] is True
    assert "Started a new configuration" in body["reply"]
    assert "Restore previous configuration" in body["reply"]
    assert (
        session.config is not old and session.dirty is False and session.schedules == []
    )
    assert (
        session.previous is not None and session.previous.config is old
    )  # it can be brought back
    assert getattr(session, ctrl.PENDING_NEW_ATTR) is None


def test_a_warning_can_only_be_used_once(client):
    session = open_example(client)
    session.dirty = True
    token = warn_about_new(client)["action"]["token"]
    choose(client, "discard", token)
    session.dirty = True
    fresh = session.config

    _, body = choose(client, "discard", token)

    assert body["ok"] is False and session.config is fresh and session.dirty is True


def test_a_wrong_or_missing_token_discards_nothing(client):
    session = open_example(client)
    session.dirty = True
    config = session.config
    warn_about_new(client)
    for token in ("wrong", ""):
        _, body = choose(client, "discard", token)
        assert body["ok"] is False
    assert session.config is config and session.dirty is True


def test_discarding_without_any_warning_is_refused(client):
    session = open_example(client)
    session.dirty = True
    config = session.config
    _, body = choose(client, "discard", "anything")
    assert body["ok"] is False and session.config is config


def test_an_unknown_choice_does_nothing(client):
    session = open_example(client)
    session.dirty = True
    config = session.config
    token = warn_about_new(client)["action"]["token"]
    _, body = choose(client, "explode", token)
    assert body["ok"] is False and "Choose Save JSON" in body["reply"]
    assert session.config is config
    assert getattr(session, ctrl.PENDING_NEW_ATTR) == token  # the warning is still open


def test_another_chat_forgets_a_waiting_warning(client):
    session = open_example(client)
    session.dirty = True
    config = session.config
    token = warn_about_new(client)["action"]["token"]
    assert client.post(CHAT_NEW_URL).status_code == 200

    _, body = choose(client, "discard", token)

    assert body["ok"] is False and session.config is config


def test_saving_from_the_warning_does_not_discard_anything(client):
    session = open_example(client)
    session.dirty = True
    config = session.config
    token = warn_about_new(client)["action"]["token"]

    response = client.post(SAVE_URL, {"filename": "keep.json"})

    assert (
        response.status_code == 200
        and 'filename="keep.json"' in response["Content-Disposition"]
    )
    assert (
        session.config is config
    )  # still open; the user now chooses Discard and Continue or Cancel
    _, body = choose(client, "discard", token)
    assert body["ok"] is True and session.config is not config


def test_the_choices_are_recorded_in_the_chat(client):
    session = open_example(client)
    session.dirty = True
    token = warn_about_new(client)["action"]["token"]
    choose(client, "cancel", token)
    last = client.get(CHAT_URL).json()["messages"][-1]
    assert (
        last["kind"] == "assistant"
        and "Cancelled" in last["text"]
        and last["action"] is None
    )


def test_the_choices_endpoint_only_accepts_post_and_is_refused_while_busy(client):
    open_example(client)
    assert client.get(NEW_URL).status_code == 405
    key = id(browser_session())
    service._BUSY.add(key)
    try:
        response = client.post(NEW_URL, {"choice": "cancel", "token": "x"})
    finally:
        service._BUSY.discard(key)
    assert response.status_code == 409 and response.json()["busy"] is True


def test_a_post_from_another_site_cannot_discard(client):
    from django.test import Client

    strict = Client(enforce_csrf_checks=True)
    assert strict.post(NEW_URL, {"choice": "discard", "token": "x"}).status_code == 403


# ---------------------------------------------------------------------- #
#  The controller on its own
# ---------------------------------------------------------------------- #
@pytest.fixture
def held(monkeypatch):
    loaded = Session()
    loaded.load(str(EXAMPLE))
    monkeypatch.setattr(ctrl, "get_session", lambda request: loaded)
    return loaded


def test_export_name_changes_nothing(held):
    held.dirty = True
    assert ctrl.export_name(None, "fall") == "fall.json"
    assert held.dirty is True and held.saved_configs == {}


def test_save_configuration_names_the_download_and_marks_it_saved(held):
    held.dirty = True
    name, content = ctrl.save_configuration(None, "fall")
    assert name == "fall.json" and "config" in json.loads(content)
    assert held.dirty is False and held.config_name == "fall.json"
    assert held.saved_config_names() == ["fall.json"]


def test_a_too_long_name_is_refused_before_anything_changes(held):
    held.dirty = True
    with pytest.raises(ControllerError) as info:
        ctrl.save_configuration(None, "x" * (MAX_FILENAME_LENGTH + 1))
    assert "too long" in info.value.message
    assert held.dirty is True and held.saved_configs == {}


def test_a_clean_configuration_starts_new_immediately(held):
    outcome = ctrl.request_new_configuration(None)
    assert outcome.started is True and held.config_name is None


def test_without_a_configuration_new_starts_immediately(monkeypatch):
    empty = Session()
    monkeypatch.setattr(ctrl, "get_session", lambda request: empty)
    assert ctrl.request_new_configuration(None).started is True
    assert empty.config is not None


def test_the_warning_carries_what_would_be_lost_and_the_save_name(held):
    held.dirty = True
    held.config_name = "spring.json"
    outcome = ctrl.request_new_configuration(None)
    assert (
        outcome.started is False
        and outcome.dirty is True
        and outcome.schedule_count == 0
    )
    assert outcome.export_name == "spring.json" and outcome.token
    assert held.config_name == "spring.json"  # nothing replaced


def test_cancel_reports_whether_a_warning_was_waiting(held):
    held.dirty = True
    token = ctrl.request_new_configuration(None).token
    assert ctrl.cancel_new_configuration(None, "wrong") is False
    assert getattr(held, ctrl.PENDING_NEW_ATTR) is None  # any cancel closes the warning
    assert ctrl.cancel_new_configuration(None, token) is False


# ---------------------------------------------------------------------- #
#  The tools and what the AI is told
# ---------------------------------------------------------------------- #
def test_the_tools_are_registered_and_none_of_them_edits_the_configuration():
    for name in (
        "save_configuration",
        "create_new_configuration",
        "open_load_configuration_form",
    ):
        tool = TOOLS_BY_NAME[name]
        assert tool.write is False and tool.needs_config is False and tool.final is True


def test_the_prompt_and_capabilities_describe_saving_without_claiming_it_happened():
    assert (
        "save_configuration" in BASE_PROMPT and "Never say or imply the" in BASE_PROMPT
    )
    assert "You cannot save the configuration" not in BASE_PROMPT
    assert "I can't save the configuration" not in CAPABILITIES


def test_a_tool_result_carries_its_action(client):
    session = open_example(client)
    session.dirty = True
    request = client.get(EDITOR_URL).wsgi_request
    result = ToolBox(request).call("save_configuration", {"filename": "fall.json"})
    assert result.ok and result.action is not None and result.changed is False
    assert result.action["kind"] == "export"
    assert chats.state(session)["messages"] == []  # recording is the service's job


def test_the_chat_page_gives_the_script_its_urls(client):
    text = client.get(EDITOR_URL).content.decode()
    assert 'data-save-url="/configuration/save/"' in text
    assert 'data-new-url="/assistant/new/"' in text
    assert 'data-editor-url="/configuration/"' in text
