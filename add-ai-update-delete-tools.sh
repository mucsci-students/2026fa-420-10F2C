#!/usr/bin/env bash
#
# add-ai-update-delete-tools.sh
#
# One step: gives the AI chat working UPDATE and DELETE tools (Sprint 3, Section 4), so it can
# change and delete rooms, labs, courses, faculty, time slots, class patterns, meetings and
# global settings. Run it on your feature/ai-chat-foundation branch AFTER add-ai-chat.sh.
#
# How it keeps to the Sprint 3 rules
#   * Every tool validates its arguments first, then calls the same controller the Edit and Delete
#     pages use, so the scheduler library decides what is valid. A rejected change leaves the
#     configuration untouched (all-or-nothing, same as the GUI).
#   * Update tools take only the values to change and merge them into the current record. A request
#     that changes nothing says so and does not mark the configuration as unsaved.
#   * Deletes take TWO messages. delete_* only describes what would be deleted (including items
#     that go with it). confirm_delete runs it only from a later message, within 10 minutes, only
#     if nothing else changed, and only from the same browser session. cancel_delete forgets it.
#   * Every real change is on the History page and can be undone there. Replies say "applied but
#     not yet saved to a file".
#   * The system prompt now lists every tool (Section 5) and says the assistant cannot validate,
#     save or generate yet.
#
# What it changes (nothing is committed for you)
#   new       gui/ai/base.py            pieces shared by tools.py and changes.py
#   new       gui/ai/changes.py         the update and delete tools
#   new       tests/test_ai_changes.py  tests for all of it
#   replaced  gui/ai/tools.py           small edits: shared pieces moved to base.py, list_meetings
#                                       added, registry includes the new tools
#   replaced  gui/ai/prompt.py          honest capability text, tool list, delete rules
#   replaced  gui/ai/runner.py          system prompt now includes the tool list
#   edited    tests/test_ai_chat.py     "what can you do" assertions
#   edited    README.md                 AI Assistant section
#
# Usage:  bash ~/add-ai-update-delete-tools.sh            apply, then run the AI tests if uv exists
#         NO_TEST=1 bash ~/add-ai-update-delete-tools.sh  apply only
#
# Safe to re-run: it changes NOTHING and says why if you are on develop, if the chat button
# (add-ai-chat.sh) is not applied yet, if a file it replaces is not the expected version, or if a
# file it touches has uncommitted changes. Keep this script OUTSIDE the repository.

set -euo pipefail

die() { echo "ERROR: $*" >&2; exit 1; }

root="$(git rev-parse --show-toplevel 2>/dev/null)" || die "Run this from inside the repository."
cd "$root"

current="$(git branch --show-current)"
case "$current" in
    ""|develop|main|master) die "You are on '${current:-no branch}'. Switch to your feature branch first (the one with the chat button)." ;;
esac

[ -f gui/static/gui/js/chat.js ] || die "The chat button is not in this branch yet. Run add-ai-chat.sh first."
[ -f gui/ai/service.py ] || die "gui/ai/service.py is missing: this branch does not have the AI assistant."
if [ -e gui/ai/changes.py ]; then
    echo "Already applied: gui/ai/changes.py exists. Nothing to do."
    exit 0
fi
[ ! -e gui/ai/base.py ] && [ ! -e tests/test_ai_changes.py ] || die "gui/ai/base.py or tests/test_ai_changes.py already exists; I will not overwrite it."

NEW_FILES=(gui/ai/base.py gui/ai/changes.py tests/test_ai_changes.py)
REPLACED=(gui/ai/tools.py gui/ai/prompt.py gui/ai/runner.py)
EDITED=(tests/test_ai_chat.py README.md)
for f in "${REPLACED[@]}" "${EDITED[@]}"; do
    [ -f "$f" ] || die "Missing $f. Is this the right repository?"
done
if ! git diff --quiet -- "${REPLACED[@]}" "${EDITED[@]}" || ! git diff --cached --quiet -- "${REPLACED[@]}" "${EDITED[@]}"; then
    die "Some files this script changes have uncommitted changes. Commit or stash them first: ${REPLACED[*]} ${EDITED[*]}"
fi

PYTHON="$(command -v python3 || command -v python || true)"
[ -n "$PYTHON" ] || die "python3 is needed."

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/new"

cat > "$tmp/new/gui__ai__base.py" <<'BASE_EOF'
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


@dataclass(frozen=True)
class ToolResult:
    """What one tool call really did, in words the user can read."""

    tool: str
    ok: bool
    message: str
    changed: bool = False  # True only when the configuration was edited
    write: bool = False  # True for tools that try to edit the configuration


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


# ---------------------------------------------------------------------- #
#  Small helpers
# ---------------------------------------------------------------------- #
def _key(name: str) -> str:
    """Case, space and punctuation-insensitive form of a name ("Roddy 140" == "RODDY140")."""
    return re.sub(r"[^0-9a-z]", "", str(name).casefold())


def _without_title(name: str) -> str:
    return re.sub(r"^(dr|prof|professor|mr|mrs|ms)\.?\s+", "", str(name).strip(), flags=re.IGNORECASE)


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
            raise ControllerError(f"'{wanted}' could mean {_join(fits)}. Say which one you mean.")
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
        parts.append("available " + "; ".join(f"{row['day']} {row['ranges']}" for row in item["availability"]))
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
BASE_EOF

