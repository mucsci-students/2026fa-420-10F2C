"""
The open/close animation for the dropdowns on the Courses, Labs, Rooms and Faculty pages:
the "Used by" lists (details.usage) and the faculty "Availability and preferences" panels
(details.item-card__more).

It is a progressive enhancement (gui/static/gui/js/dropdowns.js): without JavaScript, in a browser
that cannot animate, or when the visitor asks for reduced motion, the dropdowns open and close
instantly exactly as before. These tests pin down the wiring and the safety properties; the motion
itself was checked in a real browser.
"""

import re
from pathlib import Path
from typing import cast

import pytest

from gui import session_store

JS = Path("gui/static/gui/js/dropdowns.js")
CSS = Path("gui/static/gui/css/style.css")
PAGES = [
    "/configuration/courses/",
    "/configuration/labs/",
    "/configuration/rooms/",
    "/configuration/faculty/",
]
SCRIPT_TAG = '<script src="/static/gui/js/dropdowns.js" defer></script>'


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


def page(response):
    return response.content.decode()


def css_rules(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    return [
        (sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)
    ]


# ---------------------------------------------------------------------- #
#  Wiring
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize("url", PAGES)
def test_every_page_with_these_dropdowns_loads_the_script_exactly_once(client, url):
    assert page(client.get(url)).count(SCRIPT_TAG) == 1


def test_the_script_is_deferred_so_it_never_blocks_the_page(client):
    html = page(client.get(PAGES[0]))
    assert SCRIPT_TAG in html and "dropdowns.js" not in html.split("<body>")[0]


def test_the_script_file_is_found_by_the_static_files_finder():
    from django.contrib.staticfiles import finders

    found = finders.find("gui/js/dropdowns.js")
    assert found and Path(found).samefile(JS)


# ---------------------------------------------------------------------- #
#  Behaviour guarantees the script must keep
# ---------------------------------------------------------------------- #
def test_it_animates_exactly_the_two_kinds_of_dropdown():
    js = JS.read_text()
    assert "details.usage > summary" in js
    assert "details.item-card__more > summary" in js
    assert (
        "add-panel" not in js and "timing-options" not in js
    )  # other dropdowns are left alone


def test_without_support_or_with_reduced_motion_it_does_nothing_so_the_browser_toggles_instantly():
    js = JS.read_text()
    assert "prefers-reduced-motion: reduce" in js
    assert "typeof Element.prototype.animate" in js
    assert re.search(
        r"if\s*\(\s*!canAnimate\(\)\s*\)\s*\{?\s*return", js
    )  # bail out BEFORE preventDefault


def test_it_only_takes_over_the_click_after_deciding_it_can_animate():
    js = JS.read_text()
    assert js.index("canAnimate()") < js.index("preventDefault")


def test_it_handles_a_second_click_in_the_middle_of_an_animation():
    js = JS.read_text()
    assert "WeakMap" in js and ".cancel()" in js


def test_it_never_leaves_the_dropdown_stuck_open_or_clipped_afterwards():
    js = JS.read_text()
    assert "onfinish" in js
    assert 'style.clipPath = ""' in js
    assert re.search(r"details\.open\s*=\s*opening", js)


def test_it_does_not_clip_the_arrow_that_hangs_beside_the_last_chip():
    js = JS.read_text()
    assert "overflow" not in js
    assert re.search(
        r'clipPath\s*=\s*"inset\(-?\d+px -\d+(rem|px) 0 -\d+(rem|px)\)"', js
    )


def test_it_builds_no_html_and_runs_no_strings():
    js = JS.read_text()
    assert "innerHTML" not in js and "eval(" not in js and "new Function" not in js


def test_the_motion_is_short_enough_not_to_feel_slow():
    duration = int(
        cast(
            "re.Match[str]", re.search(r"var DURATION\s*=\s*(\d+)\s*;", JS.read_text())
        ).group(1)
    )
    assert 150 <= duration <= 350


# ---------------------------------------------------------------------- #
#  The arrow turns in step with the motion
# ---------------------------------------------------------------------- #
def test_the_arrow_turns_smoothly():
    icon = next(
        body for sel, body in css_rules(CSS.read_text()) if sel == ".usage__icon"
    )
    assert re.search(r"transition:\s*transform\s+[\d.]+m?s", icon)


def test_the_arrow_flips_back_at_the_start_of_closing_not_at_the_end():
    selectors = [sel for sel, _ in css_rules(CSS.read_text())]
    assert (
        ".usage[open] .usage__icon" in selectors
    )  # opening: turns as soon as it opens
    assert ".usage.is-closing .usage__icon" in selectors
    assert selectors.index(".usage.is-closing .usage__icon") > selectors.index(
        ".usage[open] .usage__icon"
    )
    body = next(
        b
        for s, b in css_rules(CSS.read_text())
        if s == ".usage.is-closing .usage__icon"
    )
    assert re.search(r"transform:\s*none", body)


def test_the_script_marks_a_closing_dropdown_with_the_class_the_stylesheet_uses():
    assert "is-closing" in JS.read_text()


def test_reduced_motion_turns_the_arrow_transition_off():
    css = re.sub(r"/\*.*?\*/", "", CSS.read_text(), flags=re.DOTALL)
    assert re.search(
        r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{[^@]*?\.usage__icon\s*\{[^}]*transition:\s*none",
        css,
    )


# ---------------------------------------------------------------------- #
#  Nothing else changed
# ---------------------------------------------------------------------- #
def test_the_markup_the_animation_relies_on_is_unchanged(client):
    labs = page(client.get("/configuration/labs/"))
    assert '<details class="usage">' in labs and "<summary>" in labs
    faculty = page(client.get("/configuration/faculty/"))
    assert '<details class="item-card__more">' in faculty
