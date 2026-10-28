"""
The AI assistant's tools for generating schedules (Sprint 3: schedule generation from the chat).

    ToolBox(request).call("prepare_schedule_generation", {"limit": 5})    # shows the settings, runs nothing
    ToolBox(later(request)).call("confirm_schedule_generation")            # in a LATER message: runs it

The AI never runs the solver itself. It can only ask for one of these tools by name, and every tool
goes through the same controllers the Schedule Generator page uses (gui/controllers/schedule_controller.py,
settings.py, config_controller.py). So the checks, the generation and the stored results are the
application's own, and the Schedule Viewer simply shows what the session now holds.

Generating is two steps, and the server (not the model) enforces them, like the delete safeguard:

  1. prepare_schedule_generation checks that a configuration is open, that the application accepts it
     (the same full validation as Validate) and that nothing else is generating, then SHOWS the user the
     generation limit and optimizer flags this run would use, and waits. A limit or flags the user named
     are checked here too. Nothing is generated yet.
  2. confirm_schedule_generation runs it, but only when the user's NEXT message agrees. A run that was
     described in a request cannot be confirmed in that same request, the settings go stale after 10
     minutes, and the run is refused when the configuration changed in between. The configuration is
     validated again right before the solver starts.

The limit and flags chosen in the chat apply to THIS RUN ONLY, exactly like the overrides on the Schedule
Generator page. The saved configuration is never edited by generating (the job works on a copy), and a
change to the saved settings only happens through update_global_settings when the user asks for it.

When there is no configuration, the tools say one has to be created or loaded and offer both ways:
create_new_configuration (gui/ai/lifecycle.py), and load_saved_configuration for a configuration that is
available in this session. Loading can continue straight into step 1. load_saved_configuration does not
replace a configuration that has unsaved changes or schedules to lose: that stays with the Configuration
Editor, which asks first.

A failed run never shows a partial schedule: the controller only stores results when the run succeeded,
and the reply explains what happened in the same words the Schedule Generator page uses.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app import schedule_ops
from gui.ai import diagnose
from gui.ai.base import (
    LOAD_OR_NEW_ACTION,
    UNDO_CHIP,
    AiTool,
    NoArgs,
    Outcome,
    _join,
    _plural,
    find_name,
)
from gui.ai.changes import _PENDING_ATTR as DELETE_SLOT
from gui.ai.changes import _token
from gui.ai.undo import recent_changes
from gui.controllers import config_controller, schedule_controller, settings
from gui.controllers.errors import ControllerError
from gui.session_store import get_session

PLAN_SECONDS = 600  # reviewed settings stop being confirmable after this long
WAIT_ENV = (
    "AI_GENERATION_WAIT_SECONDS"  # how long one chat request waits for the solver
)
DEFAULT_WAIT_SECONDS = 600
MAX_WAIT_SECONDS = 3600
_PLAN_ATTR = "ai_generation_plan"  # where the reviewed settings wait, on the browser's own Session

GO_AHEAD = "Go ahead and generate"
CANCEL = "Cancel"
GENERATE = "Generate schedules"
CREATE_NEW = "Create a new configuration"

_now: Callable[[], float] = (
    time.monotonic
)  # tests replace this to age the reviewed settings


# ---------------------------------------------------------------------- #
#  Argument schemas (what the model must send; checked before anything runs)
# ---------------------------------------------------------------------- #
class ControllerErrorWithChips(ControllerError):
    """A refusal that also offers quick replies (read by the tool box when it builds the answer)."""

    suggestions: tuple[str, ...] = ()


class PrepareArgs(BaseModel):
    limit: int | None = Field(
        default=None,
        description="How many schedules to generate, only if the user named a number. Leave out to keep "
        "the current choice (the saved generation limit, unless the user already chose another)",
    )
    optimizer_flags: list[str] | None = Field(
        default=None,
        description="The optimizer flags to turn on for this run, only if the user named some; an empty "
        "list means none. Leave out to keep the current choice (the saved flags, unless the user already "
        "chose others)",
    )


class LoadArgs(BaseModel):
    name: str = Field(
        description="The name of the configuration to load, as the user wrote it"
    )
    continue_to_generation: bool = Field(
        default=False,
        description="True when the user's goal was to generate schedules and they are loading a "
        "configuration so that it can go on: the settings review follows right after the load",
    )


@dataclass(frozen=True)
class _Plan:
    """The settings the user was shown, waiting for their go-ahead."""

    limit: int
    flags: tuple[str, ...]
    token: str  # which request showed them, so they cannot be confirmed in the same one
    created: float
    version: int  # the configuration version they were checked against
    config: object  # the configuration they were checked against (a new/loaded one is a different object)


# ---------------------------------------------------------------------- #
#  Small helpers
# ---------------------------------------------------------------------- #
def wait_seconds() -> float:
    """How long one chat request waits for the solver before it leaves the run going."""
    raw = os.environ.get(WAIT_ENV, "").strip()
    try:
        value = float(raw) if raw else DEFAULT_WAIT_SECONDS
    except ValueError:
        value = DEFAULT_WAIT_SECONDS
    return max(0.1, min(value, MAX_WAIT_SECONDS))


def _short(text: str, limit: int = 600) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _saved_names(request) -> list[str]:
    return [name for name, _label in config_controller.saved_config_choices(request)]


def _in_known_order(flags: set[str] | list[str]) -> tuple[str, ...]:
    return tuple(flag for flag in settings.known_flags() if flag in flags)


def _check_limit(value: int) -> int:
    if isinstance(value, bool) or value <= 0:
        raise ControllerError(settings.LIMIT_MESSAGE)
    return value


def _check_flags(wanted: list[str]) -> tuple[str, ...]:
    """Map what the user typed to real optimizer flags; an unknown one is refused, never guessed."""
    known = settings.known_flags()
    found: list[str] = []
    for item in wanted:
        flag = find_name(str(item).strip(), known)
        if flag is None:
            raise ControllerError(
                f"'{item}' is not a valid optimizer flag. The valid flags are: {_join(known)}."
            )
        found.append(flag)
    return _in_known_order(found)


def _problems(problems: list[str]) -> str:
    return "\n".join(f"- {problem}" for problem in problems)


def _require_valid(request, refusal: str) -> None:
    """Run the application's full validation; refuse (with the reasons) when it fails."""
    problems = config_controller.validate_configuration(request)
    if problems:
        raise ControllerError(
            f"The configuration is not valid, {refusal}\n{_problems(problems)}\n"
            "Fix these first (I can change items for you), then ask me again."
        )


