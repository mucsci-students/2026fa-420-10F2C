"""
Undo, redo and the change history for the AI chat.

    "undo that"                         undo_changes()
    "put the room we deleted back"      undo_changes(containing="Roddy 136")  (after looking at the history)
    "undo the last 3 changes"           undo_changes(count=3)
    "redo that"                         redo_changes()
    "what did I change?"                show_change_history()

Same history as the Undo / Redo buttons and the History page (app/history.py through
gui/controllers/history_controller.py): the same 25 changes, the same safety (a change that no
longer fits is refused), and an undo can itself be redone. Generated schedules and creating or
loading a configuration are not part of it, exactly as on the History page.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from gui.ai.base import _NOISE, UNDO_CHIP, AiTool, NoArgs, Outcome, _plural, _tokens
from gui.controllers import history_controller
from gui.controllers.errors import ControllerError

MAX_STEPS = 10
SHOWN = 12  # changes listed by show_change_history

REDO_CHIP = "Redo that change"
GENERATE_CHIP = "Generate schedules"


class UndoArgs(BaseModel):
    count: int = Field(
        default=1,
        ge=1,
        le=MAX_STEPS,
        description="How many of the newest changes to undo",
    )
    containing: str | None = Field(
        default=None,
        description=(
            "Words that name the change to take back, for example the item's name: 'Roddy 136' or "
            "'deleted Roddy 136'. Undoes the newest matching change AND every change made after it. "
            "Leave out to undo just the newest change(s)."
        ),
    )


class RedoArgs(BaseModel):
    count: int = Field(
        default=1,
        ge=1,
        le=MAX_STEPS,
        description="How many undone changes to bring back",
    )


def _stem(word: str) -> str:
    """'deleted', 'delete', 'deleting' -> 'delet', so a change is found however it is worded."""
    if word.isdigit() or len(word) <= 4:
        return word
    for suffix in ("ing", "ed", "es", "s", "e"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _words(text: str) -> set[str]:
    return {_stem(token) for token in _tokens(text)}


# Words around the name of a change ("the room I deleted", "that last one") that are not part of its label.
_FILLER = frozenset(
    [
        "i",
        "my",
        "we",
        "me",
        "you",
        "that",
        "this",
        "it",
        "its",
        "last",
        "just",
        "recent",
        "recently",
        "of",
        "did",
        "made",
        "was",
        "were",
        "had",
        "earlier",
    ]
)


def _matches(entry: dict, wanted: str) -> bool:
    typed = {
        _stem(token)
        for token in _tokens(wanted)
        if token not in _NOISE and token not in _FILLER
    }
    if not typed:
        return False
    return typed <= _words(f"{entry['label']} {entry.get('summary', '')}")


def _recent(entries: list[dict], limit: int = SHOWN) -> str:
    return "\n".join(
        f"{number}. {row['label']} ({row['when']})"
        for number, row in enumerate(entries[:limit], 1)
    )


def show_change_history(request, args: NoArgs) -> str:
    state = history_controller.describe_history(request)
    undo, redo = state["undo_entries"], state["redo_entries"]
    if not undo and not redo:
        return (
            "There are no changes to undo or redo yet. (Creating or loading a configuration starts a fresh "
            "history, and generated schedules are never part of it.)"
        )
    lines = []
    if undo:
        lines.append(f"Changes that can be undone, newest first ({len(undo)}):")
        lines.append(_recent(undo))
    if redo:
        lines.append(
            f"Changes that were undone and can be redone, next one first ({len(redo)}):"
        )
        lines.append(_recent(redo))
    return "\n".join(lines)


def undo_changes(request, args: UndoArgs) -> Outcome:
    state = history_controller.describe_history(request)
    entries = state["undo_entries"]
    wanted = (args.containing or "").strip()
    steps = min(args.count, len(entries))
    if wanted:
        hit = next((row for row in entries if _matches(row, wanted)), None)
        if hit is None:
            if any(_matches(row, wanted) for row in state["redo_entries"]):
                raise ControllerError(
                    'That change is already undone. Say "redo" to bring it back.'
                )
            if not entries:
                raise ControllerError("There is nothing to undo.")
            raise ControllerError(
                f"I couldn't find a change matching '{wanted}'. The newest changes are:\n{_recent(entries, 5)}"
            )
        steps = hit["steps"]
    elif not entries:
        raise ControllerError("There is nothing to undo.")

    labels = [history_controller.undo(request) for _ in range(steps)]
    if steps == 1:
        text = f"Undid: {labels[0]}."
    else:
        text = (
            f"Undid {_plural(steps, 'change')}, newest first: "
            + "; ".join(labels)
            + "."
        )
    if wanted and steps > 1:
        text += f" ({_plural(steps - 1, 'later change')} had to be undone with it.)"
    if labels[-1].lower().startswith("delete"):
        text += " It is back, together with everything that was removed with it."
    text += ' Say "redo" to bring it back.'
    return Outcome(text, (REDO_CHIP, GENERATE_CHIP), edited=True, note=False)


def redo_changes(request, args: RedoArgs) -> Outcome:
    state = history_controller.describe_history(request)
    if not state["redo_entries"]:
        raise ControllerError("There is nothing to redo.")
    steps = min(args.count, len(state["redo_entries"]))
    labels = [history_controller.redo(request) for _ in range(steps)]
    text = (
        f"Redid: {labels[0]}."
        if steps == 1
        else f"Redid {_plural(steps, 'change')}: " + "; ".join(labels) + "."
    )
    return Outcome(text, (UNDO_CHIP, GENERATE_CHIP), edited=True, note=False)


def recent_changes(request, limit: int = 3) -> list[str]:
    """Labels of the newest changes that can be undone (for explaining a failed run)."""
    try:
        return [
            row["label"]
            for row in history_controller.describe_history(request)["undo_entries"][
                :limit
            ]
        ]
    except Exception:  # noqa: BLE001 - explaining must never be the thing that fails
        return []


UNDO_TOOLS = [
    AiTool(
        "show_change_history",
        "Look at the changes that can be undone or redone (newest first). Use it to work out what to undo "
        "when the user says things like 'put it back' or 'undo what I did'.",
        NoArgs,
        show_change_history,
    ),
    AiTool(
        "undo_changes",
        "Undo changes to the configuration: the newest one, the newest N (count), or a specific one named by "
        "words (containing), which also undoes everything made after it. Brings back deleted items with "
        "everything removed together with them. Use for undo, revert, restore, 'put it back'.",
        UndoArgs,
        undo_changes,
        acts=True,
    ),
    AiTool(
        "redo_changes",
        "Bring back changes that were just undone (the opposite of undo_changes).",
        RedoArgs,
        redo_changes,
        acts=True,
    ),
]
