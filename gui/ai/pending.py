"""
Pending actions: the Command pattern behind every "describe first, confirm in the next message" step.

Some assistant actions must never happen in the same message that asked for them. The assistant first
DESCRIBES what it would do, remembers that, and only does it when the user confirms in a LATER message
(or forgets it when the user cancels):

    delete_room("Roddy 136")        describes the delete        -> a PendingDelete is staged
    confirm_delete()                in a later message          -> the delete runs
    prepare_schedule_generation()   shows the settings          -> a PendingGeneration is staged
    confirm_schedule_generation()   in a later message          -> the run starts

That is the Command pattern: a request is turned into an object that is created now and carried out
later.

    PendingAction (Command)         what every waiting action offers: execute(request), and the
                                    sentences it uses when it can no longer run
    PendingDelete, PendingGeneration (concrete Commands, in gui/ai/changes.py and gui/ai/generation.py)
                                    each holds what it needs to run, and calls its receiver: the delete
                                    controllers, and schedule_controller.start_generation
    stage / confirm / take / forget (the invoker's side, below)
                                    shared by every kind, so the confirmation flow exists once
    the delete_* and prepare_* tools (the clients) build a command and stage it

Where a command waits: one attribute per kind on the browser's own Session (the "slot"; its name is
passed in, so each module keeps its own). Staging a command may drop another kind that was waiting
(`replaces`), so reviewing generation settings drops a described delete.

The checks in confirm(), in this order. Each failure raises a ControllerError with the command's own
sentence and changes nothing:

    1. something is waiting                    (the caller says what to answer when nothing is)
    2. it was not staged by THIS request        same_request_message()
    3. nothing blocks it                        blocked_message(), checked BEFORE it is used up
    4. it is used up, whatever happens next     (the slot is cleared)
    5. it has not expired                       expired_message()
    6. it is still what was described           stale_message()
    7. it runs                                  execute()

Nothing here knows what a delete or a generation is, which is the point: a new kind of waiting action
is one new subclass, not another copy of this flow.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from typing import Any

from gui.controllers.errors import ControllerError


def request_token(request) -> str:
    """Identifies THIS request, so 'asked just now' can be told from 'asked earlier'."""
    token = getattr(request, "_ai_request_token", None)
    if token is None:
        token = uuid.uuid4().hex
        request._ai_request_token = token
    return token


class PendingAction(ABC):
    """The Command: an action that was described and waits for the user's confirmation.

    A subclass is a small dataclass that holds what it needs to run. It must have `label` (what to
    call it), `token` (the request that staged it), `created` (when, on the module's own clock) and
    `ttl` (how many seconds it stays confirmable).
    """

    label: str
    token: str
    created: float
    ttl: float

    @abstractmethod
    def execute(self, request) -> Any:
        """Carry the action out (call the receiver) and return what to tell the user."""

    @abstractmethod
    def same_request_message(self) -> str:
        """What to say when the user tries to confirm in the very message that described it."""

    @abstractmethod
    def expired_message(self) -> str:
        """What to say when it was described too long ago."""

    def blocked_message(self, request) -> str | None:
        """A sentence when something else stops it from running right now, or None."""
        return None

    def stale_message(self, request) -> str | None:
        """A sentence when it is no longer what was described (the configuration changed), or None."""
        return None


def current(session, slot: str) -> PendingAction | None:
    """The command waiting in `slot`, or None."""
    return getattr(session, slot, None)


def stage(
    session, slot: str, action: PendingAction, *, replaces: Iterable[str] = ()
) -> None:
    """Remember `action` as waiting, dropping whatever was waiting in the `replaces` slots."""
    forget(session, *replaces)
    setattr(session, slot, action)


def take(session, slot: str) -> PendingAction | None:
    """Forget the command in `slot` and hand it back (None when nothing was waiting): for cancelling."""
    action = current(session, slot)
    forget(session, slot)
    return action


def forget(session, *slots: str) -> None:
    """Empty these slots: whatever was waiting there can no longer be confirmed."""
    for slot in slots:
        setattr(session, slot, None)


def confirm(
    request,
    session,
    slot: str,
    *,
    now: Callable[[], float],
    nothing_waiting: str,
) -> Any:
    """The one confirmation flow: check the waiting command (see the module docstring), then run it.

    `now` is the owning module's clock (tests age a waiting command by replacing it);
    `nothing_waiting` is the sentence for an empty slot.
    """
    action = current(session, slot)
    if action is None:
        raise ControllerError(nothing_waiting)
    if action.token == request_token(request):
        raise ControllerError(action.same_request_message())
    blocked = action.blocked_message(request)
    if blocked:
        raise ControllerError(blocked)
    forget(session, slot)  # used up, whatever happens next
    if now() - action.created > action.ttl:
        raise ControllerError(action.expired_message())
    stale = action.stale_message(request)
    if stale:
        raise ControllerError(stale)
    return action.execute(request)
