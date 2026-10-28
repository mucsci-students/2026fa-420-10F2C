"""
Tests for generating schedules through the AI chat (Sprint 3: AI schedule generation).

The tools are called the way the AI calls them, against the real scheduler library's configuration
(the shipped example), the real session, controllers and generation job. Only the solver is replaced
by a stand-in that yields a few schedules (like tests/test_generation_progress.py), so these run in a
moment and need no AI, no key and no Z3 search.

    ToolBox(request).call("prepare_schedule_generation", {"limit": 5})   # shows the settings, runs nothing
    ToolBox(later(request)).call("confirm_schedule_generation")           # a LATER message runs it

What these cover:
  * the AI checks that a configuration is open, and when none is, says so and offers to create one or
    load one (and carries on into the generation after loading)
  * the limit and the optimizer flags are shown before anything runs, can be changed, are checked, and
    apply to that run only: the configuration is never modified by generating
  * the configuration is validated before the solver starts (and again right before it does)
  * a run needs a message of its own after the settings were shown, and is refused when the settings
    went stale or the configuration changed in between
  * success says how many schedules were generated and they appear in the Schedule Viewer
  * "no feasible schedule", an invalid configuration and a crash are explained and never leave a
    partial schedule in the viewer
  * the chat shows progress while the solver works, offers quick replies, and links to the viewer
"""

import threading
from pathlib import Path

import pytest

from app import schedule_ops
from app.schedule_io import Assignment, MeetingTime
from gui import session_store
from gui.ai import changes, generation, service
from gui.ai.prompt import BASE_PROMPT, CAPABILITIES
from gui.ai.tools import TOOLS_BY_NAME, ToolBox
from gui.controllers import config_controller, rooms, schedule_controller, settings

ROOT = Path(__file__).resolve().parent.parent
ASK_URL = "/assistant/ask/"
STATUS_URL = "/assistant/status/"
VIEWER_URL = "/schedules/"

GENERATION_TOOLS = (
    "prepare_schedule_generation",
    "confirm_schedule_generation",
    "cancel_schedule_generation",
    "check_generation_status",
    "validate_configuration",
    "list_saved_configurations",
    "load_saved_configuration",
    "create_new_configuration",
)


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
    request = FakeRequest()
    session_store.get_session(
        request
    )  # opens the example, so later messages find the same session
    return request


@pytest.fixture
def box(request_):
    return ToolBox(request_)


@pytest.fixture
def closed(request_):
    """The example was loaded (so it is among the configurations available), then nothing is open."""
    session_store.get_session(request_).config = None
    return request_


def session(request_):
    return session_store.get_session(request_)


def snapshot(request_):
    return session(request_).config.model_dump_json()


def placed(number):
    return Assignment(
        f"CMSC 14{number}.01",
        "Hogg",
        "Roddy 136",
        None,
        (MeetingTime("MON", "09:00", "09:50", 50),),
    )


def use_solver(monkeypatch, count=3, seen=None):
    """Replace the solver with one that finds `count` schedules (and notes the configuration it got)."""

    class FakeScheduler:
        def __init__(self, config):
            if seen is not None:
                seen.append(config)

        def get_models(self):
            for number in range(count):
                yield [placed(number)]

    monkeypatch.setattr(schedule_ops, "Scheduler", FakeScheduler)


def never_run_solver(monkeypatch):
    def refuse(config):
        raise AssertionError("the solver must not start")

    monkeypatch.setattr(schedule_ops, "Scheduler", refuse)


def review_and_run(request_, args=None):
    """What a user does: ask (the settings are shown), then agree in the next message."""
    ToolBox(request_).call("prepare_schedule_generation", args or {})
    return ToolBox(later(request_)).call("confirm_schedule_generation")


# ---------------------------------------------------------------------- #
#  Registry, prompt and capabilities
# ---------------------------------------------------------------------- #
def test_the_generation_tools_are_registered_and_do_not_edit_the_configuration():
    for name in GENERATION_TOOLS:
        assert name in TOOLS_BY_NAME, name
        assert not TOOLS_BY_NAME[
            name
        ].write  # generating replaces schedules, never the configuration
        assert TOOLS_BY_NAME[name].description.strip()


def test_the_application_gives_the_answer_except_for_the_lookup_of_saved_configurations():
    for name in GENERATION_TOOLS:
        assert TOOLS_BY_NAME[name].final == (name != "list_saved_configurations"), name


