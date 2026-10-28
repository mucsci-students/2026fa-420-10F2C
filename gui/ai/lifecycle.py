"""
The AI tools that start, save and load a configuration (Sprint 3).

gui/ai/tools.py has the read and add tools and gui/ai/changes.py the update and delete tools; these
three are about the configuration as a whole. None of them replaces or exports anything behind the
user's back: each hands the browser an action, and the user's own click carries it out.

    save_configuration       checks the request and offers a Save JSON button. The button posts to
                             the same Save view as the Configuration Editor, so there is one export.
    start_new_configuration  starts at once when nothing would be lost; otherwise warns and offers
                             Save JSON, Discard and Continue, and Cancel (gui/controllers/
                             config_controller.py remembers what the user was warned about).
    configuration_actions    offers the Configuration Editor's New and Load forms.

A download is only ever started, never confirmed: the app cannot see whether the browser finished
it, and every message says so.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from gui.ai.base import AiTool, BrowserAction, NoArgs
from gui.controllers import config_controller
from gui.session_store import get_session

DOWNLOAD_NOTE = "Your browser decides where it goes, and this app cannot tell whether the download finished."
NOTHING_TO_SAVE = (
    "There is nothing to save: no configuration is loaded. Ask me to start a new configuration, "
    "or load an existing JSON file with the form below, then ask me to save again."
)


class SaveConfigurationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str | None = Field(
        default=None,
        description="Optional JSON file name, only if the user gave one. Never a path: the browser decides where it goes",
    )


def _file_name_field(filename: str) -> dict:
    """What the chat needs to draw the File name box: its starting text and the same limits the
    Configuration Editor's box and the server use."""
    return {
        "filename": filename,
        "pattern": config_controller.FILENAME_PATTERN,
        "maxlength": config_controller.MAX_FILENAME_LENGTH,
    }


def save_configuration(request, args: SaveConfigurationArgs) -> BrowserAction:
    if get_session(request).config is None:
        return BrowserAction(NOTHING_TO_SAVE, {"kind": "configuration"})
    name = config_controller.check_export(request, args.filename)
    return BrowserAction(
        f"Ready to download '{name}'. Change the file name if you like, then click Save JSON to start the "
        f"download. {DOWNLOAD_NOTE}",
        {"kind": "export", **_file_name_field(name)},
    )


def start_new_configuration(request, args: NoArgs) -> BrowserAction:
    outcome = config_controller.request_new_configuration(request)
    if outcome.started:
        return BrowserAction(config_controller.STARTED_NEW, {"kind": "refresh"})
    lost = config_controller.discard_note(outcome.dirty, outcome.schedule_count)
    return BrowserAction(
        f"Starting a new configuration replaces the one you have open and would discard {lost}. "
        f"{config_controller.RESTORE_HINT} Choose Save JSON to download the current configuration first "
        "(you can change its file name), Discard and Continue to start the new one, or Cancel to keep "
        f"everything as it is. Nothing changes until you choose. {DOWNLOAD_NOTE}",
        {
            "kind": "replace",
            "token": outcome.token,
            **_file_name_field(outcome.export_name),
        },
    )


def configuration_actions(request, args: NoArgs) -> BrowserAction:
    return BrowserAction(
        "Use the Load Configuration form below to choose a JSON file. The whole file is checked before "
        "anything changes, and you confirm before unsaved changes are discarded. Then ask me to save again.",
        {"kind": "configuration"},
    )


LIFECYCLE_TOOLS: tuple[AiTool, ...] = (
    AiTool(
        "save_configuration",
        "Offer to download the current configuration as a JSON file. Use for save, download or save-as "
        "requests. It only offers a Save JSON button: never say the file was saved.",
        SaveConfigurationArgs,
        save_configuration,
        needs_config=False,
    ),
    AiTool(
        "start_new_configuration",
        "Start a new configuration. When the open one has unsaved changes or schedules it warns first and "
        "the user chooses Save JSON, Discard and Continue, or Cancel. Never replace anything yourself.",
        NoArgs,
        start_new_configuration,
        needs_config=False,
    ),
    AiTool(
        "configuration_actions",
        "Offer the Configuration Editor's forms for LOADING a configuration from a JSON file. Use when the "
        "user asks to load or open a configuration.",
        NoArgs,
        configuration_actions,
        needs_config=False,
    ),
)
