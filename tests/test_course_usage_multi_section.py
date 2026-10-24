"""
The Courses page "Used by" dropdown, final spec (Courses only):

  * ONE chip, "N preferences": how many faculty prefer the course. There is no conflicts chip.
  * Opened, the dropdown lists the faculty WITH their weights, highest weight first. Conflicts are not shown.
  * A course nobody prefers shows nothing at all.
  * Every section of a course shares the references of its course ID, so every one of them shows them.
    Showing them is display only: deleting a section that is not the last of its ID still changes no
    references, and deleting the last one still removes them (tests/test_dependencies.py, unchanged).
  * The dropdown arrow replaces the "details" link. Rooms, Labs, Faculty and Class Patterns are unchanged.

Runs against the REAL scheduler library and the shipped example configuration. Expected values are
computed from the raw JSON file, never from the code under test.
"""

import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.template.loader import render_to_string

from app.commands.common import apply_session_edit
from app.crud import ValidationFailure, apply_edit
from app.session import Session
from gui import session_store
from gui.controllers import dependencies as deps
from gui.controllers.courses import describe_courses
from gui.session_store import EXAMPLE_CONFIG_PATH

RAW = json.loads(Path(EXAMPLE_CONFIG_PATH).read_text())
RAW_COURSES = RAW["config"]["courses"]
RAW_FACULTY = RAW["config"]["faculty"]
COURSES_URL = "/configuration/courses/"
PARTIAL = "gui/components/usage_summary.html"
PARTIAL_FILE = Path("gui/templates/gui/components/usage_summary.html")
CSS = Path("gui/static/gui/css/style.css")
CONFLICT_TITLE = "Listed as a conflict by"
PREFERRED_TITLE = "Preferred by"


# ---------------------------------------------------------------------- #
#  Expected values, from the raw file
# ---------------------------------------------------------------------- #
def raw_section_count(course_id):
    return sum(course["course_id"] == course_id for course in RAW_COURSES)


def raw_conflicting_sections(course_id):
    """Sections of OTHER course ids that list this id as a conflict, as "ID.NN" display names."""
    seen, names = {}, []
    for course in RAW_COURSES:
        seen[course["course_id"]] = seen.get(course["course_id"], 0) + 1
        if course["course_id"] != course_id and course_id in (course.get("conflicts") or []):
            names.append(f"{course['course_id']}.{seen[course['course_id']]:02d}")
    return names


def raw_preferences(course_id):
    """(faculty name, weight) for everyone who prefers this course id, in faculty order."""
    return [
        (person["name"], person["course_preferences"][course_id])
        for person in RAW_FACULTY
        if course_id in (person.get("course_preferences") or {})
    ]


def raw_chip(course_id):
    count = len(raw_preferences(course_id))
    return [] if not count else [f"{count} preference{'' if count == 1 else 's'}"]


def raw_names(course_id):
    """Highest weight first; equal weights may be in any order, so compare them as sorted-by-weight."""
    return [f"{name} ({weight})" for name, weight in sorted(raw_preferences(course_id), key=lambda p: -p[1])]


def weights_of(names):
    return [int(re.search(r"\((\d+)\)$", n).group(1)) for n in names]


MULTI_SECTION_IDS = sorted({c["course_id"] for c in RAW_COURSES if raw_section_count(c["course_id"]) > 1})
SHOWN_SECTIONS = sum(bool(raw_preferences(c["course_id"])) for c in RAW_COURSES)


@pytest.fixture
def session():
    loaded = Session()
    loaded.load(str(EXAMPLE_CONFIG_PATH))
    return loaded


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


def positions(session, course_id):
    return [i for i, c in enumerate(session.config.config.courses) if c.course_id == course_id]


def delete_section(session, index):
    config = session.config
    the_plan = deps.plan(config, "course", index)
    deps.resolve(the_plan)
    mutate, notices = deps.build(config, "course", index, the_plan)
    apply_session_edit(session, config, "course", mutate, label="Delete course")
    return notices


