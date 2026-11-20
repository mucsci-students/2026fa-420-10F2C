"""
Locking sections by talking to the AI chat (selective regeneration, in words).

A lock keeps one section exactly as a schedule places it (instructor, room, lab, days and times) the
next time schedules are generated. The padlock buttons in the Schedule Viewer, the "Locked sections"
card on the Schedule Generator and the tools below all read and write the SAME list, the session's
locks (app/locks.py), through the same controller (gui/controllers/locks.py). So whatever is done in the
chat shows on both pages, and what was done on the pages is what the chat lists.

    lock_sections            lock one or more sections, as the schedule the user is looking at places them
    unlock_sections          unlock one or more sections
    view_locked_sections     "which sections are locked?" (the sections the Schedule Generator lists)
    unlock_all_sections      remove every lock
    lock_faculty_sections    lock everything one instructor teaches in that schedule
    unlock_faculty_sections  unlock everything one instructor teaches
    list_schedule_sections   a lookup, only for the AI: the sections of that schedule and their lock state

Rules every one of them follows
  * Locks are not part of the configuration. These tools never touch it, never mark it as unsaved and
    never enter the undo history. They are therefore not "write" tools, and the reply does not say
    "not yet saved to a file".
  * They are not "acts" tools either (gui/ai/base.AiTool.acts): locking neither interrupts nor drops
    a request that is waiting for details, which is about the configuration.
  * Check everything, then change. A request with one unknown or ambiguous section, or one clash,
    changes nothing, and the reply says so. Ambiguity is reported as a plain failure rather than a
    waiting question, so a batch is never left half-remembered: the user answers and the AI asks again.
  * Names are matched like everywhere else in the chat (find_name): "141.01", "cmsc141.01" and
    "CMSC 141.01" are one section; part of a name is enough; two matches are asked about, never guessed.
  * Which schedule? The one open in the Schedule Viewer: chat.js sends its number and
    gui/views_ai.py stores it on the request (note_viewed_schedule). On any other page schedule 1 is
    used, and the reply says so. The user can name another ("from schedule 3").
  * Every reply is the application's own words (the tools are "final"), except list_schedule_sections,
    which only the AI reads.

The page behind the chat is redrawn after a lock change: gui/ai/tools.py notices that the lock list's
version moved and sets ToolResult.locks_changed, which gui/ai/service.py turns into a refresh.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.locks import Lock
from app.schedule_io import Assignment
from app.schedule_view import NO_FACULTY_LABEL, NO_LOCATION_LABEL
from gui.ai.base import AiTool, AmbiguousName, NoArgs, Outcome, find_name, suggest
from gui.calendar_layout import range_text
from gui.constants import DAY_NAMES, TIME_FORMAT_24, TIME_FORMAT_OPTIONS
from gui.controllers import locks as lock_controller
from gui.controllers import schedule_controller
from gui.controllers.errors import ControllerError

# Where gui/views_ai.py leaves the schedule number the Schedule Viewer was showing, on the request.
VIEWED_SCHEDULE_ATTR = "ai_viewed_schedule"
# The session key the Schedule Viewer keeps the 12-hour / 24-hour choice in (gui/views.TIME_FORMAT_KEY).
TIME_FORMAT_KEY = "viewer_time_format"

NOTHING_LOCKED = "No sections are currently locked."
NO_CHANGE_NOTE = "The configuration was not changed."
NOT_LOCKED_NOTE = "Nothing was locked, and your existing locks and the configuration were not changed."
NOT_UNLOCKED_NOTE = "Nothing was unlocked, and the configuration was not changed."
SHOW_CHIP = "Show locked sections"
GENERATE_CHIP = "Generate schedules"
MAX_LISTED = 12  # how many names an error message lists before "and N more"


# ---------------------------------------------------------------------- #
#  Which schedule is the user looking at?
# ---------------------------------------------------------------------- #
def note_viewed_schedule(request, raw: object) -> None:
    """Remember, on the request, which schedule the Schedule Viewer is showing.

    `raw` is what the chat sent: the page's schedule number, or nothing when the page is not the
    Schedule Viewer. Anything that is not a plain positive number counts as "not sent".
    """
    text = str(raw or "").strip()
    number = int(text) if text.isascii() and text.isdigit() and len(text) <= 6 else None
    setattr(request, VIEWED_SCHEDULE_ATTR, number)


def _schedule_target(
    request, explicit: int | None
) -> tuple[int, list[Assignment], bool]:
    """(schedule number, its sections, True when schedule 1 was only assumed).

    An explicit number from the user wins (and a wrong one is reported by the controller). Otherwise
    the schedule the viewer was showing; a number outside the range falls back to 1, exactly as the
    viewer itself does. With nothing sent (any other page) schedule 1 is assumed.
    """
    count = schedule_controller.schedule_count(request)
    if count == 0:
        raise ControllerError(schedule_controller.NO_SCHEDULES_MESSAGE)
    assumed = False
    if explicit is not None:
        number = explicit
    else:
        sent = getattr(request, VIEWED_SCHEDULE_ATTR, None)
        if sent is None:
            number, assumed = (
                1,
                count > 1,
            )  # with one schedule there is nothing to explain
        else:
            number = sent if 1 <= sent <= count else 1
    return number, schedule_controller.get_schedule(request, number - 1), assumed


def _assumed_note(number: int, assumed: bool) -> str:
    if not assumed:
        return ""
    return (
        f" I used schedule {number} because no schedule is open in the Schedule Viewer."
    )


# ---------------------------------------------------------------------- #
#  Wording helpers
# ---------------------------------------------------------------------- #
def _quoted(names: Iterable[str]) -> list[str]:
    return [f'"{name}"' for name in names]


def _and(items: Sequence[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _or(items: Sequence[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} or {items[-1]}"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _few(names: Sequence[str]) -> str:
    shown = ", ".join(names[:MAX_LISTED])
    extra = len(names) - MAX_LISTED
    return shown + (f" and {extra} more" if extra > 0 else "")


def _time_format(request) -> str:
    """The clock the user chose in the Schedule Viewer (24-hour unless they picked 12-hour)."""
    session = getattr(request, "session", None)
    saved = session.get(TIME_FORMAT_KEY) if session is not None else None
    return saved if saved in TIME_FORMAT_OPTIONS else TIME_FORMAT_24


def _when(assignment: Assignment, time_format: str) -> str:
    if not assignment.meetings:
        return "no meeting times"
    return ", ".join(
        f"{DAY_NAMES.get(meeting.day, meeting.day)[:3]} "
        f"{range_text(meeting.start, meeting.end, time_format)}"
        for meeting in assignment.meetings
    )


def _where(assignment: Assignment) -> str:
    places = [place for place in (assignment.room, assignment.lab) if place]
    return ", ".join(places) if places else NO_LOCATION_LABEL


def _describe(assignment: Assignment, time_format: str) -> str:
    """One section the way the Schedule Generator's table shows it: section, instructor, place, times."""
    return (
        f"{assignment.course}: {assignment.faculty or NO_FACULTY_LABEL}, "
        f"{_where(assignment)}, {_when(assignment, time_format)}"
    )


