"""
Tests for exporting the configuration as a standard browser download and for the chat's
new-configuration warning (replaces the earlier File System Access picker design).

What they pin down
  * There is ONE export: the Configuration Editor's Save button and the chat's Save JSON button post
    to the same view, which answers with an ordinary attachment. Nothing depends on
    showSaveFilePicker or any other experimental browser feature.
  * The exported JSON is the current configuration, validated, with a safe .json name.
  * A download is only started, never confirmed, so the pages say so.
  * Starting a new configuration from the chat warns first, replaces only on an explicit confirm,
    and the confirmation is single use, session scoped, and refused when what the user was warned
    about has changed.

The AI is replaced by a scripted runner; no OpenAI connection or API key is used.
"""

import json
from pathlib import Path

import pytest
from django.test import Client

from gui import session_store
from gui.ai import service
from gui.controllers import config_controller as controller
from gui.controllers import rooms
from gui.controllers.errors import ControllerError

ROOT = Path(__file__).resolve().parent.parent
SAVE = "/configuration/save/"
CONFIRM = "/configuration/new/confirm/"
CANCEL = "/configuration/new/cancel/"
ASK = "/assistant/ask/"
EDITOR = "/configuration/"


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


def current():
    return next(iter(session_store._SESSIONS.values()))


def edit_room(client, name="EDITED"):
    """A real edit through the same controller the pages use, so the history and dirty flag move."""
    rooms.add_room(
        type("Request", (), {"session": client.session})(),
        {"name": name, "capacity": 30},
    )


def with_runner(monkeypatch, *calls):
    """Make the chat call these (tool name, arguments) pairs, as the AI would."""

    class Runner:
        def run(self, text, toolbox):
            for name, arguments in calls:
                toolbox.call(name, arguments)
            return ""

    monkeypatch.setattr(service, "get_runner", lambda: Runner())


def ask(client, text="go"):
    return client.post(ASK, {"message": text}).json()


# ---------------------------------------------------------------------- #
#  One export: a standard download
# ---------------------------------------------------------------------- #
def test_save_is_a_standard_json_attachment_with_the_current_configuration(client):
    client.get(EDITOR)
    edit_room(client, "BEFORE SAVE")
    response = client.post(SAVE)
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    disposition = response["Content-Disposition"]
    assert disposition.startswith("attachment;") and ".json" in disposition
    data = json.loads(response.content)
    assert data == json.loads(current().dumps())
    assert "BEFORE SAVE" in response.content.decode()


def test_exporting_hands_the_text_over_clears_the_flag_and_keeps_a_session_snapshot(
    client,
):
    client.get(EDITOR)
    edit_room(client)
    assert current().dirty
    response = client.post(SAVE, {"filename": "fall"})
    assert not current().dirty
    assert current().saved_configs["fall.json"] == response.content.decode()
    assert current().config_name == "fall.json"


@pytest.mark.parametrize(
    "asked, used",
    [
        ("fall", "fall.json"),
        ("Fall 2026.JSON", "Fall 2026.JSON"),
        ('my "cfg"', "my _cfg_.json"),
    ],
)
def test_a_requested_file_name_is_used_and_made_safe(client, asked, used):
    client.get(EDITOR)
    response = client.post(SAVE, {"filename": asked})
    assert f'filename="{used}"' in response["Content-Disposition"]


@pytest.mark.parametrize(
    "asked", ["../secret.json", "/tmp/out.json", "C:\\temp\\out.json", ".."]
)
def test_a_path_is_refused_not_used_as_a_destination(client, asked):
    client.get(EDITOR)
    edit_room(client)
    response = client.post(SAVE, {"filename": asked})
    assert "Content-Disposition" not in response
    assert "not a path" in response.content.decode()
    assert current().dirty  # a failed export never marks the configuration saved


def test_an_invalid_configuration_is_not_exported_and_stays_unsaved(client):
    client.get(EDITOR)
    session = current()
    session.config.config.rooms.clear()  # bypasses edit mode on purpose
    session.dirty = True
    response = client.post(SAVE)
    assert "Content-Disposition" not in response
    assert "was not saved" in response.content.decode()
    assert session.dirty


def test_the_editor_and_the_chat_post_to_the_same_save_view(client):
    page = client.get(EDITOR).content.decode()
    assert (
        page.count(f'action="{SAVE}"') == 2
    )  # the editor's Save form and the chat's hidden one
    hidden = page.split('id="config-export-form"', 1)[1].split(">", 1)[0]
    assert (
        f'action="{SAVE}"' in hidden
        and "data-loading-download" in hidden
        and "hidden" in hidden
    )
    for path in ("/", "/generate/", "/schedules/"):
        assert 'id="config-export-form"' in client.get(path).content.decode()


