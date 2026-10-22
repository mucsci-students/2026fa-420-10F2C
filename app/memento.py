"""
The Memento design pattern, used for undo and redo (Sprint 2 Sections 11 and 12,
Sprint 3 Section 13).

Model-layer code: no HTTP, no templates, and no scheduler-library imports, so it
can be unit-tested on its own.

THE PATTERN (Gamma, Helm, Johnson, Vlissides)
    Capture an object's internal state, without breaking its encapsulation, so
    the object can be returned to that state later.

    Participant          Here
    -------------------  ---------------------------------------------------
    Originator           ConfigOriginator: creates mementos from the loaded
                         configuration and restores the configuration from them
    Memento              Memento (abstract) and one concrete class per kind of
                         configuration item (see MEMENTO_TYPES). Each one
                         knows how to read and write ITS OWN slice of the
                         configuration, and nobody else looks inside it
    CompositeMemento     A set of mementos taken together, so a change that
                         touches several kinds of item (deleting a room also
                         changes course lists and faculty preferences) is still
                         one step to undo
    Caretaker            app.history.ConfigHistory: keeps the undo and redo
                         stacks of CompositeMementos and never opens one

WHY ONE MEMENTO PER KIND OF ITEM
    An edit usually changes one part of the configuration, so only that part is
    remembered: editing a room keeps a RoomsMemento, not a copy of every course
    and every faculty member. A cascading delete keeps exactly the mementos of
    the parts it touched. Each memento also describes its own change in plain
    words ("Removed room Roddy 136"), so the History page needs no knowledge of
    how rooms, courses or faculty are stored.

    Meetings live inside their class pattern, so PatternsMemento carries them.

HOW A RESTORE STAYS SAFE
    ConfigOriginator.restore() writes the remembered parts through the scheduler
    library's edit mode, which validates the whole result and copies it back
    only if it is valid, so a restore is all-or-nothing like every other edit.
"""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any, ClassVar


class MementoError(Exception):
    """Raised when a remembered state cannot be put back."""


# ---------------------------------------------------------------------- #
#  Small helpers
# ---------------------------------------------------------------------- #
def _course_key(course) -> str:
    section = getattr(course, "section_id", None)
    course_id = course.course_id
    return f"{course_id}.{section}" if section else str(course_id)


def _plural(word: str, count: int) -> str:
    if count == 1:
        return word
    return "faculty members" if word == "faculty member" else f"{word}s"


def _unmatched(mine: list, other: list, name_of) -> list[str]:
    """Names of the items in `mine` that have no equal twin in `other`.

    Items are compared with ==, which for the library's Pydantic records
    compares their values (so a set that lists its members in another order is
    still equal)."""
    pool = list(other)
    names = []
    for item in mine:
        for position, candidate in enumerate(pool):
            if candidate == item:
                del pool[position]
                break
        else:
            names.append(name_of(item))
    return names


def _field_names(obj) -> list[str]:
    fields = getattr(type(obj), "model_fields", None)
    return list(fields) if fields else list(vars(obj))


def _assign(owner, name: str, value) -> None:
    """Put `value` into owner.<name>, changing a list or dict IN PLACE so that
    nothing holding the old list is left pointing at stale data."""
    current = getattr(owner, name, None)
    if isinstance(current, list) and isinstance(value, list):
        current[:] = value
    elif isinstance(current, dict) and isinstance(value, dict):
        current.clear()
        current.update(value)
    else:
        setattr(owner, name, value)


