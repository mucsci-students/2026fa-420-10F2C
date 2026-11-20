"""
Tests for the Command pattern behind "describe first, confirm in the next message"
(gui/ai/pending.py, with PendingDelete in gui/ai/changes.py and PendingGeneration in
gui/ai/generation.py).

They use plain stand-ins for the session and the request, so no Django, solver or AI is involved. The
whole-chat behaviour (deleting a room, generating schedules) is covered by test_ai_changes.py,
test_ai_generation.py, test_ai_clarify.py and test_ai_chats.py, which this change does not edit.
"""

from types import SimpleNamespace

import pytest

from gui.ai import changes, generation, pending
from gui.ai.base import WAITING_ATTR, NoArgs
from gui.controllers.errors import ControllerError

SLOT = "ai_test_slot"
OTHER = "ai_test_other"


class Request:
    """A stand-in for one request (the token is remembered on it, like a Django request)."""


class Recorder(pending.PendingAction):
    """A concrete Command that records what happened to it."""

    ttl = 600.0

    def __init__(self, token="earlier", created=0.0, *, blocked=None, stale=None):
        self.label = "the thing"
        self.token = token
        self.created = created
        self.blocked = blocked
        self.stale = stale
        self.ran = 0

    def execute(self, request):
        self.ran += 1
        return "ran"

    def same_request_message(self):
        return "same request"

    def expired_message(self):
        return "expired"

    def blocked_message(self, request):
        return self.blocked

    def stale_message(self, request):
        return self.stale


def confirm(session, now=5.0, request=None):
    return pending.confirm(
        request or Request(),
        session,
        SLOT,
        now=lambda: now,
        nothing_waiting="nothing is waiting",
    )


# ---------------------------------------------------------------------- #
#  The Command interface and the slots
# ---------------------------------------------------------------------- #
def test_the_command_is_abstract():
    with pytest.raises(TypeError):
        vars(pending)[
            "PendingAction"
        ]()  # looked up by name: a direct call is flagged as abstract


def test_the_request_token_is_stable_for_one_request_and_differs_between_requests():
    first, second = Request(), Request()
    assert pending.request_token(first) == pending.request_token(first)
    assert pending.request_token(first) != pending.request_token(second)


def test_staging_remembers_a_command_and_current_returns_it():
    session = SimpleNamespace()
    assert pending.current(session, SLOT) is None
    command = Recorder()
    pending.stage(session, SLOT, command)
    assert pending.current(session, SLOT) is command
    assert getattr(session, SLOT) is command  # the slot is the session attribute


def test_staging_can_drop_another_kind_that_was_waiting():
    session = SimpleNamespace()
    other = Recorder()
    pending.stage(session, OTHER, other)
    pending.stage(session, SLOT, Recorder(), replaces=(OTHER,))
    assert pending.current(session, OTHER) is None
    assert pending.current(session, SLOT) is not None


def test_staging_leaves_other_kinds_alone_unless_asked():
    session = SimpleNamespace()
    other = Recorder()
    pending.stage(session, OTHER, other)
    pending.stage(session, SLOT, Recorder())
    assert pending.current(session, OTHER) is other


def test_take_hands_the_command_back_and_empties_the_slot():
    session = SimpleNamespace()
    command = Recorder()
    pending.stage(session, SLOT, command)
    assert pending.take(session, SLOT) is command
    assert pending.current(session, SLOT) is None
    assert pending.take(session, SLOT) is None


def test_forget_empties_every_slot_it_is_given_and_ignores_empty_ones():
    session = SimpleNamespace()
    pending.stage(session, SLOT, Recorder())
    pending.stage(session, OTHER, Recorder())
    pending.forget(session, SLOT, OTHER, "never_used")
    assert pending.current(session, SLOT) is None
    assert pending.current(session, OTHER) is None


# ---------------------------------------------------------------------- #
#  The one confirmation flow
# ---------------------------------------------------------------------- #
def test_confirming_with_nothing_waiting_says_what_the_caller_asked_it_to():
    with pytest.raises(ControllerError) as error:
        confirm(SimpleNamespace())
    assert error.value.message == "nothing is waiting"


