"""
Asking follow-up questions before a change is made (Sprint 3: AI request clarification).

A request that lacks a value, or names something that matches several items, is NOT run. The tool box
(gui/ai/tools.py) stops it, stores what the user already said, and the reply asks only for what is still
missing or unclear. Nothing in the configuration changes while the request waits.

    "Add a room named RODDY150"      add_room has no capacity: the request waits, the reply asks for it
    "It holds 35"                    provide_details({"capacity": 35}): merged into the stored request, then run

Who does what:
  * The AI chooses the tool, as everywhere. To answer it calls provide_details with ONLY the new details;
    to start over it calls the tool again (that replaces the waiting request); to drop it, cancel_pending_request.
  * The application owns the state. The stored request is the tool's name and the raw values given so far;
    provide_details merges the new details over them (a value given again corrects the earlier one) and runs
    the ORIGINAL tool, so the tool's own argument schema and checks decide what is required and valid. Nothing
    here repeats them. Values may be structured (lists, nested objects): they are checked by the same schema.
  * A value that was given, even an empty one ("none"), is answered and never asked again. Whether it is a
    value at all is the schema's business: a "none" the tool cannot accept is asked again, with the reason.
  * Where a question comes from: a required value that is missing (the schema), a value the library requires
    but the schema defaults that the user did not give (AiTool.ask: a faculty member's credit range, course
    limit and availability, a time slot's spacing; the question is the schema's own description, which names
    the default, and "default" accepts it), a recommended value that was not given (add_course asks for
    faculty and rooms), a name that fits several items, or a rule a tool checks itself (it raises NeedsDetails,
    gui/ai/base.py). Everything that is missing is asked in one message.
  * "Given" means the AI sent the value. The framework fills in defaults before it calls a tool, so the
    runner (gui/ai/runner.py) hands the tool box only the arguments the AI really sent.

While a request waits, every tool that changes something (AiTool.acts_on_state) is refused until it is
finished, cancelled or has waited too long; reading tools are not. One thing waits at a time: a question
replaces a waiting delete or generation review, like they replace each other. A request waits for ten
minutes, and is forgotten when another chat opens or a different configuration replaces the open one.
Edits made in between do not cancel it: it is checked again when it finally runs.

A combined change (apply_changes) waits as a whole. A step that needs details rolls the batch back, and the
details are given for that step: provide_details(details, step=2).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_core import to_jsonable_python

from gui.ai.base import (
    WAITING_ATTR,
    AiTool,
    NoArgs,
    Outcome,
    Question,
    ToolResult,
    Unchanged,
    _join,
)
from gui.ai.changes import PENDING_SECONDS
from gui.ai.generation import _forget_waiting
from gui.controllers.errors import ControllerError
from gui.session_store import get_session

CANCEL_CHIP = "Cancel"
BATCH_TOOL = "apply_changes"
NOTHING_WAITING = (
    "Nothing is waiting for details, so nothing was changed. Say what you want to do."
)

_now: Callable[[], float] = (
    time.monotonic
)  # tests replace this to age a waiting request


class ProvideDetailsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    details: dict[str, Any] = Field(
        description="ONLY the new or corrected values, keyed by the tool's own argument names, exactly as "
        "they are named in the waiting request. The application keeps everything already given",
    )
    step: int | None = Field(
        default=None,
        description="Only for a waiting combined change: the number of the step the details belong to",
    )


@dataclass
class Waiting:
    tool: str
    details: dict[
        str, Any
    ]  # the raw arguments given so far (for a combined change: {"operations": [...]})
    questions: tuple[Question, ...]
    created: float
    step: int | None = None  # the step the questions are about (combined change only)


# ---------------------------------------------------------------------- #
#  The stored request
# ---------------------------------------------------------------------- #
def _expired(held: Waiting) -> bool:
    return _now() - held.created > PENDING_SECONDS


def current(session) -> Waiting | None:
    """The request that is waiting for details now, or None (nothing waits, or it waited too long)."""
    held = getattr(session, WAITING_ATTR, None)
    return None if held is None or _expired(held) else held


def forget(session) -> None:
    setattr(session, WAITING_ATTR, None)


def store(
    session,
    tool: str,
    details: Mapping[str, Any],
    questions: tuple[Question, ...],
    step: int | None = None,
) -> Waiting:
    """Keep an unfinished request. It replaces anything else that waits for the user (one at a time)."""
    _forget_waiting(session)
    held = Waiting(tool, to_jsonable_python(dict(details)), questions, _now(), step)
    setattr(session, WAITING_ATTR, held)
    return held


def ask(
    session,
    tool: str,
    details: Mapping[str, Any],
    questions: tuple[Question, ...],
    step: int | None = None,
    remember: bool = True,
) -> Waiting:
    """The request that has to wait for `questions`; kept on the session unless `remember` is False
    (the steps of a combined change report their questions to apply_changes instead)."""
    if remember:
        return store(session, tool, details, questions, step)
    return Waiting(
        tool, to_jsonable_python(dict(details)), tuple(questions), _now(), step
    )


def take(session) -> tuple[Waiting | None, bool]:
    """Remove and return the waiting request, and whether it had waited too long."""
    held = getattr(session, WAITING_ATTR, None)
    forget(session)
    return held, held is not None and _expired(held)


def drop(session) -> str:
    """A fresh request replaces the waiting one: forget it and say so ('' when nothing waited)."""
    held = current(session)
    forget(session)
    return f"I dropped the earlier unfinished request to {label(held)}." if held else ""


# ---------------------------------------------------------------------- #
#  Words
# ---------------------------------------------------------------------- #
def label(held: Waiting) -> str:
    """'add room 'RODDY150'': what the waiting request is, for the user."""
    if held.tool == BATCH_TOOL:
        count = len(held.details.get("operations", ()))
        return f"apply {count} change{'' if count == 1 else 's'} together"
    verb = held.tool.replace("_", " ")
    name = next(
        (held.details[key] for key in ("name", "course_id") if held.details.get(key)),
        None,
    )
    return f"{verb} '{name}'" if name else verb


def _show(value: Any) -> str:
    if isinstance(value, list):
        return _join((_show(item) for item in value), "none")
    if isinstance(value, dict):
        return ", ".join(f"{key}={_show(item)}" for key, item in value.items())
    return str(value)


def _noted(held: Waiting) -> str:
    if held.tool == BATCH_TOOL:
        return _join(step["tool"] for step in held.details.get("operations", ()))
    return ", ".join(f"{key}: {_show(value)}" for key, value in held.details.items())


def render(held: Waiting) -> str:
    """The question the user sees: only what is missing or unclear, what is already noted, how to cancel."""
    lines = [
        f"I need a bit more before I can {label(held)}. Nothing has been changed yet."
    ]
    for question in held.questions:
        where = ""
        if held.step is not None:
            step_tool = held.details["operations"][held.step - 1]["tool"]
            where = f"Step {held.step} ({step_tool}): "
        lines.append(
            f"- {where}{question.field + ': ' if question.field else ''}{question.text}"
        )
    noted = _noted(held)
    if noted:
        lines.append(f"Already noted: {noted}.")
    lines.append(
        'Reply with the missing details, or say "cancel" to drop this request.'
    )
    return "\n".join(lines)


def refusal(held: Waiting) -> str:
    return (
        f'I\'m still waiting for details to {label(held)}. Give them, or say "cancel", before I do '
        "anything else. Nothing was changed."
    )


def prompt_note(session) -> str:
    """What the AI is told each request while one waits, so it answers with provide_details."""
    held = current(session)
    if held is None:
        return ""
    questions = "\n".join(
        f"  - {question.field or 'details'}: {question.text}"
        for question in held.questions
    )
    step = (
        f" (step {held.step} of the combined change)" if held.step is not None else ""
    )
    return (
        f"\nA request is waiting for details: {label(held)} (tool {held.tool}){step}. Nothing has been "
        f"changed.\nThe user already gave: {json.dumps(held.details, default=str)}\nStill needed:\n{questions}\n"
        "If the user's newest message answers or corrects these, call provide_details with ONLY those "
        "details (use the argument names above; the application keeps the rest"
        + ("; give step for a combined change" if held.tool == BATCH_TOOL else "")
        + "). If it is a new request, call that tool as usual: it replaces the waiting one. If the user "
        "wants to drop it, call cancel_pending_request. Other actions are refused until then."
    )


# ---------------------------------------------------------------------- #
#  Where a question comes from
# ---------------------------------------------------------------------- #
def missing_questions(
    tool: AiTool, error: ValidationError
) -> tuple[Question, ...] | None:
    """The questions for arguments the schema says are missing, or None when anything else is wrong
    (a wrong value is a failure, as before)."""
    problems = error.errors()
    if not problems or any(
        item["type"] != "missing" or len(item["loc"]) != 1 for item in problems
    ):
        return None
    return tuple(
        Question(str(item["loc"][0]), _describe(tool, str(item["loc"][0])))
        for item in problems
    )


def _describe(tool: AiTool, field: str) -> str:
    info = tool.args.model_fields.get(field)
    return (
        info.description if info and info.description else ""
    ) or "Please give this."


DEFAULT_HINT = 'Say "default" to use the default.'


def unanswered(tool: AiTool, given: Iterable[str]) -> tuple[Question, ...]:
    """Questions for the values the library requires but the tool's schema defaults (AiTool.ask) that the
    user did not give. A value that was sent, even an empty one, is answered. The question is the schema's
    own description, which also names the default."""
    sent = set(given)
    return tuple(
        Question(field, f"{_describe(tool, field).rstrip('.')}. {DEFAULT_HINT}")
        for field in tool.ask
        if field not in sent
    )


def provided(error: ValidationError) -> dict[str, Any] | None:
    """What the AI sent, recovered from a missing-value error (the framework reports it without the call)."""
    for item in error.errors():
        if isinstance(item.get("input"), dict):
            return dict(item["input"])
    return None


def field_for(details: Mapping[str, Any], wanted: str) -> str | None:
    """Which value of the request a name came from (an ambiguous name must be answered for that value)."""
    target = wanted.strip()
    for key, value in details.items():
        if isinstance(value, str) and value.strip() == target:
            return key
        if isinstance(value, list) and any(
            isinstance(item, str) and item.strip() == target for item in value
        ):
            return key
    return None


# ---------------------------------------------------------------------- #
#  The answer
# ---------------------------------------------------------------------- #
def _split(held: Waiting, step: int | None, tools: Mapping[str, AiTool]):
    """(the tool the details are for, the values given for it, how to put new ones back into the request)."""
    if held.tool != BATCH_TOOL:
        return tools[held.tool], held.details, lambda merged: merged
    operations = held.details["operations"]
    if step is None:
        raise ControllerError(
            "That request is a combined change: say which step the details are for (for example step 2)."
        )
    if not 1 <= step <= len(operations):
        raise ControllerError(
            f"There is no step {step}: the combined change has {len(operations)} steps."
        )
    operation = operations[step - 1]
    if operation["tool"] not in tools:
        raise ControllerError(
            f"Step {step} uses an action I do not know ({operation['tool']})."
        )

    def put_back(merged: dict[str, Any]) -> dict[str, Any]:
        steps = [dict(item) for item in operations]
        steps[step - 1] = {**steps[step - 1], "arguments": merged}
        return {**held.details, "operations": steps}

    return tools[operation["tool"]], dict(operation.get("arguments") or {}), put_back


def _corrections(given: Mapping[str, Any], details: Mapping[str, Any]) -> str:
    changed = [
        f"{key}: {_show(given[key])} -> {_show(value)}"
        for key, value in details.items()
        if key in given and given[key] != value
    ]
    return (
        f"Changed from what you said before: {'; '.join(changed)}." if changed else ""
    )


def resume(
    request,
    args: ProvideDetailsArgs,
    tools: Mapping[str, AiTool],
    run: Callable[[str, dict[str, Any]], ToolResult],
) -> str:
    """Merge the user's details into the waiting request and run it again through the tool box.

    `run(tool_name, raw_arguments)` is the tool box's own call, so the request gets exactly the checks it
    would have got had it been complete. It stores a new question when something is still missing.
    """
    session = get_session(request)
    held, expired = take(session)
    if held is None:
        raise ControllerError(NOTHING_WAITING)
    if expired:
        raise ControllerError(
            f"The request to {label(held)} waited too long, so I dropped it and nothing was changed. "
            "Ask me again."
        )

    def keep(message: str) -> ControllerError:
        setattr(
            session, WAITING_ATTR, held
        )  # a refused answer leaves the request waiting
        return ControllerError(message)

    if not args.details:
        raise keep("Tell me the details to add (for example a capacity or a name).")
    try:
        tool, given, put_back = _split(held, args.step, tools)
    except ControllerError as error:
        raise keep(error.message) from error
    unknown = [key for key in args.details if key not in tool.args.model_fields]
    if unknown:
        known = _join(tool.args.model_fields)
        raise keep(
            f"{_join(repr(key) for key in unknown)} {'is' if len(unknown) == 1 else 'are'} not "
            f"{'a detail' if len(unknown) == 1 else 'details'} of {tool.name.replace('_', ' ')}. "
            f"The details are: {known}."
        )

    merged = {**given, **args.details}
    wrong = _wrong_values(tool, merged)
    if wrong:
        for field in wrong:
            merged.pop(field)  # the bad value is not kept; it is asked again
        waiting = store(
            session,
            held.tool,
            put_back(merged),
            tuple(Question(field, message) for field, message in wrong.items()),
            held.step if held.tool == BATCH_TOOL else None,
        )
        return Outcome(render(waiting), (CANCEL_CHIP,), questions=waiting.questions)

    details = put_back(merged)
    result = run(held.tool, details)
    if (
        result.questions
    ):  # something is still missing: the tool box stored the request again
        return Outcome(result.message, result.suggestions, questions=result.questions)
    if not result.ok:
        setattr(
            session,
            WAITING_ATTR,
            Waiting(
                held.tool,
                to_jsonable_python(details),
                held.questions,
                _now(),
                held.step,
            ),
        )
        raise ControllerError(
            f'{result.message} The request is still waiting: tell me what to change, or say "cancel".'
        )
    notes = _corrections(given, args.details)
    text = result.message + (f"\n{notes}" if notes else "")
    if not result.changed:
        return (
            Unchanged(text)
            if not result.suggestions
            else Outcome(text, result.suggestions)
        )
    return Outcome(
        text, result.suggestions, edited=True, note=result.note, action=result.action
    )


def _wrong_values(tool: AiTool, merged: Mapping[str, Any]) -> dict[str, str]:
    """Values the schema rejects (wrong type, out of range): the field and why. Missing ones are not wrong;
    the tool box asks for those when it runs."""
    try:
        tool.args.model_validate(merged)
    except ValidationError as error:
        return {
            str(item["loc"][0]): f"{str(item['msg']).removeprefix('Value error, ')}. "
            f"{_describe(tool, str(item['loc'][0]))}"
            for item in error.errors()
            if item["type"] != "missing" and item["loc"]
        }
    return {}


# ---------------------------------------------------------------------- #
#  Cancel
# ---------------------------------------------------------------------- #
def cancel_pending_request(request, args: NoArgs) -> str:
    """Drop the waiting request. The configuration is never touched."""
    held, _ = take(get_session(request))
    if held is None:
        return Unchanged("Nothing was waiting for details.")
    return Unchanged(
        f"Cancelled. Nothing was changed: the request to {label(held)} was dropped."
    )


CLARIFY_TOOLS: tuple[AiTool, ...] = (
    AiTool(
        "cancel_pending_request",
        "Drop the request that is waiting for details (the user says cancel, never mind, forget it). "
        "Nothing is changed.",
        NoArgs,
        cancel_pending_request,
        needs_config=False,
    ),
)