# ---------------------------------------------------------------------- #
#  Memento: the abstract part
# ---------------------------------------------------------------------- #
class Memento(ABC):
    """A saved copy of ONE part of the configuration.

    Subclasses say where their part lives (_read) and how to put it back
    (_write). Everything else is shared."""

    area: ClassVar[str]  # short key, e.g. "rooms"
    title: ClassVar[str]  # what a person calls it, e.g. "rooms"

    def __init__(self, state: Any) -> None:
        self._state = state

    # -- what a subclass provides --------------------------------------- #
    @staticmethod
    @abstractmethod
    def _read(config) -> Any:
        """The live part of `config` this memento is about (not a copy)."""

    @staticmethod
    @abstractmethod
    def _write(config, state: Any) -> None:
        """Put `state` back into `config`."""

    @abstractmethod
    def describe_change(self, config) -> list[str]:
        """What differs between this saved part and the one now in `config`,
        as phrases like "Removed room A". Empty when nothing differs."""

    # -- shared behaviour ------------------------------------------------ #
    @classmethod
    def exists_in(cls, config) -> bool:
        """True when `config` has this part at all (a trimmed-down configuration
        used in a unit test may not)."""
        try:
            cls._read(config)
        except AttributeError:
            return False
        return True

    @classmethod
    def capture(cls, config) -> Memento:
        """Save an independent copy of this part of `config`."""
        return cls(copy.deepcopy(cls._read(config)))

    def restore_to(self, config) -> None:
        """Put the saved part back into `config` (as a fresh copy, so the
        memento can be used again, for example by a later redo)."""
        self._write(config, copy.deepcopy(self._state))

    def differs_from(self, config) -> bool:
        """True when the part now in `config` is not what was saved."""
        return self._state != self._read(config)

    def __repr__(self) -> str:
        return f"<{type(self).__name__}>"


class _ItemListMemento(Memento):
    """A memento for a list of named items (rooms, courses, ...)."""

    word: ClassVar[str]  # singular, e.g. "room"

    @staticmethod
    @abstractmethod
    def _name_of(item) -> str:
        """How the item is called in a sentence."""

    def describe_change(self, config) -> list[str]:
        old, new = list(self._state), list(self._read(config))
        gone = _unmatched(old, new, self._name_of)
        came = _unmatched(new, old, self._name_of)
        changed = [name for name in gone if name in came]
        parts = []
        for verb, names in (
            ("Removed", [n for n in gone if n not in changed]),
            ("Added", [n for n in came if n not in changed]),
            ("Changed", changed),
        ):
            if not names:
                continue
            noun = _plural(self.word, len(names))
            if len(names) <= 2:
                parts.append(f"{verb} {noun} {', '.join(names)}")
            else:
                parts.append(f"{verb} {len(names)} {noun}")
        return parts


# ---------------------------------------------------------------------- #
#  The concrete mementos, one per kind of item
# ---------------------------------------------------------------------- #
class RoomsMemento(_ItemListMemento):
    area = "rooms"
    title = "rooms"
    word = "room"

    @staticmethod
    def _read(config):
        return config.config.rooms

    @staticmethod
    def _write(config, state):
        _assign(config.config, "rooms", state)

    @staticmethod
    def _name_of(item) -> str:
        return item.name


class LabsMemento(_ItemListMemento):
    area = "labs"
    title = "labs"
    word = "lab"

    @staticmethod
    def _read(config):
        return config.config.labs

    @staticmethod
    def _write(config, state):
        _assign(config.config, "labs", state)

    @staticmethod
    def _name_of(item) -> str:
        return item.name


class CoursesMemento(_ItemListMemento):
    area = "courses"
    title = "courses"
    word = "course"

    @staticmethod
    def _read(config):
        return config.config.courses

    @staticmethod
    def _write(config, state):
        _assign(config.config, "courses", state)

    @staticmethod
    def _name_of(item) -> str:
        return _course_key(item)


class FacultyMemento(_ItemListMemento):
    area = "faculty"
    title = "faculty"
    word = "faculty member"

    @staticmethod
    def _read(config):
        return config.config.faculty

    @staticmethod
    def _write(config, state):
        _assign(config.config, "faculty", state)

    @staticmethod
    def _name_of(item) -> str:
        return item.name


class PatternsMemento(_ItemListMemento):
    """Class patterns, including the meetings that belong to each one."""

    area = "patterns"
    title = "class patterns"
    word = "class pattern"

    @staticmethod
    def _read(config):
        return config.time_slot_config.classes

    @staticmethod
    def _write(config, state):
        _assign(config.time_slot_config, "classes", state)

    @staticmethod
    def _name_of(item) -> str:
        return f"{item.credits}-credit pattern"