cat > "$tmp/new/gui__ai__changes.py" <<'CHANGES_EOF'
"""
The AI assistant's tools that change or remove things (Sprint 3 Section 4).

    ToolBox(request).call("update_room", {"name": "Roddy 140", "capacity": 40})
    ToolBox(request).call("delete_room", {"name": "Roddy 136"})     # shows what would change
    ToolBox(request).call("confirm_delete")                          # in a LATER message

Updates
    "Create, update, and delete items in the required configuration areas": every area has an
    update tool (rooms, labs, courses, faculty, time slots, class patterns, meetings, global
    settings). The model only sends what the user wants changed; the tool reads the item as it is
    right now, merges the change into it, and hands the complete result to the same controller the
    Edit form uses. So the scheduler library validates the COMPLETE configuration, and a failed
    edit leaves the last valid configuration untouched, with nothing half-applied. A successful
    edit lands in the undo history like any other edit.

Deletes (the same safeguard as the Delete pages)
    The Delete pages show what a delete will change and wait for the Delete button. The AI has no
    button, so a delete is two steps, and the server (not the model) enforces it:

      1. delete_room / delete_lab / delete_course / delete_faculty / delete_time_slot /
         delete_class_pattern / delete_meeting only DESCRIBE the delete, using the same plan the
         Delete page shows (gui/controllers/dependencies.py: what else changes, which course
         sections would be deleted too, what blocks it). Nothing is deleted.
      2. confirm_delete runs it, but only when the user's NEXT message asks for it. A delete
         described in a request cannot be confirmed in that same request, the description goes
         stale after 10 minutes, and it is refused if the configuration changed in between.

    Every delete goes through the normal controller, so the cascade is one validated edit and can
    be undone from the History page.

Nothing here edits the configuration directly; every change is a controller call.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, field_validator

from gui.ai.base import (
    WEEKDAYS,
    AiTool,
    AvailabilityArgs,
    CourseArgs,
    NameArgs,
    NoArgs,
    Unchanged,
    _course_line,
    _day,
    _join,
    _notes,
    _place,
    _plural,
    _resolve,
    find_name,
)
from gui.constants import DAY_NAMES
from gui.controllers import (
    courses,
    faculty,
    labs,
    meetings,
    patterns,
    rooms,
    settings,
    timeslots,
)
from gui.controllers import dependencies as deps
from gui.controllers.common import require_config
from gui.controllers.errors import ControllerError
from gui.session_store import get_session

PENDING_SECONDS = 600  # a described delete stops being confirmable after this long
_PENDING_ATTR = "ai_pending"  # where the described delete waits, on the browser's own Session
UNDO_HINT = "You can undo it from the History page."
NOTHING_TO_CHANGE = "Tell me what to change, for example a new capacity or name."

_now: Callable[[], float] = time.monotonic  # tests replace this to age a pending delete


# ---------------------------------------------------------------------- #
#  Small helpers
# ---------------------------------------------------------------------- #
def _existing(wanted: str, names: Iterable[str], label: str) -> str:
    """The existing item the user meant, or a ControllerError saying there is none."""
    found = find_name(str(wanted).strip(), names)
    if found is None:
        raise ControllerError(f"No {label} named '{str(wanted).strip()}' exists.")
    return found


def _hhmm(value: str) -> str:
    """'9:00' -> '09:00' so a time typed loosely still finds the block it names."""
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(value))
    return f"{int(match.group(1)):02d}:{match.group(2)}" if match else str(value).strip()


def _version(request) -> int:
    """Changes every time the configuration really changes (undo and redo included)."""
    return get_session(request).history.version


def _token(request) -> str:
    """Identifies THIS request, so a delete can tell 'asked just now' from 'asked earlier'."""
    token = getattr(request, "_ai_request_token", None)
    if token is None:
        token = uuid.uuid4().hex
        request._ai_request_token = token
    return token


def _weekday(value: str) -> str:
    try:
        return _day(value)
    except ValueError as error:
        raise ControllerError(str(error)) from error


class ListChange(BaseModel):
    """How to change a list: replace all of it, or add to it and remove from it."""

    replace: list[str] | None = Field(
        default=None, description="Make the list exactly these. Leave out to keep the current list"
    )
    add: list[str] = Field(default_factory=list, description="Things to add to the list")
    remove: list[str] = Field(default_factory=list, description="Things to take out of the list")

    @property
    def asked(self) -> bool:
        return self.replace is not None or bool(self.add) or bool(self.remove)


def _asked(*values: Any) -> bool:
    """True when the user asked for at least one change (not None, False or empty)."""
    for value in values:
        if isinstance(value, ListChange):
            if value.asked:
                return True
        elif value is None or value is False or value == "" or value == []:
            continue
        else:
            return True
    return False


def _edited_list(current: list[str], change: ListChange | None, known: Iterable[str] | None = None) -> list[str]:
    """`current` with the change applied; names are matched to `known` items when given."""
    if change is None or not change.asked:
        return list(current)
    known = list(known) if known is not None else None

    def match(items: list[str], against: Iterable[str] | None) -> list[str]:
        return _resolve(items, against) if against is not None else [str(item).strip() for item in items]

    result = match(change.replace, known) if change.replace is not None else list(current)
    gone = set(match(change.remove, list(current) if known is None else known))
    result = [item for item in result if item not in gone]
    for item in match(change.add, known):
        if item not in result:
            result.append(item)
    return list(dict.fromkeys(result))


def _list_changes(label: str, before: list[str], after: list[str]) -> list[str]:
    added = [item for item in after if item not in before]
    removed = [item for item in before if item not in after]
    lines = []
    if added:
        lines.append(f"{label} added: {_join(added)}")
    if removed:
        lines.append(f"{label} removed: {_join(removed)}")
    if not added and not removed and before != after:
        lines.append(f"{label} reordered")
    return lines


def _times_from(items: Iterable[AvailabilityArgs]) -> dict[str, list[dict]]:
    times: dict[str, list[dict]] = {}
    for item in items:
        times.setdefault(item.day, []).append({"start": _hhmm(item.start), "end": _hhmm(item.end)})
    return times


def _times_text(times: dict) -> str:
    rows = [
        f"{day} " + ", ".join(f"{block['start']}-{block['end']}" for block in times[day])
        for day in WEEKDAYS
        if times.get(day)
    ]
    return "; ".join(rows) if rows else "any time"


def _finish(request, before_version: int, label: str, changes: list[str], notices: list[str], now: str = "") -> str:
    """The reply for an update: what changed, built from what the controller really did."""
    if _version(request) == before_version:
        return Unchanged(f"{label} already has those values, so nothing was changed.")
    said = "; ".join(changes) if changes else "updated"
    return f"{label} updated: {said}." + (f" Now: {now}." if now else "") + _notes(notices)


# ---------------------------------------------------------------------- #
#  Rooms and labs
# ---------------------------------------------------------------------- #
class UpdatePlaceArgs(BaseModel):
    name: str = Field(description="The room or lab to change, as the user wrote it")
    new_name: str | None = Field(default=None, description="A new name. Only when the user wants to rename it")
    capacity: int | None = Field(default=None, description="The new capacity. Only when it should change")
    features: ListChange | None = Field(
        default=None, description="Change the features it provides: replace the list, or add/remove some"
    )
    availability: list[AvailabilityArgs] | None = Field(
        default=None,
        description="The COMPLETE new weekly availability (every day and time range). Leave out to keep it",
    )
    any_time: bool = Field(default=False, description="True to make it available at any time (clears availability)")


def _update_place(request, args: UpdatePlaceArgs, *, kind: str, names, get, update) -> str:
    label = kind.capitalize()
    found = _existing(args.name, names, kind)
    if not _asked(args.new_name, args.capacity, args.features, args.availability, args.any_time):
        raise ControllerError(NOTHING_TO_CHANGE)
    current = get(request, found)

    new_name = (args.new_name or "").strip() or found
    capacity = current["capacity"] if args.capacity is None else args.capacity
    features = _edited_list(current["features"], args.features)
    times = current["times"]
    if args.any_time:
        times = {}
    elif args.availability is not None:
        times = _times_from(args.availability)

    changes = []
    if new_name != found:
        changes.append(f"renamed to '{new_name}'")
    if capacity != current["capacity"]:
        changes.append(f"capacity {current['capacity']} -> {capacity}")
    changes += _list_changes("features", current["features"], features)
    if times != current["times"]:
        changes.append(f"availability: {_times_text(times)}")
    if not changes:
        return Unchanged(f"{label} '{found}' already has those values, so nothing was changed.")

    before = _version(request)
    notices = update(request, found, {"name": new_name, "capacity": capacity, "features": features, "times": times})
    return _finish(request, before, f"{label} '{found}'", changes, notices, _place(get(request, new_name)))


def update_room(request, args: UpdatePlaceArgs) -> str:
    names = [room.name for room in get_session(request).config.config.rooms]
    return _update_place(request, args, kind="room", names=names, get=rooms.get_room, update=rooms.update_room)


def update_lab(request, args: UpdatePlaceArgs) -> str:
    names = [lab.name for lab in get_session(request).config.config.labs]
    return _update_place(request, args, kind="lab", names=names, get=labs.get_lab, update=labs.update_lab)


# ---------------------------------------------------------------------- #
#  Courses
# ---------------------------------------------------------------------- #
class SectionArgs(CourseArgs):
    section: str | None = Field(
        default=None,
        description='Which section, e.g. "02", only when the course has several. Leave out if it has one',
    )


class UpdateCourseArgs(SectionArgs):
    new_course_id: str | None = Field(default=None, description='A new course ID, e.g. "CMSC 421"')
    new_section_id: str | None = Field(default=None, description="A new section ID")
    credits: int | None = Field(default=None, description="New credit hours (an enabled class pattern must have them)")
    capacity: int | None = Field(default=None, description="New enrollment capacity")
    modality: str | None = Field(default=None, description="in_person, online, or hybrid")
    rooms: ListChange | None = Field(default=None, description="Rooms the course may use (names of existing rooms)")
    labs: ListChange | None = Field(default=None, description="Labs the course may use (names of existing labs)")
    faculty: ListChange | None = Field(
        default=None,
        description="Faculty who teach it (existing names). Replacing with an empty list lets the scheduler choose",
    )
    conflicts: ListChange | None = Field(default=None, description="Course IDs it must not overlap with")
    required_room_features: ListChange | None = Field(default=None, description="Features its room must have")
    required_lab_features: ListChange | None = Field(default=None, description="Features its lab must have")
    reserve_room_during_lab: bool | None = Field(default=None, description="Keep the room reserved during lab meetings")


def _find_section(request, args: SectionArgs, what: str) -> dict:
    """The one course section the user meant, as a row of describe_courses()."""
    rows = courses.describe_courses(request)["courses"]
    course_id = _existing(args.course_id, sorted({row["course_id"] for row in rows}), "course")
    sections = [row for row in rows if row["course_id"] == course_id]
    if args.section is None or not str(args.section).strip():
        if len(sections) > 1:
            listing = _join(row["display"] for row in sections)
            raise ControllerError(f"{course_id} has {len(sections)} sections ({listing}). Say which one to {what}.")
        return sections[0]
    wanted = str(args.section).strip().casefold()
    for row in sections:
        names = {str(row["section_id"] or "").casefold(), row["display"].casefold(), row["display"].split(".")[-1].casefold()}
        if wanted in names:
            return row
    raise ControllerError(f"{course_id} has no section '{args.section}'. Its sections are: {_join(row['display'] for row in sections)}.")


def update_course(request, args: UpdateCourseArgs) -> str:
    session = get_session(request)
    entities = session.config.config
    if not _asked(
        args.new_course_id, args.new_section_id, args.credits, args.capacity, args.modality, args.rooms,
        args.labs, args.faculty, args.conflicts, args.required_room_features, args.required_lab_features,
        args.reserve_room_during_lab,
    ):  # fmt: skip
        raise ControllerError(NOTHING_TO_CHANGE)
    row = _find_section(request, args, "change")
    current = courses.get_course(request, row["index"])

    form = dict(current)
    form["course_id"] = (args.new_course_id or "").strip() or current["course_id"]
    form["section_id"] = (args.new_section_id or "").strip() or current["section_id"]
    for key in ("credits", "capacity"):
        if getattr(args, key) is not None:
            form[key] = getattr(args, key)
    if args.modality is not None:
        form["modality"] = args.modality.strip().lower()
    if args.reserve_room_during_lab is not None:
        form["reserve_room_during_lab"] = args.reserve_room_during_lab

    other_ids = sorted({c.course_id for position, c in enumerate(entities.courses) if position != row["index"]})
    for key, field, known in (
        ("room", args.rooms, [room.name for room in entities.rooms]),
        ("lab", args.labs, [lab.name for lab in entities.labs]),
        ("faculty", args.faculty, [person.name for person in entities.faculty]),
        ("conflicts", args.conflicts, other_ids),
    ):
        form[key] = _edited_list(current[key], field, known)
    for key, field in (("required_room_features", args.required_room_features), ("required_lab_features", args.required_lab_features)):
        before = [item.strip() for item in str(current[key]).split(",") if item.strip()]
        form[key] = _edited_list(before, field)

    changes = []
    for label, key in (("course ID", "course_id"), ("section ID", "section_id"), ("credits", "credits"),
                       ("capacity", "capacity"), ("modality", "modality"),
                       ("keep room during lab", "reserve_room_during_lab")):  # fmt: skip
        if form[key] != current[key]:
            changes.append(f"{label} {current[key]} -> {form[key]}")
    for label, key in (("rooms", "room"), ("labs", "lab"), ("faculty", "faculty"), ("conflicts", "conflicts")):
        changes += _list_changes(label, current[key], form[key])
    for label, key in (("required room features", "required_room_features"), ("required lab features", "required_lab_features")):
        before = [item.strip() for item in str(current[key]).split(",") if item.strip()]
        changes += _list_changes(label, before, form[key])
    name = row["display"]
    if not changes:
        return Unchanged(f"{name} already has those values, so nothing was changed.")

    before_version = _version(request)
    notices = courses.update_course(request, row["index"], form, expected_course_id=current["course_id"])
    now_row = courses.describe_courses(request)["courses"][row["index"]]
    return _finish(request, before_version, f"Course {name}", changes, notices, _course_line(now_row))


# ---------------------------------------------------------------------- #
#  Faculty
# ---------------------------------------------------------------------- #
class PreferenceArgs(BaseModel):
    kind: str = Field(description="What the preference is for: course, room or lab")
    name: str = Field(description="The course ID, room name or lab name")
    weight: int | None = Field(
        default=None, ge=0, le=10, description="How much they want it, 0 to 10. Leave out to REMOVE the preference"
    )

    @field_validator("kind")
    @classmethod
    def check_kind(cls, value: str) -> str:
        kind = str(value).strip().lower()
        if kind not in ("course", "room", "lab"):
            raise ValueError("kind must be course, room or lab")
        return kind


class UpdateFacultyArgs(BaseModel):
    name: str = Field(description="The faculty member to change, as the user wrote it")
    new_name: str | None = Field(default=None, description="A new name. Only when the user wants to rename them")
    minimum_credits: int | None = Field(default=None, description="Fewest credits they must teach")
    maximum_credits: int | None = Field(default=None, description="Most credits they can teach")
    unique_course_limit: int | None = Field(default=None, description="Most different courses they can teach")
    maximum_days: int | None = Field(default=None, description="Most teaching days per week (0 to 5)")
    availability: list[AvailabilityArgs] | None = Field(
        default=None, description="The COMPLETE new weekly availability (every day and range). Leave out to keep it"
    )
    mandatory_days: ListChange | None = Field(default=None, description="Weekdays (MON..FRI) they must teach on")
    preferences: list[PreferenceArgs] | None = Field(
        default=None, description="Course, room or lab preferences to set (with a weight) or remove (no weight)"
    )


def update_faculty(request, args: UpdateFacultyArgs) -> str:
    session = get_session(request)
    entities = session.config.config
    found = _existing(args.name, [person.name for person in entities.faculty], "faculty member")
    if not _asked(
        args.new_name, args.minimum_credits, args.maximum_credits, args.unique_course_limit, args.maximum_days,
        args.availability, args.mandatory_days, args.preferences,
    ):  # fmt: skip
        raise ControllerError(NOTHING_TO_CHANGE)
    current = faculty.get_faculty(request, found)

    form = {key: current[key] for key in (
        "name", "minimum_credits", "maximum_credits", "unique_course_limit", "maximum_days",
        "mandatory_days", "times", "course_preferences", "room_preferences", "lab_preferences",
    )}  # fmt: skip
    form["name"] = (args.new_name or "").strip() or found
    for key in ("minimum_credits", "maximum_credits", "unique_course_limit", "maximum_days"):
        if getattr(args, key) is not None:
            form[key] = getattr(args, key)
        elif form[key] is None:
            # The edit form needs a whole number here; never invent one for the user.
            raise ControllerError(f"{found} has no {key.replace('_', ' ')} set. Tell me what it should be.")
    if args.availability is not None:
        form["times"] = _times_from(args.availability)
    if args.mandatory_days is not None and args.mandatory_days.asked:
        day_change = ListChange(
            replace=None if args.mandatory_days.replace is None else [_weekday(d) for d in args.mandatory_days.replace],
            add=[_weekday(d) for d in args.mandatory_days.add],
            remove=[_weekday(d) for d in args.mandatory_days.remove],
        )  # fmt: skip
        form["mandatory_days"] = _edited_list(current["mandatory_days"], day_change)

    form["course_preferences"] = dict(current["course_preferences"])
    form["room_preferences"] = dict(current["room_preferences"])
    form["lab_preferences"] = dict(current["lab_preferences"])
    known = {
        "course": sorted({course.course_id for course in entities.courses}),
        "room": [room.name for room in entities.rooms],
        "lab": [lab.name for lab in entities.labs],
    }
    preference_changes = []
    for item in args.preferences or []:
        bucket = form[f"{item.kind}_preferences"]
        target = find_name(item.name.strip(), list(bucket) if item.weight is None else known[item.kind])
        if target is None:
            raise ControllerError(
                f"No {item.kind} named '{item.name.strip()}' "
                + ("has a preference to remove." if item.weight is None else "exists to have a preference for.")
            )
        if item.weight is None:
            bucket.pop(target, None)
            preference_changes.append(f"{item.kind} preference for {target} removed")
        elif bucket.get(target) != item.weight:
            bucket[target] = item.weight
            preference_changes.append(f"{item.kind} preference for {target} set to {item.weight}")

    changes = []
    if form["name"] != found:
        changes.append(f"renamed to '{form['name']}'")
    for label, key in (("minimum credits", "minimum_credits"), ("maximum credits", "maximum_credits"),
                       ("different-course limit", "unique_course_limit"), ("teaching days", "maximum_days")):  # fmt: skip
        if form[key] != current[key]:
            changes.append(f"{label} {current[key]} -> {form[key]}")
    if form["times"] != current["times"]:
        changes.append(f"availability: {_times_text(form['times'])}")
    changes += _list_changes("mandatory days", current["mandatory_days"], form["mandatory_days"])
    changes += preference_changes
    if not changes:
        return Unchanged(f"Faculty member '{found}' already has those values, so nothing was changed.")

    before_version = _version(request)
    notices = faculty.update_faculty(request, found, form)
    now = faculty.get_faculty(request, form["name"])
    summary = (
        f"{now['minimum_credits']}-{now['maximum_credits']} credits, at most "
        f"{_plural(now['unique_course_limit'], 'different course')} and {_plural(now['maximum_days'], 'teaching day')}"
    )
    return _finish(request, before_version, f"Faculty member '{found}'", changes, notices, summary)


# ---------------------------------------------------------------------- #
#  Time slots
# ---------------------------------------------------------------------- #
class TimeSlotRef(BaseModel):
    day: str = Field(description="Weekday: MON, TUE, WED, THU or FRI")
    start: str = Field(description='Start time of the existing time slot, 24-hour, e.g. "08:00"')

    @field_validator("day")
    @classmethod
    def check_day(cls, value: str) -> str:
        return _day(value)


class UpdateTimeSlotArgs(TimeSlotRef):
    new_start: str | None = Field(default=None, description="New start time (24-hour)")
    new_end: str | None = Field(default=None, description="New end time (24-hour)")
    new_spacing: int | None = Field(default=None, description="New minutes between possible class start times")


class TimingOptionsArgs(BaseModel):
    max_time_gap: int | None = Field(default=None, description="Largest gap in minutes allowed between a faculty member's classes")
    min_time_overlap: int | None = Field(default=None, description="Smallest overlap in minutes that counts as an overlap")


def _find_block(request, day: str, start: str) -> tuple[int, dict]:
    blocks = timeslots.describe_timeslots(request)
    row = next(item for item in blocks["days"] if item["day"] == day)["blocks"]
    wanted = _hhmm(start)
    for block in row:
        if block["start"] == wanted:
            return block["index"], block
    starts = _join(f"{block['start']}-{block['end']}" for block in row)
    raise ControllerError(f"There is no time slot starting at {wanted} on {DAY_NAMES[day]}. Its time slots are: {starts}.")


def update_time_slot(request, args: UpdateTimeSlotArgs) -> str:
    if not _asked(args.new_start, args.new_end, args.new_spacing):
        raise ControllerError(NOTHING_TO_CHANGE)
    index, block = _find_block(request, args.day, args.start)
    form = {
        "start": _hhmm(args.new_start) if args.new_start else block["start"],
        "end": _hhmm(args.new_end) if args.new_end else block["end"],
        "spacing": block["spacing"] if args.new_spacing is None else args.new_spacing,
    }
    label = f"The {DAY_NAMES[args.day]} time slot {block['start']}-{block['end']}"
    if (form["start"], form["end"], form["spacing"]) == (block["start"], block["end"], block["spacing"]):
        return Unchanged(f"{label} already has those values, so nothing was changed.")
    before = _version(request)
    warnings = timeslots.update_timeslot(request, args.day, index, form)
    now = f"{form['start']}-{form['end']}, a class can start every {form['spacing']} minutes"
    return _finish(request, before, label, [f"now {now}"], warnings)


def update_timing_options(request, args: TimingOptionsArgs) -> str:
    if not _asked(args.max_time_gap, args.min_time_overlap):
        raise ControllerError(NOTHING_TO_CHANGE)
    now = timeslots.describe_timeslots(request)
    form = {
        "max_time_gap": args.max_time_gap if args.max_time_gap is not None else now["max_time_gap"],
        "min_time_overlap": args.min_time_overlap if args.min_time_overlap is not None else now["min_time_overlap"],
    }
    changes = []
    if form["max_time_gap"] != now["max_time_gap"]:
        changes.append(f"max time gap {now['max_time_gap']} -> {form['max_time_gap']} min")
    if form["min_time_overlap"] != now["min_time_overlap"]:
        changes.append(f"min time overlap {now['min_time_overlap']} -> {form['min_time_overlap']} min")
    if not changes:
        return Unchanged("The time slot timing options already have those values, so nothing was changed.")
    before = _version(request)
    timeslots.update_timing_options(request, form)
    return _finish(request, before, "The time slot timing options", changes, [])


# ---------------------------------------------------------------------- #
#  Class patterns and meetings
# ---------------------------------------------------------------------- #
class PatternRef(BaseModel):
    pattern_number: int = Field(description='The pattern number shown by list_class_patterns ("Pattern 2" is 2)')


class UpdatePatternArgs(PatternRef):
    credits: int | None = Field(default=None, description="New credit hours")
    start_time: str | None = Field(default=None, description="A fixed 24-hour start time for the whole pattern")
    clear_start_time: bool = Field(default=False, description="True to remove the pattern's fixed start time")
    enabled: bool | None = Field(default=None, description="True to enable the pattern, False to disable it")


class MeetingRef(PatternRef):
    meeting_number: int = Field(description="The meeting's number within its pattern, counting from 1")


class AddMeetingArgs(PatternRef):
    day: str = Field(description="Weekday: MON, TUE, WED, THU or FRI")
    duration: int = Field(description="Length of the meeting in minutes")
    lab: bool = Field(default=False, description="True if this meeting is held in a lab")
    delivery: str = Field(default="in_person", description="in_person, online, or hybrid")
    start_time: str | None = Field(default=None, description="Fixed 24-hour start time, only if the user gave one")

    @field_validator("day")
    @classmethod
    def check_day(cls, value: str) -> str:
        return _day(value)


class UpdateMeetingArgs(MeetingRef):
    day: str | None = Field(default=None, description="New weekday: MON, TUE, WED, THU or FRI")
    duration: int | None = Field(default=None, description="New length in minutes")
    lab: bool | None = Field(default=None, description="True if it should be held in a lab")
    delivery: str | None = Field(default=None, description="in_person, online, or hybrid")
    start_time: str | None = Field(default=None, description="A fixed 24-hour start time")
    clear_start_time: bool = Field(default=False, description="True to remove the meeting's fixed start time")

    @field_validator("day")
    @classmethod
    def check_day(cls, value: str | None) -> str | None:
        return None if value is None else _day(value)


def _pattern_index(request, args: PatternRef) -> int:
    count = len(get_session(request).config.time_slot_config.classes)
    if not 0 <= args.pattern_number < count:
        raise ControllerError(
            f"There is no class pattern {args.pattern_number}. Patterns are numbered 0 to {count - 1}; "
            "list_class_patterns shows them."
        )
    return args.pattern_number


def _meeting_index(request, args: MeetingRef) -> tuple[int, int]:
    pattern = _pattern_index(request, args)
    count = len(get_session(request).config.time_slot_config.classes[pattern].meetings)
    if not 1 <= args.meeting_number <= count:
        raise ControllerError(f"Pattern {pattern} has {_plural(count, 'meeting')}, numbered 1 to {count}.")
    return pattern, args.meeting_number - 1


def add_meeting(request, args: AddMeetingArgs) -> str:
    pattern = _pattern_index(request, args)
    warnings = meetings.add_meeting(
        request,
        pattern,
        {"day": args.day, "duration": args.duration, "lab": args.lab, "delivery": args.delivery, "start_time": args.start_time},
    )
    return (
        f"Meeting added to pattern {pattern}: {DAY_NAMES[args.day]} {args.duration} min"
        + (" (lab)" if args.lab else "")
        + "."
        + _notes(warnings)
    )


def update_class_pattern(request, args: UpdatePatternArgs) -> str:
    if not _asked(args.credits, args.start_time, args.clear_start_time, args.enabled):
        raise ControllerError(NOTHING_TO_CHANGE)
    index = _pattern_index(request, args)
    current = patterns.get_pattern(request, index)
    form = {
        "credits": current["credits"] if args.credits is None else args.credits,
        "start_time": "" if args.clear_start_time else (_hhmm(args.start_time) if args.start_time else current["start_time"]),
        "enabled": current["enabled"] if args.enabled is None else args.enabled,
    }
    changes = []
    if form["credits"] != current["credits"]:
        changes.append(f"credits {current['credits']} -> {form['credits']}")
    if form["start_time"] != current["start_time"]:
        changes.append(f"start time {current['start_time'] or 'none'} -> {form['start_time'] or 'none'}")
    if form["enabled"] != current["enabled"]:
        changes.append("enabled" if form["enabled"] else "disabled")
    label = f"Class pattern {index}"
    if not changes:
        return Unchanged(f"{label} already has those values, so nothing was changed.")
    before = _version(request)
    warnings = patterns.update_pattern(request, index, form)
    return _finish(request, before, label, changes, warnings, current["summary"])


def update_meeting(request, args: UpdateMeetingArgs) -> str:
    if not _asked(args.day, args.duration, args.lab, args.delivery, args.start_time, args.clear_start_time):
        raise ControllerError(NOTHING_TO_CHANGE)
    pattern, meeting = _meeting_index(request, args)
    current = meetings.get_meeting(request, pattern, meeting)
    form = {
        "day": args.day or current["day"],
        "duration": current["duration"] if args.duration is None else args.duration,
        "lab": current["lab"] if args.lab is None else args.lab,
        "delivery": (args.delivery or current["delivery"]).strip().lower(),
        "start_time": "" if args.clear_start_time else (_hhmm(args.start_time) if args.start_time else current["start_time"]),
    }
    changes = []
    for label, key in (("day", "day"), ("duration", "duration"), ("lab", "lab"), ("delivery", "delivery"), ("start time", "start_time")):
        if form[key] != current[key]:
            changes.append(f"{label} {current[key] or 'none'} -> {form[key] or 'none'}")
    label = f"Meeting {args.meeting_number} of pattern {pattern}"
    if not changes:
        return Unchanged(f"{label} already has those values, so nothing was changed.")
    before = _version(request)
    warnings = meetings.update_meeting(request, pattern, meeting, form)
    return _finish(request, before, label, changes, warnings)


# ---------------------------------------------------------------------- #
#  Global settings
# ---------------------------------------------------------------------- #
class UpdateSettingsArgs(BaseModel):
    limit: int | None = Field(default=None, description="New generation limit (a positive whole number)")
    reset_limit: bool = Field(default=False, description="True to put the generation limit back to its default")
    enable_flags: list[str] = Field(default_factory=list, description="Optimizer flags to turn on")
    disable_flags: list[str] = Field(default_factory=list, description="Optimizer flags to turn off")


def update_global_settings(request, args: UpdateSettingsArgs) -> str:
    if not _asked(args.limit, args.reset_limit, args.enable_flags, args.disable_flags):
        raise ControllerError(NOTHING_TO_CHANGE)
    if args.limit is not None and args.reset_limit:
        raise ControllerError("Ask for either a new generation limit or a reset to the default, not both.")
    data = settings.describe_settings(request)
    known = [flag["name"] for flag in data["flags"]]
    enable = [_existing(flag, known, "optimizer flag") for flag in args.enable_flags]
    disable = [_existing(flag, known, "optimizer flag") for flag in args.disable_flags]
    if set(enable) & set(disable):
        raise ControllerError("The same optimizer flag can't be turned both on and off.")
    wanted = [flag for flag in known if (flag in data["enabled_flags"] and flag not in disable) or flag in enable]
    limit = data["default_limit"] if args.reset_limit else args.limit
    before = _version(request)
    changes = settings.update_settings(request, {"limit": limit, "optimizer_flags": wanted})
    if _version(request) == before:
        return Unchanged("The global settings already have those values, so nothing was changed.")
    return "Global settings updated: " + " ".join(changes)


# ---------------------------------------------------------------------- #
#  Deletes: described first, carried out only when the NEXT message confirms
# ---------------------------------------------------------------------- #
@dataclass
class _Pending:
    label: str
    token: str  # the request that described it
    created: float
    version: int  # the configuration it described
    done: str
    run: Callable[[Any], list[str]]


def _short_names(names: list[str], limit: int = 8) -> str:
    names = list(names)
    return _join(names) if len(names) <= limit else _join(names[:limit]) + f" and {len(names) - limit} more"


def _plan_lines(plan: deps.Plan) -> list[str]:
    lines = [f"- {effect}" for effect in plan.effects]
    for group in plan.groups:
        lines.append(f"  {group['title']}: {_short_names(group['names'])}")
    lines += [f"- Note: {note}" for note in plan.notes]
    return lines or ["- Nothing else in the configuration refers to it."]


def _stage(request, *, label: str, lines: list[str], done: str, run: Callable[[Any], list[str]]) -> str:
    """Remember the delete that was just described, and tell the user what it would do."""
    session = get_session(request)
    setattr(
        session,
        _PENDING_ATTR,
        _Pending(label, _token(request), _now(), session.history.version, done, run),
    )
    return "\n".join(
        [f"Deleting {label} would do this:"]
        + lines
        + ['Nothing has been deleted yet. Reply "confirm" to delete it, or "cancel" to keep it.']
    )


def _stage_plan(request, kind: str, ident, label: str, run: Callable[[Any], list[str]]) -> str:
    config = require_config(get_session(request), "deleting")
    the_plan = deps.plan(config, kind, ident)
    deps.resolve(the_plan)  # raises with the reason when something blocks the delete
    return _stage(request, label=label, lines=_plan_lines(the_plan), done=f"Deleted {label}.", run=run)


def delete_room(request, args: NameArgs) -> str:
    name = _existing(args.name, [room.name for room in get_session(request).config.config.rooms], "room")
    return _stage_plan(request, "room", name, f"room '{name}'", lambda req: rooms.delete_room(req, name))


def delete_lab(request, args: NameArgs) -> str:
    name = _existing(args.name, [lab.name for lab in get_session(request).config.config.labs], "lab")
    return _stage_plan(request, "lab", name, f"lab '{name}'", lambda req: labs.delete_lab(req, name))


def delete_faculty(request, args: NameArgs) -> str:
    people = [person.name for person in get_session(request).config.config.faculty]
    name = _existing(args.name, people, "faculty member")
    return _stage_plan(request, "faculty", name, f"faculty member '{name}'", lambda req: faculty.delete_faculty(req, name))


def delete_course(request, args: SectionArgs) -> str:
    row = _find_section(request, args, "delete")
    course_id, index = row["course_id"], row["index"]
    return _stage_plan(
        request, "course", index, f"course section {row['display']}",
        lambda req: courses.delete_course(req, index, expected_course_id=course_id),
    )  # fmt: skip


def delete_class_pattern(request, args: PatternRef) -> str:
    index = _pattern_index(request, args)
    pattern = patterns.get_pattern(request, index)
    label = f"class pattern {index} ({pattern['credits']} credits: {pattern['summary']})"
    return _stage_plan(request, "pattern", index, label, lambda req: patterns.delete_pattern(req, index))


def delete_time_slot(request, args: TimeSlotRef) -> str:
    index, block = _find_block(request, args.day, args.start)
    day_blocks = next(item for item in timeslots.describe_timeslots(request)["days"] if item["day"] == args.day)["blocks"]
    if len(day_blocks) == 1:
        raise ControllerError(f"Can't delete the only time block on {args.day} -- every weekday needs at least one.")
    label = f"the {DAY_NAMES[args.day]} time slot {block['start']}-{block['end']}"
    return _stage(
        request, label=label, lines=["- Nothing else in the configuration refers to it, but fewer time slots may leave some classes with fewer places to go."],
        done=f"Deleted {label}.", run=lambda req: timeslots.delete_timeslot(req, args.day, index),
    )  # fmt: skip


def delete_meeting(request, args: MeetingRef) -> str:
    pattern, meeting = _meeting_index(request, args)
    count = len(get_session(request).config.time_slot_config.classes[pattern].meetings)
    if count == 1:
        raise ControllerError(meetings.LAST_MEETING_MESSAGE)
    row = meetings.get_meeting(request, pattern, meeting)
    label = f"meeting {args.meeting_number} of pattern {pattern} ({row['summary']})"
    return _stage(
        request, label=label, lines=["- It is removed from its class pattern; the pattern keeps its other meetings."],
        done=f"Deleted {label}.", run=lambda req: meetings.delete_meeting(req, pattern, meeting),
    )  # fmt: skip


def confirm_delete(request, args: NoArgs) -> str:
    """Carry out the delete described in an EARLIER message, if it is still what was described."""
    session = get_session(request)
    pending = getattr(session, _PENDING_ATTR, None)
    if pending is None:
        raise ControllerError("There is nothing waiting to be deleted. Ask me to delete something first, then confirm.")
    if pending.token == _token(request):
        raise ControllerError(
            "A delete has to be confirmed in a separate message, after you have seen what it would change. "
            "Nothing was deleted."
        )
    setattr(session, _PENDING_ATTR, None)  # used up, whatever happens next
    if _now() - pending.created > PENDING_SECONDS:
        raise ControllerError(f"That delete ({pending.label}) was described too long ago. Ask me again.")
    if session.history.version != pending.version:
        raise ControllerError(
            f"The configuration changed after I described deleting {pending.label}, so I did not delete it. "
            "Ask me again to see what it would do now."
        )
    notices = pending.run(request)
    return f"{pending.done}{_notes(notices)} {UNDO_HINT}"


def cancel_delete(request, args: NoArgs) -> str:
    """Forget the delete that was described. Nothing is deleted."""
    session = get_session(request)
    pending = getattr(session, _PENDING_ATTR, None)
    setattr(session, _PENDING_ATTR, None)
    if pending is None:
        return Unchanged("Nothing was waiting to be deleted.")
    label = pending.label[:1].upper() + pending.label[1:]
    return Unchanged(f"Cancelled. {label} was not deleted.")


# ---------------------------------------------------------------------- #
#  The registry for this file
# ---------------------------------------------------------------------- #
CHANGE_TOOLS: tuple[AiTool, ...] = (
    AiTool("add_meeting", "Add one meeting to an existing class pattern.", AddMeetingArgs, add_meeting, write=True),
    AiTool(
        "update_room",
        "Change a room: rename it, change its capacity, features or availability. Send only what changes.",
        UpdatePlaceArgs,
        update_room,
        write=True,
    ),
    AiTool(
        "update_lab",
        "Change a lab: rename it, change its capacity, features or availability. Send only what changes.",
        UpdatePlaceArgs,
        update_lab,
        write=True,
    ),
    AiTool(
        "update_course",
        "Change one course section: ID, credits, capacity, modality, rooms, labs, faculty, conflicts, "
        "required features. Send only what changes.",
        UpdateCourseArgs,
        update_course,
        write=True,
    ),
    AiTool(
        "update_faculty",
        "Change a faculty member: name, credit limits, teaching days, availability, mandatory days, "
        "preferences. Send only what changes.",
        UpdateFacultyArgs,
        update_faculty,
        write=True,
    ),
    AiTool(
        "update_time_slot",
        "Change one time slot (found by its weekday and start time): its start, end or spacing.",
        UpdateTimeSlotArgs,
        update_time_slot,
        write=True,
    ),
    AiTool(
        "update_timing_options",
        "Change the max time gap and min time overlap used with time slots.",
        TimingOptionsArgs,
        update_timing_options,
        write=True,
    ),
    AiTool(
        "update_class_pattern",
        "Change a class pattern (found by its number): credits, fixed start time, enabled or disabled.",
        UpdatePatternArgs,
        update_class_pattern,
        write=True,
    ),
    AiTool(
        "update_meeting",
        "Change one meeting of a class pattern: day, duration, lab, delivery or fixed start time.",
        UpdateMeetingArgs,
        update_meeting,
        write=True,
    ),
    AiTool(
        "update_global_settings",
        "Change the global settings: the generation limit and which optimizer flags are on.",
        UpdateSettingsArgs,
        update_global_settings,
        write=True,
    ),
    AiTool("delete_room", "Describe what deleting a room would change. Deletes nothing yet.", NameArgs, delete_room),
    AiTool("delete_lab", "Describe what deleting a lab would change. Deletes nothing yet.", NameArgs, delete_lab),
    AiTool(
        "delete_course",
        "Describe what deleting a course section would change. Deletes nothing yet.",
        SectionArgs,
        delete_course,
    ),
    AiTool(
        "delete_faculty",
        "Describe what deleting a faculty member would change. Deletes nothing yet.",
        NameArgs,
        delete_faculty,
    ),
    AiTool(
        "delete_time_slot",
        "Describe what deleting a time slot (found by weekday and start time) would change. Deletes nothing yet.",
        TimeSlotRef,
        delete_time_slot,
    ),
    AiTool(
        "delete_class_pattern",
        "Describe what deleting a class pattern would change. Deletes nothing yet.",
        PatternRef,
        delete_class_pattern,
    ),
    AiTool(
        "delete_meeting",
        "Describe what deleting one meeting of a class pattern would change. Deletes nothing yet.",
        MeetingRef,
        delete_meeting,
    ),
    AiTool(
        "confirm_delete",
        "Carry out the delete that a delete_* tool described in an EARLIER message. Call it only when the "
        "user's newest message agrees to go ahead (such as 'confirm' or 'yes'), never in the same message "
        "that asked for the delete.",
        NoArgs,
        confirm_delete,
        write=True,
    ),
    AiTool(
        "cancel_delete",
        "Drop the delete that was described. Call it when the user says no, cancel or keep it.",
        NoArgs,
        cancel_delete,
    ),
)
CHANGES_EOF

cat > "$tmp/new/tests__test_ai_changes.py" <<'TEST_CHANGES_EOF'
"""
Tests for the AI assistant's update and delete tools (Sprint 3 Section 4, Section 10.1).