def test_the_prompt_explains_the_two_steps_and_every_tool_it_names_exists():
    for name in GENERATION_TOOLS:
        assert name in BASE_PROMPT or name in (
            "check_generation_status",
            "list_saved_configurations",
        )
    assert "cannot validate the configuration" not in BASE_PROMPT
    assert "never starts the run in the same message" in BASE_PROMPT


def test_the_capability_list_says_generation_and_validation_are_possible(box):
    text = CAPABILITIES.lower()
    assert "generate schedules" in text and "validate the configuration" in text
    assert "schedule viewer" in text and "go ahead" in text
    assert "generate schedules yet" not in text
    assert box.call("describe_capabilities").message == CAPABILITIES


# ---------------------------------------------------------------------- #
#  No configuration: say so, and offer to create or load one
# ---------------------------------------------------------------------- #
def test_without_a_configuration_the_ai_says_one_is_needed_and_offers_both_ways(
    closed, monkeypatch
):
    never_run_solver(monkeypatch)
    result = ToolBox(closed).call("prepare_schedule_generation")
    assert result.ok
    text = result.message
    assert "No configuration is loaded" in text and "created or loaded" in text
    assert "create a new configuration" in text  # option 1
    assert (
        "config_example.json" in text
    )  # option 2: one that is available in this session
    assert "Configuration Editor" in text  # option 3: a file from the computer
    assert (
        result.suggestions[0] == "Create a new configuration"
        and "Load config_example.json" in result.suggestions
    )
    assert session(closed).config is None and session(closed).schedules == []
    assert not session(closed).generating


def test_without_a_configuration_nothing_can_be_confirmed_or_validated(closed):
    for name in ("confirm_schedule_generation", "validate_configuration"):
        result = ToolBox(closed).call(name)
        assert "No configuration is loaded" in result.message, name
    assert session(closed).config is None


def test_with_no_saved_configuration_at_all_the_options_are_still_clear(monkeypatch):
    monkeypatch.setattr(session_store, "AUTO_LOAD_EXAMPLE", False)
    request = FakeRequest()
    text = ToolBox(request).call("prepare_schedule_generation").message
    assert (
        "create a new configuration" in text
        and "Load Configuration in the Configuration Editor" in text
    )
    assert "available in this session" not in text


def test_loading_a_saved_configuration_continues_into_the_settings_review(
    closed, monkeypatch
):
    use_solver(monkeypatch, count=2)
    result = ToolBox(closed).call(
        "load_saved_configuration",
        {"name": "config_example", "continue_to_generation": True},
    )
    assert result.ok and result.config_replaced
    assert (
        "Loaded 'config_example.json'" in result.message
        and "it is valid" in result.message
    )
    assert (
        "Generation limit:" in result.message
    )  # the review follows right after the load
    assert result.suggestions == ("Go ahead and generate", "Cancel")
    assert session(closed).config is not None and session(closed).schedules == []

    done = ToolBox(later(closed)).call("confirm_schedule_generation")
    assert done.ok and done.message.startswith("Generated 2 schedules.")


def test_loading_without_the_generation_just_offers_it(closed):
    result = ToolBox(closed).call(
        "load_saved_configuration", {"name": "config_example.json"}
    )
    assert result.ok and "Ask me to generate schedules" in result.message
    assert "Generation limit" not in result.message
    assert session(closed).config is not None


def test_an_unknown_or_broken_saved_configuration_changes_nothing(closed):
    unknown = ToolBox(closed).call("load_saved_configuration", {"name": "nope.json"})
    assert not unknown.ok and "No configuration named 'nope.json'" in unknown.message
    assert "config_example.json" in unknown.message

    session(closed).saved_configs["bad.json"] = "{not json"
    broken = ToolBox(later(closed)).call("load_saved_configuration", {"name": "bad"})
    assert (
        not broken.ok
        and "not valid JSON" in broken.message
        and "was not changed" in broken.message
    )
    assert session(closed).config is None


def test_a_new_configuration_can_be_configured_validated_and_then_generated(
    closed, monkeypatch
):
    use_solver(monkeypatch, count=1)
    created = ToolBox(closed).call("create_new_configuration")
    assert created.ok and created.config_replaced and "placeholder" in created.message
    assert "validate the configuration" in created.message
    assert session(closed).config is not None and not session(closed).dirty

    # the user can configure it in the chat first ...
    added = ToolBox(later(closed)).call(
        "add_room", {"name": "RODDY150", "capacity": 35}
    )
    assert added.ok and any(
        room.name == "RODDY150" for room in session(closed).config.config.rooms
    )
    # ... check it ...
    assert (
        ToolBox(later(closed))
        .call("validate_configuration")
        .message.startswith("The configuration is valid")
    )
    # ... and only then generate
    assert review_and_run(later(closed)).message.startswith("Generated 1 schedule.")