class TimeSlotsMemento(Memento):
    """Weekday time blocks and the other timing options (everything in the
    time-slot configuration except the class patterns)."""

    area = "time_slots"
    title = "time slots"

    @staticmethod
    def _read(config):
        slots = config.time_slot_config
        return {
            name: getattr(slots, name)
            for name in _field_names(slots)
            if name != "classes"
        }

    @staticmethod
    def _write(config, state):
        for name, value in state.items():
            _assign(config.time_slot_config, name, value)

    def describe_change(self, config) -> list[str]:
        return ["Changed time slots"] if self.differs_from(config) else []


class SettingsMemento(Memento):
    """Global settings: the generation limit and the optimizer flags."""

    area = "settings"
    title = "global settings"

    @staticmethod
    def _read(config):
        return {"limit": config.limit, "optimizer_flags": config.optimizer_flags}

    @staticmethod
    def _write(config, state):
        _assign(config, "limit", state["limit"])
        _assign(config, "optimizer_flags", state["optimizer_flags"])

    def describe_change(self, config) -> list[str]:
        return ["Changed global settings"] if self.differs_from(config) else []


# In the order a description lists them.
MEMENTO_TYPES: tuple[type[Memento], ...] = (
    RoomsMemento,
    LabsMemento,
    CoursesMemento,
    FacultyMemento,
    PatternsMemento,
    TimeSlotsMemento,
    SettingsMemento,
)
_BY_AREA = {kind.area: kind for kind in MEMENTO_TYPES}


# ---------------------------------------------------------------------- #
#  Several mementos taken together
# ---------------------------------------------------------------------- #
class CompositeMemento:
    """Mementos of several parts of the configuration, kept and restored as one."""

    def __init__(self, parts: Iterable[Memento] = ()) -> None:
        self._parts: dict[str, Memento] = {part.area: part for part in parts}

    @classmethod
    def capture(cls, config, areas: Iterable[str] | None = None) -> CompositeMemento:
        """Save the named parts of `config` (every part when `areas` is None).

        A part the configuration does not have is skipped."""
        wanted = list(_BY_AREA) if areas is None else list(areas)
        return cls(
            _BY_AREA[area].capture(config)
            for area in wanted
            if _BY_AREA[area].exists_in(config)
        )

    @property
    def areas(self) -> list[str]:
        return list(self._parts)

    def __len__(self) -> int:
        return len(self._parts)

    def changed_since(self, config) -> CompositeMemento:
        """Only the parts whose saved state differs from what `config` holds now."""
        return CompositeMemento(
            part for part in self._parts.values() if part.differs_from(config)
        )

    def restore_to(self, config) -> None:
        for part in self._parts.values():
            part.restore_to(config)

    def describe_change(self, config) -> str:
        """Plain words for what differs from `config`, e.g.
        "Removed room Roddy 136; Changed 3 courses". "" when nothing differs."""
        phrases: list[str] = []
        for part in self._parts.values():
            phrases += part.describe_change(config)
        return "; ".join(phrases)


# ---------------------------------------------------------------------- #
#  The originator
# ---------------------------------------------------------------------- #
class ConfigOriginator:
    """The object whose state is saved and restored: the loaded configuration."""

    def __init__(self, config) -> None:
        self.config = config

    def create_memento(self, areas: Iterable[str] | None = None) -> CompositeMemento:
        """Save the current state of the named parts (all of them by default)."""
        return CompositeMemento.capture(self.config, areas)

    def restore(self, memento: CompositeMemento) -> None:
        """Put every part held by `memento` back, all or nothing.

        The write happens on the library's edit-mode draft, which validates the
        complete configuration and copies it back only when it is valid."""
        try:
            with self.config.edit_mode() as draft:
                memento.restore_to(draft)
        except Exception as error:
            raise MementoError(
                f"The earlier state could not be restored, so nothing was changed: {error}"
            ) from error
