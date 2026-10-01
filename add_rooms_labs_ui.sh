#!/usr/bin/env bash
# Adds the Rooms and Labs pages to the Django GUI (Configuration Editor, Section 7).
#
# The rooms/labs *controllers* (gui/controllers/rooms.py, labs.py) already exist from
# PR #81 but nothing in the browser used them. This script adds the missing front end,
# following the Time Slots pattern:
#
#   gui/forms.py                         + RoomForm, LabForm, availability helpers
#   gui/views_rooms.py, views_labs.py    new: list / add / edit / delete views
#   gui/urls.py                          + routes under /configuration/rooms/ and /labs/
#   gui/views.py                         "Rooms" and "Labs" rows on the editor home now link
#   gui/templates/gui/*                  new: rooms/labs list, edit, delete pages
#   gui/templates/gui/config_editor.html TODO text updated
#   tests/test_gui_rooms_labs.py         new: page and form tests for both
#
# Run from anywhere inside the repo:   bash add_rooms_labs_ui.sh
# Safe to re-run: it stops if it has already been applied. Undo with: git checkout . && git clean -fd gui tests
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

if [ ! -f gui/controllers/rooms.py ] || [ ! -f gui/controllers/labs.py ] || [ ! -f gui/views.py ]; then
    echo "ERROR: run this inside the 2026fa-420-10F2C repo, after pulling develop (needs gui/controllers/rooms.py and labs.py)." >&2
    exit 1
fi
if [ -f gui/views_rooms.py ]; then
    echo "Already applied (gui/views_rooms.py exists). Nothing to do." >&2
    exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Writes a room-flavoured template, then makes the lab copy by renaming room -> lab.
# __BLURB__ is the one sentence that differs between the two pages.
ROOM_BLURB="Rooms are where lecture meetings are held. Courses list the rooms they may use, and faculty can have room preferences."
LAB_BLURB="Labs are the computer or lab spaces used for lab meetings. Courses list the labs they may use, and faculty can have lab preferences."

make_pair() {  # make_pair <template-file> <room-dest> <lab-dest>
    sed -e "s|__BLURB__|$ROOM_BLURB|g" "$1" > "$2"
    sed -e 's/rooms/labs/g' -e 's/Rooms/Labs/g' -e 's/room/lab/g' -e 's/Room/Lab/g' \
        -e "s|__BLURB__|$LAB_BLURB|g" "$1" > "$3"
}

# ---------------------------------------------------------------------- #
#  1. Forms (patch gui/forms.py)
# ---------------------------------------------------------------------- #
python3 - <<'PY'
from pathlib import Path

path = Path("gui/forms.py")
text = path.read_text()

def replace_once(old, new):
    global text
    assert text.count(old) == 1, f"forms.py: expected exactly one match for {old!r}"
    text = text.replace(old, new)

# Docstring bookkeeping.
replace_once(
    "    - ScheduleImportForm (Schedule Viewer: load schedules from a JSON file)\n",
    "    - ScheduleImportForm (Schedule Viewer: load schedules from a JSON file)\n"
    "    - RoomForm / LabForm (rooms and labs: name, capacity, features, availability)\n",
)
replace_once("    - RoomForm            (name, capacity, features, availability)\n", "")
replace_once("    - LabForm             (name, capacity, features, availability)\n", "")

replace_once("from django import forms\n", "import re\n\nfrom django import forms\n")

