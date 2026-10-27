"""
Course and Faculty card footers (REQ-6): the "Used by" chips sit BESIDE Edit and Delete, opening the
dropdown moves nothing, and the opened list sits underneath, lined up with Edit.

The layout is CSS only, on the existing native <details>/<summary> markup, and applies only to footers
that carry the `item-card__foot--usage` modifier (Courses and Faculty). In a browser without
`::details-content` the old layout and the script-driven animation are kept. These tests pin down the
wiring; the positions themselves were measured in a real browser (see the report).
"""

import re
from pathlib import Path

import pytest

from gui import session_store

CSS = Path("gui/static/gui/css/style.css")
JS = Path("gui/static/gui/js/dropdowns.js")
TEMPLATES = Path("gui/templates/gui")
MODIFIER = "item-card__foot--usage"
FOOTER = f'<footer class="item-card__foot {MODIFIER}">'


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


def strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def inner_block(css, header):
    """The text between the braces of the first block whose header starts with `header`."""
    css = strip_comments(css)
    start = css.index(header)
    depth, i = 0, css.index("{", start)
    begin = i + 1
    while True:
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[begin:i]
        i += 1


def rules_in(text):
    return [
        (sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", text)
    ]


def body_for(rules, selector):
    return " ".join(
        body for sel, body in rules if selector in [s.strip() for s in sel.split(",")]
    )


SUPPORTS = "@supports selector(details::details-content)"
REDUCED = "@media (prefers-reduced-motion: reduce)"


@pytest.fixture(scope="module")
def layout():
    """The plain rules of the guarded block (its nested reduced-motion block is tested on its own)."""
    block = inner_block(CSS.read_text(), SUPPORTS)
    nested = inner_block(block, REDUCED)
    return rules_in(block.replace(f"{REDUCED} {{{nested}}}", ""))


# ---------------------------------------------------------------------- #
#  Markup
# ---------------------------------------------------------------------- #
def test_faculty_footers_carry_the_modifier(client):
    text = client.get("/configuration/faculty/").content.decode()
    assert text.count(FOOTER) == text.count('<footer class="item-card__foot') > 0


def test_course_footers_are_plain_with_just_edit_and_delete(client):
    text = client.get("/configuration/courses/").content.decode()
    assert MODIFIER not in text and text.count('<footer class="item-card__foot">') > 0


def test_class_pattern_footers_are_left_as_they_were(client):
    text = client.get("/configuration/patterns/").content.decode()
    assert '<footer class="item-card__foot"' in text and MODIFIER not in text


def test_the_markup_the_layout_relies_on_is_unchanged(client):
    text = client.get("/configuration/faculty/").content.decode()
    assert re.search(
        r'<footer class="item-card__foot item-card__foot--usage">\s*<a class="btn" href="[^"]+">Edit</a>\s*<a class="btn btn-danger"',
        text,
    )
    assert '<details class="usage">' in text and "<summary>" in text


# ---------------------------------------------------------------------- #
#  CSS: guarded, scoped, and doing the three jobs
# ---------------------------------------------------------------------- #
def test_the_new_layout_only_applies_where_the_browser_supports_it():
    assert SUPPORTS in strip_comments(CSS.read_text())


def test_every_rule_in_the_guarded_block_is_scoped_to_the_modifier(layout):
    assert layout
    for selector, _ in layout:
        assert all(MODIFIER in part for part in selector.split(",")), selector


def test_the_footer_is_a_grid_with_the_buttons_then_the_chips(layout):
    footer = body_for(layout, f".{MODIFIER}")
    assert re.search(r"display:\s*grid", footer)
    assert re.search(
        r"grid-template-columns:\s*auto\s+auto\s+minmax\(0,\s*1fr\)", footer
    )
    assert re.search(r"align-items:\s*center", footer)


def test_the_details_has_no_box_so_its_summary_and_list_join_the_footer_grid(layout):
    assert re.search(
        r"display:\s*contents", body_for(layout, f".{MODIFIER} > details.usage")
    )


def test_the_chips_sit_in_the_first_row_beside_the_buttons(layout):
    summary = body_for(layout, f".{MODIFIER} > details.usage > summary")
    assert re.search(r"grid-column:\s*3", summary) and re.search(
        r"grid-row:\s*1", summary
    )


def test_the_opened_list_spans_the_footer_in_the_row_below(layout):
    content = body_for(layout, f".{MODIFIER} > details.usage::details-content")
    assert re.search(r"grid-column:\s*1\s*/\s*-1", content) and re.search(
        r"grid-row:\s*2", content
    )


def test_the_card_grows_and_shrinks_smoothly_with_the_browsers_own_transition(layout):
    closed = body_for(layout, f".{MODIFIER} > details.usage::details-content")
    assert re.search(r"block-size:\s*0", closed) and re.search(
        r"overflow:\s*clip", closed
    )
    assert re.search(r"transition:[^;]*block-size[^;]*;", closed)
    assert re.search(r"content-visibility\s+[\d.]+m?s\s+allow-discrete", closed)
    assert re.search(
        r"block-size:\s*auto",
        body_for(layout, f".{MODIFIER} > details.usage[open]::details-content"),
    )
    assert re.search(
        r"interpolate-size:\s*allow-keywords", body_for(layout, f".{MODIFIER}")
    )


def test_the_motion_is_the_same_length_as_the_scripted_dropdowns(layout):
    css_ms = (
        float(
            re.search(
                r"block-size\s+([\d.]+)s",
                body_for(layout, f".{MODIFIER} > details.usage::details-content"),
            ).group(1)
        )
        * 1000
    )
    script_ms = int(re.search(r"var DURATION\s*=\s*(\d+)\s*;", JS.read_text()).group(1))
    assert css_ms == script_ms


def test_reduced_motion_removes_the_transition(layout):
    css = strip_comments(CSS.read_text())
    media = re.findall(r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{", css)
    assert media
    block = inner_block(CSS.read_text(), SUPPORTS)
    assert re.search(r"@media\s*\(prefers-reduced-motion:\s*reduce\)", block)
    inside = inner_block(block, "@media (prefers-reduced-motion: reduce)")
    assert (
        re.search(r"transition:\s*none", inside)
        and "details.usage::details-content" in inside
    )


def test_no_hard_coded_colours_in_the_new_rules(layout):
    assert not any(
        re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(", body) for _, body in layout
    )


def test_the_old_flex_footer_is_still_there_for_browsers_that_need_it():
    css = strip_comments(CSS.read_text())
    outside = css.replace(inner_block(CSS.read_text(), SUPPORTS), "")
    footer = body_for(rules_in(outside), ".item-card__foot")
    assert re.search(r"display:\s*flex", footer) and re.search(
        r"flex-wrap:\s*wrap", footer
    )


# ---------------------------------------------------------------------- #
#  The script steps aside when the details has no box
# ---------------------------------------------------------------------- #
def test_the_height_animation_script_leaves_boxless_dropdowns_to_the_stylesheet():
    js = JS.read_text()
    assert 'getComputedStyle(summary.parentNode).display === "contents"' in js
    check = js.index('display === "contents"')
    assert js.index("canAnimate()") < js.index("preventDefault") and check < js.index(
        "preventDefault"
    )


def test_the_other_dropdowns_are_still_animated_by_the_script():
    js = JS.read_text()
    assert "details.usage > summary" in js and "details.item-card__more > summary" in js