The tools are called the way the AI calls them, against the real scheduler library and the
shipped example configuration (rooms Roddy 136/140/147, labs Linux/Mac, faculty such as Hogg,
Schwartz and sam, and course sections such as CMSC 140 x2 and CMSC 420). No AI is involved.

    ToolBox(request).call("update_room", {"name": "Roddy 140", "capacity": 20})
    ToolBox(request).call("delete_room", {"name": "Roddy 136"})   # only describes the delete
    ToolBox(later(request)).call("confirm_delete")                # a LATER message does it

What these cover, from the Sprint 3 requirements:
  * every area can be updated and deleted through the tools (Section 4)
  * arguments are validated before anything runs, and a rejected edit leaves the last valid
    configuration untouched (Section 4)
  * deletes use the same safeguard as the Delete pages: they are shown first, need a separate
    confirmation, and are undoable (Section 4, "same deletion ... safeguards")
  * the reply says what really happened, and whether it is applied or also saved (Section 4)
"""

import pytest

from gui import session_store
from gui.ai import changes
from gui.ai.tools import TOOLS_BY_NAME, ToolBox
from gui.controllers import meetings as meeting_ctrl
from gui.controllers import patterns as pattern_ctrl


class FakeRequest:
    """Enough of a Django request for get_session(): just a session dict."""

    def __init__(self, session=None):
        self.session = {} if session is None else dict(session)


def later(request):
    """The NEXT message from the same browser: a new request that shares the browser's session."""
    return FakeRequest(request.session)


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


