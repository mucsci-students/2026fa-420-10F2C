"""
The delete review pages have no tick-box.

Deleting a room, faculty member or class pattern that other records depend on used to need a ticked
box ("I understand this also deletes 3 course sections") before the red Delete button would work. Now
the review page lists exactly what will change (including any course sections that go too) and the red
button does it in one click. These tests hold the rest of the safety net in place:

  * the review page still lists every affected record, and a plain GET deletes nothing;
  * Cancel (or anything that is not an explicit confirm) deletes nothing;
  * a delete that is not allowed (the only room, ...) is still blocked, with the reason;
  * the library still has the last word, and a rejected cascade changes nothing;
  * every cascade is still one undoable step.

Runs against the REAL scheduler library and the shipped example configuration.
"""

import copy
import inspect
import re
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

import pytest

from gui import session_store
from gui.controllers import dependencies as deps
from gui.controllers import faculty as faculty_ctrl
from gui.controllers import labs as labs_ctrl
from gui.controllers import patterns as patterns_ctrl
from gui.controllers import rooms as rooms_ctrl
from tests.canonical import canonical

ROOMS = "/configuration/rooms/"
LABS = "/configuration/labs/"
FACULTY = "/configuration/faculty/"
PATTERNS = "/configuration/patterns/"


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


def browser_session():
    return next(iter(session_store._SESSIONS.values()))


def page(response):
    return response.content.decode()


def config_json():
    return canonical(browser_session().config.model_dump_json())


def sections():
    return [course.course_id for course in browser_session().config.config.courses]


def add_two_credit_pattern_world(client):
    """A 2-credit pattern and two 2-credit sections that only it can schedule."""
    client.get(PATTERNS)
    with browser_session().config.edit_mode() as draft:
        pattern = copy.deepcopy(draft.time_slot_config.classes[0])
        pattern.credits = 2
        draft.time_slot_config.classes.append(pattern)
        for section in (None, "B"):
            course = copy.deepcopy(draft.config.courses[0])
            course.course_id, course.section_id, course.credits = "CMSC 199", section, 2
            course.conflicts, course.faculty = [], ["Hardy"]
            draft.config.courses.append(course)
    return len(browser_session().config.time_slot_config.classes) - 1


# One entry per kind of review page that can also delete course sections. `prepare` makes the
# record exist in the session and returns the URL of its review page.
CASES = {
    "room": {
        "prepare": lambda client: (
            client.get(ROOMS),
            f"{ROOMS}{quote('Roddy 136')}/delete/",
        )[1],
        "gone": lambda: (
            "Roddy 136" not in [r.name for r in browser_session().config.config.rooms]
        ),
        "extra_sections": 3,
    },
    "faculty": {
        "prepare": lambda client: (client.get(FACULTY), f"{FACULTY}Zoppetti/delete/")[
            1
        ],
        "gone": lambda: (
            "Zoppetti" not in [p.name for p in browser_session().config.config.faculty]
        ),
        "extra_sections": 2,
    },
    "pattern": {
        "prepare": lambda client: (
            f"{PATTERNS}{add_two_credit_pattern_world(client)}/delete/"
        ),
        "gone": lambda: (
            not any(
                c.credits == 2
                for c in browser_session().config.time_slot_config.classes
            )
        ),
        "extra_sections": 2,
    },
}


@pytest.fixture(params=list(CASES))
def case(request, client):
    spec = cast("Any", CASES[request.param])
    return {
        "url": spec["prepare"](client),
        "gone": spec["gone"],
        "extra_sections": spec["extra_sections"],
    }


# ====================================================================== #
#  The review page
# ====================================================================== #
def test_the_review_page_has_no_tick_box_but_still_lists_what_goes_too(client, case):
    text = page(client.get(case["url"]))
    assert 'type="checkbox"' not in text
    assert 'name="confirm_extra"' not in text
    assert "I understand this also deletes" not in text
    assert "Course sections that would be deleted" in text
    assert (
        'name="action" value="confirm"' in text
        and 'name="action" value="cancel"' in text
    )