def test_nothing_relies_on_the_file_system_access_api():
    searched = list((ROOT / "gui/static/gui/js").glob("*.js")) + list(
        (ROOT / "gui/templates").rglob("*.html")
    )
    assert searched
    for path in searched:
        text = path.read_text(encoding="utf-8")
        assert "showSaveFilePicker" not in text, path
        assert "createWritable" not in text, path


def test_the_chat_script_uses_the_form_download_and_never_inserts_html():
    script = (ROOT / "gui/static/gui/js/configuration_export.js").read_text(
        encoding="utf-8"
    )
    for label in ("Save JSON", "Discard and Continue", "Cancel"):
        assert f'"{label}"' in script
    assert "requestSubmit" in script and "config-export-form" in script
    assert "innerHTML" not in script
    assert "can't tell whether the download finished" in script
    chat = (ROOT / "gui/static/gui/js/chat.js").read_text(encoding="utf-8")
    assert "ConfigurationExport.addAction" in chat


# ---------------------------------------------------------------------- #
#  Naming the file: one rule, used by the editor's box, the chat's box and the server
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name", ["fall", "Fall 2026.json", "a.b-c_d", "automne-\u00e9t\u00e9"]
)
def test_the_shared_pattern_accepts_plain_file_names(name):
    import re

    assert re.fullmatch(controller.FILENAME_PATTERN, name)


@pytest.mark.parametrize(
    "name", ["a/b", "../x", "a\\b", "C:\\x", "tab\there", "new\nline"]
)
def test_the_shared_pattern_rejects_paths_and_control_characters(name):
    import re

    assert not re.fullmatch(controller.FILENAME_PATTERN, name)


def test_the_editors_save_form_has_a_file_name_box_starting_with_the_default(client):
    page = client.get(EDITOR).content.decode()
    form = page.split(f'action="{SAVE}"', 1)[1].split("</form>", 1)[0]
    box = form.split('name="filename"', 1)[1].split(">", 1)[0]
    assert 'value="config_example.json"' in box
    assert f'maxlength="{controller.MAX_FILENAME_LENGTH}"' in box
    assert f'pattern="{controller.FILENAME_PATTERN}"' in box
    assert 'for="export-filename"' in form  # the box is labelled


def test_the_box_starts_with_the_default_name_for_a_new_configuration(client):
    client.get(EDITOR)
    client.post("/configuration/new/", {})
    assert 'value="scheduler_config.json"' in client.get(EDITOR).content.decode()


def test_the_editor_download_uses_the_typed_name_or_the_default(client):
    client.get(EDITOR)
    named = client.post(SAVE, {"filename": "my plan"})
    assert 'filename="my plan.json"' in named["Content-Disposition"]
    blank = client.post(SAVE, {"filename": "   "})
    assert (
        'filename="my plan.json"' in blank["Content-Disposition"]
    )  # blank keeps the name it now has


def test_a_too_long_file_name_is_refused_and_nothing_is_marked_saved(client):
    client.get(EDITOR)
    edit_room(client)
    response = client.post(
        SAVE, {"filename": "x" * (controller.MAX_FILENAME_LENGTH + 1)}
    )
    assert (
        "Content-Disposition" not in response
        and "too long" in response.content.decode()
    )
    assert current().dirty


def test_the_chats_file_name_box_is_built_with_the_same_limits():
    script = (ROOT / "gui/static/gui/js/configuration_export.js").read_text(
        encoding="utf-8"
    )
    assert "reportValidity" in script and '"File name"' in script
    assert "action.pattern" in script and "action.maxlength" in script


def test_pressing_enter_in_the_chats_file_name_box_saves_like_the_button():
    script = (ROOT / "gui/static/gui/js/configuration_export.js").read_text(
        encoding="utf-8"
    )
    assert (
        'event.key === "Enter"' in script
        and "isComposing" in script
        and "preventDefault" in script
    )
    assert (
        "fileNameBox(parent, action, save)" in script
        and script.count("fileNameBox(parent, action, save)") == 2
    )
    # In the editor the box sits inside the Save form, so Enter already submits it natively.