def _origin(lock: Lock) -> str:
    return f" (locked from schedule {lock.source})" if lock.source else ""


# ---------------------------------------------------------------------- #
#  Matching what the user typed to real names
# ---------------------------------------------------------------------- #
def _not_found(
    unknown: Sequence[str],
    names: Sequence[str],
    *,
    single: str,
    several: str,
    where: str,
    hint: str,
    outcome: str,
) -> str:
    if len(unknown) == 1:
        quoted = f'"{unknown[0]}"'
        text = f"I couldn't find {single} called {quoted} {where}."
        close = suggest(unknown[0], names)
        if close:
            text += f" Did you mean {_or(_quoted(close))}?"
    else:
        text = f"I couldn't find {several} {where}: {_and(_quoted(unknown))}."
    return " ".join(part for part in (text, hint, outcome) if part)


def _resolve(
    wanted: Sequence[str],
    names: Sequence[str],
    *,
    single: str,
    several: str,
    where: str,
    hint: str,
    outcome: str,
) -> list[str]:
    """Map each name the user typed to an exact one, or raise a ControllerError that says why not.

    Nothing has changed at this point, and `outcome` says so in the message. A name that fits two
    items is reported (not guessed); so is every name that fits none.
    """
    found: list[str] = []
    unknown: list[str] = []
    for text in wanted:
        try:
            name = find_name(text, names)
        except AmbiguousName as error:
            raise ControllerError(f"{error.message} {outcome}") from error
        if name is None:
            unknown.append(text)
        elif name not in found:
            found.append(name)
    if unknown:
        raise ControllerError(
            _not_found(
                unknown,
                names,
                single=single,
                several=several,
                where=where,
                hint=hint,
                outcome=outcome,
            )
        )
    return found