def _fresh_plan(session) -> _Plan | None:
    """The reviewed settings, if they are still current: the same configuration, unchanged, recent."""
    plan = getattr(session, _PLAN_ATTR, None)
    if (
        plan is None
        or plan.config is not session.config
        or plan.version != session.history.version
    ):
        return None
    return plan if _now() - plan.created <= PLAN_SECONDS else None


def _refuse_if_it_would_discard(request, doing: str, where: str) -> None:
    """New and Load throw the open configuration away. The Configuration Editor asks first, so the
    chat only does it when there is nothing to lose."""
    session = get_session(request)
    if session.config is None:
        return
    lost = config_controller.discard_note(bool(session.dirty), len(session.schedules))
    if lost:
        raise ControllerError(
            f"{doing} would discard {lost}, so I did not do it. Use {where} in the Configuration Editor "
            "instead: it asks you first."
        )


def _forget_waiting(session) -> None:
    """A different configuration is now open: nothing described for the old one may be confirmed."""
    setattr(session, _PLAN_ATTR, None)
    setattr(session, DELETE_SLOT, None)
    setattr(session, config_controller.PENDING_NEW_ATTR, None)


def _no_configuration(request, wanted: str) -> Outcome:
    """No configuration is open: say so, and offer both ways forward."""
    names = _saved_names(request)
    lines = [
        (
            f"No configuration is loaded, so I can't {wanted} yet. A configuration has to be created or loaded first. "
            "You can:"
        ),
        '- Create a new one: say "create a new configuration".',
    ]
    if names:
        lines.append(
            f'- Load one that is available in this session ({_join(names)}): say "load {names[0]}".'
        )
    lines.append(
        "- Load a file from your computer: use Load Configuration in the Configuration Editor, then ask me again."
    )
    lines.append(
        "When one is open and valid, I'll show you the generation settings before generating."
    )
    suggestions = [CREATE_NEW] + [f"Load {name}" for name in names[:3]]
    return Outcome("\n".join(lines), suggestions, action=LOAD_OR_NEW_ACTION)


