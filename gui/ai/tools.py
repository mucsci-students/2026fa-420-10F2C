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
import threading
from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.memento import ConfigOriginator, MementoError
from gui.ai.base import (
    NO_CONFIG_MESSAGE,
    UNDO_CHIP,
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
    _key,
    _notes,
    _place,
    _plural,
    _require,
    _resolve,
    find_name,
    not_found,
)
from gui.ai.changes import CHANGE_TOOLS
from gui.ai.diagnose import DIAGNOSE_TOOLS
from gui.ai.generation import GENERATION_TOOLS
from gui.ai.lifecycle import LIFECYCLE_TOOLS
from gui.ai.prompt import CAPABILITIES
from gui.ai.undo import UNDO_TOOLS
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
    capacity: int = Field(
        description="How many students it holds (a positive whole number)"
    )
    features: list[str] = Field(
        default_factory=list, description="Features it provides, if the user named any"
    )


class AddCourseArgs(BaseModel):
    course_id: str = Field(description='The course ID, e.g. "CMSC 421"')
    credits: int = Field(
        description="Credit hours; an enabled class pattern must have this many credits"
    )
    capacity: int | None = Field(
        default=None,
        description="Enrollment capacity. Leave out if the user did not say; the smallest listed room's "
        "capacity is used, and if there is no room the tool asks for it",
    )
    rooms: list[str] = Field(
        default_factory=list, description="Names of existing rooms the course may use"
    )
    labs: list[str] = Field(
        default_factory=list, description="Names of existing labs the course may use"
    )
    faculty: list[str] = Field(
        default_factory=list,
        description="Names of existing faculty who teach it. Ask the user if not given; leave empty only "
        "when some faculty already prefer this course",
    )
    conflicts: list[str] = Field(
        default_factory=list, description="Course IDs it must not overlap with"
    )
    section_id: str | None = Field(
        default=None, description="Section ID, only if the user gave one"
    )
    modality: str = Field(
        default="in_person", description="in_person, online, or hybrid"
    )


class AddFacultyArgs(BaseModel):
    name: str = Field(
        description="The faculty member's name, exactly as the user wrote it"
    )
    maximum_credits: int = Field(
        default=12, description="Most credits they can teach (default 12)"
    )
    minimum_credits: int = Field(
        default=0, description="Fewest credits they must teach (default 0)"
    )
    unique_course_limit: int = Field(
        default=2, description="Most different courses they can teach (default 2)"
    )
    maximum_days: int = Field(
        default=5, description="Most teaching days per week (default 5)"
    )
    availability: list[AvailabilityArgs] = Field(
        default_factory=list,
        description="When they can teach. Leave empty for the default, every weekday 09:00-17:00",
    )


class AddTimeSlotArgs(BaseModel):
    day: str = Field(description="Weekday: MON, TUE, WED, THU or FRI")
    start: str = Field(description='24-hour start time, e.g. "09:00"')
    end: str = Field(description='24-hour end time, e.g. "17:00"')
    spacing: int = Field(
        default=60,
        description="Minutes between possible class start times (default 60)",
    )

    @field_validator("day")
    @classmethod
    def check_day(cls, value: str) -> str:
        return _day(value)


class MeetingArgs(BaseModel):
    day: str = Field(description="Weekday: MON, TUE, WED, THU or FRI")
    duration: int = Field(description="Length of the meeting in minutes")
    lab: bool = Field(
        default=False, description="True if this meeting is held in a lab"
    )
    delivery: str = Field(
        default="in_person", description="in_person, online, or hybrid"
    )
    start_time: str | None = Field(
        default=None, description="Fixed 24-hour start time, only if the user gave one"
    )

    @field_validator("day")
    @classmethod
    def check_day(cls, value: str) -> str:
        return _day(value)