text = text.rstrip("\n") + '''


# ---------------------------------------------------------------------- #
#  Rooms and Labs (Section 7). The two have identical fields, so they share
#  one base class; the controllers (gui/controllers/rooms.py, labs.py) do the
#  real validation and the reference checks.
# ---------------------------------------------------------------------- #
_AVAILABILITY_LINE = re.compile(r"^(\\w+)\\s+(\\d{1,2}):(\\d{2})\\s*-\\s*(\\d{1,2}):(\\d{2})$")


def parse_availability(text):
    """Turn the availability box into {"MON": [{"start": "09:00", "end": "17:00"}], ...}.

    One range per line, e.g. "MON 09:00-17:00"; a day may appear on several
    lines. Returns (times, problems). `times` is None when the box is blank,
    which means "available any time". Only the shape is checked here; whether
    a range is acceptable (end after start, etc.) is decided by the scheduler
    library through the controller.
    """
    times = {}
    problems = []
    for number, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        match = _AVAILABILITY_LINE.match(line)
        if not match:
            problems.append(f'Line {number} ("{line}") is not in the form MON 09:00-17:00.')
            continue
        day = match.group(1).upper()
        if day not in DAY_NAMES:
            problems.append(
                f"Line {number}: '{match.group(1)}' is not a weekday. Use one of: {', '.join(DAY_NAMES)}."
            )
            continue
        start_h, start_m, end_h, end_m = (int(part) for part in match.groups()[1:])
        if start_h > 23 or end_h > 23 or start_m > 59 or end_m > 59:
            problems.append(f"Line {number}: use 24-hour times such as 09:00 or 17:30.")
            continue
        times.setdefault(day, []).append(
            {"start": f"{start_h:02d}:{start_m:02d}", "end": f"{end_h:02d}:{end_m:02d}"}
        )
    return (times or None), problems


def availability_to_text(times):
    """The reverse of parse_availability, for filling the box when editing."""
    lines = []
    for day in DAY_NAMES:
        for block in (times or {}).get(day, []):
            lines.append(f"{day} {block['start']}-{block['end']}")
    return "\\n".join(lines)


class _SpaceForm(forms.Form):
    name = forms.CharField(
        label="Name",
        help_text="Must be unique. It can only be changed while no course or faculty member uses it.",
    )
    capacity = forms.IntegerField(label="Capacity", min_value=1, help_text="Number of seats (a whole number).")
    features = forms.CharField(
        label="Features",
        required=False,
        help_text="Separated by commas, e.g. projector, whiteboard. Leave blank for none.",
    )
    times = forms.CharField(
        label="Availability",
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text=(
            "Leave blank if it is available at any time. Otherwise one range per line, "
            "e.g. MON 09:00-17:00 (24-hour times; a day can have several lines)."
        ),
    )

    def clean_times(self):
        times, problems = parse_availability(self.cleaned_data.get("times", ""))
        if problems:
            raise forms.ValidationError(problems)
        return times


class RoomForm(_SpaceForm):
    """Add or edit a room (Section 7, Rooms row)."""


class LabForm(_SpaceForm):
    """Add or edit a lab (Section 7, Labs row)."""
'''
path.write_text(text)
PY

# ---------------------------------------------------------------------- #
#  2. Views
# ---------------------------------------------------------------------- #
cat > "$TMP/views.tpl" <<'EOF'
"""
Views for the Rooms pages (Configuration Editor, Section 7, Rooms row).

Same shape as the Time Slots views in gui/views.py: parse the request, call the
controller (gui/controllers/rooms.py), then either redirect with a flash
message (success) or re-render the same page with the errors on the form
(failure), so the user's input is kept and the configuration is untouched.
Rooms are identified by name in the URL.
"""

from django.contrib import messages
from django.shortcuts import redirect, render

from gui.controllers import rooms as room_controller
from gui.controllers.errors import ControllerError
from gui.forms import RoomForm, availability_to_text
from gui.views import _attach_errors


def _render_rooms(request, add_form=None):
    data = room_controller.describe_rooms(request)
    context = {"active": "config", "data": data}
    if data["has_config"]:
        if add_form is None:
            add_form = RoomForm()
        context["add_form"] = add_form
    return render(request, "gui/rooms.html", context)


def rooms(request):
    """Rooms page: the current rooms and a form to add one."""
    return _render_rooms(request)


def room_add(request):
    if request.method != "POST":
        return redirect("gui:rooms")
    form = RoomForm(request.POST)
    if form.is_valid():
        try:
            room_controller.add_room(request, form.cleaned_data)
        except ControllerError as error:
            _attach_errors(form, error)
        else:
            messages.success(request, f"Room '{form.cleaned_data['name']}' added.")
            return redirect("gui:rooms")
    return _render_rooms(request, add_form=form)


def room_edit(request, room_name):
    try:
        room = room_controller.get_room(request, room_name)
    except ControllerError as error:
        messages.error(request, error.message)
        return redirect("gui:rooms")

    if request.method == "POST":
        form = RoomForm(request.POST)
        if form.is_valid():
            try:
                room_controller.update_room(request, room_name, form.cleaned_data)
            except ControllerError as error:
                _attach_errors(form, error)
            else:
                messages.success(request, f"Room '{form.cleaned_data['name']}' updated.")
                return redirect("gui:rooms")
    else:
        form = RoomForm(
            initial={
                "name": room["name"],
                "capacity": room["capacity"],
                "features": ", ".join(room["features"]),
                "times": availability_to_text(room["times"]),
            }
        )
    return render(request, "gui/room_edit.html", {"active": "config", "form": form, "room": room})


def room_delete(request, room_name):
    """Confirmation page (GET) and the confirm/cancel actions (POST).

    A room that a course or faculty member still uses cannot be deleted; the
    page lists what uses it instead (Section 12).
    """
    try:
        room = room_controller.get_room(request, room_name)
    except ControllerError as error:
        messages.error(request, error.message)
        return redirect("gui:rooms")

    if request.method == "POST":
        if request.POST.get("action") != "confirm":
            messages.info(request, "Cancelled.")
            return redirect("gui:rooms")
        try:
            room_controller.delete_room(request, room_name)
        except ControllerError as error:
            messages.error(request, error.message)
        else:
            messages.success(request, f"Room '{room_name}' deleted.")
        return redirect("gui:rooms")

    return render(request, "gui/room_delete.html", {"active": "config", "room": room})
