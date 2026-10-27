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
    not_found,
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
    names = list(names)
    found = find_name(str(wanted).strip(), names)
    if found is None:
        raise ControllerError(not_found(label, wanted, names))
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
    """True when the user asked for at least one change. None and empty mean "not asked";
    False IS a request for optional yes/no fields (disable, not a lab). Flags that default to
    False are passed as `flag or None`."""
    for value in values:
        if isinstance(value, ListChange):
            if value.asked:
                return True
        elif value is None or value == "" or value == []:
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
    if not _asked(args.new_name, args.capacity, args.features, args.availability, args.any_time or None):
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
    if not _asked(args.credits, args.start_time, args.clear_start_time or None, args.enabled):
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
    if not _asked(args.day, args.duration, args.lab, args.delivery, args.start_time, args.clear_start_time or None):
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
    if not _asked(args.limit, args.reset_limit or None, args.enable_flags, args.disable_flags):
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
        "Carry out the delete that a delete_* tool described in an EARLIER message. The application "
        "remembers which one, so call it immediately, with no questions, whenever the user's newest "
        "message just agrees to go ahead ('confirm', 'yes', 'do it'). Never in the same message that "
        "asked for the delete.",
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