def add_course_sections(session, course_id, count=2, conflicts=()):
    with session.config.edit_mode() as draft:
        for _ in range(count):
            course = copy.deepcopy(draft.config.courses[0])
            course.course_id, course.conflicts, course.faculty = course_id, list(conflicts), ["Hardy"]
            draft.config.courses.append(course)


def prefer(session, faculty_name, course_id, weight):
    def mutate(draft):
        person = next(p for p in draft.config.faculty if p.name == faculty_name)
        person.course_preferences = {**person.course_preferences, course_id: weight}

    apply_edit(session.config, "faculty", mutate)


def usage(session, index):
    return deps.usage(session.config, "course", index)


def page(response):
    return response.content.decode()


def browser_session():
    return next(iter(session_store._SESSIONS.values()))


# ====================================================================== #
#  The example really has what these tests rely on
# ====================================================================== #
def test_the_example_data_is_what_the_expectations_assume():
    assert MULTI_SECTION_IDS == ["CMSC 140", "CMSC 161", "CMSC 340", "CMSC 366"]
    assert [raw_chip(i) for i in MULTI_SECTION_IDS] == [["1 preference"], ["3 preferences"], ["1 preference"], ["1 preference"]]
    assert len(raw_conflicting_sections("CMSC 161")) == 2 and SHOWN_SECTIONS == len(RAW_COURSES) == 17


# ====================================================================== #
#  The chip: preferences only, short text
# ====================================================================== #
@pytest.mark.parametrize("course_id", sorted({c["course_id"] for c in RAW_COURSES}))
def test_every_section_has_exactly_one_chip_and_it_counts_faculty_preferences(session, course_id):
    for index in positions(session, course_id):
        groups = usage(session, index)["groups"]
        assert [g["chip"] for g in groups] == raw_chip(course_id)
        assert all(g["chip"] for g in groups)  # a group is a chip plus its list


def test_there_is_no_conflicts_chip_anywhere_on_the_page_data(session):
    for index in range(len(session.config.config.courses)):
        assert not any("conflict" in g["chip"] for g in usage(session, index)["groups"])


@pytest.mark.parametrize("course_id", MULTI_SECTION_IDS)
def test_every_section_of_a_multi_section_course_shows_the_same_chip(session, course_id):
    chips = {tuple(g["chip"] for g in usage(session, i)["groups"]) for i in positions(session, course_id)}
    assert chips == {tuple(raw_chip(course_id))}


def test_the_chip_is_singular_for_one_preference_and_plural_for_several(session):
    assert usage(session, positions(session, "CMSC 140")[0])["groups"][0]["chip"] == "1 preference"
    assert usage(session, positions(session, "CMSC 161")[0])["groups"][0]["chip"] == "3 preferences"


def test_the_preference_group_keeps_its_wording_tone_and_title(session):
    (group,) = usage(session, positions(session, "CMSC 161")[0])["groups"]
    assert (group["tone"], group["title"]) == ("", PREFERRED_TITLE)


def test_the_chip_follows_a_new_preference(session):
    before = positions(session, "CMSC 340")[0]
    assert usage(session, before)["groups"][0]["chip"] == "1 preference"
    prefer(session, "Hobbs", "CMSC 340", 3)
    assert usage(session, before)["groups"][0]["chip"] == "2 preferences"


# ====================================================================== #
#  The open list: faculty with weights, then conflicts
# ====================================================================== #
@pytest.mark.parametrize("course_id", sorted({c["course_id"] for c in RAW_COURSES}))
def test_the_faculty_names_carry_their_weights(session, course_id):
    (group,) = usage(session, positions(session, course_id)[0])["groups"]
    assert group["names"] == raw_names(course_id)


def test_a_weight_of_zero_is_shown_not_dropped(session):
    prefer(session, "Hobbs", "CMSC 140", 0)
    (group,) = usage(session, 0)["groups"]
    assert "Hobbs (0)" in group["names"]