# ---------------------------------------------------------------------- #
#  Arguments
# ---------------------------------------------------------------------- #
def _names(value: Any) -> list[str]:
    """The names the model sent as a clean list (a single string is accepted too)."""
    if value is None:
        return []
    items = list(value) if isinstance(value, (list, tuple, set)) else [value]
    return [text for text in (str(item).strip() for item in items) if text]


SCHEDULE_FIELD = Field(
    default=None,
    description=(
        "Schedule number (1-based). Leave it out: the application uses the schedule the user is "
        "looking at. Only set it when the user names a schedule ('from schedule 3')."
    ),
)


class LockSectionsArgs(BaseModel):
    sections: list[str] = Field(
        default_factory=list,
        description=(
            "Every section to lock, as the user wrote them (for example 'CMSC 141.01' or '141.01'). "
            "Put all of them in this one call."
        ),
    )
    schedule: int | None = SCHEDULE_FIELD
    replace_existing_locks: bool = Field(
        default=False,
        description=(
            "True to unlock every OTHER locked section first, so the sections named here become the "
            "only locks ('lock only ...', 'replace my locks with ...')."
        ),
    )

    @field_validator("sections", mode="before")
    @classmethod
    def clean_sections(cls, value: Any) -> list[str]:
        return _names(value)


class UnlockSectionsArgs(BaseModel):
    sections: list[str] = Field(
        default_factory=list,
        description="Every locked section to unlock, as the user wrote them. Put all of them in this one call.",
    )

    @field_validator("sections", mode="before")
    @classmethod
    def clean_sections(cls, value: Any) -> list[str]:
        return _names(value)


class ScheduleArgs(BaseModel):
    schedule: int | None = SCHEDULE_FIELD


class LockFacultyArgs(BaseModel):
    faculty: str = Field(
        default="",
        description="The instructor, as the user wrote it (a last name is enough).",
    )
    schedule: int | None = SCHEDULE_FIELD


class UnlockFacultyArgs(BaseModel):
    faculty: str = Field(
        default="",
        description="The instructor whose locked sections to unlock, as the user wrote it.",
    )


# ---------------------------------------------------------------------- #
#  Tools
# ---------------------------------------------------------------------- #
def _locked_text(change: lock_controller.LockChange, number: int, assumed: bool) -> str:
    sentences: list[str] = []
    if change.locked:
        sentences.append(f"Locked {_and(_quoted(change.locked))}.")
    if change.replaced:
        sentences.append(
            f"Re-locked {_and(_quoted(change.replaced))} to the placement in schedule "
            f"{number} instead of the earlier lock."
        )
    if change.already:
        verb = "was" if len(change.already) == 1 else "were"
        sentences.append(
            f"{_and(_quoted(change.already))} {verb} already locked exactly like this."
        )
    if change.released:
        sentences.append(
            f"Unlocked {_plural(len(change.released), 'other section')} "
            f"({_few(change.released)}), so the sections you named are now the only locks."
        )
    kept = change.locked + change.replaced
    if kept:
        sentences.append(
            f"{'It stays' if len(kept) == 1 else 'They stay'} exactly as placed the next "
            "time you generate schedules."
        )
    sentences.append(NO_CHANGE_NOTE)
    return " ".join(sentences) + _assumed_note(number, assumed)


