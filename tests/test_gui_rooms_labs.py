"""
Tests for the Rooms and Labs pages (Sprint 2 Section 7) and the forms behind
them (gui/forms.py, gui/views_rooms.py, gui/views_labs.py).

Rooms and labs behave the same, so every page test runs once for each. They run
against the REAL scheduler library and the shipped example configuration, where
every room and lab is used by a course: that is what makes "cannot delete" and
"cannot rename" testable. To test a delete that works, a test adds a new,
unused room/lab first.
"""

import re
from pathlib import Path
from urllib.parse import quote

import pytest
from django.template.loader import render_to_string

from gui import session_store
from gui.forms import availability_to_text, parse_availability

KINDS = {
    "room": {"base": "/configuration/rooms/", "collection": "rooms", "existing": "Roddy 136"},
    "lab": {"base": "/configuration/labs/", "collection": "labs", "existing": "Linux"},
}


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


@pytest.fixture(params=list(KINDS))
def kind(request):
    return {"key": request.param, **KINDS[request.param]}


def browser_session():
    """The single Session the current test client created."""
    return next(iter(session_store._SESSIONS.values()))


def page(response):
    return response.content.decode()


def items(kind):
    return getattr(browser_session().config.config, kind["collection"])


def find(kind, name):
    return next((item for item in items(kind) if item.name == name), None)


def edit_url(kind, name):
    return f"{kind['base']}{quote(name)}/edit/"


def delete_url(kind, name):
    return f"{kind['base']}{quote(name)}/delete/"


def removed_rename_url(kind, name):
    return f"{kind['base']}{quote(name)}/rename/confirm/"


def new_item(**overrides):
    data = {"name": "Annex 1", "capacity": "20", "features": "projector, whiteboard", "times": ""}
    data.update(overrides)
    return data


# ---------------------------------------------------------------------- #
#  The availability text helpers
# ---------------------------------------------------------------------- #
def test_blank_availability_means_any_time():
    assert parse_availability("  \n ") == (None, [])


def test_availability_lines_are_read_and_padded():
    times, problems = parse_availability("mon 9:00-17:00\nMON 18:00 - 19:00\nTUE 08:30-10:00")
    assert problems == []
    assert times == {
        "MON": [{"start": "09:00", "end": "17:00"}, {"start": "18:00", "end": "19:00"}],
        "TUE": [{"start": "08:30", "end": "10:00"}],
    }


def test_availability_problems_name_the_line():
    _, problems = parse_availability("MON 09:00-17:00\nSUN 09:00-17:00\nMON 9-5\nTUE 25:00-26:00")
    assert len(problems) == 3
    assert "Line 2" in problems[0] and "not a weekday" in problems[0]
    assert "Line 3" in problems[1] and "MON 09:00-17:00" in problems[1]
    assert "Line 4" in problems[2] and "24-hour" in problems[2]


def test_availability_text_round_trips():
    text = "MON 09:00-17:00\nMON 18:00-19:00\nWED 08:00-12:00"
    times, _ = parse_availability(text)
    assert availability_to_text(times) == text
    assert availability_to_text(None) == ""


# ---------------------------------------------------------------------- #
#  Pages (through Django's test client)
# ---------------------------------------------------------------------- #
def test_editor_home_links_to_the_page(client, kind):
    text = page(client.get("/configuration/"))
    assert f'href="{kind["base"]}"' in text


def test_list_page_shows_the_existing_items(client, kind):
    response = client.get(kind["base"])
    assert response.status_code == 200
    text = page(response)
    assert kind["existing"] in text
    assert "Unsaved changes" not in text


def test_list_page_shows_the_empty_state_without_a_configuration(client, kind, monkeypatch):
    monkeypatch.setattr(session_store, "AUTO_LOAD_EXAMPLE", False)
    response = client.get(kind["base"])
    assert response.status_code == 200
    assert "No configuration is loaded" in page(response)