class AddPatternArgs(BaseModel):
    credits: int = Field(description="Credit hours of courses that use this pattern")
    meetings: list[MeetingArgs] = Field(
        min_length=1, description="The weekly meetings, at least one"
    )
    start_time: str | None = Field(
        default=None, description="Fixed 24-hour start time, only if the user gave one"
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
    lines.append(
        "It has unsaved changes." if data["dirty"] else "It has no unsaved changes."
    )
    return "\n".join(lines)


def list_rooms(request, args) -> str:
    items = _require(rooms.describe_rooms(request))["rooms"]
    if not items:
        return "There are no rooms in the configuration."
    return "\n".join(
        [f"Rooms ({len(items)}):"]
        + [f"- {room['name']}: {_place(room)}" for room in items]
    )


def get_room(request, args: NameArgs) -> str:
    items = _require(rooms.describe_rooms(request))["rooms"]
    found = find_name(args.name, [room["name"] for room in items])
    if found is None:
        return not_found("room", args.name, [room["name"] for room in items])
    room = next(room for room in items if room["name"] == found)
    used = f" Used by {_join(room['referenced_by'])}." if room["referenced_by"] else ""
    return f"Room {room['name']}: {_place(room)}.{used}"


def list_labs(request, args) -> str:
    items = _require(labs.describe_labs(request))["labs"]
    if not items:
        return "There are no labs in the configuration."
    return "\n".join(
        [f"Labs ({len(items)}):"] + [f"- {lab['name']}: {_place(lab)}" for lab in items]
    )


def get_lab(request, args: NameArgs) -> str:
    items = _require(labs.describe_labs(request))["labs"]
    found = find_name(args.name, [lab["name"] for lab in items])
    if found is None:
        return not_found("lab", args.name, [lab["name"] for lab in items])
    lab = next(lab for lab in items if lab["name"] == found)
    used = f" Used by {_join(lab['referenced_by'])}." if lab["referenced_by"] else ""
    return f"Lab {lab['name']}: {_place(lab)}.{used}"


def list_courses(request, args) -> str:
    rows = _require(courses.describe_courses(request))["courses"]
    if not rows:
        return "There are no courses in the configuration."
    lines = [f"Course sections ({len(rows)}):"]
    lines += [
        f"- {row['display']}: {row['credits']} credits, capacity {row['capacity']}"
        for row in rows
    ]
    return "\n".join(lines)


def get_course(request, args: CourseArgs) -> str:
    rows = _require(courses.describe_courses(request))["courses"]
    found = find_name(args.course_id, sorted({row["course_id"] for row in rows}))
    if found is None:
        ids = sorted({row["course_id"] for row in rows})
        return not_found("course", args.course_id, ids).replace(" named '", " '", 1)
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
        f"- {person['name']}: {person['minimum_credits']}-{person['maximum_credits']} credits"
        for person in people
    ]
    return "\n".join(lines)


def get_faculty(request, args: NameArgs) -> str:
    people = _require(faculty.describe_faculty(request))["faculty"]
    found = find_name(args.name, [person["name"] for person in people])
    if found is None:
        return not_found(
            "faculty member", args.name, [person["name"] for person in people]
        )
    person = next(person for person in people if person["name"] == found)
    available = (
        "; ".join(f"{row['day']} {row['ranges']}" for row in person["availability"])
        or "never"
    )
    preferences = "; ".join(
        f"{group['label']}: "
        + _join(f"{entry['name']} ({entry['weight']})" for entry in group["entries"])
        for group in person["preferences"]
        if group["entries"]
    )
    limit, days = person["unique_course_limit"], person["maximum_days"]
    lines = [
        f"Faculty member {person['name']}: {person['minimum_credits']}-{person['maximum_credits']} credits, "
        + (
            f"at most {_plural(limit, 'different course')}, "
            if limit is not None
            else ""
        )
        + (
            f"at most {_plural(days, 'teaching day')} a week."
            if days is not None
            else "no limit on teaching days."
        ),
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
        blocks = [
            f"{b['start']}-{b['end']} (every {b['spacing']} min)" for b in day["blocks"]
        ]
        lines.append(f"- {day['day']}: {_join(blocks)}")
    lines.append(
        f"Max time gap: {data['max_time_gap']} min. Min time overlap: {data['min_time_overlap']} min."
    )
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
        lines.append(
            f"- Pattern {row['index']}: {row['credits']} credits{extra}: {row['summary']}"
        )
    return "\n".join(lines)


def list_meetings(request, args) -> str:
    rows = _require(meetings.describe_meetings(request))["patterns"]
    if not rows:
        return "There are no class patterns, so there are no meetings."
    lines = [
        "Meetings, by class pattern (meetings are numbered from 1 within their pattern):"
    ]
    for row in rows:
        extra = "" if row["enabled"] else ", disabled"
        lines.append(f"- Pattern {row['index']} ({row['credits']} credits{extra}):")
        lines += [
            f"  {number}. {meeting['summary']}"
            for number, meeting in enumerate(row["meetings"], start=1)
        ]
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
    rooms.add_room(
        request,
        {"name": args.name, "capacity": args.capacity, "features": args.features},
    )
    return f"Room '{args.name.strip()}' added with capacity {args.capacity}."


def add_lab(request, args: AddPlaceArgs) -> str:
    labs.add_lab(
        request,
        {"name": args.name, "capacity": args.capacity, "features": args.features},
    )
    return f"Lab '{args.name.strip()}' added with capacity {args.capacity}."


def _someone_prefers(people, course_id: str) -> bool:
    """True when some faculty member already has a preference for this course (the library can
    then work out who teaches it, so the user does not have to name a teacher)."""
    wanted = _key(course_id)
    return any(
        _key(name) == wanted for person in people for name in person.course_preferences
    )


def add_course(request, args: AddCourseArgs) -> str:
    entities = require_config(get_session(request), "adding a course").config
    room_names = _resolve(args.rooms, [room.name for room in entities.rooms])
    lab_names = _resolve(args.labs, [lab.name for lab in entities.labs])
    teachers = _resolve(args.faculty, [person.name for person in entities.faculty])
    conflicts = _resolve(
        args.conflicts, sorted({course.course_id for course in entities.courses})
    )

    # Guard rail: a course needs these before it can exist. Ask for ALL that are missing at once,
    # instead of trying and failing one library error at a time (or letting the AI guess).
    capacity, capacity_note = args.capacity, ""
    sizes = {
        room.name: room.capacity for room in entities.rooms if room.name in room_names
    }
    missing = []
    if capacity is None:
        if sizes:
            smallest = min(sizes, key=lambda name: sizes[name])
            capacity, capacity_note = sizes[smallest], f" (from room {smallest})"
        else:
            missing.append(
                "Capacity is required. Say how many students the course holds."
            )
    if not teachers and not _someone_prefers(entities.faculty, args.course_id):
        missing.append(
            "Faculty is required. Say which faculty member teaches it (they must already exist; "
            "otherwise add the faculty member first)."
        )
    if missing:
        raise ControllerError(
            f"I need a bit more before I can add {args.course_id.strip()}. "
            + " ".join(missing)
        )

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
        f"rooms: {_join(room_names)}, labs: {_join(lab_names)}, faculty: {taught}."
        + _notes(notices)
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
        request,
        args.day,
        {"start": args.start, "end": args.end, "spacing": args.spacing},
    )
    return (
        f"Time slot added on {DAY_NAMES[args.day]}: {args.start}-{args.end}, "
        f"a class can start every {args.spacing} minutes." + _notes(warnings)
    )