@pytest.mark.parametrize("course_id", sorted({c["course_id"] for c in RAW_COURSES}))
def test_the_faculty_are_listed_highest_weight_first(session, course_id):
    (group,) = usage(session, positions(session, course_id)[0])["groups"]
    assert weights_of(group["names"]) == sorted(weights_of(group["names"]), reverse=True)


def test_the_highest_weight_comes_first_whatever_the_faculty_order(session):
    prefer(session, "Hobbs", "CMSC 140", 9)  # Hardy (5) is earlier in the faculty list
    (group,) = usage(session, 0)["groups"]
    assert group["names"] == ["Hobbs (9)", "Hardy (5)"]


def test_a_course_has_no_conflict_list_in_its_dropdown(session):
    for index in range(len(session.config.config.courses)):
        result = usage(session, index)
        assert "lists" not in result and not any(CONFLICT_TITLE in g["title"] for g in result["groups"])


def test_there_is_no_shared_by_note_any_more(session):
    for index in range(len(session.config.config.courses)):
        assert not usage(session, index).get("notes")


# ====================================================================== #
#  Referenced only by conflicts: nothing is shown
# ====================================================================== #
def test_a_course_with_conflicts_but_no_faculty_preference_is_not_in_use(session):
    add_course_sections(session, "CMSC 777", count=2)
    other = positions(session, "CMSC 152")[0]
    apply_edit(session.config, "course", lambda d: setattr(d.config.courses[other], "conflicts", ["CMSC 777"]))
    for index in positions(session, "CMSC 777"):
        result = usage(session, index)
        assert result["in_use"] is False and result["groups"] == []
        assert not result.get("lists")  # nothing to open, so the conflicts are not shown either


def test_a_course_nobody_references_at_all_is_not_in_use(session):
    add_course_sections(session, "CMSC 777", count=2)
    for index in positions(session, "CMSC 777"):
        assert usage(session, index)["in_use"] is False


def test_the_dropdown_appears_as_soon_as_somebody_prefers_the_course(session):
    add_course_sections(session, "CMSC 777", count=2)
    other = positions(session, "CMSC 152")[0]
    apply_edit(session.config, "course", lambda d: setattr(d.config.courses[other], "conflicts", ["CMSC 777"]))
    prefer(session, "Hobbs", "CMSC 777", 4)
    result = usage(session, positions(session, "CMSC 777")[0])
    assert result["in_use"] is True
    assert [g["chip"] for g in result["groups"]] == ["1 preference"] and result["groups"][0]["names"] == ["Hobbs (4)"]


# ====================================================================== #
#  The reference functions
# ====================================================================== #
def test_the_library_does_not_allow_a_course_to_conflict_with_itself(session):
    add_course_sections(session, "CMSC 777", count=2)
    first = positions(session, "CMSC 777")[0]
    with pytest.raises(ValidationFailure, match="cannot conflict with itself"):
        apply_edit(session.config, "course", lambda d: setattr(d.config.courses[first], "conflicts", ["CMSC 777"]))


def test_sections_of_the_same_course_are_never_references_to_each_other():
    """The function must not lean on the library's guarantee, so check it on stand-in objects."""

    def section(course_id, conflicts):
        return SimpleNamespace(course_id=course_id, section_id=None, conflicts=conflicts)

    config = SimpleNamespace(
        config=SimpleNamespace(
            courses=[section("X", ["X"]), section("X", []), section("Y", ["X"])],
            faculty=[SimpleNamespace(name="Pat", course_preferences={"X": 1})],
        )
    )
    conflicts, faculty = deps._course_references(config, "X")
    assert conflicts == ["Y.01"] and faculty == ["Pat"]


def test_the_delete_helper_is_the_references_function_behind_the_last_section_guard(session):
    assert deps._course_dependents(session.config, 3) == ([], [])  # CMSC 161.01: two more sections remain
    last = positions(session, "CMSC 162")[0]
    assert deps._course_dependents(session.config, last) == deps._course_references(session.config, "CMSC 162")