EOF
make_pair "$TMP/views.tpl" gui/views_rooms.py gui/views_labs.py

# ---------------------------------------------------------------------- #
#  3. Templates
# ---------------------------------------------------------------------- #
cat > "$TMP/list.tpl" <<'EOF'
{% extends "gui/base.html" %}
{% block title %}Scheduler — Rooms{% endblock %}
{% block content %}
<p class="breadcrumb"><a href="{% url 'gui:config_editor' %}">Configuration Editor</a> &rsaquo; Rooms</p>
<h1>Rooms</h1>
<p>__BLURB__</p>

{% if not data.has_config %}
<div class="empty-state" role="status">
    <h2>No configuration is loaded</h2>
    <p>Create or load a configuration in the <a href="{% url 'gui:config_editor' %}">Configuration Editor</a> before editing rooms.</p>
</div>
{% else %}

<h2>Current rooms</h2>
<table class="data-table">
    <thead>
        <tr>
            <th scope="col">Name</th>
            <th scope="col">Capacity</th>
            <th scope="col">Features</th>
            <th scope="col">Availability</th>
            <th scope="col">Actions</th>
        </tr>
    </thead>
    <tbody>
    {% for room in data.rooms %}
        <tr>
            <td>{{ room.name }}</td>
            <td>{{ room.capacity }}</td>
            <td>{% if room.features %}{{ room.features|join:", " }}{% else %}&mdash;{% endif %}</td>
            <td>{% if room.unrestricted %}Any time{% else %}{% for row in room.availability %}{{ row.day }} {{ row.ranges }}{% if not forloop.last %}<br>{% endif %}{% endfor %}{% endif %}</td>
            <td class="actions">
                <a class="btn" href="{% url 'gui:room_edit' room.name %}">Edit</a>
                {% if room.can_delete %}
                <a class="btn btn-danger" href="{% url 'gui:room_delete' room.name %}">Delete</a>
                {% else %}
                <span class="btn btn-disabled" aria-disabled="true">Delete</span>
                <span class="help">In use by {{ room.referenced_by|join:", " }}.</span>
                {% endif %}
            </td>
        </tr>
    {% empty %}
        <tr><td colspan="5">No rooms yet. Add one below.</td></tr>
    {% endfor %}
    </tbody>
</table>

<h2>Add a room</h2>
<form method="post" action="{% url 'gui:room_add' %}" class="edit-form">
    {% csrf_token %}
    {% include "gui/components/form_fields.html" with form=add_form %}
    <button type="submit" class="btn btn-primary">Add room</button>
</form>
{% endif %}
{% endblock %}
EOF
make_pair "$TMP/list.tpl" gui/templates/gui/rooms.html gui/templates/gui/labs.html

cat > "$TMP/edit.tpl" <<'EOF'
{% extends "gui/base.html" %}
{% block title %}Scheduler — Edit Room{% endblock %}
{% block content %}
<p class="breadcrumb"><a href="{% url 'gui:config_editor' %}">Configuration Editor</a> &rsaquo; <a href="{% url 'gui:rooms' %}">Rooms</a> &rsaquo; Edit</p>
<h1>Edit room</h1>
<p>
    Editing <strong>{{ room.name }}</strong>. Nothing changes until you apply your edits.
    {% if not room.can_delete %}
    This room is used by {{ room.referenced_by|join:", " }}, so its name cannot be changed until those are removed.
    {% endif %}
</p>
<form method="post" class="edit-form">
    {% csrf_token %}
    {% include "gui/components/form_fields.html" with form=form %}
    <button type="submit" class="btn btn-primary">Apply changes</button>
    <a class="btn" href="{% url 'gui:rooms' %}">Cancel</a>
</form>
{% endblock %}
EOF
make_pair "$TMP/edit.tpl" gui/templates/gui/room_edit.html gui/templates/gui/lab_edit.html

cat > "$TMP/delete.tpl" <<'EOF'
{% extends "gui/base.html" %}
{% block title %}Scheduler — Delete Room{% endblock %}
{% block content %}
<p class="breadcrumb"><a href="{% url 'gui:config_editor' %}">Configuration Editor</a> &rsaquo; <a href="{% url 'gui:rooms' %}">Rooms</a> &rsaquo; Delete</p>
<h1>Delete room</h1>
{% if not room.can_delete %}
<div class="alert alert-error" role="alert">
    <p><strong>Cannot delete:</strong> {{ room.name }} is still used by:</p>
    <ul>
        {% for item in room.referenced_by %}<li>{{ item }}</li>{% endfor %}
    </ul>
    <p>Remove this room from those records first.</p>