def test_confirming_in_a_later_message_runs_the_command_once_and_uses_it_up():
    session, command = SimpleNamespace(), Recorder()
    pending.stage(session, SLOT, command)
    assert confirm(session) == "ran"
    assert command.ran == 1
    assert pending.current(session, SLOT) is None
    with pytest.raises(ControllerError):
        confirm(session)  # a second confirm finds nothing
    assert command.ran == 1


def test_confirming_in_the_same_message_is_refused_and_the_command_keeps_waiting():
    session, command = SimpleNamespace(), Recorder()
    request = Request()
    command.token = pending.request_token(request)
    pending.stage(session, SLOT, command)
    with pytest.raises(ControllerError) as error:
        confirm(session, request=request)
    assert error.value.message == "same request"
    assert command.ran == 0
    assert pending.current(session, SLOT) is command


def test_a_command_that_is_blocked_is_refused_and_keeps_waiting():
    session, command = SimpleNamespace(), Recorder(blocked="something else first")
    pending.stage(session, SLOT, command)
    with pytest.raises(ControllerError) as error:
        confirm(session)
    assert error.value.message == "something else first"
    assert command.ran == 0
    assert pending.current(session, SLOT) is command


def test_an_expired_command_is_refused_and_used_up():
    session, command = SimpleNamespace(), Recorder(created=0.0)
    pending.stage(session, SLOT, command)
    with pytest.raises(ControllerError) as error:
        confirm(session, now=command.ttl + 1)
    assert error.value.message == "expired"
    assert command.ran == 0
    assert pending.current(session, SLOT) is None


def test_a_command_exactly_at_its_limit_is_still_confirmable():
    session, command = SimpleNamespace(), Recorder(created=0.0)
    pending.stage(session, SLOT, command)
    assert confirm(session, now=command.ttl) == "ran"


def test_a_stale_command_is_refused_and_used_up():
    session, command = SimpleNamespace(), Recorder(stale="it changed")
    pending.stage(session, SLOT, command)
    with pytest.raises(ControllerError) as error:
        confirm(session)
    assert error.value.message == "it changed"
    assert command.ran == 0
    assert pending.current(session, SLOT) is None


def test_the_checks_run_in_order_same_request_then_blocked_then_expired_then_stale():
    request = Request()
    command = Recorder(blocked="blocked", stale="stale", created=0.0)
    command.token = pending.request_token(request)
    session = SimpleNamespace()
    pending.stage(session, SLOT, command)
    with pytest.raises(ControllerError) as error:
        confirm(session, now=command.ttl + 1, request=request)
    assert error.value.message == "same request"
    command.token = "earlier"
    with pytest.raises(ControllerError) as error:
        confirm(session, now=command.ttl + 1)
    assert error.value.message == "blocked"
    command.blocked = None
    with pytest.raises(ControllerError) as error:
        confirm(session, now=command.ttl + 1)
    assert error.value.message == "expired"
    pending.stage(session, SLOT, command)
    with pytest.raises(ControllerError) as error:
        confirm(session, now=1.0)
    assert error.value.message == "stale"


# ---------------------------------------------------------------------- #
#  PendingDelete (a concrete Command), through the real tools
# ---------------------------------------------------------------------- #
@pytest.fixture
def config_session(monkeypatch):
    """A session stand-in that both tool modules read, with a configuration version of 3."""
    session = SimpleNamespace(
        config=object(),
        history=SimpleNamespace(version=3),
        locks=None,
        generation_job=None,
    )
    monkeypatch.setattr(changes, "get_session", lambda request: session)
    monkeypatch.setattr(generation, "get_session", lambda request: session)
    return session


def staged_delete(session, version=3, run=None, token="earlier"):
    command = changes.PendingDelete(
        "room 'Roddy 136'",
        token,
        changes._now(),
        version,
        "Deleted room 'Roddy 136'.",
        run or (lambda request: ["Also removed it from 2 courses."]),
    )
    pending.stage(session, changes._PENDING_ATTR, command)
    return command


def test_a_described_delete_runs_when_confirmed_later(config_session):
    ran = []
    staged_delete(config_session, run=lambda request: ran.append(request) or ["a note"])
    message = changes.confirm_delete(Request(), NoArgs())
    assert message.startswith("Deleted room 'Roddy 136'.")
    assert "a note" in message and changes.UNDO_HINT in message
    assert len(ran) == 1
    assert pending.current(config_session, changes._PENDING_ATTR) is None