def test_clicking_save_json_posts_a_chat_message_and_never_claims_it_was_saved():
    script = (ROOT / "gui/static/gui/js/configuration_export.js").read_text(
        encoding="utf-8"
    )
    assert 'chat.addMessage("assistant", "Download requested. "' in script
    assert "can't tell whether the download finished" in script
    assert "was saved" not in script.replace("can't confirm it was saved", "")
    # An ignored second click gets a notice instead of a false "requested"; a rejected name gets none.
    assert 'return "busy"' in script and "exportForm.dataset.submitting" in script
    assert "A download is already starting" in script and 'return "invalid"' in script


# ---------------------------------------------------------------------- #
#  The chat's save request
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text", ["Save my configuration", "Download my config", "Save as fall.json"]
)
def test_chat_save_offers_a_download_button_and_changes_nothing(
    client, monkeypatch, text
):
    with_runner(monkeypatch, ("save_configuration", {"filename": "fall.json"}))
    client.get(EDITOR)
    edit_room(client)
    snapshots = dict(current().saved_configs)
    reply = ask(client, text)
    assert reply["ok"] and reply["changed"] is False
    (action,) = reply["actions"]
    assert action["kind"] == "export" and action["filename"] == "fall.json"
    assert (
        action["pattern"] == controller.FILENAME_PATTERN
        and action["maxlength"] == controller.MAX_FILENAME_LENGTH
    )
    assert "can't tell whether the download finished" in reply["reply"].replace(
        "cannot", "can't"
    )
    assert "saved" not in reply["reply"].lower().replace(
        "can't tell", ""
    )  # never claims it was saved
    assert current().dirty and current().saved_configs == snapshots


def test_chat_save_without_a_configuration_explains_and_offers_new_and_load(
    client, monkeypatch
):
    monkeypatch.setattr(session_store, "AUTO_LOAD_EXAMPLE", False)
    with_runner(monkeypatch, ("save_configuration", {}))
    reply = ask(client)
    assert "nothing to save" in reply["reply"].lower()
    assert reply["actions"] == [{"kind": "configuration"}]


def test_chat_save_of_an_invalid_configuration_offers_nothing(client, monkeypatch):
    with_runner(monkeypatch, ("save_configuration", {}))
    client.get(EDITOR)
    current().config.config.rooms.clear()
    reply = ask(client)
    assert reply["ok"] is False and reply["actions"] == []
    assert "not valid" in reply["reply"]


def test_chat_save_refuses_a_path(client, monkeypatch):
    with_runner(monkeypatch, ("save_configuration", {"filename": "/etc/x.json"}))
    client.get(EDITOR)
    reply = ask(client)
    assert reply["ok"] is False and reply["actions"] == []
    assert "not a path" in reply["reply"]


# ---------------------------------------------------------------------- #
#  Starting a new configuration: the controller
# ---------------------------------------------------------------------- #
@pytest.fixture
def session(monkeypatch):
    from app.session import Session

    loaded = Session()
    loaded.load("app/examples/config_example.json")
    monkeypatch.setattr(controller, "get_session", lambda request: loaded)
    return loaded


@pytest.fixture
def empty_session(monkeypatch):
    from app.session import Session

    empty = Session()
    monkeypatch.setattr(controller, "get_session", lambda request: empty)
    return empty