def test_looking_at_the_review_page_deletes_nothing(client, case):
    before = config_json()
    client.get(case["url"])
    assert config_json() == before
    assert not case["gone"]() and not browser_session().history.can_undo


def test_the_page_still_says_the_deletion_can_be_undone(client, case):
    assert "undo" in page(client.get(case["url"])).lower()


# ====================================================================== #
#  One click does everything
# ====================================================================== #
def test_one_click_deletes_the_record_and_the_sections_that_depended_on_it(
    client, case
):
    before = len(sections())
    response = client.post(case["url"], {"action": "confirm"}, follow=True)
    text = page(response)
    assert response.status_code == 200
    assert case["gone"]()
    assert len(sections()) == before - case["extra_sections"]
    assert f"Also deleted {case['extra_sections']} course sections" in text
    assert "nothing was changed" not in text and "Tick the box" not in text


def test_the_cascade_is_still_one_undoable_step(client, case):
    before = config_json()
    client.post(case["url"], {"action": "confirm"}, follow=True)
    assert config_json() != before and browser_session().history.can_undo
    browser_session().history.undo(browser_session())
    assert config_json() == before


def test_an_old_page_that_still_sends_the_tick_works_the_same(client, case):
    """A browser tab opened before this change may still post the old field; it is simply ignored."""
    before = len(sections())
    client.post(case["url"], {"action": "confirm", "confirm_extra": "on"}, follow=True)
    assert case["gone"]() and len(sections()) == before - case["extra_sections"]


def test_posting_confirm_twice_does_not_delete_anything_else(client):
    client.get(ROOMS)
    url = f"{ROOMS}{quote('Roddy 136')}/delete/"
    client.post(url, {"action": "confirm"}, follow=True)
    after_first = config_json()
    response = client.post(url, {"action": "confirm"}, follow=True)
    assert "no longer exists" in page(response)
    assert config_json() == after_first


# ====================================================================== #
#  Nothing is deleted unless the user explicitly confirms
# ====================================================================== #
@pytest.mark.parametrize(
    "data",
    [
        {},
        {"action": "cancel"},
        {"action": ""},
        {"action": "bogus"},
        {"action": "CONFIRM"},
    ],
)
def test_anything_but_an_explicit_confirm_deletes_nothing(client, case, data):
    before = config_json()
    response = client.post(case["url"], data, follow=True)
    assert "Cancelled" in page(response)
    assert config_json() == before and not browser_session().history.can_undo


def test_a_tick_alone_never_deletes(client):
    client.get(ROOMS)
    before = config_json()
    client.post(
        f"{ROOMS}{quote('Roddy 136')}/delete/", {"confirm_extra": "on"}, follow=True
    )
    assert config_json() == before


def test_get_with_the_old_parameters_never_deletes(client):
    client.get(ROOMS)
    before = config_json()
    client.get(f"{ROOMS}{quote('Roddy 136')}/delete/?action=confirm&confirm_extra=on")
    assert config_json() == before


# ====================================================================== #
#  The other safety nets are untouched
# ====================================================================== #
def test_the_only_room_is_still_blocked_with_the_reason_and_no_delete_button(client):
    client.get(ROOMS)
    client.post("/configuration/new/", {"new-confirm_replace": "on"})
    name = browser_session().config.config.rooms[0].name
    text = page(client.get(f"{ROOMS}{quote(name)}/delete/"))
    assert "Cannot delete" in text and "only room" in text
    assert 'name="action" value="confirm"' not in text
    before = config_json()
    response = client.post(
        f"{ROOMS}{quote(name)}/delete/", {"action": "confirm"}, follow=True
    )
    assert config_json() == before
    assert "only room" in page(response)