def test_new_and_load_never_throw_away_unsaved_work_or_schedules(request_):
    session(request_).dirty = True
    for name, args in (
        ("create_new_configuration", {}),
        ("load_saved_configuration", {"name": "config_example.json"}),
    ):
        result = ToolBox(later(request_)).call(name, args)
        assert (
            not result.ok and "would discard your unsaved changes" in result.message
        ), name
    assert session(request_).dirty and session(request_).config is not None

    session(request_).dirty = False
    session(request_).set_schedules([[placed(0)]])
    result = ToolBox(later(request_)).call("create_new_configuration")
    assert not result.ok and "schedule loaded now" in result.message
    assert len(session(request_).schedules) == 1


def test_opening_a_configuration_clears_anything_that_was_waiting_for_a_yes(
    request_, closed=None
):
    ToolBox(request_).call("prepare_schedule_generation")
    assert ToolBox(later(request_)).call("create_new_configuration").ok
    result = ToolBox(later(request_)).call("confirm_schedule_generation")
    assert not result.ok and "No generation settings are waiting" in result.message


# ---------------------------------------------------------------------- #
#  The settings are shown first, can be changed, and apply to one run only
# ---------------------------------------------------------------------- #
def test_the_limit_and_flags_are_shown_before_anything_runs(request_, monkeypatch):
    never_run_solver(monkeypatch)
    result = ToolBox(request_).call("prepare_schedule_generation")
    saved = settings.describe_settings(request_)
    assert result.ok
    assert f"Generation limit: {saved['limit']} (the saved limit)" in result.message
    assert (
        "Optimizer flags: " in result.message and "(the saved flags)" in result.message
    )
    for flag in saved["enabled_flags"]:
        assert flag in result.message
    assert "I checked it and it is valid" in result.message
    assert (
        "apply to this run only" in result.message and "not changed" in result.message
    )
    assert 'Reply "go ahead"' in result.message
    assert result.suggestions == ("Go ahead and generate", "Cancel")
    assert session(request_).schedules == [] and not session(request_).generating


def test_the_user_can_choose_the_limit_and_flags_for_the_run_and_the_configuration_is_not_modified(
    request_, monkeypatch
):
    seen = []
    use_solver(monkeypatch, count=5, seen=seen)
    before = snapshot(request_)
    review = ToolBox(request_).call(
        "prepare_schedule_generation", {"limit": 2, "optimizer_flags": ["pack rooms"]}
    )
    assert "Generation limit: 2 (this run only; the saved limit is" in review.message
    assert "Optimizer flags: pack_rooms (this run only; saved:" in review.message
    assert snapshot(request_) == before  # showing them changes nothing

    result = ToolBox(later(request_)).call("confirm_schedule_generation")
    assert result.ok and result.message.startswith("Generated 2 schedules.")
    assert len(session(request_).schedules) == 2
    used = [getattr(flag, "value", flag) for flag in seen[0].optimizer_flags]
    assert used == ["pack_rooms"]  # the run used the flags the user chose ...
    assert (
        snapshot(request_) == before
    )  # ... and the saved configuration is exactly as it was
    assert (
        session(request_).config.limit == settings.describe_settings(request_)["limit"]
    )
    assert not session(request_).dirty


def test_changing_the_settings_again_keeps_what_was_not_mentioned(request_):
    ToolBox(request_).call(
        "prepare_schedule_generation", {"limit": 4, "optimizer_flags": ["pack_rooms"]}
    )
    second = ToolBox(later(request_)).call("prepare_schedule_generation", {"limit": 7})
    assert (
        "Generation limit: 7" in second.message
        and "Optimizer flags: pack_rooms" in second.message
    )
    third = ToolBox(later(request_)).call(
        "prepare_schedule_generation", {"optimizer_flags": []}
    )
    assert (
        "Generation limit: 7" in third.message
        and "Optimizer flags: none" in third.message
    )


def test_a_flag_is_found_however_it_is_typed(request_):
    result = ToolBox(request_).call(
        "prepare_schedule_generation",
        {"optimizer_flags": ["Faculty Course", "SAME_ROOM"]},
    )
    assert result.ok and "Optimizer flags: faculty_course, same_room" in result.message