@pytest.fixture
def request_():
    return FakeRequest()


@pytest.fixture
def box(request_):
    return ToolBox(request_)


def session(request_):
    return session_store.get_session(request_)


def config(request_):
    return session(request_).config


def snapshot(request_):
    return config(request_).model_dump_json()


def fresh(request_):
    """Open the configuration and mark it as saved, so the next change is easy to spot."""
    session(request_).dirty = False
    return request_


def room(request_, name):
    return next((item for item in config(request_).config.rooms if item.name == name), None)


def lab(request_, name):
    return next((item for item in config(request_).config.labs if item.name == name), None)


def person(request_, name):
    return next((item for item in config(request_).config.faculty if item.name == name), None)


def sections(request_, course_id):
    return [item for item in config(request_).config.courses if item.course_id == course_id]


def course_ids(request_):
    return {item.course_id for item in config(request_).config.courses}


def confirm(request_):
    """Confirm in a later message, the way a user answers "confirm"."""
    return ToolBox(later(request_)).call("confirm_delete")


# ---------------------------------------------------------------------- #
#  Registry
# ---------------------------------------------------------------------- #
UPDATE_TOOLS = (
    "update_room",
    "update_lab",
    "update_course",
    "update_faculty",
    "update_time_slot",
    "update_timing_options",
    "update_class_pattern",
    "update_meeting",
    "update_global_settings",
)
DELETE_TOOLS = (
    "delete_room",
    "delete_lab",
    "delete_course",
    "delete_faculty",
    "delete_time_slot",
    "delete_class_pattern",
    "delete_meeting",
)


def test_every_area_can_be_updated_and_deleted():
    for name in UPDATE_TOOLS + DELETE_TOOLS + ("confirm_delete", "cancel_delete", "add_meeting", "list_meetings"):
        assert name in TOOLS_BY_NAME, name


def test_updates_write_and_delete_requests_only_describe():
    assert all(TOOLS_BY_NAME[name].write for name in UPDATE_TOOLS)
    assert not any(TOOLS_BY_NAME[name].write for name in DELETE_TOOLS)  # they delete nothing
    assert TOOLS_BY_NAME["confirm_delete"].write and not TOOLS_BY_NAME["cancel_delete"].write


def test_update_tools_only_require_what_names_the_item():
    required = lambda name: set(TOOLS_BY_NAME[name].args.model_json_schema()["required"])
    assert required("update_room") == {"name"}
    assert required("update_course") == {"course_id"}
    assert required("update_class_pattern") == {"pattern_number"}
    assert required("update_meeting") == {"pattern_number", "meeting_number"}
    assert required("update_time_slot") == {"day", "start"}


# ---------------------------------------------------------------------- #
#  Rooms and labs
# ---------------------------------------------------------------------- #
def test_update_room_changes_only_what_was_asked(box, request_):
    fresh(request_)
    result = box.call("update_room", {"name": "roddy 140", "capacity": 40})
    assert result.ok and result.changed and result.write
    assert "capacity 28 -> 40" in result.message
    assert room(request_, "Roddy 140").capacity == 40
    assert room(request_, "Roddy 136").capacity == 28  # nothing else moved
    assert session(request_).dirty is True  # applied, not saved
    assert session(request_).history.can_undo  # and undoable like any other edit


def test_update_room_rename_follows_every_reference(box, request_):
    result = box.call("update_room", {"name": "Roddy 147", "new_name": "Roddy 150"})
    assert result.ok and result.changed
    assert room(request_, "Roddy 147") is None and room(request_, "Roddy 150")
    assert all("Roddy 147" not in item.room for item in config(request_).config.courses)
    assert any("Roddy 150" in item.room for item in config(request_).config.courses)
    assert "Roddy 150" in person(request_, "Hardy").room_preferences  # faculty preference moved too


def test_update_room_adds_and_removes_features(box, request_):
    box.call("update_room", {"name": "Roddy 136", "features": {"add": ["projector", "whiteboard"]}})
    assert sorted(room(request_, "Roddy 136").features) == ["projector", "whiteboard"]
    result = ToolBox(request_).call("update_room", {"name": "Roddy 136", "features": {"remove": ["projector"]}})
    assert result.ok and "features removed: projector" in result.message
    assert sorted(room(request_, "Roddy 136").features) == ["whiteboard"]


def test_update_room_with_the_same_values_changes_nothing(box, request_):
    fresh(request_)
    before = snapshot(request_)
    result = box.call("update_room", {"name": "Roddy 140", "capacity": 28})
    assert result.ok and not result.changed
    assert "nothing was changed" in result.message
    assert snapshot(request_) == before
    assert session(request_).dirty is False and not session(request_).history.can_undo


def test_update_room_without_any_change_asks_what_to_change(box, request_):
    before = snapshot(request_)
    result = box.call("update_room", {"name": "Roddy 140"})
    assert not result.ok and result.write and not result.changed
    assert "what to change" in result.message
    assert snapshot(request_) == before