class TestRequestNewConfiguration:
    def test_with_nothing_loaded_it_starts_at_once(self, empty_session):
        outcome = controller.request_new_configuration(None)
        assert outcome.started and outcome.token is None
        assert empty_session.config is not None

    def test_with_nothing_to_lose_it_starts_at_once(self, session):
        old = session.config
        outcome = controller.request_new_configuration(None)
        assert outcome.started
        assert session.config is not old and session.previous.config is old

    def test_unsaved_changes_are_warned_about_and_nothing_changes(self, session):
        session.dirty = True
        old = session.config
        outcome = controller.request_new_configuration(None)
        assert not outcome.started and outcome.token
        assert outcome.dirty and outcome.schedule_count == 0
        assert session.config is old and session.dirty

    def test_schedules_alone_are_warned_about(self, session):
        session.schedules = ["a", "b"]
        outcome = controller.request_new_configuration(None)
        assert not outcome.started and not outcome.dirty and outcome.schedule_count == 2
        assert session.schedules == ["a", "b"]

    def test_confirming_replaces_clears_schedules_and_keeps_the_old_one_restorable(
        self, session
    ):
        session.dirty = True
        session.schedules = ["a"]
        old = session.config
        token = controller.request_new_configuration(None).token
        controller.confirm_new_configuration(None, token)
        assert (
            session.config is not old
            and session.dirty is False
            and session.schedules == []
        )
        assert (
            session.previous.config is old
            and session.previous.dirty
            and session.previous.schedules == ["a"]
        )

    def test_cancelling_changes_nothing_and_kills_the_token(self, session):
        session.dirty = True
        session.schedules = ["a"]
        old = session.config
        token = controller.request_new_configuration(None).token
        controller.cancel_new_configuration(None, token)
        assert session.config is old and session.dirty and session.schedules == ["a"]
        with pytest.raises(ControllerError):
            controller.confirm_new_configuration(None, token)
        assert session.config is old

    def test_a_confirmation_is_single_use(self, session):
        session.dirty = True
        token = controller.request_new_configuration(None).token
        controller.confirm_new_configuration(None, token)
        replacement = session.config
        with pytest.raises(ControllerError):
            controller.confirm_new_configuration(None, token)
        assert session.config is replacement

    def test_a_wrong_token_is_refused_and_the_real_warning_survives(self, session):
        session.dirty = True
        token = controller.request_new_configuration(None).token
        with pytest.raises(ControllerError):
            controller.confirm_new_configuration(None, "not-the-token")
        controller.confirm_new_configuration(None, token)

    def test_a_newer_warning_replaces_an_older_one(self, session):
        session.dirty = True
        first = controller.request_new_configuration(None).token
        second = controller.request_new_configuration(None).token
        old = session.config
        with pytest.raises(ControllerError):
            controller.confirm_new_configuration(None, first)
        assert session.config is old
        controller.confirm_new_configuration(None, second)

    def test_an_edit_after_the_warning_makes_the_confirmation_refuse(
        self, session, monkeypatch
    ):
        monkeypatch.setattr(
            rooms, "get_session", lambda request: session
        )  # edit the same session
        session.dirty = True
        token = controller.request_new_configuration(None).token
        old = session.config
        rooms.add_room(None, {"name": "LATE", "capacity": 20})
        with pytest.raises(ControllerError) as error:
            controller.confirm_new_configuration(None, token)
        assert "changed after I warned you" in error.value.message
        assert session.config is old and session.config.config.rooms[-1].name == "LATE"

    def test_a_different_number_of_schedules_makes_the_confirmation_refuse(
        self, session
    ):
        session.schedules = ["a"]
        token = controller.request_new_configuration(None).token
        session.schedules = ["a", "b"]
        old = session.config
        with pytest.raises(ControllerError):
            controller.confirm_new_configuration(None, token)
        assert session.config is old

    def test_downloading_in_between_does_not_invalidate_the_warning(self, session):
        session.dirty = True
        token = controller.request_new_configuration(None).token
        controller.save_configuration(None)  # Save JSON clicked in the chat
        assert session.dirty is False
        controller.confirm_new_configuration(None, token)
        assert session.previous is not None

    def test_a_failed_export_in_between_leaves_the_choice_open(self, session):
        session.dirty = True
        token = controller.request_new_configuration(None).token
        session.config.config.rooms.clear()  # makes the export fail validation
        with pytest.raises(ControllerError):
            controller.save_configuration(None)
        assert session.dirty
        old = session.config
        controller.confirm_new_configuration(None, token)
        assert session.config is not old

    def test_an_old_warning_expires(self, session, monkeypatch):
        session.dirty = True
        token = controller.request_new_configuration(None).token
        old = session.config
        monkeypatch.setattr(controller, "monotonic", lambda: float("inf"))
        with pytest.raises(ControllerError) as error:
            controller.confirm_new_configuration(None, token)
        assert "too old" in error.value.message and session.config is old


# ---------------------------------------------------------------------- #
#  Starting a new configuration: through the chat and its buttons
# ---------------------------------------------------------------------- #
def make_busy(client):
    """An open configuration with unsaved changes AND generated schedules."""
    client.get(EDITOR)
    edit_room(client)
    current().schedules = ["one", "two"]
    return current()


def test_chat_warns_about_unsaved_changes_and_schedules_and_changes_nothing(
    client, monkeypatch
):
    with_runner(monkeypatch, ("start_new_configuration", {}))
    session = make_busy(client)
    before = (session.config, session.dirty, list(session.schedules))
    reply = ask(client, "start a new configuration")
    assert reply["ok"] and reply["changed"] is False
    (action,) = reply["actions"]
    assert action["kind"] == "replace" and action["token"]
    assert (
        action["filename"] == "config_example.json"
        and action["pattern"]
        and action["maxlength"]
    )
    text = reply["reply"]
    assert "your unsaved changes" in text and "2 schedules" in text
    for choice in ("Save JSON", "Discard and Continue", "Cancel"):
        assert choice in text
    assert (
        "Restore previous configuration" in text
        and "cannot tell whether the download finished" in text
    )
    assert (session.config, session.dirty, session.schedules) == before