# ---------------------------------------------------------------------- #
#  Step 1: check everything, show the settings, wait
# ---------------------------------------------------------------------- #
def prepare_schedule_generation(request, args: PrepareArgs) -> str:
    session = get_session(request)
    if session.config is None:
        return _no_configuration(request, "generate schedules")
    if schedule_controller.is_generating(request):
        raise ControllerError(schedule_controller.BUSY_MESSAGE)
    _require_valid(request, "so I did not start. Nothing was generated:")

    saved = settings.describe_settings(request)
    current = _fresh_plan(session)
    limit = (
        args.limit
        if args.limit is not None
        else (current.limit if current else saved["limit"])
    )
    flags = (
        _check_flags(args.optimizer_flags)
        if args.optimizer_flags is not None
        else (current.flags if current else _in_known_order(saved["enabled_flags"]))
    )
    limit = _check_limit(limit)

    setattr(session, DELETE_SLOT, None)  # only one thing waits for a "yes" at a time
    setattr(
        session,
        _PLAN_ATTR,
        _Plan(
            limit,
            flags,
            _token(request),
            _now(),
            session.history.version,
            session.config,
        ),
    )

    saved_flags = _in_known_order(saved["enabled_flags"])
    limit_note = (
        "the saved limit"
        if limit == saved["limit"]
        else f"this run only; the saved limit is {saved['limit']}"
    )
    flags_note = (
        "the saved flags"
        if flags == saved_flags
        else f"this run only; saved: {_join(saved_flags, 'none')}"
    )
    name = getattr(session, "config_name", None)
    lines = [
        f"Ready to generate schedules from {name or 'the open configuration'}. I checked it and it is valid.",
        "This run would use:",
        f"- Generation limit: {limit} ({limit_note})",
        f"- Optimizer flags: {_join(flags, 'none')} ({flags_note})",
        "These apply to this run only. Your saved settings and your configuration are not changed.",
    ]
    if session.schedules:
        lines.append(
            f"{_plural(len(session.schedules), 'schedule')} loaded now will be replaced if this succeeds."
        )
    lines.append(
        'Reply "go ahead" to generate, or tell me a different limit or optimizer flags. '
        f"Optimizer flags you can use: {_join(settings.known_flags())}."
    )
    return Outcome("\n".join(lines), (GO_AHEAD, CANCEL))


# ---------------------------------------------------------------------- #
#  Step 2: run it (only after the user agreed in a later message)
# ---------------------------------------------------------------------- #
def confirm_schedule_generation(request, args: NoArgs) -> str:
    session = get_session(request)
    if session.config is None:
        return _no_configuration(request, "generate schedules")
    plan = getattr(session, _PLAN_ATTR, None)
    waiting_delete = getattr(session, DELETE_SLOT, None)
    if plan is None:
        if waiting_delete is not None:
            raise ControllerError(
                "Nothing is waiting to be generated. A delete is waiting for your answer instead: "
                'reply "confirm" to delete it or "cancel" to keep it.'
            )
        raise ControllerError(
            "No generation settings are waiting for a go-ahead. Ask me to generate schedules first, "
            "and I will show you the settings."
        )
    if plan.token == _token(request):
        raise ControllerError(
            "Generating has to be confirmed in a separate message, after you have seen the settings. "
            "Nothing was started."
        )
    if waiting_delete is not None:
        raise ControllerError(
            'A delete is waiting for your answer too, so I did not start generating. Reply "confirm" or '
            '"cancel" for the delete, then ask me to generate again.'
        )

    setattr(session, _PLAN_ATTR, None)  # used up, whatever happens next
    if _now() - plan.created > PLAN_SECONDS:
        raise ControllerError(
            "Those generation settings were shown too long ago. Ask me to generate again."
        )
    if plan.config is not session.config or plan.version != session.history.version:
        raise ControllerError(
            "The configuration changed after I showed you the generation settings, so I did not start. "
            "Ask me to generate again to review them."
        )
    _require_valid(request, "so I did not start. Nothing was generated:")

    before = schedule_controller.schedule_count(request)
    schedule_controller.start_generation(
        request, limit_override=plan.limit, optimizer_overrides=list(plan.flags)
    )
    job = getattr(session, "generation_job", None)
    if job is not None and not job.wait(wait_seconds()):
        return (
            f"The solver is still working after {_plural(round(wait_seconds() / 60), 'minute')}, so I left it running. "
            "Any schedules it finds appear in the Schedule Viewer when it finishes. "
            'Ask me "how is the generation going?" to check, or say "cancel the generation" to stop it.'
        )
    return _report(request, before=before, limit=plan.limit)


