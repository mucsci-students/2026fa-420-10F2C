"""
The AI tools that save, start and load a configuration as a whole (Sprint 3: configuration saving).

gui/ai/tools.py has the read and add tools, gui/ai/changes.py the update and delete tools and
gui/ai/generation.py generation. None of the tools here saves, replaces or loads anything behind the
user's back: each one hands the chat an *action* to draw (see Outcome.action in gui/ai/base.py), and
the user's own click carries it out.

    save_configuration       checks the request and shows a file name box with a Save JSON button. The
                             button posts to the Configuration Editor's own Save view (gui:config_save), so
                             there is one export: the same validation, the same JSON, the same download.
    create_new_configuration starts at once when nothing would be lost. Otherwise it warns about what would
                             be discarded and offers Save JSON, Discard and Continue and Cancel; the two
                             choices that change anything go through choose_new_configuration, which
                             accepts only the warning that was just shown (config_controller keeps its
                             token).
    open_load_configuration_form
                             points to the Configuration Editor's Load Configuration form, which checks the
                             whole file and asks before discarding unsaved changes.

A download is only ever started, never confirmed: the application cannot see whether the browser finished
it or where it went, and every message says so. The app writes nothing to disk, so it can never overwrite a
file; the browser decides what happens to an existing file of the same name.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from gui.ai.base import LOAD_OR_NEW_ACTION, AiTool, NoArgs, Outcome
from gui.ai.generation import _forget_waiting
from gui.constants import FILENAME_PATTERN, MAX_FILENAME_LENGTH
from gui.controllers import config_controller
from gui.controllers.errors import ControllerError
from gui.session_store import get_session

DOWNLOAD_NOTE = (
    "Your browser decides where the file goes and what happens if a file with that name already exists, "
    "and this app cannot tell whether the download finished."
)
NOTHING_TO_SAVE = (
    "There is nothing to save: no configuration is loaded. Start a new configuration, or load an existing "
    "JSON file with Load Configuration below, then ask me to save again."
)
NEW_STARTED = (
    "Started a new configuration. It holds a placeholder room, course, faculty member, time slots and class "
    "pattern so that it is valid, but it is not useful yet. Add your own rooms, labs, courses, faculty, time "
    'slots and class patterns (ask me, or use the Configuration Editor), say "validate the configuration" '
    "when you are done, then ask me to generate schedules."
)
NEW_CHIP = "Start a new configuration"
DISCARD = "discard"
CANCEL = "cancel"


class SaveConfigurationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str | None = Field(
        default=None,
        description="Optional JSON file name, only if the user gave one. Never a path: the browser decides where it goes",
    )


def _file_name_field(filename: str) -> dict:
    """What the chat needs to draw the file name box: its starting text and the same limits the
    Configuration Editor's box has."""
    return {
        "filename": filename,
        "pattern": FILENAME_PATTERN,
        "maxlength": MAX_FILENAME_LENGTH,
    }


def save_configuration(request, args: SaveConfigurationArgs) -> Outcome:
    if get_session(request).config is None:
        return Outcome(NOTHING_TO_SAVE, (NEW_CHIP,), action=LOAD_OR_NEW_ACTION)
    name = config_controller.export_name(request, args.filename)
    return Outcome(
        f"Ready to download '{name}'. Change the file name if you like, then click Save JSON to start the "
        f"download. {DOWNLOAD_NOTE}",
        action={"kind": "export", **_file_name_field(name)},
    )


def create_new_configuration(request, args: NoArgs) -> Outcome:
    outcome = config_controller.request_new_configuration(request)
    if outcome.started:
        _forget_waiting(get_session(request))
        return Outcome(NEW_STARTED, ("Validate the configuration", "What can you do?"))
    lost = config_controller.discard_note(outcome.dirty, outcome.schedule_count)
    return Outcome(
        f"Starting a new configuration replaces the one you have open and would discard {lost}. "
        f"{config_controller.RESTORE_HINT} Choose Save JSON to download the current configuration first "
        "(you can change its file name), Discard and Continue to start the new one, or Cancel to keep "
        f"everything as it is. Nothing changes until you choose. {DOWNLOAD_NOTE}",
        action={
            "kind": "replace",
            "token": outcome.token,
            **_file_name_field(outcome.export_name),
        },
    )


def open_load_configuration_form(request, args: NoArgs) -> Outcome:
    return Outcome(
        "Use Load Configuration below to choose a JSON file; it is the same form as in the Configuration "
        "Editor. The whole file is checked before anything changes, and unsaved changes are only discarded "
        "after you confirm. When it is loaded, ask me to carry on.",
        (NEW_CHIP,),
        action=LOAD_OR_NEW_ACTION,
    )


@dataclass(frozen=True)
class Resolution:
    """How a choice on the new-configuration warning ended (the endpoint turns it into JSON)."""

    ok: bool
    message: str
    refresh: bool = False  # the page behind the chat shows the old configuration


def choose_new_configuration(request, choice: str, token: str) -> Resolution:
    """Discard and Continue / Cancel, the two choices of the warning that create_new_configuration showed.

    Save JSON is not here: it is the Configuration Editor's save, so it never touches the configuration
    except to mark it saved. Anything that fails or is cancelled leaves the configuration as it was.
    """
    if choice == DISCARD:
        try:
            config_controller.confirm_new_configuration(request, token)
        except ControllerError as error:
            return Resolution(False, error.message)
        _forget_waiting(get_session(request))
        return Resolution(
            True,
            f"{NEW_STARTED} {config_controller.RESTORE_HINT}",
            refresh=True,
        )
    if choice == CANCEL:
        config_controller.cancel_new_configuration(request, token)
        return Resolution(
            True,
            "Cancelled. Nothing was changed: your configuration, its unsaved changes and its schedules "
            "are exactly as they were.",
        )
    return Resolution(False, "Choose Save JSON, Discard and Continue, or Cancel.")


LIFECYCLE_TOOLS: tuple[AiTool, ...] = (
    AiTool(
        "save_configuration",
        "Offer to download the open configuration as a JSON file. Use for save, download or save-as requests "
        '("save as fall.json": pass the name). It only shows a file name box and a Save JSON button: never '
        "say the file was saved.",
        SaveConfigurationArgs,
        save_configuration,
        needs_config=False,
    ),
    AiTool(
        "create_new_configuration",
        "Start a new configuration, which begins with placeholder items the user then replaces. Use when the "
        "user wants to start or create a new configuration. When the open one has unsaved changes or schedules "
        "it only warns; the user chooses Save JSON, Discard and Continue or Cancel. Never replace anything "
        "yourself.",
        NoArgs,
        create_new_configuration,
        needs_config=False,
    ),
    AiTool(
        "open_load_configuration_form",
        "Show the Configuration Editor's Load Configuration form, for loading a configuration from a JSON "
        "file on the user's computer. Use when the user asks to load or open a file.",
        NoArgs,
        open_load_configuration_form,
        needs_config=False,
    ),
)