def lock_sections(request, args: LockSectionsArgs) -> Outcome:
    if not args.sections:
        raise ControllerError(
            "Say which section to lock, for example: lock CMSC 141.01."
        )
    number, schedule, assumed = _schedule_target(request, args.schedule)
    names = [item.course for item in schedule]
    chosen = _resolve(
        args.sections,
        names,
        single="a section",
        several="these sections",
        where=f"in schedule {number}",
        hint=f"Ask me to list the sections in schedule {number} to see their exact names.",
        outcome=NOT_LOCKED_NOTE,
    )
    change = lock_controller.lock_sections(
        request, number, chosen, args.replace_existing_locks
    )
    return Outcome(_locked_text(change, number, assumed), (SHOW_CHIP, GENERATE_CHIP))


def unlock_sections(request, args: UnlockSectionsArgs) -> Outcome:
    if not args.sections:
        raise ControllerError(
            "Say which section to unlock, for example: unlock CMSC 141.01."
        )
    held = lock_controller.locked_entries(request)
    if not held:
        return Outcome(f"{NOTHING_LOCKED} There is nothing to unlock.")
    names = [lock.section for lock in held]
    chosen = _resolve(
        args.sections,
        names,
        single="a section",
        several="these sections",
        where="among the locked sections",
        hint=f"Locked sections: {_few(names)}.",
        outcome=NOT_UNLOCKED_NOTE,
    )
    done = lock_controller.unlock_sections(request, chosen)
    return Outcome(
        f"Unlocked {_and(_quoted(done))}. "
        f"{'It can' if len(done) == 1 else 'They can'} change the next time you generate "
        f"schedules. {NO_CHANGE_NOTE}",
        (SHOW_CHIP,),
    )


def view_locked_sections(request, args: NoArgs) -> Outcome:
    held = lock_controller.locked_entries(request)
    if not held:
        return Outcome(
            f"{NOTHING_LOCKED} Ask me to lock a section of the schedule you are viewing "
            "and the next generation will keep it exactly as it is."
        )
    time_format = _time_format(request)
    one = len(held) == 1
    lines = [
        (
            f"{_plural(len(held), 'section')} {'is' if one else 'are'} locked. The next "
            f"generation keeps {'it' if one else 'them'} exactly as listed:"
        )
    ]
    lines += [
        f"- {_describe(lock.assignment, time_format)}{_origin(lock)}" for lock in held
    ]
    return Outcome("\n".join(lines), (GENERATE_CHIP,))


def unlock_all_sections(request, args: NoArgs) -> Outcome:
    count = lock_controller.clear_all(request)
    if count == 0:
        return Outcome("No sections were locked, so there was nothing to unlock.")
    which = "the one locked section" if count == 1 else f"all {count} locked sections"
    return Outcome(
        f"Unlocked {which}. {'It can' if count == 1 else 'They can'} change the next time "
        f"you generate schedules. {NO_CHANGE_NOTE}"
    )


def lock_faculty_sections(request, args: LockFacultyArgs) -> Outcome:
    if not args.faculty.strip():
        raise ControllerError(
            "Say whose sections to lock, for example: lock everything Hogg teaches."
        )
    number, schedule, assumed = _schedule_target(request, args.schedule)
    people = sorted(
        {name for item in schedule if (name := item.faculty)}, key=str.casefold
    )
    (chosen,) = _resolve(
        [args.faculty.strip()],
        people,
        single="an instructor",
        several="these instructors",
        where=f"teaching in schedule {number}",
        hint=f"Instructors in schedule {number}: {_few(people)}." if people else "",
        outcome=NOT_LOCKED_NOTE,
    )
    text = lock_controller.lock_faculty(request, number, chosen)
    return Outcome(
        f"{text} {NO_CHANGE_NOTE}{_assumed_note(number, assumed)}",
        (SHOW_CHIP, GENERATE_CHIP),
    )