def test_update_room_for_a_room_that_does_not_exist(box, request_):
    before = snapshot(request_)
    result = box.call("update_room", {"name": "Atlantis", "capacity": 10})
    assert not result.ok and "No room named 'Atlantis'" in result.message
    assert snapshot(request_) == before


def test_a_rejected_room_edit_leaves_the_last_valid_configuration(box, request_):
    fresh(request_)
    before = snapshot(request_)
    result = box.call("update_room", {"name": "Roddy 140", "capacity": 0})
    assert not result.ok and result.write and not result.changed
    assert snapshot(request_) == before
    assert session(request_).dirty is False and not session(request_).history.can_undo


def test_malformed_update_arguments_are_rejected_before_anything_runs(box, request_):
    before = snapshot(request_)
    result = box.call("update_room", {"name": "Roddy 140", "capacity": "lots"})
    assert not result.ok and "capacity" in result.message
    result = box.call(
        "update_room", {"name": "Roddy 140", "availability": [{"day": "someday", "start": "09:00", "end": "10:00"}]}
    )
    assert not result.ok and "weekday" in result.message.lower()
    assert snapshot(request_) == before


def test_update_lab_changes_capacity(box, request_):
    result = box.call("update_lab", {"name": "mac", "capacity": 30})
    assert result.ok and result.changed
    assert lab(request_, "Mac").capacity == 30 and lab(request_, "Linux").capacity == 28


# ---------------------------------------------------------------------- #
#  Courses
# ---------------------------------------------------------------------- #
def test_update_course_with_several_sections_asks_which_one(box, request_):
    before = snapshot(request_)
    result = box.call("update_course", {"course_id": "CMSC 140", "capacity": 20})
    assert not result.ok and "has 2 sections" in result.message and "CMSC 140.01" in result.message
    assert snapshot(request_) == before


def test_update_course_changes_just_the_chosen_section(box, request_):
    result = box.call("update_course", {"course_id": "CMSC 140", "section": "02", "capacity": 20})
    assert result.ok and result.changed and "capacity 28 -> 20" in result.message
    first, second = sections(request_, "CMSC 140")
    assert (first.capacity, second.capacity) == (28, 20)


def test_update_course_edits_lists_by_adding_and_removing(box, request_):
    result = box.call(
        "update_course",
        {"course_id": "cmsc420", "conflicts": {"add": ["CMSC 162"]}, "labs": {"replace": ["Linux"]}},
    )
    assert result.ok and result.changed, result.message
    (course,) = sections(request_, "CMSC 420")
    assert "CMSC 162" in course.conflicts and "CMSC 380" in course.conflicts  # added, the rest kept
    assert list(course.lab) == ["Linux"]


def test_update_course_can_hand_staffing_back_to_the_scheduler(box, request_):
    result = box.call("update_course", {"course_id": "CMSC 161", "section": "01", "faculty": {"replace": []}})
    assert result.ok and result.changed, result.message
    assert not sections(request_, "CMSC 161")[0].faculty  # "chosen from faculty preferences"


def test_renaming_a_course_updates_what_points_at_it(box, request_):
    result = box.call("update_course", {"course_id": "CMSC 420", "new_course_id": "CMSC 421"})
    assert result.ok and result.changed, result.message
    assert "CMSC 420" not in course_ids(request_) and "CMSC 421" in course_ids(request_)
    assert "CMSC 421" in person(request_, "Hobbs").course_preferences
    assert "CMSC 420" not in person(request_, "Hobbs").course_preferences


def test_update_course_with_an_unknown_room_changes_nothing(box, request_):
    fresh(request_)
    before = snapshot(request_)
    result = box.call("update_course", {"course_id": "CMSC 420", "rooms": {"add": ["Atlantis"]}})
    assert not result.ok and result.write and "Atlantis" in result.message
    assert snapshot(request_) == before and session(request_).dirty is False


# ---------------------------------------------------------------------- #
#  Faculty
# ---------------------------------------------------------------------- #
def test_update_faculty_changes_limits_and_preferences(box, request_):
    result = box.call(
        "update_faculty",
        {
            "name": "dr. schwartz",
            "maximum_credits": 4,
            "preferences": [
                {"kind": "course", "name": "cmsc420", "weight": 7},
                {"kind": "room", "name": "Roddy 140"},  # no weight: remove it
            ],
        },
    )
    assert result.ok and result.changed, result.message
    schwartz = person(request_, "Schwartz")
    assert schwartz.maximum_credits == 4
    assert schwartz.course_preferences["CMSC 420"] == 7
    assert "Roddy 140" not in schwartz.room_preferences and "Roddy 136" in schwartz.room_preferences


def test_update_faculty_rejects_a_preference_for_something_that_does_not_exist(box, request_):
    before = snapshot(request_)
    result = box.call("update_faculty", {"name": "Hogg", "preferences": [{"kind": "course", "name": "CMSC 999", "weight": 5}]})
    assert not result.ok and "CMSC 999" in result.message
    result = box.call("update_faculty", {"name": "Hogg", "preferences": [{"kind": "room", "name": "Roddy 140", "weight": 99}]})
    assert not result.ok
    assert snapshot(request_) == before


# ---------------------------------------------------------------------- #
#  Time slots, class patterns, meetings, global settings
# ---------------------------------------------------------------------- #
def test_update_time_slot_finds_the_slot_by_day_and_start(box, request_):
    result = box.call("update_time_slot", {"day": "monday", "start": "8:00", "new_spacing": 30})
    assert result.ok and result.changed, result.message
    assert config(request_).time_slot_config.times["MON"][0].spacing == 30


def test_update_time_slot_lists_the_real_slots_when_none_matches(box, request_):
    before = snapshot(request_)
    result = box.call("update_time_slot", {"day": "MON", "start": "09:15", "new_spacing": 30})
    assert not result.ok and "no time slot starting at 09:15" in result.message and "08:00-19:00" in result.message
    assert snapshot(request_) == before


def test_update_timing_options(box, request_):
    result = box.call("update_timing_options", {"max_time_gap": 40})
    assert result.ok and result.changed and "max time gap 30 -> 40" in result.message
    assert config(request_).time_slot_config.max_time_gap == 40
    assert config(request_).time_slot_config.min_time_overlap == 45  # untouched


def test_update_class_pattern_can_disable_it(box, request_):
    result = box.call("update_class_pattern", {"pattern_number": 1, "enabled": False})
    assert result.ok and result.changed, result.message
    assert config(request_).time_slot_config.classes[1].disabled is True
    assert config(request_).time_slot_config.classes[0].disabled is False


def test_update_class_pattern_with_a_number_that_does_not_exist(box, request_):
    result = box.call("update_class_pattern", {"pattern_number": 99, "enabled": False})
    assert not result.ok and "no class pattern 99" in result.message.lower()


def test_update_meeting_is_found_by_pattern_and_meeting_number(box, request_):
    result = box.call("update_meeting", {"pattern_number": 0, "meeting_number": 2, "duration": 60})
    assert result.ok and result.changed, result.message
    meetings = config(request_).time_slot_config.classes[0].meetings
    assert [meeting.duration for meeting in meetings] == [50, 60, 50]
    result = box.call("update_meeting", {"pattern_number": 0, "meeting_number": 9, "duration": 60})
    assert not result.ok and "numbered 1 to 3" in result.message


def test_add_meeting_appends_to_the_pattern(box, request_):
    result = box.call("add_meeting", {"pattern_number": 1, "day": "monday", "duration": 50})
    assert result.ok and result.changed, result.message
    assert len(config(request_).time_slot_config.classes[1].meetings) == 3


def test_list_meetings_shows_numbered_meetings(box):
    result = box.call("list_meetings")
    assert result.ok and not result.write
    assert "Pattern 0" in result.message and "numbered from 1" in result.message


def test_update_global_settings_changes_limit_and_flags_together(box, request_):
    result = box.call("update_global_settings", {"limit": 25, "disable_flags": ["pack_rooms"]})
    assert result.ok and result.changed, result.message
    assert config(request_).limit == 25
    flags = [str(getattr(flag, "value", flag)) for flag in config(request_).optimizer_flags]
    assert "pack_rooms" not in flags and "faculty_course" in flags


def test_update_global_settings_can_reset_the_limit(box, request_):
    box.call("update_global_settings", {"limit": 25})
    result = ToolBox(request_).call("update_global_settings", {"reset_limit": True})
    assert result.ok and config(request_).limit == 10


def test_update_global_settings_rejects_nonsense(box, request_):
    before = snapshot(request_)
    assert not box.call("update_global_settings", {"limit": 5, "reset_limit": True}).ok
    assert not box.call("update_global_settings", {"enable_flags": ["warp_drive"]}).ok
    assert not box.call("update_global_settings", {"limit": 0}).ok
    assert snapshot(request_) == before


@pytest.mark.parametrize(
    "tool, args",
    [
        ("update_room", {"name": "Roddy 140", "capacity": 40}),
        ("update_course", {"course_id": "CMSC 420", "capacity": 20}),
        ("update_faculty", {"name": "sam", "maximum_credits": 6}),
        ("update_global_settings", {"limit": 25}),
    ],
)
def test_without_a_configuration_updates_say_so(tool, args, box, monkeypatch, request_):
    monkeypatch.setattr(session_store, "AUTO_LOAD_EXAMPLE", False)
    result = ToolBox(FakeRequest()).call(tool, args)
    assert not result.ok and "no configuration" in result.message.lower()


# ---------------------------------------------------------------------- #
#  Deletes are described first and only a later message carries them out
# ---------------------------------------------------------------------- #
def test_a_delete_request_only_describes_what_would_happen(box, request_):
    fresh(request_)
    before = snapshot(request_)
    result = box.call("delete_room", {"name": "roddy 136"})
    assert result.ok and not result.changed and not result.write
    assert "Roddy 136" in result.message and "Nothing has been deleted yet" in result.message
    assert snapshot(request_) == before
    assert session(request_).dirty is False and not session(request_).history.can_undo


def test_the_description_lists_the_sections_that_would_be_deleted_too(box, request_):
    result = box.call("delete_room", {"name": "Roddy 136"})  # the only room of CMSC 362 and 476
    assert result.ok and "CMSC 476" in result.message
    assert "CMSC 476" in course_ids(request_)  # still here: nothing was deleted


def test_a_delete_cannot_be_confirmed_in_the_same_message(box, request_):
    before = snapshot(request_)
    assert box.call("delete_room", {"name": "Roddy 136"}).ok
    result = box.call("confirm_delete")
    assert not result.ok and "separate message" in result.message
    assert snapshot(request_) == before
    assert confirm(request_).ok  # the next message can


def test_confirming_in_a_later_message_deletes_it_and_it_can_be_undone(box, request_):
    fresh(request_)
    box.call("delete_room", {"name": "Roddy 136"})
    result = confirm(request_)
    assert result.ok and result.changed and result.write
    assert "Deleted room 'Roddy 136'" in result.message and "History page" in result.message
    assert room(request_, "Roddy 136") is None
    assert session(request_).dirty is True and session(request_).history.can_undo


def test_deleting_a_room_also_deletes_the_sections_that_cannot_exist_without_it(box, request_):
    box.call("delete_room", {"name": "Roddy 136"})
    assert confirm(request_).ok
    assert room(request_, "Roddy 136") is None
    assert "CMSC 476" not in course_ids(request_)  # its only room was Roddy 136


def test_a_confirmation_works_once(box, request_):
    box.call("delete_lab", {"name": "Mac"})
    assert confirm(request_).ok
    again = confirm(request_)
    assert not again.ok and "nothing waiting" in again.message


def test_confirming_with_nothing_described_deletes_nothing(request_):
    before = snapshot(request_)
    result = ToolBox(request_).call("confirm_delete")
    assert not result.ok and "nothing waiting" in result.message
    assert snapshot(request_) == before


def test_cancel_forgets_the_delete(box, request_):
    before = snapshot(request_)
    box.call("delete_room", {"name": "Roddy 136"})
    result = ToolBox(later(request_)).call("cancel_delete")
    assert result.ok and not result.changed and "Cancelled" in result.message
    assert not confirm(request_).ok
    assert snapshot(request_) == before


def test_a_newer_description_replaces_the_older_one(box, request_):
    box.call("delete_room", {"name": "Roddy 136"})
    ToolBox(later(request_)).call("delete_lab", {"name": "Mac"})
    assert confirm(request_).ok
    assert lab(request_, "Mac") is None and room(request_, "Roddy 147")


def test_a_delete_is_refused_when_the_configuration_changed_after_it_was_described(box, request_):
    box.call("delete_lab", {"name": "Mac"})
    assert ToolBox(later(request_)).call("update_room", {"name": "Roddy 136", "capacity": 30}).ok
    result = confirm(request_)
    assert not result.ok and "changed after I described" in result.message
    assert lab(request_, "Mac")


def test_a_described_delete_expires(box, request_, monkeypatch):
    box.call("delete_lab", {"name": "Mac"})
    monkeypatch.setattr(changes, "_now", lambda: changes.time.monotonic() + changes.PENDING_SECONDS + 5)
    result = confirm(request_)
    assert not result.ok and "too long ago" in result.message
    assert lab(request_, "Mac")


