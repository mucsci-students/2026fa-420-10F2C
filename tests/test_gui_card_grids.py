"""
Faculty and Course cards size to their own content, so opening the dropdown on one card never
stretches the card beside it. Class Patterns keep the equal-height grid, because nobody asked to change them.

The cause was the shared card grid: `.card-grid` uses `align-items: stretch`, so every card in a row is
as tall as the tallest one. The two pages opt out with the `card-grid--start` modifier.
"""

import re
from pathlib import Path

import pytest

from gui import session_store

CSS = Path("gui/static/gui/css/style.css")
OPTED_OUT = [("/configuration/faculty/", "faculty-list")]


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


def page(response):
    return response.content.decode()


def grid_classes(text, grid_id=None):
    pattern = rf'<div class="([^"]*)" id="{grid_id}"' if grid_id else r'<div class="(card-grid[^"]*)"'
    match = re.search(pattern, text)
    assert match, "card grid not found"
    return match.group(1).split()


def rules(css):
    """(selector list, declarations) pairs in source order, with comments removed."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)]


@pytest.mark.parametrize("url, grid_id", OPTED_OUT)
def test_faculty_and_course_grids_opt_out_of_stretching(client, url, grid_id):
    classes = grid_classes(page(client.get(url)), grid_id)
    assert "card-grid" in classes and "card-grid--start" in classes


@pytest.mark.parametrize("url, grid_id", OPTED_OUT + [("/configuration/courses/", "course-list")])
def test_the_grids_keep_the_ids_the_search_box_uses(client, url, grid_id):
    text = page(client.get(url))
    assert f'id="{grid_id}"' in text
    assert f'data-filter-input="#{grid_id}"' in text


def test_course_cards_keep_the_equal_height_grid(client):
    assert grid_classes(page(client.get("/configuration/courses/")), "course-list") == ["card-grid"]


def test_class_patterns_keep_the_equal_height_grid(client):
    assert grid_classes(page(client.get("/configuration/patterns/"))) == ["card-grid"]


def test_the_base_grid_still_stretches_and_the_modifier_does_not():
    declared = rules(CSS.read_text())
    base = [body for sel, body in declared if sel == ".card-grid"]
    modifier = [body for sel, body in declared if sel == ".card-grid--start"]
    assert base and re.search(r"align-items:\s*stretch", base[0])
    assert modifier and re.search(r"align-items:\s*start", modifier[0])


def test_the_modifier_comes_after_the_base_rule_so_it_wins():
    selectors = [sel for sel, _ in rules(CSS.read_text())]
    assert selectors.index(".card-grid--start") > selectors.index(".card-grid")


def test_the_modifier_changes_nothing_but_the_alignment():
    modifier = next(body for sel, body in rules(CSS.read_text()) if sel == ".card-grid--start")
    assert [d.split(":")[0].strip() for d in modifier.split(";") if d.strip()] == ["align-items"]


def test_the_single_column_layout_on_small_screens_is_untouched():
    text = CSS.read_text()
    assert re.search(r"\.card-grid,\s*\.day-grid,\s*\.split\s*\{\s*grid-template-columns:\s*1fr;", text)