def unlock_faculty_sections(request, args: UnlockFacultyArgs) -> Outcome:
    if not args.faculty.strip():
        raise ControllerError(
            "Say whose sections to unlock, for example: unlock everything Hogg teaches."
        )
    held = lock_controller.locked_entries(request)
    if not held:
        return Outcome(f"{NOTHING_LOCKED} There is nothing to unlock.")
    people = sorted(
        {name for lock in held if (name := lock.assignment.faculty)}, key=str.casefold
    )
    (chosen,) = _resolve(
        [args.faculty.strip()],
        people,
        single="an instructor",
        several="these instructors",
        where="among the locked sections",
        hint=f"Instructors with locked sections: {_few(people)}." if people else "",
        outcome=NOT_UNLOCKED_NOTE,
    )
    text = lock_controller.unlock_faculty(request, chosen)
    return Outcome(f"{text} {NO_CHANGE_NOTE}", (SHOW_CHIP,))


def list_schedule_sections(request, args: ScheduleArgs) -> Outcome:
    """A lookup for the AI: every section of the schedule the user is looking at, and its lock state."""
    number, schedule, assumed = _schedule_target(request, args.schedule)
    count = schedule_controller.schedule_count(request)
    states = lock_controller.section_states(request, schedule)
    time_format = _time_format(request)
    marks = {
        lock_controller.LOCKED: " [locked]",
        lock_controller.DIFFERENT: " [locked, but placed differently in this schedule]",
    }
    lines = [f"Schedule {number} of {count} has {_plural(len(schedule), 'section')}:"]
    for item in sorted(schedule, key=lambda assignment: assignment.course):
        mark = marks.get(states[item.course], "")
        lines.append(f"- {_describe(item, time_format)}{mark}")
    note = _assumed_note(number, assumed).strip()
    if note:
        lines.append(note)
    return Outcome("\n".join(lines))


# ---------------------------------------------------------------------- #
#  Registry (gui/ai/tools.py adds these to TOOLS)
# ---------------------------------------------------------------------- #
# Said in the description of every lock tool (the model reads those), next to the prompt's own rule.
WITH_GENERATION = (
    "If the user's message ALSO asks to generate schedules, you MUST call prepare_schedule_generation in "
    "the SAME response, right after this tool (with limit when they named a number): this tool's reply is "
    "a final answer, so a response that stops here silently drops the generation they asked for."
)

LOCK_TOOLS: tuple[AiTool, ...] = (
    AiTool(
        "lock_sections",
        "Lock one or more course sections so the next schedule generation keeps them exactly as they are "
        "(same instructor, room, lab, days and times). They are locked as the schedule the user is looking "
        "at in the Schedule Viewer places them; the application knows which one, so pass schedule only when "
        "the user names a schedule number. Pass EVERY section the user asked for in ONE call, as they wrote "
        "them ('CMSC 141.01', '141.01'): it is all or nothing, so one wrong name locks nothing. Set "
        "replace_existing_locks when the named sections should become the ONLY locks. Locks are not part of "
        "the configuration, so this never changes it. It acts at once; no confirmation step. When the user "
        "describes sections (by instructor, room, day or time) instead of naming them, call "
        "list_schedule_sections first. " + WITH_GENERATION,
        LockSectionsArgs,
        lock_sections,
        needs_config=False,
    ),
    AiTool(
        "unlock_sections",
        "Unlock one or more locked sections so the next generation may change them. Pass every section to "
        "unlock in ONE call; all or nothing. Never changes the configuration. Acts at once. "
        + WITH_GENERATION,
        UnlockSectionsArgs,
        unlock_sections,
        needs_config=False,
    ),
    AiTool(
        "view_locked_sections",
        "Say which sections are currently locked (instructor, room or lab, days and times, and the schedule "
        "each was locked from). These are the same sections the Schedule Generator lists. Use for 'which "
        "sections are locked?', 'show my locks'. With none locked it says so.",
        NoArgs,
        view_locked_sections,
        needs_config=False,
    ),
    AiTool(
        "unlock_all_sections",
        "Remove every lock at once. Use for 'unlock everything', 'clear all locks'. Never changes the "
        "configuration. To lock a new set in its place, prefer lock_sections with replace_existing_locks. "
        + WITH_GENERATION,
        NoArgs,
        unlock_all_sections,
        needs_config=False,
    ),
    AiTool(
        "lock_faculty_sections",
        "Lock every section one instructor teaches in the schedule the user is looking at ('lock everything "
        "Hogg teaches'). A last name is enough. Pass schedule only when the user names a schedule number. "
        + WITH_GENERATION,
        LockFacultyArgs,
        lock_faculty_sections,
        needs_config=False,
    ),
    AiTool(
        "unlock_faculty_sections",
        "Unlock every locked section one instructor teaches ('unlock everything Hogg teaches'). "
        + WITH_GENERATION,
        UnlockFacultyArgs,
        unlock_faculty_sections,
        needs_config=False,
    ),
    AiTool(
        "list_schedule_sections",
        "List every section of the schedule the user is looking at: instructor, room or lab, days and times, "
        "and whether it is locked. For you to read, not for the user. Call it before locking or unlocking "
        "when the user describes sections (by instructor, room, day, time or course) instead of naming each "
        "one, then pass the exact names to lock_sections.",
        ScheduleArgs,
        list_schedule_sections,
        needs_config=False,
    ),
)


