"""
Tests for gui/controllers/dependencies.py (Sprint 2 Section 12): the one place that
knows how rooms, labs, faculty, courses and class patterns point at each other.

They run against the REAL scheduler library and the shipped example configuration
(3 rooms, 2 labs, 17 course sections, 10 faculty, 16 class patterns).
"""

import copy

import pytest

from app.commands.common import apply_session_edit
from app.session import Session
from gui.controllers import dependencies as deps
from gui.controllers.errors import ControllerError
from gui.session_store import EXAMPLE_CONFIG_PATH
from tests.canonical import canonical


@pytest.fixture
def session():
    loaded = Session()
    loaded.load(str(EXAMPLE_CONFIG_PATH))
    return loaded


def run_delete(session, kind, ident):
    """Do what a delete page does: plan, check it is allowed, cascade in ONE edit."""
    config = session.config
    plan = deps.plan(config, kind, ident)
    deps.resolve(plan)
    mutate, notices = deps.build(config, kind, ident, plan)
    apply_session_edit(session, config, kind, mutate, label=f"Delete {kind}")
    return notices


def sections_per_course(session):
    counts = {}
    for course in session.config.config.courses:
        counts[course.course_id] = counts.get(course.course_id, 0) + 1
    return counts


def lists_before(session, field):
    return [set(getattr(course, field) or []) for course in session.config.config.courses]


def course_named(config, course_id):
    return [course for course in config.config.courses if course.course_id == course_id]


# ---------------------------------------------------------------------- #
#  "Who uses this?" (list pages)
# ---------------------------------------------------------------------- #
def test_a_rooms_usage_counts_courses_and_faculty(session):
    usage = deps.usage(session.config, "room", "Roddy 136")
    assert usage["in_use"] is True
    assert [group["chip"] for group in usage["groups"]] == ["9 courses", "9 faculty preferences"]


def test_a_labs_usage_works_the_same_way(session):
    usage = deps.usage(session.config, "lab", "Mac")
    assert usage["in_use"] is True
    assert usage["groups"][0]["chip"] == "7 courses"


def test_a_faculty_members_usage_counts_assignments_and_sole_candidacy(session):
    usage = deps.usage(session.config, "faculty", "Zoppetti")
    assert [group["chip"] for group in usage["groups"]] == ["1 course", "candidate: 2"]


def test_a_member_nobody_depends_on_is_not_in_use(session):
    assert deps.usage(session.config, "faculty", "sam")["in_use"] is False


def test_every_section_of_a_course_shows_the_faculty_preferences_its_course_id_has(session):
    first_of_two = deps.usage(session.config, "course", 0)               # CMSC 140 has a second section
    assert first_of_two["in_use"] is True
    assert [group["chip"] for group in first_of_two["groups"]] == ["1 preference"]
    last = deps.usage(session.config, "course", 6)                          # the only CMSC 162
    assert [group["chip"] for group in last["groups"]] == ["1 preference"]


def test_a_course_usage_has_no_conflicts_chip_and_no_conflict_list(session):
    usage = deps.usage(session.config, "course", 6)                         # the only CMSC 162
    assert all("conflict" not in group["chip"] for group in usage["groups"])
    assert "lists" not in usage


def test_a_pattern_is_only_needed_when_it_is_the_last_enabled_one_for_its_credits(session):
    assert deps.usage(session.config, "pattern", 0)["in_use"] is False   # 3 credits, but no course uses them
    assert deps.usage(session.config, "pattern", 2)["in_use"] is False   # other enabled 4-credit patterns exist


def test_unknown_records_are_reported_not_crashed_on(session):
    with pytest.raises(ControllerError, match="no longer exists"):
        deps.usage(session.config, "room", "Nowhere 1")
    with pytest.raises(ControllerError, match="no longer exists"):
        deps.plan(session.config, "course", 999)


# ---------------------------------------------------------------------- #
#  Rooms and labs
# ---------------------------------------------------------------------- #
SOLE_ROOM_SECTIONS = ["CMSC 161.01", "CMSC 362.01", "CMSC 476.01"]


def test_the_plan_lists_the_sections_that_could_not_be_scheduled_without_the_room(session):
    plan = deps.plan(session.config, "room", "Roddy 136")
    deleted = next(group for group in plan.groups if group["title"].startswith("Course sections that would be deleted"))
    assert deleted["names"] == SOLE_ROOM_SECTIONS
    assert len(plan.removes_courses) == 3
    assert "11 course sections" in plan.effects[0]          # the other sections just lose it from their list
    assert plan.in_use and not plan.blocked