# ====================================================================== #
#  Deleting is unchanged
# ====================================================================== #
def test_deleting_a_section_that_is_not_the_last_still_changes_no_references(session):
    plan = deps.plan(session.config, "course", 3)
    assert plan.effects == [] and plan.groups == [] and not plan.blocked
    conflicts = [list(c.conflicts or []) for c in session.config.config.courses]
    prefs = [dict(p.course_preferences or {}) for p in session.config.config.faculty]
    assert delete_section(session, 3) == []
    assert [list(c.conflicts or []) for c in session.config.config.courses] == conflicts[:3] + conflicts[4:]
    assert [dict(p.course_preferences or {}) for p in session.config.config.faculty] == prefs


def test_the_other_sections_keep_their_chip_when_one_section_is_deleted(session):
    delete_section(session, positions(session, "CMSC 161")[-1])
    for index in positions(session, "CMSC 161"):
        assert [g["chip"] for g in usage(session, index)["groups"]] == ["3 preferences"]


def test_deleting_the_last_section_still_removes_the_references_and_the_dropdown_goes(session):
    for _ in range(2):
        delete_section(session, positions(session, "CMSC 161")[-1])
    notices = delete_section(session, positions(session, "CMSC 161")[0])
    assert notices == ["Removed CMSC 161 from the conflict list of 2 course sections and 3 faculty course preferences."]
    assert all("CMSC 161" not in (c.conflicts or []) for c in session.config.config.courses)
    assert all("CMSC 161" not in (p.course_preferences or {}) for p in session.config.config.faculty)


def test_the_delete_review_page_data_still_lists_conflicts_and_preferences(session):
    (only,) = positions(session, "CMSC 162")
    plan = deps.plan(session.config, "course", only)
    assert [g["title"] for g in plan.groups] == ["Conflict lists", "Faculty preferences"]


def test_the_courses_list_carries_the_same_usage(monkeypatch, session):
    from gui.controllers import courses as courses_controller

    monkeypatch.setattr(courses_controller, "get_session", lambda request: session)
    rows = describe_courses(None)["courses"]
    assert [g["chip"] for g in rows[3]["usage"]["groups"]] == ["3 preferences"]
    assert "lists" not in rows[3]["usage"]


def test_other_kinds_of_record_are_unchanged(session):
    assert [g["chip"] for g in deps.usage(session.config, "room", "Roddy 136")["groups"]] == ["9 courses", "9 faculty preferences"]
    assert [g["chip"] for g in deps.usage(session.config, "faculty", "Zoppetti")["groups"]] == ["1 course", "candidate: 2"]
    for kind, ident in (("room", "Roddy 136"), ("lab", "Mac"), ("faculty", "Zoppetti"), ("pattern", 2)):
        assert not deps.usage(session.config, kind, ident).get("lists")


# ====================================================================== #
#  The partial: one chip and one list per group
# ====================================================================== #
def render(usage, **extra):
    return render_to_string(PARTIAL, {"usage": usage, **extra})


GROUP = {"chip": "2 preferences", "tone": "", "title": "Preferred by", "names": ["Ann (5)", "Bo (2)"]}


def test_the_arrow_follows_the_last_chip():
    html = render({"in_use": True, "groups": [GROUP]}, icon=True)
    assert html.count('class="chip') == 1
    assert re.search(r'2 preferences</span><svg class="usage__icon"', html)
    assert "Ann (5), Bo (2)" in html.split("</summary>")[1]


def test_list_text_is_escaped():
    html = render({"in_use": True, "groups": [{**GROUP, "names": ["<script>alert(1)</script>"]}]})
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_notes_and_lists_support_is_gone_from_the_partial_and_the_stylesheet():
    text = PARTIAL_FILE.read_text()
    assert "notes" not in text and "usage__note" not in text and "usage.lists" not in text
    assert "usage__note" not in CSS.read_text()


def test_the_partial_has_no_course_specific_logic():
    code = PARTIAL_FILE.read_text().split("{% endcomment %}", 1)[1]
    assert "course" not in code.lower() and "section" not in code.lower() and "preference" not in code.lower()