# ---------------------------------------------------------------------- #
#  Safety net: "lock X and generate 5 schedules" must never lose the second half
#
#  A lock tool's reply is the application's final answer, so if the AI calls ONLY the lock tool
#  the turn ends there and the generation the user asked for is dropped. The prompt and the tool
#  descriptions tell the AI to call both; this makes sure of it, on the server, whatever the AI did.
#
#  It does exactly what the AI should have done: it calls prepare_schedule_generation, which only
#  SHOWS the settings (and the locked sections) and waits. Nothing is generated: the user still
#  agrees in a later message, like every other generation.
# ---------------------------------------------------------------------- #
_LOCK_CHANGING = frozenset(
    {
        "lock_sections",
        "unlock_sections",
        "unlock_all_sections",
        "lock_faculty_sections",
        "unlock_faculty_sections",
    }
)
_GENERATION_TOOLS = frozenset(
    {
        "prepare_schedule_generation",
        "confirm_schedule_generation",
        "cancel_schedule_generation",
    }
)
_ASKS_TO_GENERATE = re.compile(
    r"\bgenerat\w*|\bre-?generat\w*|\b(?:make|create|build|produce|run|get)\b[^.!?\n]{0,30}\bschedules?\b",
    re.IGNORECASE,
)
# Anything that postpones or refuses: then the AI's own judgement stands (the safety net stays out).
_NOT_NOW = re.compile(
    r"\b(?:do not|dont|not yet|no need|without|later|afterwards?|after|until|before|instead|never|"
    r"stop|cancel|skip|will not)\b|n't\b",
    re.IGNORECASE,
)
_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
_COUNT = re.compile(
    r"\b(\d{1,4}|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(?:(?:new|more|different|fresh|other)\s+)?(?:schedules?|options|results)\b",
    re.IGNORECASE,
)


def _requested_count(text: str) -> int | None:
    found = _COUNT.search(text)
    if found is None:
        return None
    raw = found.group(1).casefold()
    count = int(raw) if raw.isdigit() else _NUMBER_WORDS[raw]
    return count if count > 0 else None


def finish_generation_request(text: str, toolbox: Any) -> bool:
    """Make sure a message that locks or unlocks AND asks to generate gets both.

    Call it after the AI has finished (gui/ai/service.py). It acts only when every lock or unlock
    the AI made worked, no generation tool was called, the message clearly asks to generate and
    does not postpone it. Then it calls prepare_schedule_generation, which shows the settings and
    the locked sections and waits for "go ahead". Returns True when it did.
    """
    results = list(toolbox.results)
    lock_results = [result for result in results if result.tool in _LOCK_CHANGING]
    if not lock_results or not all(result.ok for result in lock_results):
        return False
    if any(result.tool in _GENERATION_TOOLS for result in results):
        return False
    if not _ASKS_TO_GENERATE.search(text) or _NOT_NOW.search(text):
        return False
    count = _requested_count(text)
    toolbox.call("prepare_schedule_generation", {"limit": count} if count else {})
    return True