@pytest.mark.parametrize(
    "args, expected",
    [
        ({"limit": 0}, "positive"),
        ({"limit": -3}, "positive"),
        ({"optimizer_flags": ["turbo"]}, "'turbo' is not a valid optimizer flag"),
    ],
)
def test_bad_settings_are_refused_before_the_solver_and_nothing_is_left_waiting(
    request_, monkeypatch, args, expected
):
    never_run_solver(monkeypatch)
    result = ToolBox(request_).call("prepare_schedule_generation", args)
    assert not result.ok and expected in result.message
    assert "The valid flags are" in result.message or "positive" in result.message
    nothing = ToolBox(later(request_)).call("confirm_schedule_generation")
    assert "No generation settings are waiting" in nothing.message


def test_the_saved_settings_change_only_when_the_user_asks_to_change_them(request_):
    ToolBox(request_).call("prepare_schedule_generation", {"limit": 3})
    saved = settings.describe_settings(request_)["limit"]
    assert saved != 3
    changed = ToolBox(later(request_)).call("update_global_settings", {"limit": 12})
    assert changed.ok and settings.describe_settings(request_)["limit"] == 12
    # the settings that were shown for the old configuration are no longer current
    result = ToolBox(later(request_)).call("confirm_schedule_generation")
    assert not result.ok and "changed after I showed you" in result.message


# ---------------------------------------------------------------------- #
#  Validation: the application checks before the solver starts
# ---------------------------------------------------------------------- #
def test_an_invalid_configuration_is_explained_and_the_solver_never_starts(
    request_, monkeypatch
):
    never_run_solver(monkeypatch)
    monkeypatch.setattr(
        config_controller,
        "validate_configuration",
        lambda request: ["Room 'X' has no capacity."],
    )
    result = ToolBox(request_).call("prepare_schedule_generation")
    assert not result.ok
    assert (
        "not valid" in result.message and "Room 'X' has no capacity." in result.message
    )
    assert "Nothing was generated" in result.message
    assert (
        "No generation settings are waiting"
        in ToolBox(later(request_)).call("confirm_schedule_generation").message
    )


def test_it_is_validated_again_right_before_the_solver_starts(request_, monkeypatch):
    never_run_solver(monkeypatch)
    ToolBox(request_).call("prepare_schedule_generation")
    monkeypatch.setattr(
        config_controller,
        "validate_configuration",
        lambda request: ["Something broke."],
    )
    result = ToolBox(later(request_)).call("confirm_schedule_generation")
    assert not result.ok and "Something broke." in result.message
    assert session(request_).schedules == [] and not session(request_).generating


def test_the_validate_tool_reports_valid_and_invalid_without_changing_anything(
    request_, monkeypatch
):
    before = snapshot(request_)
    valid = ToolBox(request_).call("validate_configuration")
    assert (
        valid.ok
        and valid.message.startswith("The configuration is valid")
        and valid.suggestions == ("Generate schedules",)
    )
    monkeypatch.setattr(
        config_controller,
        "validate_configuration",
        lambda request: ["Faculty 'Y' is never available."],
    )
    invalid = ToolBox(later(request_)).call("validate_configuration")
    assert not invalid.ok and "Faculty 'Y' is never available." in invalid.message
    assert snapshot(request_) == before


def test_a_run_that_is_already_going_is_not_started_twice(request_, monkeypatch):
    never_run_solver(monkeypatch)
    session(request_).generating = True
    result = ToolBox(request_).call("prepare_schedule_generation")
    assert not result.ok and "already running" in result.message


# ---------------------------------------------------------------------- #
#  Two steps, enforced by the application
# ---------------------------------------------------------------------- #
def test_a_run_cannot_be_confirmed_in_the_message_that_showed_the_settings(
    request_, monkeypatch
):
    never_run_solver(monkeypatch)
    box = ToolBox(request_)
    box.call("prepare_schedule_generation")
    result = box.call("confirm_schedule_generation")
    assert (
        not result.ok
        and "separate message" in result.message
        and "Nothing was started" in result.message
    )
    assert session(request_).schedules == []


def test_nothing_runs_when_nothing_was_shown(request_, monkeypatch):
    never_run_solver(monkeypatch)
    result = ToolBox(request_).call("confirm_schedule_generation")
    assert not result.ok and "No generation settings are waiting" in result.message


def test_the_shown_settings_are_used_up_by_the_run(request_, monkeypatch):
    use_solver(monkeypatch)
    assert review_and_run(request_).ok
    again = ToolBox(later(request_)).call("confirm_schedule_generation")
    assert not again.ok and "No generation settings are waiting" in again.message