def test_adding_confirms_lists_it_and_flags_unsaved_changes(client, kind):
    data = new_item(times="MON 09:00-17:00")
    response = client.post(kind["base"] + "add/", data, follow=True)
    text = page(response)
    assert "Annex 1" in text and "added" in text
    assert "MON 09:00-17:00" in text
    assert "Unsaved changes" in text
    added = find(kind, "Annex 1")
    assert added.capacity == 20
    assert sorted(added.features) == ["projector", "whiteboard"]
    assert browser_session().dirty is True


def test_adding_a_duplicate_name_is_rejected(client, kind):
    client.get(kind["base"])  # creates the session
    before = len(items(kind))
    response = client.post(kind["base"] + "add/", new_item(name=kind["existing"]))
    assert response.status_code == 200
    assert "already exists" in page(response)
    assert len(items(kind)) == before


def test_bad_capacity_is_reported_on_the_form_and_keeps_what_was_typed(client, kind):
    client.get(kind["base"])
    before = len(items(kind))
    response = client.post(kind["base"] + "add/", new_item(capacity="0"))
    text = page(response)
    assert "greater than or equal to 1" in text
    assert "Annex 1" in text  # the typed name is still in the form
    response = client.post(kind["base"] + "add/", new_item(capacity="lots"))
    assert "Enter a whole number" in page(response)
    assert len(items(kind)) == before


def test_bad_availability_is_reported_and_nothing_is_added(client, kind):
    client.get(kind["base"])
    before = len(items(kind))
    response = client.post(kind["base"] + "add/", new_item(times="SUN 09:00-17:00"))
    assert "is not a weekday" in page(response)
    assert len(items(kind)) == before


def test_get_on_the_add_url_just_redirects(client, kind):
    assert client.get(kind["base"] + "add/").status_code == 302


def test_edit_page_shows_the_current_values_and_changes_nothing_until_submitted(client, kind):
    client.get(kind["base"])
    original = find(kind, kind["existing"]).capacity
    response = client.get(edit_url(kind, kind["existing"]))
    assert response.status_code == 200
    text = page(response)
    assert f'value="{kind["existing"]}"' in text
    assert f'value="{original}"' in text
    assert find(kind, kind["existing"]).capacity == original


def test_editing_applies_on_submit(client, kind):
    client.get(kind["base"])
    data = new_item(name=kind["existing"], capacity="30", features="", times="")
    response = client.post(edit_url(kind, kind["existing"]), data, follow=True)
    assert "updated" in page(response)
    assert find(kind, kind["existing"]).capacity == 30


def test_renaming_something_in_use_updates_all_references_directly(client, kind):
    client.get(kind["base"])
    data = new_item(name="Renamed", capacity="30", features="", times="")
    response = client.post(edit_url(kind, kind["existing"]), data, follow=True)
    assert "updated" in page(response)
    assert f"Renamed &#x27;{kind['existing']}&#x27; to &#x27;Renamed&#x27;" in page(response)
    assert find(kind, kind["existing"]) is None
    assert find(kind, "Renamed") is not None

    course_field = kind["key"]
    preference_field = f"{kind['key']}_preferences"
    assert any("Renamed" in (getattr(course, course_field) or []) for course in browser_session().config.config.courses)
    assert all(kind["existing"] not in (getattr(course, course_field) or []) for course in browser_session().config.config.courses)
    assert any(
        "Renamed" in (getattr(person, preference_field) or {})
        for person in browser_session().config.config.faculty
    )


def test_rename_confirmation_page_is_not_available(client, kind):
    """Rooms and labs now expose only their direct edit endpoints."""
    assert client.get(removed_rename_url(kind, kind["existing"])).status_code == 404


def test_editing_something_that_no_longer_exists_redirects_with_an_error(client, kind):
    response = client.get(edit_url(kind, "Nowhere 9"), follow=True)
    assert "no longer exists" in page(response)