def test_confirming_a_delete_in_the_same_message_changes_nothing(config_session):
    request = Request()
    ran = []
    staged_delete(
        config_session,
        token=pending.request_token(request),
        run=lambda req: ran.append(req) or [],
    )
    with pytest.raises(ControllerError) as error:
        changes.confirm_delete(request, NoArgs())
    assert "separate message" in error.value.message and "Nothing was deleted" in (
        error.value.message
    )
    assert ran == []
    assert pending.current(config_session, changes._PENDING_ATTR) is not None


def test_a_delete_is_refused_when_the_configuration_changed_since(config_session):
    ran = []
    staged_delete(config_session, version=2, run=lambda req: ran.append(req) or [])
    with pytest.raises(ControllerError) as error:
        changes.confirm_delete(Request(), NoArgs())
    assert "changed after I described deleting room 'Roddy 136'" in error.value.message
    assert ran == []
    assert pending.current(config_session, changes._PENDING_ATTR) is None


def test_a_delete_described_too_long_ago_is_refused(config_session, monkeypatch):
    staged_delete(config_session)
    monkeypatch.setattr(
        changes, "_now", lambda: changes.time.monotonic() + changes.PENDING_SECONDS + 5
    )
    with pytest.raises(ControllerError) as error:
        changes.confirm_delete(Request(), NoArgs())
    assert "described too long ago" in error.value.message


def test_confirming_a_delete_with_nothing_waiting_says_so(config_session):
    with pytest.raises(ControllerError) as error:
        changes.confirm_delete(Request(), NoArgs())
    assert "nothing waiting to be deleted" in error.value.message.lower()


def test_cancelling_a_delete_forgets_it(config_session):
    staged_delete(config_session)
    assert changes.cancel_delete(Request(), NoArgs()) == (
        "Cancelled. Room 'Roddy 136' was not deleted."
    )
    assert pending.current(config_session, changes._PENDING_ATTR) is None
    assert changes.cancel_delete(Request(), NoArgs()) == (
        "Nothing was waiting to be deleted."
    )


# ---------------------------------------------------------------------- #
#  PendingGeneration (a concrete Command), through the real tools
# ---------------------------------------------------------------------- #
def staged_plan(session, token="earlier"):
    plan = generation.PendingGeneration(
        limit=5,
        flags=("pack_rooms",),
        token=token,
        created=generation._now(),
        version=session.history.version,
        config=session.config,
        locks_version=0,
    )
    pending.stage(
        session, generation._PLAN_ATTR, plan, replaces=(changes._PENDING_ATTR,)
    )
    return plan


@pytest.fixture
def solver(monkeypatch):
    """No validation, no solver: record what would have been started and what is reported."""
    started = []
    monkeypatch.setattr(generation, "_require_valid", lambda request, refusal: None)
    monkeypatch.setattr(
        generation.schedule_controller, "schedule_count", lambda request: 0
    )
    monkeypatch.setattr(
        generation.schedule_controller,
        "start_generation",
        lambda request, **kwargs: started.append(kwargs),
    )
    monkeypatch.setattr(
        generation, "_report", lambda request, before, limit: f"reported {limit}"
    )
    return started


def test_reviewed_settings_start_the_run_when_confirmed_later(config_session, solver):
    staged_plan(config_session)
    assert generation.confirm_schedule_generation(Request(), NoArgs()) == "reported 5"
    assert solver == [{"limit_override": 5, "optimizer_overrides": ["pack_rooms"]}]
    assert pending.current(config_session, generation._PLAN_ATTR) is None


def test_confirming_generation_in_the_same_message_starts_nothing(
    config_session, solver
):
    request = Request()
    staged_plan(config_session, token=pending.request_token(request))
    with pytest.raises(ControllerError) as error:
        generation.confirm_schedule_generation(request, NoArgs())
    assert "separate message" in error.value.message and "Nothing was started" in (
        error.value.message
    )
    assert solver == []
    assert pending.current(config_session, generation._PLAN_ATTR) is not None