def test_a_rejected_cascade_still_changes_nothing_and_shows_the_reason(
    client, monkeypatch
):
    from app.crud import ValidationFailure

    def reject(session_, config, area, mutate, label=None):
        raise ValidationFailure(area, "simulated whole-config rejection")

    client.get(ROOMS)
    before = config_json()
    monkeypatch.setattr(rooms_ctrl, "apply_session_edit", reject)
    response = client.post(
        f"{ROOMS}{quote('Roddy 136')}/delete/", {"action": "confirm"}
    )
    text = page(response)
    assert response.status_code == 200
    assert (
        "was not deleted and nothing was changed" in text
        and "simulated whole-config rejection" in text
    )
    assert (
        config_json() == before
        and not browser_session().history.can_undo
        and not browser_session().dirty
    )


def test_a_record_nothing_depends_on_is_deleted_with_one_click_as_before(client):
    client.get(ROOMS)
    client.post(
        ROOMS + "add/",
        {"name": "Annex 1", "capacity": "20", "features": "", "times": ""},
    )
    text = page(client.get(f"{ROOMS}Annex%201/delete/"))
    assert (
        "Course sections that would be deleted" not in text
        and 'type="checkbox"' not in text
    )
    client.post(f"{ROOMS}Annex%201/delete/", {"action": "confirm"}, follow=True)
    assert "Annex 1" not in [r.name for r in browser_session().config.config.rooms]


def test_labs_and_courses_are_unchanged(client):
    client.get(LABS)
    client.post(f"{LABS}Mac/delete/", {"action": "confirm"}, follow=True)
    assert "Mac" not in [lab.name for lab in browser_session().config.config.labs]
    client.get("/configuration/courses/")
    before = len(sections())
    client.post(
        "/configuration/courses/0/delete/",
        {"action": "confirm", "expected_course_id": "CMSC 140"},
        follow=True,
    )
    assert len(sections()) == before - 1


# ====================================================================== #
#  Controllers: no tick parameter any more
# ====================================================================== #
@pytest.mark.parametrize(
    "function",
    [
        rooms_ctrl.delete_room,
        labs_ctrl.delete_lab,
        faculty_ctrl.delete_faculty,
        patterns_ctrl.delete_pattern,
    ],
)
def test_the_delete_controllers_take_no_tick_parameter(function):
    assert "confirm_extra" not in inspect.signature(function).parameters


def test_the_delete_flow_helper_passes_no_confirmation_to_the_controller(client):
    from gui import views_delete

    assert list(inspect.signature(views_delete.delete_page).parameters) == [
        "request",
        "template",
        "context",
        "list_url",
        "done_text",
        "delete",
    ]
    assert "confirm_checked" not in inspect.getsource(views_delete)


def test_a_plan_has_nothing_to_tick():
    from app.session import Session

    loaded = Session()
    loaded.load(str(session_store.EXAMPLE_CONFIG_PATH))
    plan = deps.plan(loaded.config, "room", "Roddy 136")
    assert plan.removes_courses and plan.in_use
    assert not hasattr(plan, "extra_confirm") and not hasattr(plan, "needs_decision")


# ====================================================================== #
#  Nothing of the old tick-box is left behind
# ====================================================================== #
def test_no_trace_of_the_tick_box_is_left_in_the_gui_code_or_templates():
    leftovers = []
    for path in Path("gui").rglob("*"):
        if (
            path.suffix not in {".py", ".html", ".js", ".css"}
            or "__pycache__" in path.parts
        ):
            continue
        text = path.read_text()
        for needle in (
            "confirm_extra",
            "extra_confirm",
            "confirm_checked",
            "Tick the box",
            "I understand this also deletes",
        ):
            if needle in text:
                leftovers.append(f"{path}: {needle}")
    assert leftovers == []


def test_the_checkbox_style_that_only_the_tick_box_used_is_gone():
    css = re.sub(
        r"/\*.*?\*/",
        "",
        Path("gui/static/gui/css/style.css").read_text(),
        flags=re.DOTALL,
    )
    assert not re.search(r"(^|[\s,}])\.checkbox\b", css)
    assert not any(
        'class="checkbox"' in p.read_text()
        for p in Path("gui/templates").rglob("*.html")
    )