def test_another_browser_cannot_confirm_my_delete(box, request_):
    box.call("delete_lab", {"name": "Mac"})
    other = ToolBox(FakeRequest()).call("confirm_delete")  # a different browser session
    assert not other.ok and "nothing waiting" in other.message
    assert lab(request_, "Mac")


def test_delete_describes_a_missing_item_without_staging_anything(box, request_):
    result = box.call("delete_room", {"name": "Atlantis"})
    assert not result.ok and "No room named 'Atlantis'" in result.message
    assert not confirm(request_).ok


def new_pattern(request_):
    """Add a fresh one-meeting pattern (as the existing pattern tests do) and return its number."""
    pattern_ctrl.add_pattern(
        request_,
        {
            "credits": 3,
            "start_time": None,
            "enabled": True,
            "meeting_day": "TUE",
            "meeting_duration": 50,
            "meeting_lab": False,
            "meeting_delivery": "in_person",
            "meeting_start_time": None,
        },
    )
    return len(config(request_).time_slot_config.classes) - 1


def test_deleting_each_kind_of_item(request_):
    """Only deletes the existing controller tests already prove valid on the example file."""
    number = new_pattern(request_)
    meeting_ctrl.add_meeting(
        request_,
        number,
        {"day": "THU", "duration": 50, "lab": False, "delivery": "in_person", "start_time": None},
    )
    classes = lambda: config(request_).time_slot_config.classes
    cases = [
        ("delete_faculty", {"name": "Zoppetti"}, lambda: person(request_, "Zoppetti") is None),
        ("delete_lab", {"name": "Mac"}, lambda: lab(request_, "Mac") is None),
        ("delete_course", {"course_id": "CMSC 162"}, lambda: "CMSC 162" not in course_ids(request_)),
        (
            "delete_time_slot",
            {"day": "tue", "start": "13:10"},
            lambda: len(config(request_).time_slot_config.times["TUE"]) == 2,
        ),
        (
            "delete_meeting",
            {"pattern_number": number, "meeting_number": 2},
            lambda: len(classes()[number].meetings) == 1,
        ),
        (
            "delete_class_pattern",
            {"pattern_number": number},
            lambda: len(classes()) == number,
        ),
    ]
    for tool, args, deleted in cases:
        described = ToolBox(later(request_)).call(tool, args)
        assert described.ok and not described.changed, (tool, described.message)
        result = confirm(request_)
        assert result.ok and result.changed, (tool, result.message)
        assert deleted(), tool


def test_deleting_a_course_with_several_sections_asks_which(box, request_):
    result = box.call("delete_course", {"course_id": "CMSC 140"})
    assert not result.ok and "has 2 sections" in result.message
    result = box.call("delete_course", {"course_id": "CMSC 140", "section": "09"})
    assert not result.ok and "no section '09'" in result.message


def test_the_only_time_slot_of_a_day_and_the_only_meeting_of_a_pattern_cannot_be_deleted(box, request_):
    friday = box.call("delete_time_slot", {"day": "FRI", "start": "08:00"})
    assert not friday.ok and "only time block on FRI" in friday.message
    number = new_pattern(request_)
    result = box.call("delete_meeting", {"pattern_number": number, "meeting_number": 1})
    assert not result.ok
    assert not confirm(request_).ok  # nothing was staged by the refusals


# ---------------------------------------------------------------------- #
#  Through the chat endpoint, one message at a time
# ---------------------------------------------------------------------- #
SCRIPT = {
    "Delete room Roddy 136": [("delete_room", {"name": "Roddy 136"})],
    "confirm": [("confirm_delete", {})],
    "cancel": [("cancel_delete", {})],
    "Delete it and confirm": [("delete_room", {"name": "Roddy 136"}), ("confirm_delete", {})],
    "Make Roddy 140 bigger": [("update_room", {"name": "Roddy 140", "capacity": 40})],
}


class ScriptedRunner:
    """Stands in for the AI: calls the scripted tools for each message."""

    def run(self, text, toolbox):
        for name, args in SCRIPT[text]:
            toolbox.call(name, args)
        return ""


@pytest.fixture
def chat(client, monkeypatch):
    from gui.ai import service

    monkeypatch.setattr(service, "get_runner", lambda: ScriptedRunner())

    def send(text):
        return client.post("/assistant/ask/", {"message": text}).json()

    return send


def test_a_delete_over_two_chat_messages(chat):
    first = chat("Delete room Roddy 136")
    assert first["ok"] and first["changed"] is False and "Nothing has been deleted yet" in first["reply"]
    second = chat("confirm")
    assert second["ok"] and second["changed"] is True and second["dirty"] is True
    assert "Deleted room 'Roddy 136'" in second["reply"]
    assert "applied but not yet saved" in second["reply"]


def test_a_delete_and_its_confirmation_in_one_chat_message_deletes_nothing(chat, client):
    body = chat("Delete it and confirm")
    assert body["changed"] is False and body["ok"] is False
    assert "separate message" in body["reply"] and "not changed" in body["reply"].lower()
    assert chat("confirm")["changed"] is True  # the description is still waiting for a real confirmation


def test_cancel_over_chat_keeps_everything(chat):
    chat("Delete room Roddy 136")
    assert chat("cancel")["changed"] is False
    again = chat("confirm")
    assert again["ok"] is False and again["changed"] is False


def test_an_update_over_chat_reports_applied_but_not_saved(chat):
    body = chat("Make Roddy 140 bigger")
    assert body["ok"] and body["changed"] and body["dirty"]
    assert "capacity 28 -> 40" in body["reply"] and "not yet saved to a file" in body["reply"]
TEST_CHANGES_EOF

