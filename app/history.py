"""
Undo / redo history for the in-memory configuration (Sprint 2 Sections 11, 12).

Model-layer code (Section 20): no HTTP, no templates, and no scheduler-library
imports, so it can be unit-tested on its own.

HOW IT WORKS (the Memento pattern; see app/memento.py)
    This class is the CARETAKER. Every successful configuration edit passes
    through app.commands.common.apply_session_edit(). Just BEFORE the edit runs,
    that function asks this history to capture(): the originator saves a
    memento of every part of the valid configuration (rooms, labs, courses,
    faculty, class patterns, time slots, global settings). If the edit
    succeeds, record() keeps only the mementos of the parts that really
    changed; if validation rejects the edit, the mementos are simply thrown away.

    undo()  puts the saved parts back and keeps mementos of the state they
            replaced on the redo stack.
    redo()  does the reverse.
    A brand-new edit clears the redo stack (the usual undo/redo rule).

    The caretaker never looks inside a memento. It only keeps them in order,
    asks them to restore, and asks them to describe themselves in words.

WHAT IS NOT UNDOABLE (by design)
    * Creating a new configuration, loading one, or switching to a saved one
      replaces the whole configuration, so the history is cleared (those
      actions already ask before discarding unsaved work).
    * Generated schedules are not part of the history. They are left as they
      are when you undo, because they describe an earlier run.
    * History lives in memory with the session, like everything else in this
      app (Section 25: no database), so it is lost when the server restarts.
    * Only the newest MAX_ENTRIES (25) changes are remembered.

VERSIONS (used for the "schedules are out of date" notice and for safety)
    Every distinct state of the configuration has a unique version number. A
    new edit gives the configuration a NEW version; undo / redo put back the
    version the restored state had. So "the schedules were generated from
    version 7" stays true exactly as long as the configuration really is the
    one they were generated from, even after undo and redo.

    Undo / redo / jump requests may carry the version the page showed
    (`expected`). If the configuration has moved on since (for example the user
    edited in another tab) the request is refused instead of undoing the wrong
    thing.

UNSAVED-CHANGES FLAG
    Each snapshot remembers whether the configuration had unsaved changes at
    that moment, so undoing back to the loaded/saved state clears the
    "Unsaved changes" indicator. After a save, mark_saved() makes every older
    snapshot count as "unsaved", because the saved file no longer matches them.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field

from app.memento import CompositeMemento, ConfigOriginator, MementoError

MAX_ENTRIES = 25

_version_numbers = itertools.count(1)
_entry_ids = itertools.count(1)


def new_version() -> int:
    """A configuration-version number that has never been used before."""
    return next(_version_numbers)


class HistoryError(Exception):
    """Raised when there is nothing to undo or redo."""


@dataclass
class Snapshot:
    """One entry on the undo or redo stack: a memento plus what the page shows."""

    label: str      # what the change was, e.g. "Delete room 'Roddy 136'"
    memento: CompositeMemento   # the saved parts of the configuration (app/memento.py)
    dirty: bool     # whether the configuration had unsaved changes in that state
    version: int = 0            # the configuration version of that state
    summary: str = ""           # what changed, e.g. "Removed room Roddy 136; Changed 3 courses"
    at: float = field(default_factory=time.time)   # when the change was made
    id: int = field(default_factory=lambda: next(_entry_ids))  # stable address for "go back to here"


def _fallback_label(summary: str, area) -> str:
    """Name an edit that was not given a label: say what changed, if we can tell."""
    if summary:
        return summary if len(summary) <= 70 else summary[:67].rstrip() + "..."
    return f"Edit {str(area or 'configuration').replace('_', ' ')}"


class ConfigHistory:
    def __init__(self, limit: int = MAX_ENTRIES) -> None:
        self.limit = max(1, int(limit))
        self._undo: list[Snapshot] = []
        self._redo: list[Snapshot] = []
        # Identity of the configuration as it is right now (see "VERSIONS").
        self.version: int = new_version()
        # True from a successful edit until the next page shows its "Undo"
        # shortcut once (take_fresh), so the offer appears exactly when it is useful.
        self._fresh: bool = False

    # -- recording ------------------------------------------------------ #
    @staticmethod
    def capture(config) -> CompositeMemento:
        """Save mementos of every part of `config` (call this BEFORE the edit)."""
        return ConfigOriginator(config).create_memento()

    def record(
        self, label, before: CompositeMemento, dirty_before: bool, after=None, area=None
    ) -> Snapshot | None:
        """Remember a successful edit.

        `before` is what capture() returned. `after` is the configuration now:
        when it is given, only the parts that really changed are kept and the
        change is described in words. `label` names the change for the Undo
        button (a description of what changed is used when it is None).

        An edit that changed nothing (a form submitted without any change) is
        not remembered: nothing is added to the history, redo is kept, and None
        is returned."""
        if after is not None:
            before = before.changed_since(after)
            if not len(before):
                return None
            summary = before.describe_change(after)
        else:
            summary = ""
        entry = Snapshot(
            label=label or _fallback_label(summary, area),
            memento=before,
            dirty=bool(dirty_before),
            version=self.version,
            summary=summary,
        )
        self._undo.append(entry)
        extra = len(self._undo) - self.limit
        if extra > 0:
            del self._undo[:extra]
        self._redo.clear()
        self.version = new_version()
        self._fresh = True
        return entry

    def take_fresh(self) -> dict | None:
        """Consume the "a change was just made" flag. Returns what an inline Undo
        offer needs ({"label", "summary", "token"}) the first time it is asked
        after an edit, else None. Asking never changes the configuration."""
        if not self._fresh or not self._undo:
            self._fresh = False
            return None
        self._fresh = False
        latest = self._undo[-1]
        return {
            "label": latest.label,
            "summary": latest.summary if latest.summary != latest.label else "",
            "token": self.version,
        }

    # -- reading -------------------------------------------------------- #
    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_label(self) -> str | None:
        return self._undo[-1].label if self._undo else None

    @property
    def redo_label(self) -> str | None:
        return self._redo[-1].label if self._redo else None

    @staticmethod
    def _row(entry: Snapshot, steps: int) -> dict:
        return {
            "id": entry.id,
            "label": entry.label,
            "summary": entry.summary if entry.summary and entry.summary != entry.label else "",
            "when": time.strftime("%H:%M", time.localtime(entry.at)),
            "steps": steps,
        }

    def state(self) -> dict:
        """Plain data for the pages (the Undo / Redo bar and the History panel).

        undo_entries: newest change first; each has `steps` = how many changes
        going back to just before it would undo. redo_entries: the change redo
        would re-apply next comes first.
        """
        undo_entries = [self._row(e, i + 1) for i, e in enumerate(reversed(self._undo))]
        redo_entries = [self._row(e, i + 1) for i, e in enumerate(reversed(self._redo))]
        return {
            "can_undo": self.can_undo,
            "undo_label": self.undo_label,
            "undo_summary": undo_entries[0]["summary"] if undo_entries else "",
            "can_redo": self.can_redo,
            "redo_label": self.redo_label,
            "undo_count": len(self._undo),
            "redo_count": len(self._redo),
            "undo_entries": undo_entries,
            "redo_entries": redo_entries,
            "token": self.version,
        }

    # -- moving --------------------------------------------------------- #
    def check_token(self, expected) -> None:
        """Refuse a request made from a page that no longer shows the truth."""
        if expected is None or expected == "":
            return
        if str(expected) != str(self.version):
            raise HistoryError(
                "The configuration changed since that page was shown (for example in "
                "another tab), so nothing was undone or redone. Check the history and try again."
            )

    def _swap(self, session, entry: Snapshot, target: list[Snapshot]) -> None:
        """Restore `entry` and push the state it replaced onto `target`.

        The state being replaced is saved first, for the opposite stack. If the
        restore fails nothing has changed and the entry is still where it was."""
        originator = ConfigOriginator(session.config)
        replaced = originator.create_memento(entry.memento.areas)
        try:
            originator.restore(entry.memento)
        except MementoError as error:
            raise HistoryError(str(error)) from error
        target.append(
            Snapshot(entry.label, replaced, session.dirty, self.version, entry.summary, entry.at, entry.id)
        )
        session.dirty = entry.dirty
        self.version = entry.version
        self._fresh = False

    def undo(self, session, expected=None) -> str:
        """Restore the configuration from before the latest change."""
        self.check_token(expected)
        if not self._undo:
            raise HistoryError("There is nothing to undo.")
        if session.config is None:
            raise HistoryError("No configuration is loaded.")
        entry = self._undo[-1]
        self._swap(session, entry, self._redo)
        self._undo.pop()
        return entry.label

    def redo(self, session, expected=None) -> str:
        """Re-apply the change that was last undone."""
        self.check_token(expected)
        if not self._redo:
            raise HistoryError("There is nothing to redo.")
        if session.config is None:
            raise HistoryError("No configuration is loaded.")
        entry = self._redo[-1]
        self._swap(session, entry, self._undo)
        self._redo.pop()
        return entry.label

    def go_to(self, session, entry_id, expected=None) -> list[str]:
        """Jump to just BEFORE change `entry_id` (undoing it and everything
        after it), or, for a change that was already undone, to just AFTER it
        (redoing everything up to and including it).

        Returns the labels of the changes undone or redone. Nothing moves when
        the entry is unknown."""
        self.check_token(expected)
        if session.config is None:
            raise HistoryError("No configuration is loaded.")
        try:
            wanted = int(entry_id)
        except (TypeError, ValueError):
            raise HistoryError("That history entry does not exist any more.") from None
        for index, entry in enumerate(self._undo):
            if entry.id == wanted:
                return [self.undo(session) for _ in range(len(self._undo) - index)]
        for index, entry in enumerate(self._redo):
            if entry.id == wanted:
                return [self.redo(session) for _ in range(len(self._redo) - index)]
        raise HistoryError("That history entry does not exist any more.")

    # -- several edits as one step (the AI assistant's apply_changes) --- #
    def checkpoint(self) -> tuple[list[Snapshot], list[Snapshot], int]:
        """Remember the stacks and the version as they are now (see rewind_to)."""
        return list(self._undo), list(self._redo), self.version

    def rewind_to(self, checkpoint: tuple[list[Snapshot], list[Snapshot], int]) -> None:
        """Forget every change recorded since checkpoint().

        Only the history moves here. The caller puts the configuration itself
        back first (with a memento taken at the same moment), so afterwards the
        stacks, the version and the configuration all describe the earlier
        state, and a rolled-back change can't be redone by mistake."""
        undo, redo, version = checkpoint
        self._undo[:] = undo
        self._redo[:] = redo
        self.version = version
        self._fresh = False

    # -- lifecycle ------------------------------------------------------ #
    def clear(self) -> None:
        """Forget everything (a different configuration replaced the current one)."""
        self._undo.clear()
        self._redo.clear()
        self.version = new_version()
        self._fresh = False

    def mark_saved(self) -> None:
        """The configuration was just saved, so every remembered state now
        differs from the saved file and must count as having unsaved changes."""
        for entry in self._undo + self._redo:
            entry.dirty = True
