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

Update tools (#121) read the item's current values, fill in only the settings
the user named, and call the same update controller the Edit forms use, so
every check is shared. A setting the tool doesn't have ("color") is refused
with the list of real ones, never silently ignored. Renaming an item that
other items still use is refused for now: the Edit form asks for
confirmation first, and the chat has no Confirm button yet.

validate_configuration (#123) runs the Configuration Editor's Validate.

apply_changes (#128) runs several add/update tools as one change: a memento
of the whole configuration (app/memento.py) is taken first, and if any step
fails it is restored and the history is rewound, so nothing is half-applied
and Undo still matches what the user sees.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.memento import ConfigOriginator, MementoError
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

NO_CONFIG_MESSAGE = "There is no configuration yet. Load or create one first in the Configuration Editor."
NOTHING_TO_VALIDATE = (
    "There is no configuration to validate. Load or create one first in the Configuration Editor."
)
UNEXPECTED_MESSAGE = "Something went wrong while doing that, so it was stopped."
MAX_BATCH = 20  # most steps one apply_changes call may hold
WEEKDAYS = tuple(DAY_NAMES)
DEFAULT_FACULTY_HOURS = ("09:00", "17:00")  # same default as the CLI's faculty add


@dataclass(frozen=True)
class ToolResult:
    """What one tool call really did, in words the user can read."""

    tool: str
    ok: bool
    message: str
    changed: bool = False  # True only when the configuration was edited
    write: bool = False  # True for tools that try to edit the configuration


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


# ---------------------------------------------------------------------- #
#  Argument schemas (what the model must send; checked before anything runs)
# ---------------------------------------------------------------------- #
class NoArgs(BaseModel):
    pass


class NameArgs(BaseModel):
    name: str = Field(description="The name, as the user wrote it")


class CourseArgs(BaseModel):
    course_id: str = Field(description='The course ID, e.g. "CMSC 420"')


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


class AvailabilityArgs(BaseModel):
    day: str = Field(description="Weekday: MON, TUE, WED, THU or FRI")
    start: str = Field(description='24-hour start time, e.g. "09:00"')
    end: str = Field(description='24-hour end time, e.g. "17:00"')

    @field_validator("day")
    @classmethod
    def check_day(cls, value: str) -> str:
        return _day(value)


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


def _optional_day(value: str | None) -> str | None:
    return None if value is None else _day(value)


class UpdateArgs(BaseModel):
    """Base for the update tools (#121).

    Every setting is optional: only what the user named is changed. A
    setting the tool doesn't have is refused (extra="forbid") so "make it
    blue" can't quietly succeed by changing nothing. `identifies` names the
    fields that say WHICH item to change; the rest are its settings.
    """

    model_config = ConfigDict(extra="forbid")
    identifies: ClassVar[tuple[str, ...]] = ("name",)

    @classmethod
    def settings(cls) -> list[str]:
        return [name for name in cls.model_fields if name not in cls.identifies]

    def nothing_given(self) -> bool:
        return all(getattr(self, name) is None for name in type(self).settings())


class UpdatePlaceArgs(UpdateArgs):
    name: str = Field(description="The current name, as the user wrote it")
    new_name: str | None = Field(default=None, description="A new name, only if the user wants to rename it")
    capacity: int | None = Field(default=None, description="New capacity (a positive whole number)")
    features: list[str] | None = Field(default=None, description="The complete new list of features")
    availability: list[AvailabilityArgs] | None = Field(
        default=None, description="The complete new availability. An empty list means available any time"
    )


class UpdateCourseArgs(UpdateArgs):
    identifies: ClassVar[tuple[str, ...]] = ("course_id", "section_id")
    course_id: str = Field(description='The course ID, e.g. "CMSC 420"')
    section_id: str | None = Field(default=None, description="Which section, when the course has several")
    new_course_id: str | None = Field(default=None, description="A new course ID, only if the user wants to rename it")
    credits: int | None = Field(default=None, description="New credit hours")
    capacity: int | None = Field(default=None, description="New enrollment capacity")
    modality: str | None = Field(default=None, description="in_person, online, or hybrid")
    rooms: list[str] | None = Field(default=None, description="The complete new list of rooms it may use")
    labs: list[str] | None = Field(default=None, description="The complete new list of labs it may use")
    faculty: list[str] | None = Field(
        default=None,
        description="The complete new list of faculty who teach it. Empty means chosen from faculty preferences",
    )
    conflicts: list[str] | None = Field(default=None, description="The complete new list of conflicting course IDs")


class UpdateFacultyArgs(UpdateArgs):
    name: str = Field(description="The faculty member's current name, as the user wrote it")
    new_name: str | None = Field(default=None, description="A new name, only if the user wants to rename them")
    minimum_credits: int | None = Field(default=None, description="Fewest credits they must teach")
    maximum_credits: int | None = Field(default=None, description="Most credits they can teach")
    unique_course_limit: int | None = Field(default=None, description="Most different courses they can teach")
    maximum_days: int | None = Field(default=None, description="Most teaching days per week")
    availability: list[AvailabilityArgs] | None = Field(
        default=None, description="The complete new availability (when they can teach)"
    )
    mandatory_days: list[str] | None = Field(default=None, description="The complete new list of mandatory weekdays")

    @field_validator("mandatory_days")
    @classmethod
    def check_days(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else [_day(day) for day in value]


class UpdateTimeSlotArgs(UpdateArgs):
    identifies: ClassVar[tuple[str, ...]] = ("day", "start")
    day: str = Field(description="Weekday of the time slot: MON, TUE, WED, THU or FRI")
    start: str | None = Field(
        default=None, description="The slot's CURRENT 24-hour start time; needed when the day has several slots"
    )
    new_start: str | None = Field(default=None, description="New 24-hour start time")
    new_end: str | None = Field(default=None, description="New 24-hour end time")
    spacing: int | None = Field(default=None, description="New minutes between possible class start times")

    @field_validator("day")
    @classmethod
    def check_day(cls, value: str) -> str:
        return _day(value)


class UpdateTimingArgs(UpdateArgs):
    identifies: ClassVar[tuple[str, ...]] = ()
    max_time_gap: int | None = Field(default=None, description="New maximum gap between meetings, in minutes")
    min_time_overlap: int | None = Field(default=None, description="New minimum overlap, in minutes")


class UpdatePatternArgs(UpdateArgs):
    identifies: ClassVar[tuple[str, ...]] = ("pattern",)
    pattern: int = Field(description="The pattern's number, as list_class_patterns shows it")
    credits: int | None = Field(default=None, description="New credit hours")
    start_time: str | None = Field(
        default=None, description='New fixed 24-hour start time, or "" to remove the fixed start time'
    )
    enabled: bool | None = Field(default=None, description="True to enable the pattern, False to disable it")


class UpdateMeetingArgs(UpdateArgs):
    identifies: ClassVar[tuple[str, ...]] = ("pattern", "day")
    pattern: int = Field(description="The pattern's number, as list_class_patterns shows it")
    day: str = Field(description="The weekday the meeting is on NOW: MON, TUE, WED, THU or FRI")
    new_day: str | None = Field(default=None, description="Move the meeting to this weekday")
    duration: int | None = Field(default=None, description="New length in minutes")
    lab: bool | None = Field(default=None, description="True if the meeting is held in a lab")
    delivery: str | None = Field(default=None, description="in_person, online, or hybrid")
    start_time: str | None = Field(default=None, description='New fixed 24-hour start time, or "" to remove it')

    @field_validator("day")
    @classmethod
    def check_day(cls, value: str) -> str:
        return _day(value)

    @field_validator("new_day")
    @classmethod
    def check_new_day(cls, value: str | None) -> str | None:
        return _optional_day(value)


class UpdateSettingsArgs(UpdateArgs):
    identifies: ClassVar[tuple[str, ...]] = ()
    limit: int | None = Field(default=None, description="New generation limit (a positive whole number)")
    enable_flags: list[str] | None = Field(default=None, description="Optimizer flags to turn on")
    disable_flags: list[str] | None = Field(default=None, description="Optimizer flags to turn off")


class OperationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str = Field(description='The add_ or update_ tool to run, e.g. "update_room"')
    arguments: dict[str, Any] = Field(default_factory=dict, description="That tool's arguments")


class ApplyChangesArgs(BaseModel):
    operations: list[OperationArgs] = Field(
        min_length=1,
        max_length=MAX_BATCH,
        description="The changes, in order. They are applied all together, or not at all",
    )


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
#  Update tools (#121) -- read the current values, change only what was
#  named, then call the same update controller as the Edit forms
# ---------------------------------------------------------------------- #
def _show(value) -> str:
    if isinstance(value, (list, tuple, set)):
        return _join(value)
    return "none" if value in (None, "") else str(value)


def _set(changes: list[str], label: str, old, new, show: Callable[[Any], str] = _show):
    """The value to use for one setting: `new` when it was given and differs
    from `old` (and the change is noted in `changes`), otherwise `old`."""
    if new is None or new == old:
        return old
    changes.append(f"{label} from {show(old)} to {show(new)}")
    return new


def _say_what(args: UpdateArgs) -> None:
    if args.nothing_given():
        raise ControllerError(f"Say what to change. You can change: {_join(type(args).settings())}.")


def _rename_refused(name: str, users: Iterable[str], page: str) -> str:
    # The Edit form asks before renaming something other items use, and the
    # chat has no Confirm button yet, so the safe answer is to send the user there.
    return f"{name} is used by {_join(users)}; rename it on the {page} page."


def _times(availability: Iterable[AvailabilityArgs]) -> dict[str, list[dict]]:
    times: dict[str, list[dict]] = {}
    for item in availability:
        times.setdefault(item.day, []).append({"start": item.start, "end": item.end})
    return times


def _same_times(one: dict, other: dict) -> bool:
    def blocks(times):
        return {
            day: sorted((block["start"], block["end"]) for block in items)
            for day, items in (times or {}).items()
            if items
        }

    return blocks(one) == blocks(other)


def _times_text(times: dict, empty: str) -> str:
    return (
        "; ".join(
            f"{day} " + ", ".join(f"{block['start']}-{block['end']}" for block in blocks)
            for day, blocks in times.items()
            if blocks
        )
        or empty
    )


def _updated(what: str, changes: list[str], notices: Iterable[str] = ()) -> str:
    return f"{what} updated: {'; '.join(changes)}." + _notes(notices)


def _unchanged(what: str) -> str:
    return f"{what} already has those values. Nothing was changed."


_PLACES = {
    # kind: (list for the page, key in it, one item, update controller, page name)
    "room": (rooms.describe_rooms, "rooms", rooms.get_room, rooms.update_room, "Rooms"),
    "lab": (labs.describe_labs, "labs", labs.get_lab, labs.update_lab, "Labs"),
}


def _update_place(request, args: UpdatePlaceArgs, kind: str) -> str:
    describe, key, get_one, update, page = _PLACES[kind]
    _say_what(args)
    items = _require(describe(request))[key]
    found = find_name(args.name, [item["name"] for item in items])
    if found is None:
        raise ControllerError(f"No {kind} named '{args.name}' exists.")
    current = get_one(request, found)

    changes: list[str] = []
    name = _set(changes, "name", found, None if args.new_name is None else args.new_name.strip())
    if name != found and current["referenced_by"]:
        raise ControllerError(_rename_refused(found, current["referenced_by"], page))
    capacity = _set(changes, "capacity", current["capacity"], args.capacity)
    wanted_features = None if args.features is None else sorted({f.strip() for f in args.features if f.strip()})
    features = _set(changes, "features", current["features"], wanted_features)
    times = current["times"]
    if args.availability is not None and not _same_times(_times(args.availability), times):
        times = _times(args.availability)
        changes.append(f"availability to {_times_text(times, 'any time')}")

    what = f"{kind.capitalize()} '{found}'"
    if not changes:
        return _unchanged(what)
    notices = update(request, found, {"name": name, "capacity": capacity, "features": features, "times": times})
    return _updated(what, changes, notices)


def update_room(request, args: UpdatePlaceArgs) -> str:
    return _update_place(request, args, "room")


def update_lab(request, args: UpdatePlaceArgs) -> str:
    return _update_place(request, args, "lab")


def update_course(request, args: UpdateCourseArgs) -> str:
    _say_what(args)
    entities = require_config(get_session(request), "editing courses").config
    rows = _require(courses.describe_courses(request))["courses"]
    found = find_name(args.course_id, sorted({row["course_id"] for row in rows}))
    if found is None:
        raise ControllerError(f"No course '{args.course_id}' exists.")
    sections = [row for row in rows if row["course_id"] == found]
    if args.section_id is not None:
        sections = [row for row in sections if _key(row["section_id"] or "") == _key(args.section_id)]
        if not sections:
            raise ControllerError(f"{found} has no section '{args.section_id}'.")
    if len(sections) > 1:
        raise ControllerError(
            f"{found} has {len(sections)} sections ({_join(row['display'] for row in sections)}). "
            "Say which section to change."
        )
    row = sections[0]
    current = courses.get_course(request, row["index"])
    form = {field: current[field] for field in courses.COURSE_FIELDS}

    changes: list[str] = []
    new_id = None if args.new_course_id is None else args.new_course_id.strip()
    form["course_id"] = _set(changes, "course ID", current["course_id"], new_id)
    if form["course_id"] != current["course_id"] and row["referenced_by"]:
        raise ControllerError(_rename_refused(row["display"], row["referenced_by"], "Courses"))
    form["credits"] = _set(changes, "credits", current["credits"], args.credits)
    form["capacity"] = _set(changes, "capacity", current["capacity"], args.capacity)
    modality = None if args.modality is None else args.modality.strip().lower()
    form["modality"] = _set(changes, "modality", current["modality"], modality)
    for field, label, wanted, names in (
        ("room", "rooms", args.rooms, [room.name for room in entities.rooms]),
        ("lab", "labs", args.labs, [lab.name for lab in entities.labs]),
        ("faculty", "faculty", args.faculty, [person.name for person in entities.faculty]),
        ("conflicts", "conflicts", args.conflicts, sorted({course.course_id for course in entities.courses})),
    ):
        if wanted is not None:
            form[field] = _set(changes, label, current[field], _resolve(wanted, names))

    what = f"Course {row['display']}"
    if not changes:
        return _unchanged(what)
    notices = courses.update_course(request, row["index"], form, expected_course_id=found)
    return _updated(what, changes, notices)


FACULTY_FORM_FIELDS = (
    "name",
    "minimum_credits",
    "maximum_credits",
    "unique_course_limit",
    "maximum_days",
    "times",
    "mandatory_days",
    "course_preferences",
    "room_preferences",
    "lab_preferences",
)


def update_faculty(request, args: UpdateFacultyArgs) -> str:
    _say_what(args)
    people = _require(faculty.describe_faculty(request))["faculty"]
    found = find_name(args.name, [person["name"] for person in people])
    if found is None:
        raise ControllerError(f"No faculty member named '{args.name}' exists.")
    current = faculty.get_faculty(request, found)
    form = {field: current[field] for field in FACULTY_FORM_FIELDS}

    changes: list[str] = []
    form["name"] = _set(changes, "name", found, None if args.new_name is None else args.new_name.strip())
    if form["name"] != found and current["referenced_by"]:
        raise ControllerError(_rename_refused(found, current["referenced_by"], "Faculty"))
    for field in ("minimum_credits", "maximum_credits", "unique_course_limit", "maximum_days"):
        form[field] = _set(changes, field.replace("_", " "), current[field], getattr(args, field))
    if args.availability is not None and not _same_times(_times(args.availability), current["times"]):
        form["times"] = _times(args.availability)
        changes.append(f"availability to {_times_text(form['times'], 'never')}")
    form["mandatory_days"] = _set(changes, "mandatory days", current["mandatory_days"], args.mandatory_days)

    what = f"Faculty member '{found}'"
    if not changes:
        return _unchanged(what)
    notices = faculty.update_faculty(request, found, form)
    return _updated(what, changes, notices)


def update_time_slot(request, args: UpdateTimeSlotArgs) -> str:
    _say_what(args)
    config = require_config(get_session(request), "editing time slots")
    blocks = config.time_slot_config.times.get(args.day, [])
    listed = _join((f"{block.start}-{block.end}" for block in blocks), "none")
    day_name = DAY_NAMES[args.day]
    if args.start is None:
        if len(blocks) != 1:
            raise ControllerError(
                f"{day_name} has {_plural(len(blocks), 'time slot')} ({listed}). Say which one by its start time."
            )
        index = 0
    else:
        index = next((i for i, block in enumerate(blocks) if block.start == args.start.strip()), None)
        if index is None:
            raise ControllerError(f"No time slot on {day_name} starts at {args.start}. Its time slots are: {listed}.")
    current = timeslots.get_timeslot(request, args.day, index)

    changes: list[str] = []
    form = {
        "start": _set(changes, "start", current["start"], args.new_start),
        "end": _set(changes, "end", current["end"], args.new_end),
        "spacing": _set(changes, "spacing", current["spacing"], args.spacing),
    }
    what = f"The {day_name} time slot {current['start']}-{current['end']}"
    if not changes:
        return _unchanged(what)
    warnings = timeslots.update_timeslot(request, args.day, index, form)
    return _updated(what, changes, warnings)


def update_timing_options(request, args: UpdateTimingArgs) -> str:
    _say_what(args)
    current = _require(timeslots.describe_timeslots(request))
    changes: list[str] = []
    form = {
        "max_time_gap": _set(changes, "max time gap", current["max_time_gap"], args.max_time_gap),
        "min_time_overlap": _set(changes, "min time overlap", current["min_time_overlap"], args.min_time_overlap),
    }
    if not changes:
        return _unchanged("The timing options")
    timeslots.update_timing_options(request, form)
    return _updated("Timing options", changes)


def _pattern_row(request, number: int) -> dict:
    rows = _require(patterns.describe_patterns(request))["patterns"]
    if not 0 <= number < len(rows):
        raise ControllerError(
            f"There is no pattern {number}. The patterns are numbered 0 to {len(rows) - 1} (see list_class_patterns)."
        )
    return rows[number]


def update_class_pattern(request, args: UpdatePatternArgs) -> str:
    _say_what(args)
    _pattern_row(request, args.pattern)
    current = patterns.get_pattern(request, args.pattern)
    changes: list[str] = []
    form = {
        "credits": _set(changes, "credits", current["credits"], args.credits),
        "start_time": _set(changes, "start time", current["start_time"], args.start_time),
        "enabled": _set(changes, "enabled", current["enabled"], args.enabled, show=lambda on: "yes" if on else "no"),
    }
    what = f"Pattern {args.pattern}"
    if not changes:
        return _unchanged(what)
    warnings = patterns.update_pattern(request, args.pattern, form)
    return _updated(what, changes, warnings)


def update_meeting(request, args: UpdateMeetingArgs) -> str:
    _say_what(args)
    row = _pattern_row(request, args.pattern)
    on_day = [meeting for meeting in row["meetings"] if meeting["day"] == args.day]
    if not on_day:
        raise ControllerError(
            f"Pattern {args.pattern} has no meeting on {DAY_NAMES[args.day]}. It meets {row['summary']}."
        )
    if len(on_day) > 1:
        raise ControllerError(
            f"Pattern {args.pattern} has {len(on_day)} meetings on {DAY_NAMES[args.day]}; "
            "change the one you mean on the Meetings page."
        )
    current = on_day[0]
    changes: list[str] = []
    form = {
        "day": _set(changes, "day", current["day"], args.new_day),
        "duration": _set(changes, "duration", current["duration"], args.duration),
        "lab": _set(changes, "lab", current["lab"], args.lab, show=lambda on: "yes" if on else "no"),
        "delivery": _set(changes, "delivery", current["delivery"], args.delivery),
        "start_time": _set(changes, "start time", current["start_time"], args.start_time),
    }
    what = f"The {DAY_NAMES[args.day]} meeting of pattern {args.pattern}"
    if not changes:
        return _unchanged(what)
    warnings = meetings.update_meeting(request, args.pattern, current["index"], form)
    return _updated(what, changes, warnings)


def update_global_settings(request, args: UpdateSettingsArgs) -> str:
    _say_what(args)
    data = _require(settings.describe_settings(request))
    known = settings.known_flags()

    def flag(name: str) -> str:
        found = find_name(name, known)
        if found is None:
            raise ControllerError(f"'{name}' is not an optimizer flag. The flags are: {_join(known)}.")
        return found

    enable = [flag(name) for name in args.enable_flags or []]
    disable = [flag(name) for name in args.disable_flags or []]
    both = [name for name in enable if name in disable]
    if both:
        raise ControllerError(f"{_join(both)} can't be turned both on and off.")
    wanted = [name for name in known if (name in data["enabled_flags"] or name in enable) and name not in disable]
    limit = data["limit"] if args.limit is None else args.limit
    messages = settings.update_settings(request, {"limit": limit, "optimizer_flags": wanted})
    return " ".join(messages) or _unchanged("The global settings")


# ---------------------------------------------------------------------- #
#  Validate (#123) -- the Configuration Editor's Validate button
# ---------------------------------------------------------------------- #
def validate_configuration(request, args) -> str:
    if get_session(request).config is None:
        raise ControllerError(NOTHING_TO_VALIDATE)
    problems = config_controller.validate_configuration(request)
    if not problems:
        return "The configuration is valid."
    return "\n".join(["The configuration is not valid:"] + [f"- {problem}" for problem in problems])


# ---------------------------------------------------------------------- #
#  Several changes as one (#128) -- all of them, or none of them
# ---------------------------------------------------------------------- #
def _batch_tools() -> dict[str, AiTool]:
    return {tool.name: tool for tool in TOOLS if tool.write and tool.name != "apply_changes"}


def _roll_back(session, memento, checkpoint, dirty_before: bool) -> None:
    """Put the configuration, the undo history and the unsaved flag back to how
    they were before the first step (the memento was taken at that moment)."""
    try:
        ConfigOriginator(session.config).restore(memento)
    except MementoError as error:
        logger.error("apply_changes could not roll back: %s", error)
        raise ControllerError(
            "A step failed and the earlier steps could not be taken back automatically. "
            "Check the History page and undo them there."
        ) from error
    if checkpoint is not None:
        session.history.rewind_to(checkpoint)
    session.dirty = dirty_before


def apply_changes(request, args: ApplyChangesArgs) -> str:
    allowed = _batch_tools()
    refused = [operation.tool for operation in args.operations if operation.tool not in allowed]
    if refused:
        raise ControllerError(
            f"{_join(dict.fromkeys(refused))} can't be part of a combined change. "
            f"Only these can: {_join(sorted(allowed))}."
        )
    session = get_session(request)
    config = require_config(session, "making changes")
    memento = ConfigOriginator(config).create_memento()  # every part, before anything changes
    history = getattr(session, "history", None)
    checkpoint = history.checkpoint() if history is not None else None
    dirty_before = session.dirty

    steps = ToolBox(request, allowed.values())
    done: list[str] = []
    for number, operation in enumerate(args.operations, start=1):
        result = steps.call(operation.tool, operation.arguments)
        if not result.ok:
            _roll_back(session, memento, checkpoint, dirty_before)
            raise ControllerError(
                f"step {number} ({operation.tool}) failed: {result.message} "
                f"None of the {_plural(len(args.operations), 'change')} were applied."
            )
        done.append(f"{number}. {result.message}")
    return "\n".join([f"All {_plural(len(done), 'change')} were applied together:"] + done)


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
    AiTool(
        "update_room",
        "Change an existing room. Pass only the settings the user wants changed.",
        UpdatePlaceArgs,
        update_room,
        write=True,
    ),
    AiTool(
        "update_lab",
        "Change an existing lab. Pass only the settings the user wants changed.",
        UpdatePlaceArgs,
        update_lab,
        write=True,
    ),
    AiTool(
        "update_course",
        "Change an existing course section. Pass only the settings the user wants changed.",
        UpdateCourseArgs,
        update_course,
        write=True,
    ),
    AiTool(
        "update_faculty",
        "Change an existing faculty member. Pass only the settings the user wants changed.",
        UpdateFacultyArgs,
        update_faculty,
        write=True,
    ),
    AiTool(
        "update_time_slot",
        "Change one existing time slot (time block) on a weekday.",
        UpdateTimeSlotArgs,
        update_time_slot,
        write=True,
    ),
    AiTool(
        "update_timing_options",
        "Change the global timing options: max time gap and min time overlap.",
        UpdateTimingArgs,
        update_timing_options,
        write=True,
    ),
    AiTool(
        "update_class_pattern",
        "Change a class pattern's credits, fixed start time, or whether it is enabled.",
        UpdatePatternArgs,
        update_class_pattern,
        write=True,
    ),
    AiTool(
        "update_meeting",
        "Change one meeting of a class pattern: its day, length, lab, delivery or start time.",
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
    AiTool(
        "validate_configuration",
        "Check the whole configuration and list every problem. Changes nothing.",
        NoArgs,
        validate_configuration,
        needs_config=False,
    ),
    AiTool(
        "apply_changes",
        "Make several add_ or update_ changes as one: either all of them are applied, or none are. "
        "Use this whenever one request asks for more than one change.",
        ApplyChangesArgs,
        apply_changes,
        write=True,
    ),
)

TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}


def _argument_problems(error: ValidationError, tool: AiTool | None = None) -> str:
    parts = []
    unknown = []
    for item in error.errors():
        where = ".".join(str(part) for part in item.get("loc", ()))
        if item.get("type") == "extra_forbidden":
            unknown.append(f"'{where}'")
            continue
        message = str(item.get("msg", "invalid value")).removeprefix("Value error, ")
        parts.append(f"{where}: {message}" if where else message)
    if unknown:
        text = f"{_join(unknown)} {'is' if len(unknown) == 1 else 'are'} not a setting that can be changed"
        if tool is not None and issubclass(tool.args, UpdateArgs):
            text += f". You can change: {_join(tool.args.settings())}"
        parts.insert(0, text)
    return "; ".join(parts)


def _state(request) -> dict | None:
    """The configuration as plain data, to tell whether a write changed anything."""
    config = get_session(request).config
    return None if config is None else config.model_dump()


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
            reason = f"the request had invalid values ({_argument_problems(error, tool)})."
            return self._record(ToolResult(name, False, _failure(tool, reason), write=tool.write))

        if tool.needs_config and get_session(self.request).config is None:
            return self._record(ToolResult(name, False, NO_CONFIG_MESSAGE, write=tool.write))
        before = _state(self.request) if tool.write else None
        try:
            message = tool.handler(self.request, args)
        except ControllerError as error:
            return self._record(ToolResult(name, False, _failure(tool, error.message), write=tool.write))
        except Exception:
            logger.exception("AI tool %s failed unexpectedly", name)
            return self._record(ToolResult(name, False, UNEXPECTED_MESSAGE, write=tool.write))
        # "Changed" means the configuration really differs now: an update that
        # asked for values the item already had changes nothing.
        changed = tool.write and _state(self.request) != before
        return self._record(ToolResult(name, True, message, changed=changed, write=tool.write))

    def invalid(self, name: str, error: Exception) -> ToolResult:
        """Record arguments LangChain already rejected (wrong types, missing values)."""
        tool = self.tools.get(name)
        if tool is None or not isinstance(error, ValidationError):
            return self._record(
                ToolResult(name, False, "The request had invalid values.", write=bool(tool and tool.write))
            )
        reason = f"the request had invalid values ({_argument_problems(error, tool)})."
        return self._record(ToolResult(name, False, _failure(tool, reason), write=tool.write))

    def _record(self, result: ToolResult) -> ToolResult:
        self.results.append(result)
        return result