def test_deleting_such_a_room_needs_no_tick_box(session):
    plan = deps.plan(session.config, "room", "Roddy 136")
    assert deps.resolve(plan) is None
    assert not hasattr(plan, "extra_confirm") and not hasattr(plan, "needs_decision")


def test_resolve_only_looks_at_whether_the_delete_is_allowed():
    import inspect

    assert list(inspect.signature(deps.resolve).parameters) == ["the_plan"]


def test_no_other_room_takes_the_deleted_rooms_place(session):
    before = lists_before(session, "room")
    run_delete(session, "room", "Roddy 136")
    config = session.config.config
    assert [room.name for room in config.rooms] == ["Roddy 140", "Roddy 147"]
    after = lists_before(session, "room")
    kept_before = [rooms for rooms in before if rooms != {"Roddy 136"}]
    assert after == [rooms - {"Roddy 136"} for rooms in kept_before]      # nothing was added anywhere
    assert all("Roddy 136" not in person.room_preferences for person in config.faculty)


def test_the_cascade_reports_what_it_did(session):
    notices = run_delete(session, "room", "Roddy 136")
    assert notices == [
        "Removed 'Roddy 136' from 11 course sections and 9 faculty room preferences.",
        "Also deleted 3 course sections: CMSC 161.01, CMSC 362.01, CMSC 476.01.",
    ]
    counts = sections_per_course(session)
    assert counts["CMSC 161"] == 2 and "CMSC 362" not in counts and "CMSC 476" not in counts
    assert list(course_named(session.config, "CMSC 162")[0].room) == ["Roddy 140"]      # untouched
    assert session.history.undo_label == "Delete room"


def test_a_room_cascade_remembers_only_the_parts_it_changed(session):
    run_delete(session, "room", "Roddy 136")
    assert session.history._undo[-1].memento.areas == ["rooms", "courses", "faculty"]


def test_a_room_nothing_depends_on_is_removed_without_a_tick(session):
    config = session.config
    with config.edit_mode() as draft:
        spare = copy.deepcopy(draft.config.rooms[0])
        spare.name = "Spare"
        draft.config.rooms.append(spare)
    plan = deps.plan(config, "room", "Spare")
    assert not plan.in_use
    assert run_delete(session, "room", "Spare") == []


def test_a_lab_is_removed_and_its_sections_are_left_without_one(session):
    before = lists_before(session, "lab")
    plan = deps.plan(session.config, "lab", "Mac")
    assert plan.removes_courses == []
    assert any("left without" in line for line in plan.effects)
    notices = run_delete(session, "lab", "Mac")
    assert [lab.name for lab in session.config.config.labs] == ["Linux"]
    assert lists_before(session, "lab") == [labs - {"Mac"} for labs in before]    # Linux took nobody's place
    assert any("no lab" in note for note in notices)


def test_the_only_room_cannot_be_deleted(session):
    fresh = Session()
    fresh.new_config()
    name = fresh.config.config.rooms[0].name
    plan = deps.plan(fresh.config, "room", name)
    assert plan.blocked and "only room" in plan.blockers[0]
    with pytest.raises(ControllerError, match="only room"):
        deps.resolve(plan)


# ---------------------------------------------------------------------- #
#  Faculty
# ---------------------------------------------------------------------- #
def test_the_plan_separates_sections_the_scheduler_can_staff_from_ones_nobody_else_could_teach(session):
    plan = deps.plan(session.config, "faculty", "Zoppetti")
    deleted = next(group for group in plan.groups if group["title"].startswith("Course sections that would be deleted"))
    handed = next(group for group in plan.groups if group["title"].startswith("Sections the scheduler"))
    assert deleted["names"] == ["CMSC 362.01", "CMSC 476.01"]
    assert handed["names"] == ["CMSC 161.01"]                # others prefer CMSC 161
    assert "nobody is named in their place" in " ".join(plan.effects)
    assert plan.removes_courses and not plan.blocked