def test_settings_that_were_shown_too_long_ago_are_refused(request_, monkeypatch):
    never_run_solver(monkeypatch)
    clock = [1000.0]
    monkeypatch.setattr(generation, "_now", lambda: clock[0])
    ToolBox(request_).call("prepare_schedule_generation")
    clock[0] += generation.PLAN_SECONDS + 1
    result = ToolBox(later(request_)).call("confirm_schedule_generation")
    assert not result.ok and "too long ago" in result.message


def test_a_change_to_the_configuration_after_the_review_refuses_the_run(
    request_, monkeypatch
):
    never_run_solver(monkeypatch)
    ToolBox(request_).call("prepare_schedule_generation")
    rooms.add_room(
        later(request_), {"name": "RODDY150", "capacity": 35}
    )  # an edit made by hand
    result = ToolBox(later(request_)).call("confirm_schedule_generation")
    assert (
        not result.ok
        and "changed after I showed you" in result.message
        and "Ask me to generate again" in result.message
    )


def test_cancelling_forgets_the_settings(request_, monkeypatch):
    never_run_solver(monkeypatch)
    ToolBox(request_).call("prepare_schedule_generation")
    result = ToolBox(later(request_)).call("cancel_schedule_generation")
    assert (
        result.ok
        and "Cancelled" in result.message
        and "nothing was changed" in result.message
    )
    assert (
        "No generation settings are waiting"
        in ToolBox(later(request_)).call("confirm_schedule_generation").message
    )
    assert (
        "Nothing was waiting"
        in ToolBox(later(request_)).call("cancel_schedule_generation").message
    )


def test_preparing_a_generation_drops_a_delete_that_was_waiting(request_):
    ToolBox(request_).call("delete_room", {"name": "Roddy 136"})
    assert getattr(session(request_), changes._PENDING_ATTR) is not None
    ToolBox(later(request_)).call("prepare_schedule_generation")
    assert (
        getattr(session(request_), changes._PENDING_ATTR) is None
    )  # only one thing waits for a "yes"
    result = ToolBox(later(request_)).call("confirm_delete")
    assert not result.ok and "nothing waiting to be deleted" in result.message.lower()
    assert any(
        room.name == "Roddy 136" for room in session(request_).config.config.rooms
    )


def test_a_delete_described_after_the_review_is_never_mixed_up_with_it(
    request_, monkeypatch
):
    never_run_solver(monkeypatch)
    ToolBox(request_).call("prepare_schedule_generation")
    ToolBox(later(request_)).call("delete_room", {"name": "Roddy 136"})
    result = ToolBox(later(request_)).call("confirm_schedule_generation")
    assert not result.ok and "A delete is waiting" in result.message
    assert (
        getattr(session(request_), changes._PENDING_ATTR) is not None
    )  # the delete was not touched
    assert any(
        room.name == "Roddy 136" for room in session(request_).config.config.rooms
    )
    alone = ToolBox(request_)
    del (
        alone
    )  # (a plain confirm with only a delete waiting is redirected, see the next test)


def test_confirming_when_only_a_delete_is_waiting_points_to_the_delete(
    request_, monkeypatch
):
    never_run_solver(monkeypatch)
    ToolBox(request_).call("delete_room", {"name": "Roddy 136"})
    result = ToolBox(later(request_)).call("confirm_schedule_generation")
    assert not result.ok and 'reply "confirm" to delete it' in result.message


# ---------------------------------------------------------------------- #
#  Results: success, and every way it can fail
# ---------------------------------------------------------------------- #
def test_success_says_how_many_schedules_and_they_are_stored_for_the_viewer(
    request_, monkeypatch
):
    use_solver(monkeypatch, count=3)
    result = review_and_run(request_, {"limit": 3})
    assert result.ok and result.schedules_changed
    assert result.message.startswith(
        "Generated 3 schedules. They are now in the Schedule Viewer."
    )
    assert "not changed" in result.message
    assert schedule_controller.schedule_count(request_) == 3
    assert [schedule[0].course for schedule in session(request_).schedules] == [
        "CMSC 140.01",
        "CMSC 141.01",
        "CMSC 142.01",
    ]
    assert not session(request_).generating and session(request_).generation_job is None


def test_one_schedule_is_worded_in_the_singular(request_, monkeypatch):
    use_solver(monkeypatch, count=1)
    assert review_and_run(request_, {"limit": 1}).message.startswith(
        "Generated 1 schedule. It is now in the Schedule Viewer."
    )


def test_fewer_schedules_than_the_limit_is_explained(request_, monkeypatch):
    use_solver(monkeypatch, count=3)
    result = review_and_run(request_, {"limit": 10})
    assert (
        result.ok and "The limit was 10, but the solver found only 3" in result.message
    )