cat > "$tmp/new/gui__ai__tools.py" <<'TOOLS_EOF'
"""
The AI assistant's tools (Sprint 3: explicit tools routed through controllers).

Each tool is a small command object: a name, a description the model reads,
a Pydantic schema for its arguments, and a handler that calls one of the
gui/controllers/ functions the normal pages use. The model never touches the
configuration directly; it can only ask for one of these tools by name.

    ToolBox(request).call("add_room", {"name": "RODDY150", "capacity": 35})

ToolBox runs a tool for one browser's request and records every result, so
the reply the user sees is built from what the application really did, not
from the model's own text. A tool:
  * checks its arguments against its schema first (wrong types never reach
    a controller),
  * answers "There is no configuration yet..." when nothing is loaded,
  * reads the session's configuration fresh on every call, so manual edits
    made in the Configuration Editor a moment ago are always seen (story 6),
  * turns ControllerError into a plain-language failure; the controller's
    atomic edit already left the configuration unchanged.

Read tools never change anything. Add tools (story 9) go through the same
controller checks as the Add forms, duplicate names included.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from pydantic import BaseModel, Field, ValidationError, field_validator

from gui.ai.base import (
    NO_CONFIG_MESSAGE,
    WEEKDAYS,
    AiTool,
    AvailabilityArgs,
    CourseArgs,
    NameArgs,
    NoArgs,
    ToolResult,
    Unchanged,
    _course_line,
    _day,
    _join,
    _notes,
    _place,
    _plural,
    _require,
    _resolve,
    find_name,
)
from gui.ai.changes import CHANGE_TOOLS
from gui.ai.prompt import CAPABILITIES
from gui.constants import DAY_NAMES
from gui.controllers import (
    config_controller,
    courses,
    faculty,
    labs,
    meetings,
    patterns,
    rooms,
    settings,
    timeslots,
)
from gui.controllers.common import require_config
from gui.controllers.errors import ControllerError
from gui.session_store import get_session

logger = logging.getLogger("gui.ai")

UNEXPECTED_MESSAGE = "Something went wrong while doing that, so it was stopped."
DEFAULT_FACULTY_HOURS = ("09:00", "17:00")  # same default as the CLI's faculty add


# ---------------------------------------------------------------------- #
#  Argument schemas (what the model must send; checked before anything runs)
# ---------------------------------------------------------------------- #
class AddPlaceArgs(BaseModel):
    name: str = Field(description="The new name, exactly as the user wrote it")
    capacity: int = Field(description="How many students it holds (a positive whole number)")
    features: list[str] = Field(default_factory=list, description="Features it provides, if the user named any")


class AddCourseArgs(BaseModel):
    course_id: str = Field(description='The course ID, e.g. "CMSC 421"')
    credits: int = Field(description="Credit hours; an enabled class pattern must have this many credits")
    capacity: int | None = Field(
        default=None,
        description="Enrollment capacity. Leave out if not given; the smallest listed room's capacity is used",
    )
    rooms: list[str] = Field(default_factory=list, description="Names of existing rooms the course may use")
    labs: list[str] = Field(default_factory=list, description="Names of existing labs the course may use")
    faculty: list[str] = Field(
        default_factory=list,
        description="Names of existing faculty who teach it. Empty means chosen from faculty preferences",
    )
    conflicts: list[str] = Field(default_factory=list, description="Course IDs it must not overlap with")
    section_id: str | None = Field(default=None, description="Section ID, only if the user gave one")
    modality: str = Field(default="in_person", description="in_person, online, or hybrid")


class AddFacultyArgs(BaseModel):
    name: str = Field(description="The faculty member's name, exactly as the user wrote it")
    maximum_credits: int = Field(default=12, description="Most credits they can teach (default 12)")
    minimum_credits: int = Field(default=0, description="Fewest credits they must teach (default 0)")
    unique_course_limit: int = Field(default=2, description="Most different courses they can teach (default 2)")
    maximum_days: int = Field(default=5, description="Most teaching days per week (default 5)")
    availability: list[AvailabilityArgs] = Field(
        default_factory=list,
        description="When they can teach. Leave empty for the default, every weekday 09:00-17:00",
    )


class AddTimeSlotArgs(BaseModel):
    day: str = Field(description="Weekday: MON, TUE, WED, THU or FRI")
    start: str = Field(description='24-hour start time, e.g. "09:00"')
    end: str = Field(description='24-hour end time, e.g. "17:00"')
    spacing: int = Field(default=60, description="Minutes between possible class start times (default 60)")

    @field_validator("day")
    @classmethod
    def check_day(cls, value: str) -> str:
        return _day(value)


class MeetingArgs(BaseModel):
    day: str = Field(description="Weekday: MON, TUE, WED, THU or FRI")
    duration: int = Field(description="Length of the meeting in minutes")
    lab: bool = Field(default=False, description="True if this meeting is held in a lab")
    delivery: str = Field(default="in_person", description="in_person, online, or hybrid")
    start_time: str | None = Field(default=None, description="Fixed 24-hour start time, only if the user gave one")

    @field_validator("day")
    @classmethod
    def check_day(cls, value: str) -> str:
        return _day(value)


class AddPatternArgs(BaseModel):
    credits: int = Field(description="Credit hours of courses that use this pattern")
    meetings: list[MeetingArgs] = Field(min_length=1, description="The weekly meetings, at least one")
    start_time: str | None = Field(default=None, description="Fixed 24-hour start time, only if the user gave one")


# ---------------------------------------------------------------------- #
#  Read tools (story 8) -- never change anything
# ---------------------------------------------------------------------- #
def describe_capabilities(request, args) -> str:
    return CAPABILITIES


def show_configuration(request, args) -> str:
    data = _require(config_controller.describe_configuration(request))
    counts = data["counts"]
    name = data.get("name") or "an unsaved configuration"
    lines = [f"The open configuration is {name}:"]
    for key, label in (
        ("rooms", "room"),
        ("labs", "lab"),
        ("courses", "course section"),
        ("faculty", "faculty member"),
        ("time_blocks", "time slot"),
        ("patterns", "class pattern"),
        ("meetings", "meeting"),
    ):
        lines.append(f"- {_plural(counts.get(key) or 0, label)}")
    lines.append("It has unsaved changes." if data["dirty"] else "It has no unsaved changes.")
    return "\n".join(lines)


def list_rooms(request, args) -> str:
    items = _require(rooms.describe_rooms(request))["rooms"]
    if not items:
        return "There are no rooms in the configuration."
    return "\n".join([f"Rooms ({len(items)}):"] + [f"- {room['name']}: {_place(room)}" for room in items])


def get_room(request, args: NameArgs) -> str:
    items = _require(rooms.describe_rooms(request))["rooms"]
    found = find_name(args.name, [room["name"] for room in items])
    if found is None:
        return f"No room named '{args.name}' exists."
    room = next(room for room in items if room["name"] == found)
    used = f" Used by {_join(room['referenced_by'])}." if room["referenced_by"] else ""
    return f"Room {room['name']}: {_place(room)}.{used}"


def list_labs(request, args) -> str:
    items = _require(labs.describe_labs(request))["labs"]
    if not items:
        return "There are no labs in the configuration."
    return "\n".join([f"Labs ({len(items)}):"] + [f"- {lab['name']}: {_place(lab)}" for lab in items])


def get_lab(request, args: NameArgs) -> str:
    items = _require(labs.describe_labs(request))["labs"]
    found = find_name(args.name, [lab["name"] for lab in items])
    if found is None:
        return f"No lab named '{args.name}' exists."
    lab = next(lab for lab in items if lab["name"] == found)
    used = f" Used by {_join(lab['referenced_by'])}." if lab["referenced_by"] else ""
    return f"Lab {lab['name']}: {_place(lab)}.{used}"


def list_courses(request, args) -> str:
    rows = _require(courses.describe_courses(request))["courses"]
    if not rows:
        return "There are no courses in the configuration."
    lines = [f"Course sections ({len(rows)}):"]
    lines += [f"- {row['display']}: {row['credits']} credits, capacity {row['capacity']}" for row in rows]
    return "\n".join(lines)


def get_course(request, args: CourseArgs) -> str:
    rows = _require(courses.describe_courses(request))["courses"]
    found = find_name(args.course_id, sorted({row["course_id"] for row in rows}))
    if found is None:
        return f"No course '{args.course_id}' exists."
    sections = [row for row in rows if row["course_id"] == found]
    if len(sections) == 1:
        return _course_line(sections[0]) + "."
    lines = [f"{found} has {len(sections)} sections:"]
    return "\n".join(lines + [f"- {_course_line(row)}" for row in sections])


def list_faculty(request, args) -> str:
    people = _require(faculty.describe_faculty(request))["faculty"]
    if not people:
        return "There are no faculty in the configuration."
    lines = [f"Faculty ({len(people)}):"]
    lines += [
        f"- {person['name']}: {person['minimum_credits']}-{person['maximum_credits']} credits" for person in people
    ]
    return "\n".join(lines)


def get_faculty(request, args: NameArgs) -> str:
    people = _require(faculty.describe_faculty(request))["faculty"]
    found = find_name(args.name, [person["name"] for person in people])
    if found is None:
        return f"No faculty member named '{args.name}' exists."
    person = next(person for person in people if person["name"] == found)
    available = "; ".join(f"{row['day']} {row['ranges']}" for row in person["availability"]) or "never"
    preferences = "; ".join(
        f"{group['label']}: " + _join(f"{entry['name']} ({entry['weight']})" for entry in group["entries"])
        for group in person["preferences"]
        if group["entries"]
    )
    limit, days = person["unique_course_limit"], person["maximum_days"]
    lines = [
        f"Faculty member {person['name']}: {person['minimum_credits']}-{person['maximum_credits']} credits, "
        + (f"at most {_plural(limit, 'different course')}, " if limit is not None else "")
        + (f"at most {_plural(days, 'teaching day')} a week." if days is not None else "no limit on teaching days."),
        f"Available: {available}.",
        f"Mandatory days: {_join(person['mandatory_days'])}.",
        f"Preferences: {preferences or 'none'}.",
    ]
    if person["referenced_by"]:
        lines.append(f"Assigned to {_join(person['referenced_by'])}.")
    return "\n".join(lines)


def list_time_slots(request, args) -> str:
    data = _require(timeslots.describe_timeslots(request))
    lines = ["Time slots:"]
    for day in data["days"]:
        blocks = [f"{b['start']}-{b['end']} (every {b['spacing']} min)" for b in day["blocks"]]
        lines.append(f"- {day['day']}: {_join(blocks)}")
    lines.append(f"Max time gap: {data['max_time_gap']} min. Min time overlap: {data['min_time_overlap']} min.")
    return "\n".join(lines)


def list_class_patterns(request, args) -> str:
    rows = _require(patterns.describe_patterns(request))["patterns"]
    if not rows:
        return "There are no class patterns in the configuration."
    lines = [f"Class patterns ({len(rows)}) and their meetings:"]
    for row in rows:
        extra = "" if row["enabled"] else " (disabled)"
        if row["start_time"]:
            extra += f", starts at {row['start_time']}"
        lines.append(f"- Pattern {row['index']}: {row['credits']} credits{extra}: {row['summary']}")
    return "\n".join(lines)


def list_meetings(request, args) -> str:
    rows = _require(meetings.describe_meetings(request))["patterns"]
    if not rows:
        return "There are no class patterns, so there are no meetings."
    lines = ["Meetings, by class pattern (meetings are numbered from 1 within their pattern):"]
    for row in rows:
        extra = "" if row["enabled"] else ", disabled"
        lines.append(f"- Pattern {row['index']} ({row['credits']} credits{extra}):")
        lines += [f"  {number}. {meeting['summary']}" for number, meeting in enumerate(row["meetings"], start=1)]
    return "\n".join(lines)


def get_global_settings(request, args) -> str:
    data = _require(settings.describe_settings(request))
    default = " (the default)" if data["is_default_limit"] else ""
    on = [flag["name"] for flag in data["flags"] if flag["enabled"]]
    off = [flag["name"] for flag in data["flags"] if not flag["enabled"]]
    return (
        f"Generation limit: {data['limit']}{default}.\n"
        f"Optimizer flags on: {_join(on)}.\nOptimizer flags off: {_join(off)}."
    )


# ---------------------------------------------------------------------- #
#  Add tools (story 9) -- the same controller calls as the Add forms
# ---------------------------------------------------------------------- #
def add_room(request, args: AddPlaceArgs) -> str:
    rooms.add_room(request, {"name": args.name, "capacity": args.capacity, "features": args.features})
    return f"Room '{args.name.strip()}' added with capacity {args.capacity}."


def add_lab(request, args: AddPlaceArgs) -> str:
    labs.add_lab(request, {"name": args.name, "capacity": args.capacity, "features": args.features})
    return f"Lab '{args.name.strip()}' added with capacity {args.capacity}."


def add_course(request, args: AddCourseArgs) -> str:
    entities = require_config(get_session(request), "adding a course").config
    room_names = _resolve(args.rooms, [room.name for room in entities.rooms])
    lab_names = _resolve(args.labs, [lab.name for lab in entities.labs])
    teachers = _resolve(args.faculty, [person.name for person in entities.faculty])
    conflicts = _resolve(args.conflicts, sorted({course.course_id for course in entities.courses}))

    capacity, capacity_note = args.capacity, ""
    if capacity is None:
        sizes = {room.name: room.capacity for room in entities.rooms if room.name in room_names}
        if not sizes:
            raise ControllerError("Capacity is required. Say how many students the course holds.")
        smallest = min(sizes, key=lambda name: sizes[name])
        capacity, capacity_note = sizes[smallest], f" (from room {smallest})"

    notices = courses.add_course(
        request,
        {
            "course_id": args.course_id,
            "section_id": args.section_id,
            "credits": args.credits,
            "capacity": capacity,
            "modality": args.modality,
            "room": room_names,
            "lab": lab_names,
            "faculty": teachers,
            "conflicts": conflicts,
        },
    )
    taught = _join(teachers, "chosen from faculty preferences")
    return (
        f"Course '{args.course_id.strip()}' added: {args.credits} credits, capacity {capacity}{capacity_note}, "
        f"rooms: {_join(room_names)}, labs: {_join(lab_names)}, faculty: {taught}." + _notes(notices)
    )


def add_faculty(request, args: AddFacultyArgs) -> str:
    if args.availability:
        times: dict[str, list[dict]] = {day: [] for day in WEEKDAYS}
        for item in args.availability:
            times[item.day].append({"start": item.start, "end": item.end})
    else:
        start, end = DEFAULT_FACULTY_HOURS
        times = {day: [{"start": start, "end": end}] for day in WEEKDAYS}
    faculty.add_faculty(
        request,
        {
            "name": args.name,
            "minimum_credits": args.minimum_credits,
            "maximum_credits": args.maximum_credits,
            "unique_course_limit": args.unique_course_limit,
            "maximum_days": args.maximum_days,
            "times": times,
            "mandatory_days": [],
        },
    )
    available = "; ".join(
        f"{day} " + ", ".join(f"{block['start']}-{block['end']}" for block in blocks)
        for day, blocks in times.items()
        if blocks
    )
    return f"Faculty member '{args.name.strip()}' added: up to {args.maximum_credits} credits, available {available}."


def add_time_slot(request, args: AddTimeSlotArgs) -> str:
    warnings = timeslots.add_timeslot(
        request, args.day, {"start": args.start, "end": args.end, "spacing": args.spacing}
    )
    return (
        f"Time slot added on {DAY_NAMES[args.day]}: {args.start}-{args.end}, "
        f"a class can start every {args.spacing} minutes." + _notes(warnings)
    )


def add_class_pattern(request, args: AddPatternArgs) -> str:
    meetings = [meeting.model_dump() for meeting in args.meetings]
    warnings = patterns.add_pattern(
        request, {"credits": args.credits, "start_time": args.start_time, "enabled": True, "meetings": meetings}
    )
    summary = ", ".join(f"{DAY_NAMES[m.day]} {m.duration} min" + (" (lab)" if m.lab else "") for m in args.meetings)
    return f"Class pattern added: {args.credits} credits, meeting {summary}." + _notes(warnings)


# ---------------------------------------------------------------------- #
#  The registry: every tool the model is offered, in one place
# ---------------------------------------------------------------------- #
TOOLS: tuple[AiTool, ...] = (
    AiTool(
        "describe_capabilities",
        "Say what this assistant can do. Use when the user asks what you can do or asks for help.",
        NoArgs,
        describe_capabilities,
        needs_config=False,
    ),
    AiTool(
        "show_configuration",
        "Summarize the open configuration: how many of each item it has.",
        NoArgs,
        show_configuration,
    ),
    AiTool("list_rooms", "List every room with its capacity.", NoArgs, list_rooms),
    AiTool("get_room", "Show one room: capacity, features, availability, what uses it.", NameArgs, get_room),
    AiTool("list_labs", "List every lab with its capacity.", NoArgs, list_labs),
    AiTool("get_lab", "Show one lab: capacity, features, availability, what uses it.", NameArgs, get_lab),
    AiTool("list_courses", "List every course section with credits and capacity.", NoArgs, list_courses),
    AiTool(
        "get_course",
        "Show one course: credits, capacity, rooms, labs, faculty, conflicts (all of its sections).",
        CourseArgs,
        get_course,
    ),
    AiTool("list_faculty", "List every faculty member with their credit range.", NoArgs, list_faculty),
    AiTool(
        "get_faculty",
        "Show one faculty member: credits, availability, preferences, assigned courses.",
        NameArgs,
        get_faculty,
    ),
    AiTool("list_time_slots", "List the time slots (time blocks) for each weekday.", NoArgs, list_time_slots),
    AiTool(
        "list_class_patterns",
        "List the class patterns and the meetings each one has.",
        NoArgs,
        list_class_patterns,
    ),
    AiTool(
        "list_meetings",
        "List every meeting of every class pattern, numbered within its pattern.",
        NoArgs,
        list_meetings,
    ),
    AiTool(
        "get_global_settings",
        "Show the global settings: generation limit and optimizer flags.",
        NoArgs,
        get_global_settings,
    ),
    AiTool("add_room", "Add a new room.", AddPlaceArgs, add_room, write=True),
    AiTool("add_lab", "Add a new lab.", AddPlaceArgs, add_lab, write=True),
    AiTool(
        "add_course",
        "Add a new course section. Rooms, labs and faculty must already exist.",
        AddCourseArgs,
        add_course,
        write=True,
    ),
    AiTool("add_faculty", "Add a new faculty member.", AddFacultyArgs, add_faculty, write=True),
    AiTool("add_time_slot", "Add a time slot (time block) to one weekday.", AddTimeSlotArgs, add_time_slot, write=True),
    AiTool(
        "add_class_pattern",
        "Add a class pattern: a credit amount and its weekly meetings.",
        AddPatternArgs,
        add_class_pattern,
        write=True,
    ),
    *CHANGE_TOOLS,
)

TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}


def _argument_problems(error: ValidationError) -> str:
    parts = []
    for item in error.errors():
        where = ".".join(str(part) for part in item.get("loc", ()))
        message = str(item.get("msg", "invalid value")).removeprefix("Value error, ")
        parts.append(f"{where}: {message}" if where else message)
    return "; ".join(parts)


def _failure(tool: AiTool, reason: str) -> str:
    if not tool.write:
        return reason
    return f"Could not {tool.name.replace('_', ' ')}: {reason}"


class ToolBox:
    """The tools for ONE request, bound to that browser's request.

    `results` keeps what each call did, in order, so the reply can be built
    from real outcomes.
    """

    def __init__(self, request, tools: Iterable[AiTool] = TOOLS):
        self.request = request
        self.tools = {tool.name: tool for tool in tools}
        self.results: list[ToolResult] = []

    def call(self, name: str, arguments: dict | None = None) -> ToolResult:
        tool = self.tools.get(name)
        if tool is None:
            return self._record(ToolResult(name, False, f"There is no '{name}' action."))
        try:
            args = tool.args.model_validate(arguments or {})
        except ValidationError as error:
            reason = f"the request had invalid values ({_argument_problems(error)})."
            return self._record(ToolResult(name, False, _failure(tool, reason), write=tool.write))

        if tool.needs_config and get_session(self.request).config is None:
            return self._record(ToolResult(name, False, NO_CONFIG_MESSAGE, write=tool.write))
        try:
            message = tool.handler(self.request, args)
        except ControllerError as error:
            return self._record(ToolResult(name, False, _failure(tool, error.message), write=tool.write))
        except Exception:
            logger.exception("AI tool %s failed unexpectedly", name)
            return self._record(ToolResult(name, False, UNEXPECTED_MESSAGE, write=tool.write))
        edited = tool.write and not isinstance(message, Unchanged)
        return self._record(ToolResult(name, True, message, changed=edited, write=tool.write))

    def invalid(self, name: str, error: Exception) -> ToolResult:
        """Record arguments LangChain already rejected (wrong types, missing values)."""
        tool = self.tools.get(name)
        if tool is None or not isinstance(error, ValidationError):
            return self._record(
                ToolResult(name, False, "The request had invalid values.", write=bool(tool and tool.write))
            )
        reason = f"the request had invalid values ({_argument_problems(error)})."
        return self._record(ToolResult(name, False, _failure(tool, reason), write=tool.write))

    def _record(self, result: ToolResult) -> ToolResult:
        self.results.append(result)
        return result
TOOLS_EOF

cat > "$tmp/new/gui__ai__prompt.py" <<'PROMPT_EOF'
"""
The base prompt sent with every AI request, and the capability list the
assistant gives when asked "What can you do?" (user story 7).