def test_a_waiting_delete_blocks_generation_and_is_left_untouched(
    config_session, solver
):
    plan = staged_plan(config_session)
    delete = staged_delete(config_session)  # described AFTER the review: both wait
    with pytest.raises(ControllerError) as error:
        generation.confirm_schedule_generation(Request(), NoArgs())
    assert "A delete is waiting for your answer too" in error.value.message
    assert solver == []
    assert pending.current(config_session, generation._PLAN_ATTR) is plan
    assert pending.current(config_session, changes._PENDING_ATTR) is delete


def test_reviewing_the_settings_drops_a_described_delete(config_session):
    staged_delete(config_session)
    staged_plan(
        config_session
    )  # stage() with replaces=(the delete slot,), like prepare does
    assert pending.current(config_session, changes._PENDING_ATTR) is None
    assert pending.current(config_session, generation._PLAN_ATTR) is not None


def test_with_only_a_delete_waiting_generation_points_to_the_delete(
    config_session, solver
):
    staged_delete(config_session)
    with pytest.raises(ControllerError) as error:
        generation.confirm_schedule_generation(Request(), NoArgs())
    assert 'reply "confirm" to delete it' in error.value.message


def test_with_nothing_waiting_generation_asks_to_review_first(config_session, solver):
    with pytest.raises(ControllerError) as error:
        generation.confirm_schedule_generation(Request(), NoArgs())
    assert "No generation settings are waiting" in error.value.message


@pytest.mark.parametrize(
    "change, text",
    [
        (lambda session: setattr(session, "config", object()), "configuration changed"),
        (
            lambda session: setattr(session.history, "version", 99),
            "configuration changed",
        ),
        (
            lambda session: setattr(session, "locks", SimpleNamespace(version=4)),
            "locked sections changed",
        ),
    ],
)
def test_settings_are_refused_when_the_configuration_or_the_locks_changed(
    config_session, solver, change, text
):
    staged_plan(config_session)
    change(config_session)
    with pytest.raises(ControllerError) as error:
        generation.confirm_schedule_generation(Request(), NoArgs())
    assert (
        text in error.value.message
        and "Ask me to generate again" in error.value.message
    )
    assert solver == []
    assert pending.current(config_session, generation._PLAN_ATTR) is None  # used up


def test_settings_shown_too_long_ago_are_refused(config_session, solver, monkeypatch):
    staged_plan(config_session)
    monkeypatch.setattr(
        generation,
        "_now",
        lambda: generation.time.monotonic() + generation.PLAN_SECONDS + 5,
    )
    with pytest.raises(ControllerError) as error:
        generation.confirm_schedule_generation(Request(), NoArgs())
    assert "shown too long ago" in error.value.message
    assert solver == []


def test_confirming_generation_without_a_configuration_offers_both_ways_forward(
    config_session, monkeypatch
):
    config_session.config = None
    monkeypatch.setattr(generation, "_saved_names", lambda request: [])
    reply = generation.confirm_schedule_generation(Request(), NoArgs())
    assert "No configuration is loaded" in reply


def test_cancelling_the_review_forgets_it(config_session):
    staged_plan(config_session)
    reply = generation.cancel_schedule_generation(Request(), NoArgs())
    assert reply.startswith("Cancelled. No schedules were generated")
    assert pending.current(config_session, generation._PLAN_ATTR) is None
    assert generation.cancel_schedule_generation(Request(), NoArgs()) == (
        "Nothing was waiting to be generated."
    )


def test_a_fresh_review_is_reused_and_a_stale_one_is_not(config_session):
    plan = staged_plan(config_session)
    assert generation._fresh_plan(config_session) is plan
    config_session.history.version = 9
    assert generation._fresh_plan(config_session) is None


def test_a_new_chat_forgets_everything_that_was_waiting(config_session):
    staged_plan(config_session)
    staged_delete(config_session)
    setattr(config_session, WAITING_ATTR, object())
    generation._forget_waiting(config_session)
    assert pending.current(config_session, generation._PLAN_ATTR) is None
    assert pending.current(config_session, changes._PENDING_ATTR) is None
    assert getattr(config_session, WAITING_ATTR) is None


def test_both_commands_are_pending_actions():
    assert issubclass(changes.PendingDelete, pending.PendingAction)
    assert issubclass(generation.PendingGeneration, pending.PendingAction)