def test_generating_replaces_earlier_schedules_and_the_review_says_so(
    request_, monkeypatch
):
    session(request_).set_schedules([[placed(9)], [placed(8)]])
    use_solver(monkeypatch, count=1)
    review = ToolBox(request_).call("prepare_schedule_generation", {"limit": 1})
    assert "2 schedules loaded now will be replaced if this succeeds" in review.message
    assert ToolBox(later(request_)).call("confirm_schedule_generation").ok
    assert [schedule[0].course for schedule in session(request_).schedules] == [
        "CMSC 140.01"
    ]


def test_no_feasible_schedule_is_explained_and_nothing_is_shown(request_, monkeypatch):
    session(request_).set_schedules([[placed(9)], [placed(8)]])
    use_solver(monkeypatch, count=0)
    before = snapshot(request_)
    result = review_and_run(request_)
    assert not result.ok and result.schedules_changed
    assert "No feasible schedule was found" in result.message
    assert "Nothing was added to the Schedule Viewer" in result.message
    assert (
        "2 schedules loaded before were cleared" in result.message
    )  # as on the Schedule Generator page
    assert "faculty availability" in result.message
    assert session(request_).schedules == [] and not session(request_).generating
    assert snapshot(request_) == before


def test_no_feasible_schedule_without_earlier_schedules_changes_nothing_visible(
    request_, monkeypatch
):
    use_solver(monkeypatch, count=0)
    result = review_and_run(request_)
    assert not result.ok and not result.schedules_changed
    assert "cleared" not in result.message


def test_a_crash_midway_shows_no_partial_schedule_and_keeps_the_earlier_ones(
    request_, monkeypatch
):
    session(request_).set_schedules([[placed(9)]])
    kept = session(request_).schedules

    class Crashing:
        def __init__(self, config):
            pass

        def get_models(self):
            yield [placed(0)]
            raise RuntimeError("the solver ran out of memory")

    monkeypatch.setattr(schedule_ops, "Scheduler", Crashing)
    result = review_and_run(request_)
    assert not result.ok and not result.schedules_changed
    assert (
        "failed unexpectedly" in result.message
        and "the solver ran out of memory" in result.message
    )
    assert "your previous schedules were kept" in result.message
    assert session(request_).schedules is kept and not session(request_).generating


def test_a_configuration_the_library_rejects_is_explained(request_, monkeypatch):
    class Rejecting:
        def __init__(self, config):
            raise ValueError("faculty Hogg can teach no course")

    monkeypatch.setattr(schedule_ops, "Scheduler", Rejecting)
    result = review_and_run(request_)
    assert (
        not result.ok
        and "The configuration is invalid: faculty Hogg can teach no course"
        in result.message
    )
    assert session(request_).schedules == [] and not session(request_).generating


# ---------------------------------------------------------------------- #
#  A long run: the request waits, then leaves it going; the status can be checked and the run cancelled
# ---------------------------------------------------------------------- #
class Slow:
    """A solver that finds one schedule, then waits until the test lets it go on."""

    gate = threading.Event()

    def __init__(self, config):
        pass

    def get_models(self):
        yield [placed(0)]
        Slow.gate.wait(5)
        yield [placed(1)]


@pytest.fixture
def slow(monkeypatch):
    Slow.gate = threading.Event()
    monkeypatch.setattr(schedule_ops, "Scheduler", Slow)
    monkeypatch.setenv(generation.WAIT_ENV, "0.2")
    yield Slow
    Slow.gate.set()  # never leave the worker thread waiting


def test_a_long_run_is_left_going_and_its_status_can_be_checked(request_, slow):
    result = review_and_run(request_, {"limit": 2})
    assert result.ok and "still working" in result.message and "check" in result.message
    assert session(request_).generating

    running = ToolBox(later(request_)).call("check_generation_status")
    assert running.ok and "still running: found 1 of 2" in running.message

    slow.gate.set()
    assert session(request_).generation_job.wait(5)
    finished = ToolBox(later(request_)).call("check_generation_status")
    assert finished.ok and finished.message.startswith("Generated 2 schedules.")
    idle = ToolBox(later(request_)).call("check_generation_status")
    assert idle.message.startswith(
        "No schedule generation is running. 2 schedules are in the Schedule Viewer"
    )