def _report(request, *, before: int | None, limit: int | None) -> str:
    """Turn the finished run into the reply: what was generated, or why nothing was."""
    result = schedule_controller.collect_generation_result(request)
    if result is None:
        count = schedule_controller.schedule_count(request)
        return (
            "That run has already finished and was reported elsewhere (for example on the Schedule Generator page). "
            f"{_plural(count, 'schedule')} {'is' if count == 1 else 'are'} in the Schedule Viewer now."
        )
    outcome = schedule_ops.GenerationOutcome
    if result.outcome == outcome.SUCCESS:
        count = len(result.schedules)
        lines = [
            f"Generated {_plural(count, 'schedule')}. {'It is' if count == 1 else 'They are'} now in the Schedule Viewer."
        ]
        if limit and count < limit:
            lines.append(
                f"The limit was {limit}, but the solver found only {count}: that is every schedule that "
                "satisfies all the hard constraints."
            )
        lines.append("Your configuration and saved settings were not changed.")
        return " ".join(lines)
    if result.outcome == outcome.CANCELLED:
        return result.message

    _level, text = schedule_controller.describe_outcome(result)
    if result.outcome == outcome.NO_FEASIBLE_SCHEDULE:
        text += " Nothing was added to the Schedule Viewer."
        if before:
            text += f" The {_plural(before, 'schedule')} loaded before {'was' if before == 1 else 'were'} cleared."
        text += diagnose.explain_no_feasible(request)
        error = ControllerErrorWithChips(_short(text, 1200))
        error.suggestions = (
            diagnose.CHECK_CHIP,
            *((UNDO_CHIP,) if recent_changes(request, 1) else ()),
        )
        raise error
    text += " Nothing was added to the Schedule Viewer, and your previous schedules were kept."
    raise ControllerError(_short(text))


def cancel_schedule_generation(request, args: NoArgs) -> str:
    """Forget the settings that were shown, or ask a run that is still going to stop."""
    session = get_session(request)
    plan = getattr(session, _PLAN_ATTR, None)
    setattr(session, _PLAN_ATTR, None)
    job = getattr(session, "generation_job", None)
    if job is not None and not job.finished:
        job.cancel()
        return (
            "Cancelling. The run stops when the solver finishes the schedule it is working on. "
            "Nothing is saved and your previous schedules are kept."
        )
    if plan is None:
        return "Nothing was waiting to be generated."
    return "Cancelled. No schedules were generated and nothing was changed."


def check_generation_status(request, args: NoArgs) -> str:
    """How a run that is still going (or just finished) is doing."""
    status = schedule_controller.generation_status(request)
    if status["state"] == "idle":
        count = schedule_controller.schedule_count(request)
        have = (
            f"{_plural(count, 'schedule')} {'is' if count == 1 else 'are'} in the Schedule Viewer."
            if count
            else "There are no schedules yet."
        )
        return f"No schedule generation is running. {have}"
    if status["state"] == "running":
        found, limit = status["found"], status["limit"]
        progress = f"found {found} of {limit}" if limit else f"found {found}"
        stopping = " It is being cancelled." if status["cancel_requested"] else ""
        return f"A generation is still running: {progress}, {status['elapsed']:g}s elapsed.{stopping}"
    return _report(request, before=None, limit=status.get("limit"))


# ---------------------------------------------------------------------- #
#  Validate, and what to do when no configuration is open
# ---------------------------------------------------------------------- #
def validate_configuration(request, args: NoArgs) -> str:
    if get_session(request).config is None:
        return _no_configuration(request, "validate anything")
    problems = config_controller.validate_configuration(request)
    if not problems:
        return Outcome("The configuration is valid. Nothing was changed.", (GENERATE,))
    raise ControllerError(
        f"The configuration is not valid:\n{_problems(problems)}\n"
        "Nothing was changed. Fix these (I can change items for you), then ask me to validate it again."
    )


