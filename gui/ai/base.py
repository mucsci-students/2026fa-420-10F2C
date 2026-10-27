"""
Pieces shared by every file of AI tools (Sprint 3 Section 4).

gui/ai/tools.py has the read tools and the add tools; gui/ai/changes.py has the update and
delete tools. Both build their tools from the same few things, which live here so neither file
has to import the other:

    ToolResult / AiTool   what a tool call reports, and how a tool is described
    find_name()           finds the item the user meant ("roddy140" -> "RODDY140"), never guessing
    _join, _plural, ...   the small wording helpers every tool reply uses
    NoArgs, NameArgs,     argument shapes several tools share
    CourseArgs, AvailabilityArgs
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, field_validator

from gui.constants import DAY_NAMES
from gui.controllers.errors import ControllerError

NO_CONFIG_MESSAGE = "There is no configuration yet. Load or create one first in the Configuration Editor."
WEEKDAYS = tuple(DAY_NAMES)


LOOKUP_PREFIXES = ("list_", "get_", "show_")


@dataclass(frozen=True)
class ToolResult:
    """What one tool call really did, in words the user can read."""

    tool: str
    ok: bool
    message: str
    changed: bool = False  # True only when the configuration was edited
    write: bool = False  # True for tools that try to edit the configuration
    final: bool = True  # False for plain lookups: the AI sees them and goes on; they are not the answer


class Unchanged(str):
    """A successful reply that changed nothing (the item already had those values).

    A write tool that returns this is reported as a success that did not edit the configuration,
    so the user is never told that something is "applied but not yet saved" when it was not.
    """


@dataclass(frozen=True)
class AiTool:
    name: str
    description: str
    args: type[BaseModel]
    handler: Callable[[Any, Any], str]
    write: bool = False
    needs_config: bool = True

    @property
    def final(self) -> bool:
        """True when this tool's own text is the answer shown to the user.

        Lookups (list_*, get_*, show_*) are only for the AI to read: it can look something up and
        then act on it, or answer in its own words. Everything else (adds, updates, deletes, the
        delete confirmation, the capability list) ends the request with the application's own
        words, so the AI can never re-word what actually happened.
        """
        return not self.name.startswith(LOOKUP_PREFIXES)


# ---------------------------------------------------------------------- #
#  Small helpers
# ---------------------------------------------------------------------- #
def _key(name: str) -> str:
    """Case, space and punctuation-insensitive form of a name ("Roddy 140" == "RODDY140")."""
    return re.sub(r"[^0-9a-z]", "", str(name).casefold())


def _without_title(name: str) -> str:
    return re.sub(
        r"^(dr|prof|professor|mr|mrs|ms)\.?\s+",
        "",
        str(name).strip(),
        flags=re.IGNORECASE,
    )


def find_name(wanted: str, names: Iterable[str]) -> str | None:
    """The existing name the user meant, or None.

    Exact match first, then ignoring case/spaces/punctuation ("roddy140" finds
    "RODDY140"), then ignoring a title ("Dr. Hogg" finds "Hogg"). A loose
    match only counts when exactly one name fits; when several fit, a
    ControllerError asks the user which one they mean, so nothing is guessed.
    """
    names = list(names)
    if wanted in names:
        return wanted
    for loosen in (_key, lambda value: _key(_without_title(value))):
        fits = [name for name in names if loosen(name) == loosen(wanted)]
        if len(fits) == 1:
            return fits[0]
        if len(fits) > 1:
            # Never guess between two real items (e.g. "RODDY140" and "Roddy 140").
            raise ControllerError(
                f"'{wanted}' could mean {_join(fits)}. Say which one you mean."
            )
    return None


def _resolve(wanted: Iterable[str], names: Iterable[str]) -> list[str]:
    """Map each requested name to an existing one; unknown names are kept as
    typed so the controller reports them with its own message."""
    names = list(names)
    return [find_name(item, names) or item for item in wanted]


def _day(value: str) -> str:
    """'Friday', 'fri', 'FRI' -> 'FRI'."""
    text = str(value).strip().upper()
    for code, name in DAY_NAMES.items():
        if text in (code, name.upper()):
            return code
    raise ValueError(f"'{value}' is not a weekday. Use one of: {', '.join(WEEKDAYS)}.")


def _join(items: Iterable[str], empty: str = "none") -> str:
    items = [str(item) for item in items]
    return ", ".join(items) if items else empty


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _notes(lines: Iterable[str]) -> str:
    lines = [line for line in lines if line]
    return (" " + " ".join(lines)) if lines else ""


def _require(data: dict) -> dict:
    """describe_* controllers return {"has_config": False} with nothing loaded."""
    if not data.get("has_config"):
        raise ControllerError(NO_CONFIG_MESSAGE)
    return data


def _place(item: dict) -> str:
    """Capacity, features and availability of a room or lab, in one line."""
    parts = [f"capacity {item['capacity']}"]
    if item.get("features"):
        parts.append(f"features: {_join(item['features'])}")
    if item.get("availability"):
        parts.append(
            "available "
            + "; ".join(f"{row['day']} {row['ranges']}" for row in item["availability"])
        )
    return ", ".join(parts)


def _course_line(row: dict) -> str:
    if row["faculty"] is None:
        taught = f"faculty chosen from preferences ({_join(row['derived_faculty'], 'nobody prefers it yet')})"
    else:
        taught = f"faculty: {_join(row['faculty'])}"
    return (
        f"{row['display']}: {row['credits']} credits, capacity {row['capacity']}, {row['modality']}, "
        f"rooms: {_join(row['rooms'])}, labs: {_join(row['labs'])}, {taught}, "
        f"conflicts: {_join(row['conflicts'])}"
    )


# ---------------------------------------------------------------------- #
#  Argument shapes several tools share
# ---------------------------------------------------------------------- #
class NoArgs(BaseModel):
    pass


class NameArgs(BaseModel):
    name: str = Field(description="The name, as the user wrote it")


class CourseArgs(BaseModel):
    course_id: str = Field(description='The course ID, e.g. "CMSC 420"')


class AvailabilityArgs(BaseModel):
    day: str = Field(description="Weekday: MON, TUE, WED, THU or FRI")
    start: str = Field(description='24-hour start time, e.g. "09:00"')
    end: str = Field(description='24-hour end time, e.g. "17:00"')

    @field_validator("day")
    @classmethod
    def check_day(cls, value: str) -> str:
        return _day(value)