def test_faculty_cascade_names_nobody_in_their_place(session):
    before = [set(course.faculty or []) for course in session.config.config.courses]
    notices = run_delete(session, "faculty", "Zoppetti")
    config = session.config.config
    assert "Zoppetti" not in [person.name for person in config.faculty]
    assert config.courses[3].faculty is None                                # the scheduler chooses again
    counts = sections_per_course(session)
    assert "CMSC 362" not in counts and "CMSC 476" not in counts
    after = [set(course.faculty or []) for course in config.courses]
    assert after == [names - {"Zoppetti"} for i, names in enumerate(before) if i not in (10, 16)]   # nobody inherited anything
    assert notices[0] == "Removed 'Zoppetti' from 1 course section."
    assert "staffed by the scheduler" in notices[1]
    assert notices[-1].startswith("Also deleted 2 course sections")


def test_a_member_nobody_depends_on_is_removed_without_a_tick(session):
    plan = deps.plan(session.config, "faculty", "sam")
    assert not plan.removes_courses
    run_delete(session, "faculty", "sam")
    assert "sam" not in [person.name for person in session.config.config.faculty]


def test_the_only_faculty_member_cannot_be_deleted(session):
    fresh = Session()
    fresh.new_config()
    name = fresh.config.config.faculty[0].name
    assert deps.plan(fresh.config, "faculty", name).blocked


# ---------------------------------------------------------------------- #
#  Courses
# ---------------------------------------------------------------------- #
def test_deleting_the_last_section_removes_the_course_from_everything_that_named_it(session):
    notices = run_delete(session, "course", 6)
    config = session.config.config
    assert not course_named(session.config, "CMSC 162")
    assert all("CMSC 162" not in course.conflicts for course in config.courses)
    assert all("CMSC 162" not in person.course_preferences for person in config.faculty)
    assert notices == ["Removed CMSC 162 from the conflict list of 2 course sections and 1 faculty course preference."]


def test_deleting_one_of_several_sections_leaves_references_alone(session):
    before = [list(course.conflicts) for course in session.config.config.courses]
    notices = run_delete(session, "course", 0)
    assert notices == []
    assert [list(course.conflicts) for course in session.config.config.courses] == before[1:]


# ---------------------------------------------------------------------- #
#  Class patterns
# ---------------------------------------------------------------------- #
def add_two_credit_world(session):
    """A 2-credit pattern and two 2-credit course sections that only it can schedule."""
    config = session.config
    with config.edit_mode() as draft:
        pattern = copy.deepcopy(draft.time_slot_config.classes[0])
        pattern.credits = 2
        draft.time_slot_config.classes.append(pattern)
        for section, name in ((None, "Hardy"), ("B", "Hardy")):
            course = copy.deepcopy(draft.config.courses[0])
            course.course_id, course.section_id, course.credits = "CMSC 199", section, 2
            course.conflicts, course.faculty = [], [name]
            draft.config.courses.append(course)
    return len(config.time_slot_config.classes) - 1


def test_a_pattern_the_courses_depend_on_lists_them_and_needs_no_tick(session):
    index = add_two_credit_world(session)
    plan = deps.plan(session.config, "pattern", index)
    assert len(plan.removes_courses) == 2
    assert any("Course sections that would be deleted" in group["title"] for group in plan.groups)
    assert deps.resolve(plan) is None


def test_confirming_deletes_the_pattern_and_the_courses_that_needed_it(session):
    index = add_two_credit_world(session)
    notices = run_delete(session, "pattern", index)
    assert not course_named(session.config, "CMSC 199")
    assert len(session.config.time_slot_config.classes) == index
    assert notices and notices[0].startswith("Also deleted 2 course sections")


def test_a_pattern_with_a_twin_or_that_is_disabled_deletes_alone(session):
    assert deps.plan(session.config, "pattern", 0).removes_courses == []
    assert deps.plan(session.config, "pattern", 4).removes_courses == []   # disabled


# ---------------------------------------------------------------------- #
#  Everything is one undoable step
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "kind, ident",
    [("room", "Roddy 136"), ("lab", "Mac"), ("faculty", "Zoppetti"), ("course", 6)],
)
def test_every_cascade_is_undone_in_one_step(session, kind, ident):
    before = canonical(session.config.model_dump_json())
    run_delete(session, kind, ident)
    assert canonical(session.config.model_dump_json()) != before
    session.history.undo(session)
    assert canonical(session.config.model_dump_json()) == before
    assert session.dirty is False