ROOM_KIND = {"key": "room", **KINDS["room"]}
LAB_KIND = {"key": "lab", **KINDS["lab"]}


def test_list_page_summarises_usage_instead_of_listing_everything(client, kind):
    text = page(client.get(kind["base"]))
    assert "Used by" in text
    assert '<details class="usage">' in text
    assert "In use by" not in text


def usage_icons(text):
    return re.findall(r'<svg class="usage__icon".*?</svg>', text, flags=re.S)


def test_usage_toggle_is_a_small_dropdown_icon_not_a_details_link(client, kind):
    text = page(client.get(kind["base"]))
    assert "usage__toggle" not in text
    assert ">details<" not in text


def test_the_icon_sits_next_to_the_faculty_preference_chip_not_inside_it(client, kind):
    text = page(client.get(kind["base"]))
    assert re.search(r'faculty preferences?</span><svg class="usage__icon"', text)
    assert not re.search(r'<span class="chip[^"]*">[^<]*<svg', text)  # never inside a chip


def test_every_row_in_use_has_exactly_one_icon_after_its_last_chip(client, kind):
    text = page(client.get(kind["base"]))
    rows = text.count('<details class="usage">')
    assert rows > 0 and len(usage_icons(text)) == rows
    summaries = re.findall(r'<details class="usage">\s*<summary>(.*?)</summary>', text, flags=re.S)
    assert len(summaries) == rows
    for summary in summaries:
        assert summary.count("<svg") == 1
        assert re.search(r'<span class="chip[^"]*">[^<]*</span><svg class="usage__icon"', summary)
        assert summary.strip().endswith("</span>")  # nothing after the icon's hidden label


def test_the_icon_is_small_even_before_the_stylesheet_loads(client, kind):
    icon = usage_icons(page(client.get(kind["base"])))[0]
    width, height = (int(re.search(rf'{name}="(\d+)"', icon).group(1)) for name in ("width", "height"))
    assert 6 <= width <= 12 and 6 <= height <= 12


def test_the_icon_stylesheet_keeps_it_small(client):
    css = Path("gui/static/gui/css/style.css").read_text()
    size = re.search(r"\.usage__icon\s*\{[^}]*?width:\s*([\d.]+)rem", css)
    assert size and float(size.group(1)) <= 0.7
    assert re.search(r"\.usage__end\s*\{[^}]*white-space:\s*nowrap", css)  # icon never wraps away from its chip


def test_the_icon_is_hidden_from_screen_readers_but_the_control_keeps_a_name(client, kind):
    text = page(client.get(kind["base"]))
    assert 'aria-hidden="true"' in usage_icons(text)[0]
    assert '<span class="visually-hidden"> (show details)</span>' in text


def test_rooms_and_labs_use_the_identical_icon(client):
    room_icons = usage_icons(page(client.get(ROOM_KIND["base"])))
    lab_icons = usage_icons(page(client.get(LAB_KIND["base"])))
    assert room_icons and lab_icons
    assert set(room_icons) == set(lab_icons) and len(set(room_icons)) == 1


def test_the_other_pages_keep_the_text_toggle_by_default():
    in_use = {"in_use": True, "groups": [{"chip": "2 courses", "tone": "", "title": "Used by", "names": ["A", "B"]}]}
    plain = render_to_string("gui/components/usage_summary.html", {"usage": in_use})
    assert 'class="usage__toggle">details<' in plain and "usage__icon" not in plain
    icon = render_to_string("gui/components/usage_summary.html", {"usage": in_use, "icon": True})
    assert "usage__icon" in icon and "usage__toggle" not in icon