def add_class_pattern(request, args: AddPatternArgs) -> str:
    meetings = [meeting.model_dump() for meeting in args.meetings]
    warnings = patterns.add_pattern(
        request,
        {
            "credits": args.credits,
            "start_time": args.start_time,
            "enabled": True,
            "meetings": meetings,
        },
    )
    summary = ", ".join(
        f"{DAY_NAMES[m.day]} {m.duration} min" + (" (lab)" if m.lab else "")
        for m in args.meetings
    )
    return f"Class pattern added: {args.credits} credits, meeting {summary}." + _notes(
        warnings
    )


# ---------------------------------------------------------------------- #
#  Several changes as one (#128) -- all of them, or none of them
# ---------------------------------------------------------------------- #
BATCH_PREFIXES = (
    "add_",
    "update_",
)  # deletes need their own confirmation, so they stay out
MAX_BATCH = 20  # most steps one apply_changes call may hold


class OperationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str = Field(description='The add_ or update_ tool to run, e.g. "update_room"')
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="That tool's arguments"
    )


class ApplyChangesArgs(BaseModel):
    operations: list[OperationArgs] = Field(
        min_length=1,
        max_length=MAX_BATCH,
        description="The changes, in order. They are applied all together, or not at all",
    )


def _batch_tools() -> dict[str, AiTool]:
    return {
        tool.name: tool
        for tool in TOOLS
        if tool.write and tool.name.startswith(BATCH_PREFIXES)
    }


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
    """Run several add/update tools as ONE change (#128).

    A memento of the whole configuration (app/memento.py) is taken before the
    first step. If any step fails, the memento is restored and the history is
    rewound (app/history.py checkpoint / rewind_to), so nothing is half-applied
    and Undo still matches what the user sees. The steps run through a second
    ToolBox, so each one gets exactly the checks it gets on its own.
    """
    allowed = _batch_tools()
    refused = [
        operation.tool for operation in args.operations if operation.tool not in allowed
    ]
    if refused:
        raise ControllerError(
            f"{_join(dict.fromkeys(refused))} can't be part of a combined change. "
            "Only add_ and update_ actions can; deletes are confirmed one at a time."
        )
    session = get_session(request)
    config = require_config(session, "making changes")
    memento = ConfigOriginator(
        config
    ).create_memento()  # every part, before anything changes
    history = getattr(session, "history", None)
    checkpoint = history.checkpoint() if history is not None else None
    dirty_before = session.dirty

    steps = ToolBox(request, allowed.values())
    done: list[str] = []
    edited = False
    for number, operation in enumerate(args.operations, start=1):
        result = steps.call(operation.tool, operation.arguments)
        if not result.ok:
            _roll_back(session, memento, checkpoint, dirty_before)
            # The step's own message already starts with "Could not ...".
            raise ControllerError(
                f"step {number} ({operation.tool}) failed. {result.message} "
                f"None of the {_plural(len(args.operations), 'change')} were applied."
            )
        edited = edited or result.changed
        done.append(f"{number}. {result.message}")
    text = "\n".join(
        [f"All {_plural(len(done), 'change')} were applied together:"] + done
    )
    return text if edited else Unchanged(text)


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
    AiTool(
        "get_room",
        "Show one room: capacity, features, availability, what uses it.",
        NameArgs,
        get_room,
    ),
    AiTool("list_labs", "List every lab with its capacity.", NoArgs, list_labs),
    AiTool(
        "get_lab",
        "Show one lab: capacity, features, availability, what uses it.",
        NameArgs,
        get_lab,
    ),
    AiTool(
        "list_courses",
        "List every course section with credits and capacity.",
        NoArgs,
        list_courses,
    ),
    AiTool(
        "get_course",
        "Show one course: credits, capacity, rooms, labs, faculty, conflicts (all of its sections).",
        CourseArgs,
        get_course,
    ),
    AiTool(
        "list_faculty",
        "List every faculty member with their credit range.",
        NoArgs,
        list_faculty,
    ),
    AiTool(
        "get_faculty",
        "Show one faculty member: credits, availability, preferences, assigned courses.",
        NameArgs,
        get_faculty,
    ),
    AiTool(
        "list_time_slots",
        "List the time slots (time blocks) for each weekday.",
        NoArgs,
        list_time_slots,
    ),
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
    AiTool(
        "add_faculty",
        "Add a new faculty member.",
        AddFacultyArgs,
        add_faculty,
        write=True,
    ),
    AiTool(
        "add_time_slot",
        "Add a time slot (time block) to one weekday.",
        AddTimeSlotArgs,
        add_time_slot,
        write=True,
    ),
    AiTool(
        "add_class_pattern",
        "Add a class pattern: a credit amount and its weekly meetings.",
        AddPatternArgs,
        add_class_pattern,
        write=True,
    ),
    *CHANGE_TOOLS,
    AiTool(
        "apply_changes",
        "Make several add_ or update_ changes as ONE change: either all of them are applied, or none are. "
        "Use it whenever one message asks for more than one add or update.",
        ApplyChangesArgs,
        apply_changes,
        write=True,
    ),
    *GENERATION_TOOLS,
    *LIFECYCLE_TOOLS,
    *UNDO_TOOLS,
    *DIAGNOSE_TOOLS,
)

TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}


def _argument_problems(error: ValidationError) -> str:
    parts = []
    for item in error.errors():
        where = ".".join(str(part) for part in item.get("loc", ()))
        message = str(item.get("msg", "invalid value")).removeprefix("Value error, ")
        parts.append(f"{where}: {message}" if where else message)
    return "; ".join(parts)


NOT_CONFIRMED = "the application could not confirm the change, and the configuration is the same as before."
UNREPORTED_CHANGE = "The configuration was changed anyway; check the History page, where it can be undone."


def _fingerprint(session) -> str | None:
    """The whole configuration as JSON, to tell whether an action really changed it."""
    config = session.config
    return None if config is None else config.model_dump_json()


def _failure(tool: AiTool, reason: str) -> str:
    if not tool.write:
        return reason
    return f"Could not {tool.name.replace('_', ' ')}: {reason}"


class ToolBox:
    """The tools for ONE request, bound to that browser's request.

    `results` keeps what each call did, in order, so the reply can be built
    from real outcomes.
    """

    def __init__(
        self, request, tools: Iterable[AiTool] = TOOLS, history: Iterable[dict] = ()
    ):
        self.request = request
        self.tools = {tool.name: tool for tool in tools}
        self.results: list[ToolResult] = []
        # The last few chat messages ({"role", "content"}) the runner may send along (story 6).
        self.history: list[dict] = list(history)
        # The model may ask for several tools in one turn and LangChain runs them on threads: one at a time,
        # so "undo that, then generate" never interleaves and the results stay in a clear order.
        self._lock = threading.RLock()

    def call(self, name: str, arguments: dict | None = None) -> ToolResult:
        """Run one tool, and note whether it replaced the configuration or the schedules in the viewer."""
        with self._lock:
            return self._locked_call(name, arguments)

    def _locked_call(self, name: str, arguments: dict | None) -> ToolResult:
        session = get_session(self.request)
        config_before, schedules_before = session.config, tuple(session.schedules)
        tool = self.tools.get(name)
        checking = tool is not None and tool.write
        state_before = _fingerprint(session) if checking else None
        result = self._call(name, arguments)
        if checking and tool is not None:
            result = self._verified(tool, result, state_before, _fingerprint(session))
        replaced = session.config is not config_before
        schedules = tuple(session.schedules)
        schedules_changed = len(schedules) != len(schedules_before) or any(
            now is not then for now, then in zip(schedules, schedules_before)
        )
        if replaced or schedules_changed:
            result = replace(
                result, config_replaced=replaced, schedules_changed=schedules_changed
            )
            self.results[-1] = result  # _call recorded exactly one result
        return result

    def _verified(
        self, tool: AiTool, result: ToolResult, before: str | None, after: str | None
    ) -> ToolResult:
        """Check a write tool's report against the configuration itself (issue #116).

        A tool only counts as having changed something when the configuration really is different
        afterwards, and a change that did happen is always reported, so the reply can never claim
        more, or less, than what is now in the application."""
        actually_changed = before != after
        if result.changed and not actually_changed:
            logger.error(
                "AI tool %s reported a change but the configuration is the same",
                tool.name,
            )
            result = replace(
                result,
                ok=False,
                changed=False,
                suggestions=(),
                message=_failure(tool, NOT_CONFIRMED),
            )
        elif actually_changed and not result.changed:
            logger.error(
                "AI tool %s changed the configuration without reporting it", tool.name
            )
            result = replace(
                result, changed=True, message=f"{result.message} {UNREPORTED_CHANGE}"
            )
        else:
            return result
        self.results[-1] = result  # _call recorded exactly one result
        return result

    def _call(self, name: str, arguments: dict | None = None) -> ToolResult:
        tool = self.tools.get(name)
        if tool is None:
            return self._record(
                ToolResult(name, False, f"There is no '{name}' action.")
            )
        try:
            args = tool.args.model_validate(arguments or {})
        except ValidationError as error:
            reason = f"the request had invalid values ({_argument_problems(error)})."
            return self._record(
                ToolResult(name, False, _failure(tool, reason), write=tool.write)
            )

        if tool.needs_config and get_session(self.request).config is None:
            return self._record(
                ToolResult(name, False, NO_CONFIG_MESSAGE, write=tool.write)
            )
        try:
            message = tool.handler(self.request, args)
        except ControllerError as error:
            advice = tuple(
                getattr(error, "suggestions", ())
            )  # quick replies a failure can offer ("Undo the last change")
            return self._record(
                ToolResult(
                    name,
                    False,
                    _failure(tool, error.message),
                    write=tool.write,
                    suggestions=advice,
                )
            )
        except Exception:
            logger.exception("AI tool %s failed unexpectedly", name)
            return self._record(
                ToolResult(name, False, UNEXPECTED_MESSAGE, write=tool.write)
            )
        edited = (tool.write and not isinstance(message, Unchanged)) or bool(
            getattr(message, "edited", False)
        )
        suggestions = tuple(getattr(message, "suggestions", ()))
        if edited and not suggestions:
            suggestions = (
                UNDO_CHIP,
            )  # every real change can be taken back with one click
        note = bool(getattr(message, "note", True))
        return self._record(
            ToolResult(
                name,
                True,
                message,
                changed=edited,
                write=tool.write,
                suggestions=suggestions,
                note=note,
                action=getattr(message, "action", None),
            )
        )

    def invalid(self, name: str, error: Exception) -> ToolResult:
        """Record arguments LangChain already rejected (wrong types, missing values)."""
        tool = self.tools.get(name)
        if tool is None or not isinstance(error, ValidationError):
            return self._record(
                ToolResult(
                    name,
                    False,
                    "The request had invalid values.",
                    write=bool(tool and tool.write),
                )
            )
        reason = f"the request had invalid values ({_argument_problems(error)})."
        return self._record(
            ToolResult(name, False, _failure(tool, reason), write=tool.write)
        )

    def _record(self, result: ToolResult) -> ToolResult:
        tool = self.tools.get(result.tool)
        if tool is not None and not tool.final:
            result = replace(result, final=False)
        self.results.append(result)
        return result
