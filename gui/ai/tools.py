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
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from gui.ai.prompt import CAPABILITIES
from gui.constants import DAY_NAMES
from gui.controllers import (
    config_controller,
    courses,
    faculty,
    labs,
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
UNEXPECTED_MESSAGE = "Something went wrong while doing that, so it was stopped."
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
        return self._record(ToolResult(name, True, message, changed=tool.write, write=tool.write))

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