def test_the_icon_is_next_to_the_last_chip_whatever_the_number_of_chips():
    def group(chip):
        return {"chip": chip, "tone": "", "title": chip, "names": ["A"]}

    for groups in ([group("1 course")], [group("1 course"), group("2 faculty preferences")]):
        text = render_to_string(
            "gui/components/usage_summary.html", {"usage": {"in_use": True, "groups": groups}, "icon": True}
        )
        assert text.count("usage__icon") == 1
        assert re.search(rf'{re.escape(groups[-1]["chip"])}</span><svg class="usage__icon"', text)
        assert not re.search(r'<span class="chip[^"]*">[^<]*<svg', text)


def test_a_record_that_is_not_in_use_has_no_icon():
    text = render_to_string("gui/components/usage_summary.html", {"usage": {"in_use": False, "groups": []}, "icon": True})
    assert "usage__icon" not in text and "Not in use" in text


def test_the_icon_styles_use_theme_colours_and_flip_when_open():
    css = Path("gui/static/gui/css/style.css").read_text()
    assert ".usage__icon" in css
    assert re.search(r"\.usage\[open\]\s+\.usage__icon\s*\{[^}]*rotate\(180deg\)", css)
    block = re.search(r"\.usage__icon\s*\{[^}]*\}", css).group(0)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", block) and "rgb" not in block
    markup = Path("gui/templates/gui/components/usage_summary.html").read_text()
    assert "style=" not in markup and 'stroke="currentColor"' in markup  # inherits the chip's themed colour