def list_saved_configurations(request, args: NoArgs) -> str:
    session = get_session(request)
    names = _saved_names(request)
    if session.config is None:
        lines = ["No configuration is open now."]
    else:
        lines = [
            f"Open now: {getattr(session, 'config_name', None) or 'a configuration that has not been saved'}."
        ]
    if names:
        lines.append(
            f"Configurations available to load in this session: {_join(names)}."
        )
    else:
        lines.append("No other configuration is available to load in this session.")
    lines.append(
        "A file from the user's computer can only be loaded with Load Configuration in the Configuration Editor."
    )
    return "\n".join(lines)


def load_saved_configuration(request, args: LoadArgs) -> str:
    session = get_session(request)
    names = _saved_names(request)
    wanted = args.name.strip()
    found = find_name(wanted, names)
    if found is None and not wanted.lower().endswith(".json"):
        found = find_name(f"{wanted}.json", names)  # "load spring" finds spring.json
    if found is None:
        available = (
            f"Available: {_join(names)}."
            if names
            else "None is available in this session."
        )
        raise ControllerError(
            f"No configuration named '{args.name.strip()}' can be loaded. {available}"
        )
    _refuse_if_it_would_discard(request, f"Loading {found}", "Load Configuration")
    try:
        config_controller.select_saved_configuration(request, found)
    except ControllerError as error:
        raise ControllerError(
            f"{error.message} The configuration that was open was not changed."
        ) from error
    _forget_waiting(session)
    problems = config_controller.validate_configuration(request)
    if problems:
        raise ControllerError(
            f"Loaded '{found}', but it is not valid:\n{_problems(problems)}\n"
            "Fix these (I can change items for you) before generating schedules."
        )
    done = f"Loaded '{found}'. I checked it and it is valid."
    if not args.continue_to_generation:
        return Outcome(
            f"{done} Ask me to generate schedules when you are ready; I will show you the settings first.",
            (GENERATE,),
        )
    try:
        review = prepare_schedule_generation(request, PrepareArgs())
    except ControllerError as error:
        raise ControllerError(
            f"{done} But I can't generate yet: {error.message}"
        ) from error
    return Outcome(f"{done}\n{review}", getattr(review, "suggestions", ()))


# ---------------------------------------------------------------------- #
#  The registry for this file
# ---------------------------------------------------------------------- #
GENERATION_TOOLS: tuple[AiTool, ...] = (
    AiTool(
        "prepare_schedule_generation",
        "Start generating schedules. Use whenever the user asks to generate, run or make schedules, even if they "
        "already gave a number. Checks that a configuration is open and valid and shows the user the generation "
        "limit and optimizer flags for this run; nothing is generated yet. Also use it again when the user changes "
        "the limit or flags before agreeing (send the settings they want). Limit and flags here apply to this run "
        "only and never change the saved settings.",
        PrepareArgs,
        prepare_schedule_generation,
        needs_config=False,
    ),
    AiTool(
        "confirm_schedule_generation",
        "Run the generation the user was just shown. Call it ONLY when the user's message agrees to go ahead "
        '("yes", "go ahead", "generate", "start") after the settings were shown, with no questions. The '
        "application knows the settings; do not pass any.",
        NoArgs,
        confirm_schedule_generation,
        needs_config=False,
    ),
    AiTool(
        "cancel_schedule_generation",
        "Drop the generation settings that were shown (the user says cancel, no, never mind), or ask a run that is "
        "still going to stop.",
        NoArgs,
        cancel_schedule_generation,
        needs_config=False,
    ),
    AiTool(
        "check_generation_status",
        "Say how a schedule generation that is still running is doing, or report one that just finished. Use when "
        "the user asks how the generation is going.",
        NoArgs,
        check_generation_status,
        needs_config=False,
    ),
    AiTool(
        "validate_configuration",
        "Check the open configuration with the scheduler library's full validation and report any problems. "
        "Changes nothing. Use when the user asks to validate or check the configuration.",
        NoArgs,
        validate_configuration,
        needs_config=False,
    ),
    AiTool(
        "list_saved_configurations",
        "List the configurations the user can load in this session and which one is open.",
        NoArgs,
        list_saved_configurations,
        needs_config=False,
    ),
    AiTool(
        "load_saved_configuration",
        "Open one of the configurations that are available in this session (see list_saved_configurations). It is "
        "checked before anything changes. Set continue_to_generation when the user wants to generate schedules.",
        LoadArgs,
        load_saved_configuration,
        needs_config=False,
    ),
)