def test_the_partial_still_works_for_the_other_pages():
    two = {"in_use": True, "groups": [{"chip": "9 courses", "tone": "info", "title": "Courses", "names": ["A"]}, GROUP]}
    html = render(two, icon=True)
    assert html.count('class="chip') == 2 and html.count("usage__icon") == 1
    assert re.search(r'2 preferences</span><svg class="usage__icon"', html)
    plain = render(two)
    assert 'class="usage__toggle">details<' in plain and "usage__icon" not in plain
    assert "Not in use" in render({"in_use": False, "groups": []}) and render({"in_use": False, "groups": []}, quiet=True).strip() == ""


# ====================================================================== #
#  The Courses page
# ====================================================================== #
def arrows(text):
    return re.findall(r'<svg class="usage__icon".*?</svg>', text, flags=re.S)


def summaries(text):
    return re.findall(r'<details class="usage">\s*<summary>(.*?)</summary>', text, flags=re.S)


def card_for(text, display):
    """The HTML of the course card whose title is `display` (e.g. "CMSC 162.01")."""
    for card in text.split('<article class="item-card"')[1:]:
        if f">{display}</h3>" in card.split("</header>")[0]:
            return card.split("</article>")[0]
    raise AssertionError(f"no card titled {display}")


def test_course_cards_have_no_chip_dropdown_or_arrow(client):
    text = page(client.get(COURSES_URL))
    assert "<details" not in text and "usage__icon" not in text and "usage__toggle" not in text
    assert not re.search(r'class="chip[^"]*">\d+ (preferences?|conflicts?)<', text)
    assert "Listed as a conflict by" not in text


def test_every_card_lists_its_preferences_as_plain_text_highest_weight_first(client):
    text = page(client.get(COURSES_URL))
    cards = text.split('<article class="item-card"')[1:]
    assert len(cards) == len(RAW_COURSES)
    for card, course in zip(cards, RAW_COURSES):
        names = raw_names(course["course_id"])
        expected = ", ".join(names) if names else "&mdash;"
        assert re.search(rf"<dt>Preferred by</dt>\s*<dd>{re.escape(expected)}</dd>", card)


def test_every_section_of_a_multi_section_course_shows_the_same_preferences(client):
    text = page(client.get(COURSES_URL))
    for display in ("CMSC 161.01", "CMSC 161.02", "CMSC 161.03"):
        assert ", ".join(raw_names("CMSC 161")) in card_for(text, display)


def test_a_course_nobody_prefers_shows_a_dash(client):
    client.get(COURSES_URL)
    add_course_sections(browser_session(), "CMSC 777", count=2)
    text = page(client.get(COURSES_URL))
    for display in ("CMSC 777.01", "CMSC 777.02"):
        assert re.search(r"<dt>Preferred by</dt>\s*<dd>&mdash;</dd>", card_for(text, display))


def test_course_cards_are_one_shape_whatever_is_listed():
    html = Path("gui/templates/gui/courses.html").read_text()
    assert 'class="card-grid" id="course-list"' in html and "card-grid--start" not in html
    assert re.search(r"\.card-grid \{[^}]*align-items: stretch", CSS.read_text())


def test_the_other_pages_still_render_their_dropdowns_with_both_chips(client):
    rooms = page(client.get("/configuration/rooms/"))
    assert re.search(r'>\d+ courses?</span>', rooms) and re.search(r'>\d+ faculty preferences?</span>', rooms)
    for url in ("/configuration/labs/", "/configuration/faculty/"):
        assert page(client.get(url)).count('<details class="usage">') >= 1, url


def test_patterns_keep_the_details_link(client):
    include = re.search(r'\{% include "gui/components/usage_summary.html"[^%]*%\}', Path("gui/templates/gui/patterns.html").read_text())
    assert include and "icon" not in include.group(0)
    needed_by = {"in_use": True, "groups": [{"chip": "needed by 2 sections", "tone": "info", "title": "Needed by", "names": ["A", "B"]}]}
    html = render(needed_by, quiet=True)
    assert 'class="usage__toggle">details<' in html and "usage__icon" not in html