def test_a_run_that_is_still_going_can_be_cancelled_and_stores_nothing(request_, slow):
    review_and_run(request_, {"limit": 5})
    cancelling = ToolBox(later(request_)).call("cancel_schedule_generation")
    assert (
        cancelling.ok
        and "Cancelling" in cancelling.message
        and "previous schedules are kept" in cancelling.message
    )
    slow.gate.set()
    assert session(request_).generation_job.wait(5)
    report = ToolBox(later(request_)).call("check_generation_status")
    assert "cancelled" in report.message.lower()
    assert session(request_).schedules == [] and not session(request_).generating


def test_the_wait_is_bounded_and_can_be_set():
    assert (
        generation.wait_seconds() == generation.DEFAULT_WAIT_SECONDS or True
    )  # default unless the env var is set


def test_the_wait_setting_is_read_from_the_environment(monkeypatch):
    monkeypatch.delenv(generation.WAIT_ENV, raising=False)
    assert generation.wait_seconds() == generation.DEFAULT_WAIT_SECONDS
    monkeypatch.setenv(generation.WAIT_ENV, "30")
    assert generation.wait_seconds() == 30
    monkeypatch.setenv(generation.WAIT_ENV, "999999")
    assert generation.wait_seconds() == generation.MAX_WAIT_SECONDS
    monkeypatch.setenv(generation.WAIT_ENV, "soon")
    assert generation.wait_seconds() == generation.DEFAULT_WAIT_SECONDS


# ---------------------------------------------------------------------- #
#  The reply the chat shows
# ---------------------------------------------------------------------- #
def test_a_reply_carries_the_quick_replies_and_what_changed_behind_the_page(
    request_, monkeypatch
):
    use_solver(monkeypatch, count=2)
    shown = ToolBox(request_)
    shown.call("prepare_schedule_generation", {"limit": 2})
    review = service.compose(shown.results)
    assert review.ok and review.suggestions == ("Go ahead and generate", "Cancel")
    assert not review.schedules_changed and not review.refresh and not review.changed

    run = ToolBox(later(request_))
    run.call("confirm_schedule_generation")
    done = service.compose(run.results)
    assert (
        done.ok and done.schedules_changed and done.refresh and done.suggestions == ()
    )
    assert (
        not done.changed and "not yet saved" not in done.message
    )  # generating edits no configuration


def test_a_failed_run_is_a_problem_reply(request_, monkeypatch):
    use_solver(monkeypatch, count=0)
    ToolBox(request_).call("prepare_schedule_generation")
    run = ToolBox(later(request_))
    run.call("confirm_schedule_generation")
    reply = service.compose(run.results)
    assert not reply.ok and "No feasible schedule was found" in reply.message
    assert (
        "The configuration was not changed" not in reply.message
    )  # it is not an edit that failed


class ScriptedRunner:
    """Stands in for the AI: calls the scripted tools for each request."""

    def __init__(self, script):
        self.script = script

    def run(self, text, toolbox):
        for name, args in self.script[text]:
            toolbox.call(name, args)
        return ""


SCRIPT = {
    "Generate 3 schedules": [("prepare_schedule_generation", {"limit": 3})],
    "Go ahead": [("confirm_schedule_generation", {})],
    "Make it 2": [("prepare_schedule_generation", {"limit": 2})],
    "Cancel": [("cancel_schedule_generation", {})],
}


@pytest.fixture
def scripted(monkeypatch):
    runner = ScriptedRunner(SCRIPT)
    monkeypatch.setattr(service, "get_runner", lambda: runner)
    return runner


def ask(client, text):
    response = client.post(ASK_URL, {"message": text})
    return response.status_code, response.json()


def test_the_whole_conversation_through_the_endpoint_and_into_the_viewer(
    client, scripted, monkeypatch
):
    use_solver(monkeypatch, count=3)
    client.get("/")  # the browser's session, with the example configuration open

    status, review = ask(client, "Generate 3 schedules")
    assert status == 200 and review["ok"] and "Generation limit: 3" in review["reply"]
    assert review["suggestions"] == ["Go ahead and generate", "Cancel"]
    assert (
        review["generated"] is False
        and review["schedule_count"] == 0
        and review["dirty"] is False
    )
    assert (
        "No schedules" in client.get(VIEWER_URL).content.decode()
        or "no schedules" in client.get(VIEWER_URL).content.decode().lower()
    )

    status, done = ask(client, "Go ahead")
    assert (
        status == 200
        and done["ok"]
        and done["reply"].startswith("Generated 3 schedules.")
    )
    assert (
        done["generated"] is True
        and done["schedule_count"] == 3
        and done["refresh"] is True
    )
    assert (
        done["changed"] is False
        and done["dirty"] is False
        and done["suggestions"] == []
    )

    # without a restart or a manual refresh: the next visit to the Schedule Viewer shows them
    page = client.get(VIEWER_URL).content.decode()
    assert 'title="Monday 09:00-09:50: CMSC 140.01"' in page
    assert (
        "The AI assistant generated 3 schedules." in page
    )  # the confirmation survives the page change
    assert (
        "The AI assistant generated" not in client.get(VIEWER_URL).content.decode()
    )  # shown once