</div>
<a class="btn" href="{% url 'gui:rooms' %}">Back to rooms</a>
{% else %}
<p>
    Are you sure you want to delete <strong>{{ room.name }}</strong> (capacity {{ room.capacity }})?
    This cannot be undone.
</p>
<form method="post">
    {% csrf_token %}
    <button type="submit" name="action" value="confirm" class="btn btn-danger">Delete room</button>
    <button type="submit" name="action" value="cancel" class="btn">Cancel</button>
</form>
{% endif %}
{% endblock %}
EOF
make_pair "$TMP/delete.tpl" gui/templates/gui/room_delete.html gui/templates/gui/lab_delete.html

# ---------------------------------------------------------------------- #
#  4. URLs, editor home links, TODO text
# ---------------------------------------------------------------------- #
python3 - <<'PY'
from pathlib import Path


def patch(path, pairs):
    p = Path(path)
    text = p.read_text()
    for old, new in pairs:
        assert text.count(old) == 1, f"{path}: expected exactly one match for {old!r}"
        text = text.replace(old, new)
    p.write_text(text)


routes = ""
for kind, plural in (("room", "rooms"), ("lab", "labs")):
    routes += (
        f'    path("configuration/{plural}/", views_{plural}.{plural}, name="{plural}"),\n'
        f'    path("configuration/{plural}/add/", views_{plural}.{kind}_add, name="{kind}_add"),\n'
        f'    path("configuration/{plural}/<path:{kind}_name>/edit/", views_{plural}.{kind}_edit, name="{kind}_edit"),\n'
        f'    path("configuration/{plural}/<path:{kind}_name>/delete/", views_{plural}.{kind}_delete, name="{kind}_delete"),\n'
    )

delete_route = (
    '    path("configuration/timeslots/<str:day>/<int:index>/delete/", views.timeslot_delete, name="timeslot_delete"),\n'
)
patch(
    "gui/urls.py",
    [
        ("from . import views\n", "from . import views, views_labs, views_rooms\n"),
        (delete_route, delete_route + routes),
    ],
)

patch(
    "gui/views.py",
    [
        ('    ("rooms", "Rooms", None),\n', '    ("rooms", "Rooms", "gui:rooms"),\n'),
        ('    ("labs", "Labs", None),\n', '    ("labs", "Labs", "gui:labs"),\n'),
    ],
)

patch(
    "gui/templates/gui/config_editor.html",
    [
        (
            "CRUD forms for: Rooms, Labs, Courses, Faculty, Class Patterns, Meetings, Global Settings (Section 7) &mdash; Time Slots are done",
            "CRUD forms for: Courses, Faculty, Class Patterns, Meetings, Global Settings (Section 7) &mdash; Time Slots, Rooms and Labs are done",
        )
    ],
)
PY

# ---------------------------------------------------------------------- #
#  5. Tests
# ---------------------------------------------------------------------- #
cat > tests/test_gui_rooms_labs.py <<'EOF'
"""
Tests for the Rooms and Labs pages (Sprint 2 Section 7) and the forms behind
them (gui/forms.py, gui/views_rooms.py, gui/views_labs.py).

Rooms and labs behave the same, so every page test runs once for each. They run
against the REAL scheduler library and the shipped example configuration, where
every room and lab is used by a course: that is what makes "cannot delete" and
"cannot rename" testable. To test a delete that works, a test adds a new,
unused room/lab first.
"""

from urllib.parse import quote

import pytest

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


def test_renaming_something_that_is_in_use_is_blocked(client, kind):
    client.get(kind["base"])
    data = new_item(name="Renamed", capacity="30", features="", times="")
    response = client.post(edit_url(kind, kind["existing"]), data)
    assert "still referenced" in page(response)
    assert find(kind, kind["existing"]) is not None
    assert find(kind, "Renamed") is None


def test_editing_something_that_no_longer_exists_redirects_with_an_error(client, kind):
    response = client.get(edit_url(kind, "Nowhere 9"), follow=True)
    assert "no longer exists" in page(response)


def test_deleting_something_in_use_is_blocked_on_the_page_and_in_the_action(client, kind):
    client.get(kind["base"])
    text = page(client.get(delete_url(kind, kind["existing"])))
    assert "Cannot delete" in text
    assert 'value="confirm"' not in text
    response = client.post(delete_url(kind, kind["existing"]), {"action": "confirm"}, follow=True)
    assert f"Remove this {kind['key']} from those records first" in page(response)
    assert find(kind, kind["existing"]) is not None


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
EOF

echo
echo "Done. Rooms and Labs pages added. Next:"
echo "  uv run pytest tests/test_gui_rooms_labs.py tests/test_gui_controllers.py tests/test_gui_views.py"
echo "  uv run python manage.py runserver     # then open http://127.0.0.1:8000/configuration/"
git status --short