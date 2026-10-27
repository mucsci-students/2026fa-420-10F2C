"""
The assistant understands people better (Sprint 3 follow-up): part of a name is enough, a change can be
taken back with "put it back", a failed run says what is probably wrong, and one message can ask for
several things.

The tools run for real on the shipped example configuration; only the solver is replaced.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from app import schedule_ops
from app.schedule_io import Assignment, MeetingTime
from gui import session_store
from gui.ai import diagnose, service, undo
from gui.ai.base import UNDO_CHIP, find_name, not_found, suggest
from gui.ai.prompt import BASE_PROMPT, CAPABILITIES
from gui.ai.tools import TOOLS_BY_NAME, ToolBox
from gui.controllers.errors import ControllerError


class FakeRequest:
    def __init__(self, session=None):
        self.session = {} if session is None else dict(session)


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


@pytest.fixture
def request_():
    request = FakeRequest()
    session_store.get_session(request)
    return request


def later(request):
    return FakeRequest(request.session)


def session(request):
    return session_store.get_session(request)


def room_names(request):
    return [room.name for room in session(request).config.config.rooms]


def sections(request):
    return len(session(request).config.config.courses)


def use_solver(monkeypatch, count):
    class FakeScheduler:
        def __init__(self, config):
            pass

        def get_models(self):
            for number in range(count):
                yield [
                    Assignment(
                        f"CMSC 14{number}.01",
                        "Hogg",
                        "Roddy 136",
                        None,
                        (MeetingTime("MON", "09:00", "09:50", 50),),
                    )
                ]

    monkeypatch.setattr(schedule_ops, "Scheduler", FakeScheduler)


def delete_room_136(request, spoken="136"):
    """What the user does: ask for the delete, then agree in the next message."""
    ToolBox(later(request)).call("delete_room", {"name": spoken})
    return ToolBox(later(request)).call("confirm_delete")


# ---------------------------------------------------------------------- #
#  Part of a name is enough
# ---------------------------------------------------------------------- #
NAMES = ["Roddy 136", "Roddy 140", "Roddy 147"]


@pytest.mark.parametrize(
    "spoken", ["136", "room 136", "Room Roddy 136", "roddy136", "RODDY 136"]
)
def test_a_room_is_found_from_part_of_its_name(spoken):
    assert find_name(spoken, NAMES) == "Roddy 136"


def test_people_and_courses_are_found_from_part_of_a_name():
    assert find_name("hog", ["Hogg", "Dr. Xie", "Zoppetti"]) == "Hogg"
    assert find_name("xie", ["Hogg", "Dr. Xie", "Zoppetti"]) == "Dr. Xie"
    assert find_name("cmsc 140", ["CMSC 140.01", "CMSC 152"]) == "CMSC 140.01"
    assert find_name("Dr. Nobody", ["Hogg"]) is None


def test_it_asks_when_two_items_fit_and_never_guesses():
    with pytest.raises(
        ControllerError, match="'roddy' could mean Roddy 136, Roddy 140, Roddy 147"
    ):
        find_name("roddy", NAMES)
    with pytest.raises(ControllerError, match="could mean"):
        find_name("pack", ["pack_rooms", "pack_labs"])


def test_half_a_number_is_not_a_match_but_it_is_suggested():
    assert find_name("13", NAMES) is None
    assert (
        not_found("room", "13", NAMES)
        == "No room named '13' exists. Did you mean 'Roddy 136'?"
    )
    assert suggest("rody 136", NAMES) == ["Roddy 136"]
    assert not_found("room", "Atlantis", NAMES) == "No room named 'Atlantis' exists."


def test_the_tools_use_it_for_reading_deleting_and_changing(request_):
    assert (
        "Room Roddy 136" in ToolBox(request_).call("get_room", {"name": "136"}).message
    )
    review = ToolBox(later(request_)).call("delete_room", {"name": "room 136"})
    assert (
        review.ok
        and "Roddy 136" in review.message
        and "Nothing has been deleted yet" in review.message
    )
    changed = ToolBox(later(request_)).call(
        "update_room", {"name": "147", "capacity": 33}
    )
    assert changed.ok and "Roddy 147" in changed.message
    missing = ToolBox(later(request_)).call("get_room", {"name": "13"})
    assert missing.message == "No room named '13' exists. Did you mean 'Roddy 136'?"
    ambiguous = ToolBox(later(request_)).call("get_room", {"name": "roddy"})
    assert "could mean" in ambiguous.message


# ---------------------------------------------------------------------- #
#  Undo, redo, history
# ---------------------------------------------------------------------- #
def test_undo_puts_a_deleted_room_back_with_everything_removed_with_it(request_):
    before = sections(request_)
    assert delete_room_136(request_).ok
    assert "Roddy 136" not in room_names(request_) and sections(request_) < before

    result = ToolBox(later(request_)).call("undo_changes")
    assert (
        result.ok
        and result.changed
        and result.message.startswith("Undid: Delete room 'Roddy 136'")
    )
    assert "together with everything that was removed with it" in result.message
    assert "Roddy 136" in room_names(request_) and sections(request_) == before
    assert not session(request_).dirty  # back to the loaded state


def test_undo_can_name_the_change_and_takes_back_the_ones_after_it(request_):
    assert delete_room_136(request_).ok
    assert (
        ToolBox(later(request_))
        .call("add_room", {"name": "RODDY150", "capacity": 35})
        .ok
    )
    result = ToolBox(later(request_)).call(
        "undo_changes", {"containing": "deleted Roddy 136"}
    )
    assert result.ok and result.message.startswith("Undid 2 changes, newest first: ")
    assert "1 later change had to be undone with it" in result.message
    assert "Roddy 136" in room_names(request_) and "RODDY150" not in room_names(
        request_
    )


def test_undo_count_and_redo(request_):
    ToolBox(later(request_)).call("add_room", {"name": "RODDY150", "capacity": 35})
    ToolBox(later(request_)).call("add_room", {"name": "RODDY151", "capacity": 35})
    undone = ToolBox(later(request_)).call("undo_changes", {"count": 2})
    assert undone.ok and "Undid 2 changes" in undone.message
    assert not {"RODDY150", "RODDY151"} & set(room_names(request_))
    redone = ToolBox(later(request_)).call("redo_changes")
    assert (
        redone.ok
        and redone.message.startswith("Redid: ")
        and "RODDY150" in room_names(request_)
    )
    assert "RODDY151" not in room_names(request_)


@pytest.mark.parametrize(
    "wanted, label, expected",
    [
        ("Roddy 136", "Delete room 'Roddy 136'", True),
        ("deleted Roddy 136", "Delete room 'Roddy 136'", True),
        ("the room I deleted", "Delete room 'Roddy 136'", True),
        ("delete", "Delete room 'Roddy 136'", True),
        ("added RODDY150", "Add room 'RODDY150'", True),
        (
            "updated room",
            "Edit room 'Roddy 147'",
            False,
        ),  # "updated" is not "edit": say which item instead
        ("Roddy 140", "Delete room 'Roddy 136'", False),
        ("added Roddy 136", "Delete room 'Roddy 136'", False),
        (
            "room",
            "Delete room 'Roddy 136'",
            False,
        ),  # only filler words: nothing to match
    ],
)
def test_a_change_is_recognised_however_it_is_worded(wanted, label, expected):
    assert undo._matches({"label": label, "summary": ""}, wanted) is expected


def test_undo_explains_when_it_cannot(request_):
    assert (
        ToolBox(request_)
        .call("undo_changes")
        .message.endswith("There is nothing to undo.")
    )
    assert (
        ToolBox(later(request_))
        .call("redo_changes")
        .message.endswith("There is nothing to redo.")
    )
    ToolBox(later(request_)).call("add_room", {"name": "RODDY150", "capacity": 35})
    unknown = ToolBox(later(request_)).call("undo_changes", {"containing": "Atlantis"})
    assert (
        not unknown.ok
        and "couldn't find a change matching 'Atlantis'" in unknown.message
    )
    assert "Add room 'RODDY150'" in unknown.message  # the newest changes are listed
    ToolBox(later(request_)).call("undo_changes")
    again = ToolBox(later(request_)).call("undo_changes", {"containing": "RODDY150"})
    assert not again.ok and "already undone" in again.message


def test_the_history_can_be_read(request_):
    assert (
        "no changes to undo or redo yet"
        in ToolBox(request_).call("show_change_history").message
    )
    ToolBox(later(request_)).call("add_room", {"name": "RODDY150", "capacity": 35})
    ToolBox(later(request_)).call("add_room", {"name": "RODDY151", "capacity": 35})
    ToolBox(later(request_)).call("undo_changes")
    text = ToolBox(later(request_)).call("show_change_history").message
    assert (
        "Changes that can be undone, newest first (1):" in text
        and "1. Add room 'RODDY150'" in text
    )
    assert (
        "can be redone, next one first (1):" in text and "Add room 'RODDY151'" in text
    )
    assert not TOOLS_BY_NAME[
        "show_change_history"
    ].final  # a lookup: the model reads it and goes on


def test_undo_and_redo_say_what_they_did_without_the_unsaved_note(request_):
    box = ToolBox(later(request_))
    box.call("add_room", {"name": "RODDY150", "capacity": 35})
    added = service.compose(box.results)
    assert (
        "not yet saved" in added.message
        and added.changed
        and added.suggestions == (UNDO_CHIP,)
    )

    box = ToolBox(later(request_))
    box.call("undo_changes")
    reply = service.compose(box.results)
    assert reply.ok and reply.changed and "not yet saved" not in reply.message
    assert reply.suggestions == (undo.REDO_CHIP, undo.GENERATE_CHIP)


def test_every_real_change_offers_a_one_click_undo_but_a_failure_or_no_change_does_not(
    request_,
):
    assert ToolBox(later(request_)).call(
        "add_room", {"name": "RODDY150", "capacity": 35}
    ).suggestions == (UNDO_CHIP,)
    same = ToolBox(later(request_)).call(
        "update_room", {"name": "RODDY150", "capacity": 35}
    )
    assert same.suggestions == ()
    assert (
        ToolBox(later(request_))
        .call("add_room", {"name": "RODDY150", "capacity": 35})
        .suggestions
        == ()
    )
    assert ToolBox(later(request_)).call("list_rooms").suggestions == ()


# ---------------------------------------------------------------------- #
#  Several things in one message
# ---------------------------------------------------------------------- #
def test_put_the_room_back_then_generate_in_one_message(request_, monkeypatch):
    use_solver(monkeypatch, 1)
    before = sections(request_)
    assert delete_room_136(request_).ok

    box = ToolBox(later(request_))  # the model asks for both tools in one turn
    box.call("undo_changes", {"containing": "Roddy 136"})
    box.call("prepare_schedule_generation", {"limit": 1})
    reply = service.compose(box.results)
    assert (
        reply.ok
        and "Undid: Delete room 'Roddy 136'" in reply.message
        and "Generation limit: 1" in reply.message
    )
    assert sections(request_) == before and reply.changed
    assert reply.suggestions == (
        "Go ahead and generate",
        "Cancel",
    )  # the last step's quick replies

    done = ToolBox(later(request_)).call("confirm_schedule_generation")
    assert done.ok and done.message.startswith("Generated 1 schedule.")


def test_tool_calls_that_arrive_together_run_one_at_a_time(request_):
    box = ToolBox(request_)
    names = [f"RODDY{number}" for number in range(150, 158)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda name: box.call("add_room", {"name": name, "capacity": 30}), names
            )
        )
    assert all(result.ok for result in results) and len(box.results) == len(names)
    assert set(names) <= set(room_names(request_))


# ---------------------------------------------------------------------- #
#  When generation finds nothing
# ---------------------------------------------------------------------- #
def run_with_no_schedule(request, monkeypatch):
    use_solver(monkeypatch, 0)
    ToolBox(later(request)).call("prepare_schedule_generation", {"limit": 1})
    return ToolBox(later(request)).call("confirm_schedule_generation")


def test_a_failed_run_names_the_newest_changes_and_offers_to_undo(
    request_, monkeypatch
):
    assert delete_room_136(request_).ok
    result = run_with_no_schedule(request_, monkeypatch)
    assert not result.ok and "No feasible schedule was found" in result.message
    assert "Nothing was added to the Schedule Viewer" in result.message
    assert "Your newest changes were: Delete room 'Roddy 136'" in result.message
    assert "undoing them may fix it" in result.message
    assert result.suggestions == (diagnose.CHECK_CHIP, UNDO_CHIP)


def test_a_failed_run_without_changes_does_not_blame_a_change(request_, monkeypatch):
    result = run_with_no_schedule(request_, monkeypatch)
    assert not result.ok and "newest changes" not in result.message
    assert "faculty availability" in result.message  # the usual causes are still named
    assert result.suggestions == (diagnose.CHECK_CHIP,)


def test_the_check_reports_what_it_found_or_says_nothing_obvious(request_):
    result = ToolBox(request_).call("diagnose_configuration")
    assert result.ok and result.message.startswith(
        ("I checked the configuration", "I checked room sizes")
    )
    assert result.final and not TOOLS_BY_NAME["diagnose_configuration"].write


def fake_data(monkeypatch, *, rows, people, room_list=(("Big", 40),), lab_list=()):
    monkeypatch.setattr(
        diagnose.courses,
        "describe_courses",
        lambda request: {"has_config": True, "courses": rows},
    )
    monkeypatch.setattr(
        diagnose.rooms,
        "describe_rooms",
        lambda request: {"rooms": [{"name": n, "capacity": c} for n, c in room_list]},
    )
    monkeypatch.setattr(
        diagnose.labs,
        "describe_labs",
        lambda request: {"labs": [{"name": n, "capacity": c} for n, c in lab_list]},
    )
    monkeypatch.setattr(
        diagnose.faculty, "describe_faculty", lambda request: {"faculty": people}
    )


def course(
    display, credits=4, capacity=20, rooms=("Big",), faculty=("Ann",), derived=()
):
    return {
        "display": display,
        "credits": credits,
        "capacity": capacity,
        "rooms": list(rooms),
        "labs": [],
        "faculty": None if faculty is None else list(faculty),
        "derived_faculty": list(derived),
    }


def person(name, low=0, high=12):
    return {"name": name, "minimum_credits": low, "maximum_credits": high}


def test_faculty_minimums_larger_than_the_courses_are_found(monkeypatch):
    fake_data(
        monkeypatch,
        rows=[course("CMSC 140")],
        people=[person("Ann", 6, 12), person("Bo", 6, 12)],
    )
    problems = diagnose.find_problems(None)
    assert problems == [
        (
            "The faculty must teach at least 12 credits in total, but the courses only add up to 4. "
            "Add courses or lower the faculty minimums."
        )
    ]


def test_faculty_maximums_smaller_than_the_courses_are_found(monkeypatch):
    fake_data(
        monkeypatch, rows=[course("A", 4), course("B", 4)], people=[person("Ann", 0, 6)]
    )
    assert (
        "courses add up to 8 credits, but the faculty can teach at most 6"
        in diagnose.find_problems(None)[0]
    )


def test_a_course_nobody_can_teach_and_a_course_too_big_for_its_rooms_are_found(
    monkeypatch,
):
    rows = [
        course("CMSC 161.01", faculty=None, derived=()),
        course("CMSC 162.01", faculty=None, derived=("Ann",)),
        course("CMSC 330.01", capacity=60),
    ]
    fake_data(monkeypatch, rows=rows, people=[person("Ann", 0, 20)])
    problems = diagnose.find_problems(None)
    assert any(
        p.startswith("Nobody can teach CMSC 161.01: no teacher is listed")
        for p in problems
    )
    assert any(
        "CMSC 330.01 needs 60 seats but its rooms hold at most 40" in p
        for p in problems
    )
    assert not any("CMSC 162.01" in p for p in problems)


def test_a_healthy_configuration_has_no_findings(monkeypatch):
    fake_data(monkeypatch, rows=[course("A")], people=[person("Ann", 0, 12)])
    assert diagnose.find_problems(None) == []


def test_findings_are_part_of_the_failed_run_message(request_, monkeypatch):
    monkeypatch.setattr(
        diagnose,
        "find_problems",
        lambda request: ["Nobody can teach CMSC 161.01: example."],
    )
    result = run_with_no_schedule(request_, monkeypatch)
    assert (
        "What I found: Nobody can teach CMSC 161.01: example. Other common causes are"
        in result.message
    )


def test_a_broken_check_never_hides_the_real_result(request_, monkeypatch):
    def broken(request):
        raise RuntimeError("boom")

    monkeypatch.setattr(diagnose, "find_problems", broken)
    result = run_with_no_schedule(request_, monkeypatch)
    assert (
        not result.ok
        and "No feasible schedule was found" in result.message
        and "boom" not in result.message
    )
    assert (
        "I found no obvious problem" not in result.message
    )  # a check that failed does not claim a clean bill


# ---------------------------------------------------------------------- #
#  What the model is told
# ---------------------------------------------------------------------- #
def test_the_prompt_and_capabilities_cover_the_new_abilities():
    for needed in (
        "undo_changes",
        "redo_changes",
        "show_change_history",
        "diagnose_configuration",
        "Several requests in one message",
    ):
        assert needed in BASE_PROMPT, needed
    assert "part of a name" in BASE_PROMPT
    assert (
        "Undo and redo changes" in CAPABILITIES
        and "several things in one message" in CAPABILITIES
    )
    for name in (
        "undo_changes",
        "redo_changes",
        "show_change_history",
        "diagnose_configuration",
    ):
        assert name in TOOLS_BY_NAME and TOOLS_BY_NAME[name].description.strip()
    assert TOOLS_BY_NAME["undo_changes"].final and TOOLS_BY_NAME["redo_changes"].final