Every request is sent on its own: only this prompt and the user's newest
message go to the model, never earlier chat text (user story 6). The model
learns the current data by calling the read tools, which always look at the
configuration as it is right now.
"""

AREAS = (
    "rooms",
    "labs",
    "courses",
    "faculty",
    "time slots",
    "class patterns",
    "meetings",
    "global settings",
)

CAPABILITIES = (
    "I can help you look at and change your scheduler configuration:\n"
    "- View rooms, labs, courses, faculty, time slots, class patterns, meetings, and global settings.\n"
    "- Add rooms, labs, courses, faculty, time slots, class patterns, and meetings.\n"
    "- Change rooms, labs, courses, faculty, time slots, class patterns, meetings, and global settings.\n"
    "- Delete rooms, labs, courses, faculty, time slots, class patterns, and meetings. "
    "I first show what a delete would affect, and it only happens after you confirm in a new message.\n"
    "Every change goes through the same checks as the Configuration Editor, and you can undo it from "
    "the History page. Changes are applied to the configuration you have open, but they are not "
    "saved to a file until you save it.\n"
    "I can't validate the configuration, save it, or generate schedules yet; use the Configuration "
    "Editor and the Schedule Generator for those.\n"
    'Try: "List all rooms", "How many credits is CMSC 420?", "Add a room named RODDY150 with capacity 35", '
    'or "Change the capacity of Roddy 140 to 40".'
)

BASE_PROMPT = """\
You are the assistant inside a university course-scheduling application.
You help one user inspect and edit the scheduler configuration that is open
in the application right now.

Rules:
- You can only act by calling the tools you are given. Never claim that you
  looked something up or changed something unless a tool did it.
- Always use a tool to read data. Do not answer questions about rooms, labs,
  courses, faculty, time slots, class patterns, meetings, or settings from
  memory; the configuration can change between requests.
- If the user asks what you can do, or asks for help, call describe_capabilities.
- Pass names exactly as the user wrote them (for example "RODDY140" or
  "Dr. Hogg"). The tools find the matching item.
- Use 24-hour times such as "09:00", and weekday codes MON, TUE, WED, THU, FRI.
- If a request needs information the user did not give and no tool has a
  default for it, ask a short question instead of guessing.
- If the request has nothing to do with course scheduling, say so briefly.
- The scheduler library decides whether a configuration is valid. When a tool reports a
  problem, pass its explanation on plainly; do not argue with it or try to work around it.
- Changes: call the matching update_* tool and send only the values that change. Report that
  something was changed only after its tool confirms it.
- Deleting is two steps. The delete_* tools only DESCRIBE what a delete would change; nothing is
  deleted. Call confirm_delete only when the user's newest message agrees to go ahead (for
  example "confirm" or "yes"), and cancel_delete when they say no. Never call confirm_delete in
  the same message that asked for the delete.
- You cannot validate the configuration, save it to a file, or generate schedules yet. If asked,
  say so and point to the Configuration Editor (validate and save) or the Schedule Generator.
- Each request stands alone: you cannot see earlier messages. If the user says "it" or "that
  one" and you cannot tell which item they mean, ask which one.
- Keep replies short and plain.
"""


def tool_overview(tools) -> str:
    """The tool list the model is told about (Section 5): each tool's name and what it does."""
    lines = ["The tools you can call, and what each one does:"]
    lines += [f"- {tool.name}: {tool.description}" for tool in tools]
    return "\n".join(lines)
PROMPT_EOF

cat > "$tmp/new/gui__ai__runner.py" <<'RUNNER_EOF'
"""
The LangChain agent that turns a request into tool calls (Sprint 3).

Same setup as the course's LangChain example: create_agent() with OpenAI's
Responses API, and every tool marked return_direct, so after the model picks
its tool calls the app's own results are the answer. No second model call
re-words them, and the model cannot claim something happened that a tool
did not do.

Settings come from environment variables only:
    OPENAI_API_KEY   required; never written to a file, a page, or a log
    OPENAI_MODEL     optional, defaults to gpt-6-luna

Each request is sent alone: the base prompt and this one message, never
earlier chat text (user story 6). Retries are bounded (MAX_RETRIES) and every
call has a timeout, so a slow or failing service cannot hang the page or run
up the bill.

LangChain is imported inside build() so the rest of the app (and the tests
that use a fake runner) still work where it isn't installed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

from gui.ai.prompt import BASE_PROMPT, tool_overview
from gui.ai.tools import ToolBox

DEFAULT_MODEL = "gpt-6-luna"
TIMEOUT_SECONDS = 60
MAX_RETRIES = 2


class NotConfigured(Exception):
    """The AI can't run here (no API key, or LangChain isn't installed)."""


class Runner(Protocol):
    """Anything that can answer one request using the tools in `toolbox`.

    Returns the model's own text, or "" when it only called tools. Tests pass
    a fake runner that calls toolbox.call() directly, so no AI is used.
    """

    def run(self, text: str, toolbox: ToolBox) -> str: ...


def model_name() -> str:
    return os.environ.get("OPENAI_MODEL", "").strip() or DEFAULT_MODEL


@dataclass
class LangChainRunner:
    model: str = DEFAULT_MODEL
    http_client: Any = None  # tests pass an httpx client with a mocked OpenAI

    @classmethod
    def from_environment(cls) -> LangChainRunner:
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            raise NotConfigured(
                "The AI assistant isn't set up: set the OPENAI_API_KEY environment variable and restart the server."
            )
        return cls(model=model_name())

    def chat_model(self):
        from langchain_openai import ChatOpenAI

        options: dict[str, Any] = {"http_client": self.http_client} if self.http_client is not None else {}
        return ChatOpenAI(
            model=self.model,
            use_responses_api=True,
            reasoning={"effort": "medium"},
            timeout=TIMEOUT_SECONDS,
            max_retries=MAX_RETRIES,
            **options,
        )

    def build(self, toolbox: ToolBox):
        try:
            from langchain.agents import create_agent
            from langchain_core.tools import StructuredTool
        except ImportError as error:  # pragma: no cover - depends on the install
            raise NotConfigured("The AI assistant isn't installed. Run `uv sync` and restart.") from error

        def bind(name: str):
            def run_tool(**arguments) -> str:
                return toolbox.call(name, arguments).message

            return run_tool

        tools = [
            StructuredTool.from_function(
                name=tool.name,
                func=bind(tool.name),
                description=tool.description,
                args_schema=tool.args,
                return_direct=True,
                # Bad arguments come back as a normal failed result, not a crash.
                handle_validation_error=lambda error, name=tool.name: toolbox.invalid(name, error).message,
            )
            for tool in toolbox.tools.values()
        ]
        prompt = BASE_PROMPT + "\n" + tool_overview(toolbox.tools.values())
        return create_agent(model=self.chat_model(), tools=tools, system_prompt=prompt)

    def run(self, text: str, toolbox: ToolBox) -> str:
        agent = self.build(toolbox)
        # Only this request: no earlier chat text is sent (user story 6).
        result = agent.invoke({"messages": [{"role": "user", "content": text}]})
        if toolbox.results:
            return ""  # the tools' own results are the answer
        replies = [message.text for message in result["messages"][1:] if getattr(message, "text", "")]
        return "\n".join(replies).strip()
RUNNER_EOF

cat > "$tmp/apply.py" <<'APPLY_EOF'
import hashlib, json, os, sys

tmp, = sys.argv[1:]
EXPECTED = {
    "gui/ai/tools.py": "806bf6cfafa2b83ff17f4746e56436fe32ea45dc01d1562ed19fb25256dca5f6",
    "gui/ai/prompt.py": "8b794749b89b1517436f83066d518ce91fa401a6e55f83d00e3752285fc73883",
    "gui/ai/runner.py": "a1cfadf12535aef23eed77575e010e2257308dd8530737c648eccc539c58c94e",
}
README_EDITS = [["- \"Add a time slot on Friday from 17:00 to 19:00\", \"Add a class pattern for 3 credits meeting Monday for 150 minutes\"\n", "- \"Add a time slot on Friday from 17:00 to 19:00\", \"Add a class pattern for 3 credits meeting Monday for 150 minutes\"\n- \"Change the capacity of Roddy 140 to 40\", \"Give Hogg a maximum of 9 credits\", \"Disable class pattern 4\", \"Turn off the pack_rooms setting\"\n- \"Delete room Roddy 136\" (see **Deleting** below)\n"], ["With no key set, the assistant says so and nothing else changes.\n\n", "With no key set, the assistant says so and nothing else changes.\n\n**Changing and deleting.** The update tools (`update_room`, `update_lab`, `update_course`, `update_faculty`, `update_time_slot`, `update_timing_options`, `update_class_pattern`, `update_meeting`, `update_global_settings`, plus `add_meeting`) take only the values you want changed and merge them into the current record, then call the same controller the Edit pages use. A change that the scheduler library rejects is rejected as a whole, so nothing is half-applied; a request that changes nothing says so and does not mark the configuration as unsaved. Every real change is on the **History** page and can be undone there.\n\n**Deleting** takes two messages. A `delete_*` tool only describes what would be deleted (the same dependency review the Delete pages show, including other items that go with it). The delete happens only when you confirm in a *new* message (`confirm_delete`); `cancel_delete` forgets it. A pending delete expires after 10 minutes, is refused if the configuration changed after it was described, and only the browser session that asked can confirm it. The assistant cannot confirm in the same message that describes the delete.\n\nThe assistant cannot validate the configuration, save it, or generate schedules yet; it says so when asked.\n\n"], ["\nTests use a fake AI (`tests/test_ai_chat.py`, `tests/test_ai_tools.py`) or a mocked OpenAI endpoint (`tests/test_ai_langchain.py`), so no key is needed and no API calls are made.\n", "\nTests use a fake AI (`tests/test_ai_chat.py`, `tests/test_ai_tools.py`, `tests/test_ai_changes.py`) or a mocked OpenAI endpoint (`tests/test_ai_langchain.py`), so no key is needed and no API calls are made.\n"]]
CHAT_EDITS = [["    assert body[\"ok\"] is True and body[\"changed\"] is False\n    assert \"View, add, change, and delete rooms\" in body[\"reply\"]\n    assert \"Validate the configuration, save it, and generate schedules\" in body[\"reply\"]\n", "    assert body[\"ok\"] is True and body[\"changed\"] is False\n    assert \"Delete rooms, labs, courses\" in body[\"reply\"]\n    assert \"I can't validate the configuration, save it, or generate schedules yet\" in body[\"reply\"]\n"]]

def read(p):
    with open(p, encoding="utf-8", newline="") as f:
        return f.read()

for path, want in EXPECTED.items():
    got = hashlib.sha256(read(path).encode("utf-8")).hexdigest()
    if got != want:
        sys.exit(f"{path} is not the version this script expects (it was edited after add-ai-chat.sh). Nothing was changed.")

def edited(path, edits):
    text = read(path)
    for old, new in edits:
        if text.count(old) != 1:
            sys.exit(f"Could not find the expected place to edit in {path}. Nothing was changed.")
        text = text.replace(old, new)
    return text

results = {
    "README.md": edited("README.md", README_EDITS),
    "tests/test_ai_chat.py": edited("tests/test_ai_chat.py", CHAT_EDITS),
}
for name in sorted(os.listdir(os.path.join(tmp, "new"))):
    results[name.replace("__", "/")] = read(os.path.join(tmp, "new", name))
for path, text in results.items():
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
print("Applied.")
APPLY_EOF

"$PYTHON" "$tmp/apply.py" "$tmp"

echo
echo "Done. New: ${NEW_FILES[*]}"
echo "Replaced: ${REPLACED[*]}   Edited: ${EDITED[*]}"
echo "Nothing is committed. Review with: git status && git diff"

if [ -z "${NO_TEST:-}" ] && command -v uv >/dev/null 2>&1; then
    echo
    echo "Running the AI tests..."
    uv run pytest tests/test_ai_changes.py tests/test_ai_chat.py tests/test_ai_tools.py tests/test_ai_langchain.py tests/test_gui_chat.py -q
fi