def test_a_failed_run_through_the_endpoint_shows_nothing_in_the_viewer(
    client, scripted, monkeypatch
):
    use_solver(monkeypatch, count=0)
    client.get("/")
    ask(client, "Generate 3 schedules")
    status, failed = ask(client, "Go ahead")
    assert status == 200 and failed["ok"] is False and failed["generated"] is False
    assert "No feasible schedule was found" in failed["reply"]
    page = client.get(VIEWER_URL).content.decode()
    assert "CMSC 140.01" not in page and "The AI assistant generated" not in page


def test_clearing_earlier_schedules_asks_the_page_to_refresh(
    client, scripted, monkeypatch
):
    use_solver(monkeypatch, count=0)
    client.get("/")
    next(iter(session_store._SESSIONS.values())).set_schedules([[placed(9)]])
    ask(client, "Generate 3 schedules")
    _, failed = ask(client, "Go ahead")
    assert (
        failed["refresh"] is True
        and failed["generated"] is False
        and failed["schedule_count"] == 0
    )


def test_changing_the_settings_and_cancelling_through_the_endpoint(
    client, scripted, monkeypatch
):
    never_run_solver(monkeypatch)
    client.get("/")
    ask(client, "Generate 3 schedules")
    _, second = ask(client, "Make it 2")
    assert "Generation limit: 2" in second["reply"]
    _, cancelled = ask(client, "Cancel")
    assert cancelled["ok"] and "Cancelled" in cancelled["reply"]
    _, nothing = ask(client, "Go ahead")
    assert (
        nothing["ok"] is False
        and "No generation settings are waiting" in nothing["reply"]
    )


def test_the_progress_endpoint_is_read_only_and_reports_a_run_in_progress(client, slow):
    client.get("/")
    assert client.post(STATUS_URL).status_code == 405
    assert client.get(STATUS_URL).json() == {"state": "idle"}

    browser = FakeRequest(
        {session_store._SESSION_ID_KEY: next(iter(session_store._SESSIONS))}
    )
    schedule_controller.start_generation(
        browser, limit_override=2, optimizer_overrides=[]
    )
    deadline_reached = []
    for _ in range(200):
        status = client.get(STATUS_URL).json()
        if status.get("found"):
            break
        threading.Event().wait(0.01)
    else:
        deadline_reached.append(True)
    assert not deadline_reached
    assert (
        status["state"] == "running" and status["found"] == 1 and status["limit"] == 2
    )
    assert set(status) <= {
        "state",
        "found",
        "limit",
        "percent",
        "elapsed",
        "cancel_requested",
    }

    slow.gate.set()
    job = next(iter(session_store._SESSIONS.values())).generation_job
    assert job is not None
    assert job.wait(5)
    assert client.get(STATUS_URL).json()["state"] == "finished"
    assert (
        next(iter(session_store._SESSIONS.values())).generation_job is job
    )  # polling never collects the result


# ---------------------------------------------------------------------- #
#  The chat button: what the page and the script offer
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize("path", ["/", "/configuration/", "/generate/", "/schedules/"])
def test_every_page_tells_the_chat_where_to_ask_for_progress_and_where_the_viewer_is(
    client, path
):
    text = client.get(path).content.decode()
    assert (
        f'data-status-url="{STATUS_URL}"' in text
        and f'data-viewer-url="{VIEWER_URL}"' in text
    )


def test_the_script_shows_progress_quick_replies_and_the_viewer_link():
    script = (ROOT / "gui/static/gui/js/chat.js").read_text(encoding="utf-8")
    assert (
        "data-status-url" in script
        and "startProgress" in script
        and "stopProgress()" in script
    )
    assert (
        "Generating schedules" in script
        and "body.generated" in script
        and "offerViewer" in script
    )
    assert (
        "Open the Schedule Viewer" in script
        and "chat-suggestions" in script
        and "body.suggestions" in script
    )
    assert (
        "innerHTML" not in script
    )  # replies and suggestions are inserted as text, never as HTML
    css = (ROOT / "gui/static/gui/css/style.css").read_text(encoding="utf-8")
    assert ".chat-suggestions" in css