def css_block(css, selector):
    """The declarations of the rule(s) whose selector list contains `selector`."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)  # a comment above a rule must not become part of its selector
    blocks = re.findall(r"([^{}]+)\{([^}]*)\}", css)
    return " ".join(body for selectors, body in blocks if selector in [s.strip() for s in selectors.split(",")])


def test_the_tables_are_marked_for_centered_columns_and_other_tables_are_not(client, kind):
    text = page(client.get(kind["base"]))
    assert re.search(rf'<table class="data-table data-table--centered" id="{kind["key"]}-list">', text)
    other = page(client.get("/configuration/timeslots/"))
    assert "data-table--centered" not in other


def test_headers_and_cells_share_one_center_line_in_both_tables(client, kind):
    text = page(client.get(kind["base"]))
    head = re.search(r"<thead>(.*?)</thead>", text, flags=re.S).group(1)
    assert [h.strip() for h in re.findall(r"<th[^>]*>(.*?)</th>", head)] == [
        "Name", "Capacity", "Features", "Availability", "Used by", "Actions",
    ]
    row = re.search(r"<tbody>\s*<tr data-filter-item>(.*?)</tr>", text, flags=re.S).group(1)
    assert len(re.findall(r"<td[ >]", row)) == 6  # one cell under every heading


def test_the_stylesheet_centers_the_headers_and_cells_of_those_tables_only(client):
    css = Path("gui/static/gui/css/style.css").read_text()
    for selector in (".data-table--centered th", ".data-table--centered td"):
        assert re.search(r"text-align:\s*center", css_block(css, selector)), selector
    # the "Used by" summary is a flex row, so it needs justify-content to centre its chips and arrow
    assert re.search(r"justify-content:\s*center", css_block(css, ".data-table--centered .usage > summary"))
    assert re.search(r"text-align:\s*left", css_block(css, ".data-table--centered .usage__group"))
    assert re.search(r"text-align:\s*left", css_block(css, ".data-table th"))  # every other table is unchanged


def test_centered_cells_keep_their_content_on_the_same_line_as_the_header(client):
    css = Path("gui/static/gui/css/style.css").read_text()
    cells = css_block(css, ".data-table--centered td")
    assert re.search(r"vertical-align:\s*middle", cells)


def test_the_arrow_hangs_beside_its_chip_so_the_chips_stay_centered_under_the_heading(client):
    """An arrow that takes part in the centring would push its chip left of the "Used by" heading."""
    css = Path("gui/static/gui/css/style.css").read_text()
    assert re.search(r"position:\s*relative", css_block(css, ".usage__end"))
    icon = css_block(css, ".usage__icon")
    assert re.search(r"position:\s*absolute", icon)
    assert re.search(r"left:\s*calc\(100%", icon)  # starts where the chip ends


def test_deleting_something_in_use_shows_what_will_change(client, kind):
    client.get(kind["base"])
    text = page(client.get(delete_url(kind, kind["existing"])))
    assert "also changes other records" in text
    assert 'value="confirm"' in text


def test_room_cascade_needs_no_tick_even_when_a_course_would_lose_its_only_room(client):
    client.get(ROOM_KIND["base"])
    text = page(client.get(delete_url(ROOM_KIND, "Roddy 136")))
    assert 'type="checkbox"' not in text and 'name="confirm_extra"' not in text
    assert "Course sections that would be deleted" in text  # the page still says what the click will do
    response = client.post(delete_url(ROOM_KIND, "Roddy 136"), {"action": "confirm"}, follow=True)
    assert response.status_code == 200 and "Tick the box" not in page(response)
    assert find(ROOM_KIND, "Roddy 136") is None


def test_room_cascade_removes_every_reference_in_one_step(client):
    client.get(ROOM_KIND["base"])
    response = client.post(delete_url(ROOM_KIND, "Roddy 136"), {"action": "confirm"}, follow=True)
    assert "deleted" in page(response) and "Removed" in page(response)
    config = browser_session().config.config
    assert find(ROOM_KIND, "Roddy 136") is None
    assert all("Roddy 136" not in (course.room or []) for course in config.courses)
    assert all("Roddy 136" not in (person.room_preferences or {}) for person in config.faculty)
    assert all(course.room for course in config.courses)
    assert browser_session().dirty is True


def test_lab_cascade_leaves_the_section_without_one_and_names_no_other_lab(client):
    client.get(LAB_KIND["base"])
    client.post(delete_url(LAB_KIND, "Mac"), {"action": "confirm"}, follow=True)
    config = browser_session().config.config
    assert find(LAB_KIND, "Mac") is None
    assert [list(course.lab) for course in config.courses if course.course_id == "CMSC 420"] == [[]]


def test_a_cascade_that_fails_whole_config_validation_changes_nothing_and_explains(client, monkeypatch):
    """If the library rejects the cascade, the page says why, the room is still
    there, and no undo entry is recorded. (The rejection is simulated, as in the
    other rollback tests; the library's edit mode provides the real atomicity.)"""
    from app.crud import ValidationFailure
    from gui.controllers import rooms as rooms_ctrl

    def reject(session_, config, area, mutate, label=None):
        raise ValidationFailure(area, "simulated whole-config rejection")

    client.get(ROOM_KIND["base"])
    before = browser_session().config.model_dump_json()
    monkeypatch.setattr(rooms_ctrl, "apply_session_edit", reject)

    response = client.post(delete_url(ROOM_KIND, "Roddy 136"), {"action": "confirm"})

    assert response.status_code == 200
    text = page(response)
    assert "was not deleted and nothing was changed" in text
    assert "simulated whole-config rejection" in text
    assert find(ROOM_KIND, "Roddy 136") is not None
    assert browser_session().config.model_dump_json() == before
    assert browser_session().history.can_undo is False
    assert browser_session().dirty is False


def test_delete_asks_first_and_cancel_changes_nothing(client, kind):
    client.post(kind["base"] + "add/", new_item())
    text = page(client.get(delete_url(kind, "Annex 1")))
    assert "Are you sure" in text and "Annex 1" in text
    response = client.post(delete_url(kind, "Annex 1"), {"action": "cancel"}, follow=True)
    assert "Cancelled." in page(response)
    assert find(kind, "Annex 1") is not None


def test_confirming_a_delete_removes_it(client, kind):
    client.post(kind["base"] + "add/", new_item())
    response = client.post(delete_url(kind, "Annex 1"), {"action": "confirm"}, follow=True)
    assert "deleted" in page(response)
    assert find(kind, "Annex 1") is None