def test_chat_starts_at_once_when_nothing_would_be_lost(client, monkeypatch):
    with_runner(monkeypatch, ("start_new_configuration", {}))
    client.get(EDITOR)
    old = current().config
    reply = ask(client)
    assert (
        reply["actions"] == [{"kind": "refresh"}]
        and "Started a new configuration" in reply["reply"]
    )
    assert current().config is not old


def test_chat_starts_at_once_with_nothing_loaded(client, monkeypatch):
    monkeypatch.setattr(session_store, "AUTO_LOAD_EXAMPLE", False)
    with_runner(monkeypatch, ("start_new_configuration", {}))
    reply = ask(client)
    assert reply["actions"] == [{"kind": "refresh"}]
    assert current().config is not None


def test_discard_and_continue_replaces_and_reports(client, monkeypatch):
    with_runner(monkeypatch, ("start_new_configuration", {}))
    session = make_busy(client)
    token = ask(client)["actions"][0]["token"]
    result = client.post(CONFIRM, {"token": token})
    body = result.json()
    assert (
        result.status_code == 200
        and body["ok"]
        and body["changed"] is True
        and body["dirty"] is False
    )
    assert (
        "Started a new configuration" in body["message"]
        and "Restore previous configuration" in body["message"]
    )
    assert (
        session.schedules == []
        and session.config_name is None
        and session.previous.dirty
    )


def test_cancel_preserves_everything_and_reports(client, monkeypatch):
    with_runner(monkeypatch, ("start_new_configuration", {}))
    session = make_busy(client)
    config = session.config
    token = ask(client)["actions"][0]["token"]
    body = client.post(CANCEL, {"token": token}).json()
    assert body["ok"] and body["changed"] is False and body["dirty"] is True
    assert "Cancelled" in body["message"]
    assert (
        session.config is config
        and session.dirty
        and session.schedules == ["one", "two"]
    )
    assert client.post(CONFIRM, {"token": token}).status_code == 400
    assert session.config is config


def test_saving_json_first_then_discarding_still_needs_the_explicit_click(
    client, monkeypatch
):
    with_runner(monkeypatch, ("start_new_configuration", {}))
    session = make_busy(client)
    config = session.config
    token = ask(client)["actions"][0]["token"]
    download = client.post(SAVE)  # the Save JSON button
    assert "attachment" in download["Content-Disposition"]
    assert session.config is config and session.schedules == [
        "one",
        "two",
    ]  # a download replaces nothing
    assert client.post(CONFIRM, {"token": token}).json()["ok"]
    assert session.config is not config


def test_a_failed_export_replaces_nothing(client, monkeypatch):
    with_runner(monkeypatch, ("start_new_configuration", {}))
    session = make_busy(client)
    config = session.config
    ask(client)
    session.config.config.rooms.clear()
    failed = client.post(SAVE)
    assert "Content-Disposition" not in failed
    assert session.config is config and session.schedules == ["one", "two"]


def test_confirming_without_a_warning_or_from_another_session_does_nothing(
    client, monkeypatch
):
    with_runner(monkeypatch, ("start_new_configuration", {}))
    session = make_busy(client)
    config = session.config
    token = ask(client)["actions"][0]["token"]
    other = Client()
    other.get(EDITOR)
    assert other.post(CONFIRM, {"token": token}).status_code == 400
    assert Client().post(CONFIRM, {"token": "x"}).status_code == 400
    assert session.config is config and session.schedules == ["one", "two"]


@pytest.mark.parametrize("url", [CONFIRM, CANCEL])
def test_the_decision_endpoints_need_post_and_csrf(client, url):
    assert client.get(url).status_code == 405
    assert Client(enforce_csrf_checks=True).post(url, {"token": "x"}).status_code == 403


def test_the_delete_confirmation_cannot_stand_in_for_the_new_configuration_one(
    client, monkeypatch
):
    with_runner(monkeypatch, ("start_new_configuration", {}), ("confirm_delete", {}))
    session = make_busy(client)
    config = session.config
    reply = ask(client)
    assert "nothing waiting to be deleted" in reply["reply"].lower()
    assert session.config is config  # confirm_delete replaced nothing
    assert (
        session.pending_new_configuration is not None
    )  # and the warning is still open
