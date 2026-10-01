#!/usr/bin/env bash
#
# apply_config_lifecycle.sh
#
# Adds the Configuration Editor lifecycle actions -- New / Load / Save /
# Validate, with unsaved-changes protection on New and Load (Sprint 2
# Sections 8-10) -- to the `develop` branch of 2026fa-420-10F2C.
#
# Run it from the REPOSITORY ROOT (the folder with manage.py):
#
#     bash apply_config_lifecycle.sh
#
# What it does:
#   * stages every change in a temporary folder, checks that each patch
#     matches the code it expects, and byte-compiles every Python file;
#   * only then copies the result into the repo. If anything fails, your
#     repo is left exactly as it was.
#   * it never runs git commands that change anything -- no commits, no
#     pushes. Review with `git status` / `git diff`, commit when you are happy.
#
set -euo pipefail

PYTHON="$(command -v python3 || command -v python || true)"
if [[ -z "$PYTHON" ]]; then
    echo "python3 is required to apply the patches." >&2
    exit 1
fi

if [[ ! -f manage.py || ! -f app/session.py || ! -f gui/views.py ]]; then
    echo "Run this from the repository root (the folder containing manage.py)." >&2
    exit 1
fi

if [[ -e gui/controllers/common.py ]]; then
    echo "gui/controllers/common.py already exists -- this looks already applied. Nothing changed." >&2
    exit 1
fi

TOUCHED=("app/session.py" "app/commands/configuration.py" "gui/controllers/errors.py" "gui/controllers/timeslots.py" "gui/forms.py" "gui/urls.py" "gui/views.py" "gui/controllers/config_controller.py" "gui/templates/gui/config_editor.html")
if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if ! git diff --quiet HEAD -- "${TOUCHED[@]}" 2>/dev/null; then
        echo "You have uncommitted changes in files this script edits:" >&2
        git diff --name-only HEAD -- "${TOUCHED[@]}" >&2
        echo "Commit or stash them first so the changes are easy to review. Nothing changed." >&2
        exit 1
    fi
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# ---- 1. stage copies of the files that get patched ------------------------
for f in "app/session.py" "app/commands/configuration.py" "gui/controllers/errors.py" "gui/controllers/timeslots.py" "gui/forms.py" "gui/urls.py" "gui/views.py"; do
    mkdir -p "$STAGE/$(dirname "$f")"
    cp "$f" "$STAGE/$f"
done

# ---- 2. stage the new / replaced files --------------------------------------
mkdir -p "$STAGE/gui/controllers"
cat > "$STAGE/gui/controllers/common.py" <<'__FILE_0_EOF__'
"""
Helpers shared by every Configuration Editor controller (Sections 7, 10, 11).

Each configuration area (time slots today; rooms, labs, courses, faculty,
class patterns, meetings and global settings next) needs the same two things
before and after it changes the configuration:

    require_config(session, "adding a room")
        Get the loaded CombinedConfig, or raise a ControllerError that tells
        the user to create or load one first (the Section 19 empty state).

    apply_config_edit(session, config, "room", mutate, form_fields=...)
        Run `mutate(draft)` through app.crud.apply_edit(), which re-validates
        the COMPLETE configuration and leaves the previous valid one untouched
        on failure (Sections 10 and 11), mark the session as having unsaved
        changes on success, and turn any library failure into a
        ControllerError the view can show on the form.

New controllers should call these instead of copying them, so every area
reports problems and tracks unsaved changes the same way.
"""

from __future__ import annotations

from typing import Callable, Iterable

from app.commands.common import apply_session_edit
from app.crud import ValidationFailure
from app.session import ConfigError
from gui.controllers.errors import ControllerError, to_controller_error


def require_config(session, doing: str = "editing"):
    """Return the session's configuration, or raise a ControllerError.

    `doing` completes the sentence "... before <doing>." so each page can say
    what the user was trying to do, e.g. "editing time slots".
    """
    try:
        return session.require_config()
    except ConfigError as error:
        raise ControllerError(
            f"No configuration is loaded. Create or load one before {doing}."
        ) from error


def apply_config_edit(
    session,
    config,
    area: str,
    mutate: Callable[[object], None],
    form_fields: Iterable[str] = (),
) -> None:
    """Apply an atomic, fully validated edit and mark the session dirty.

    `area` is the human label used in error messages ("room", "course", ...).
    `form_fields` names the form fields library errors may be attached to.
    """
    try:
        apply_session_edit(session, config, area, mutate)
    except ValidationFailure as error:
        raise to_controller_error(error, form_fields=form_fields) from error
__FILE_0_EOF__

mkdir -p "$STAGE/gui/controllers"
cat > "$STAGE/gui/controllers/config_controller.py" <<'__FILE_1_EOF__'
"""
Controller for Configuration Editor lifecycle actions (Sections 8-10):
New, Load, Save and Validate, plus the summary the editor home page shows.

Every function gets this browser's Session through
gui.session_store.get_session(request) and calls the same app/ code the CLI
uses (Session.new_config, Session.load_bytes, Session.dumps and
app.commands.configuration.revalidate). Validation is NOT reimplemented here
(Section 3). Anything the user can fix raises ControllerError; nothing in this
module builds an HttpResponse or touches a template (Section 20).

State safety (Sections 8 and 10): Session.load_bytes() swaps the new
configuration in only after the whole file has been read and validated, so
every failure leaves the previous valid configuration exactly as it was.
"""

from __future__ import annotations

import re

from scheduler.config import ValidationError

from app.commands.configuration import revalidate
from app.session import ConfigError
from gui.controllers.common import require_config
from gui.controllers.errors import ControllerError, FieldError, describe_problems
from gui.controllers.uploads import read_upload
from gui.session_store import get_session

LOAD_FIELD = "config_file"
DEFAULT_FILENAME = "scheduler_config.json"
MAX_PROBLEMS = 8  # how many validation problems to list before "...and N more"
KEPT = "Your current configuration was kept."


# ---------------------------------------------------------------------- #
#  Page summary
# ---------------------------------------------------------------------- #
def _size(items) -> int:
    try:
        return len(items)
    except TypeError:
        return 0


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def discard_note(dirty: bool, schedule_count: int) -> str:
    """Plain-language list of what New/Load would throw away ('' if nothing).

    Starting or loading a configuration clears the schedules in the session
    too (Session.new_config / Session.load), so they are part of the warning.
    """
    parts = []
    if dirty:
        parts.append("your unsaved changes")
    if schedule_count:
        parts.append(f"the {_plural(schedule_count, 'schedule')} loaded now")
    return " and ".join(parts)


def describe_configuration(request) -> dict:
    """Everything the Configuration Editor home page needs, as plain data.

    "counts" has one entry per configuration area (None when the area has no
    meaningful count), keyed the same way as _CONFIG_AREAS in gui/views.py.
    "discard_note" is non-empty when New/Load must ask for confirmation.
    """
    session = get_session(request)
    config = session.config
    schedule_count = len(session.schedules)
    dirty = bool(session.dirty)
    state = {
        "has_config": config is not None,
        "dirty": dirty,
        "name": getattr(session, "config_name", None),
        "schedule_count": schedule_count,
        "counts": {},
        "discard_note": discard_note(dirty, schedule_count),
    }
    if config is None:
        return state

    entities = config.config
    slots = config.time_slot_config
    patterns = list(getattr(slots, "classes", None) or [])
    state["counts"] = {
        "rooms": _size(getattr(entities, "rooms", None)),
        "labs": _size(getattr(entities, "labs", None)),
        "courses": _size(getattr(entities, "courses", None)),
        "faculty": _size(getattr(entities, "faculty", None)),
        "time_blocks": sum(_size(blocks) for blocks in slots.times.values()),
        "patterns": len(patterns),
        "meetings": sum(_size(getattr(pattern, "meetings", None)) for pattern in patterns),
        "settings": None,
    }
    return state


# ---------------------------------------------------------------------- #
#  New / Load (Section 8)
# ---------------------------------------------------------------------- #
def new_configuration(request) -> None:
    """Start a fresh configuration (it holds placeholder items, because the
    library does not accept a completely empty one). The view asks for
    confirmation first when there are unsaved changes."""
    session = get_session(request)
    try:
        session.new_config()
    except ConfigError as error:
        raise ControllerError(
            f"A new configuration could not be created. {KEPT}"
        ) from error


def load_configuration(request, uploaded_file) -> str:
    """Load and validate an uploaded JSON configuration; return its file name.

    The whole file is read (read_upload) and validated (the scheduler library,
    via Session.load_bytes) before anything changes. On any problem this
    raises ControllerError on the file field and the current configuration is
    untouched.
    """
    raw = read_upload(uploaded_file, LOAD_FIELD)
    name = getattr(uploaded_file, "name", None) or "the uploaded file"
    session = get_session(request)
    try:
        session.load_bytes(raw, name)
    except ConfigError as error:
        raise ControllerError(_load_problems(error)) from error
    except Exception as error:  # noqa: BLE001 -- last resort; never lose the user's configuration
        raise ControllerError(
            [FieldError(LOAD_FIELD, f"'{name}' could not be loaded as a configuration. {KEPT}")]
        ) from error
    return name


def _load_problems(error: ConfigError) -> list[FieldError]:
    items = [FieldError(LOAD_FIELD, f"{error} {KEPT}")]
    cause = error.__cause__
    if isinstance(cause, ValidationError):
        items += [FieldError(LOAD_FIELD, text) for text in describe_problems(cause, MAX_PROBLEMS)]
    return items


# ---------------------------------------------------------------------- #
#  Save (Section 9)
# ---------------------------------------------------------------------- #
def _download_name(name: str | None) -> str:
    """A safe download file name: no path or quote characters, ends in .json."""
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", (name or "").strip()) or DEFAULT_FILENAME
    return cleaned if cleaned.lower().endswith(".json") else f"{cleaned}.json"


def save_configuration(request) -> tuple[str, str]:
    """Validate the configuration, then return (file name, JSON text).

    The text comes from the library's own Pydantic serialization. The view
    sends it as a download, so the browser decides where it goes and asks
    before replacing an existing file -- the app never overwrites anything
    on disk (Section 9). The unsaved-changes flag is cleared once the text
    is handed over.
    """
    session = get_session(request)
    require_config(session, "saving it")
    error = revalidate(session)
    if error is not None:
        raise ControllerError(
            [FieldError(None, "Not saved: the configuration is not valid.")]
            + [FieldError(None, text) for text in describe_problems(error, MAX_PROBLEMS)]
        )
    filename = _download_name(getattr(session, "config_name", None))
    content = session.dumps()
    session.mark_saved(filename)
    return filename, content


# ---------------------------------------------------------------------- #
#  Validate (Section 10)
# ---------------------------------------------------------------------- #
def validate_configuration(request) -> list[str]:
    """Re-validate the complete configuration.

    Returns [] when it is valid, otherwise plain-language problems that name
    where each one is. Raises ControllerError when nothing is loaded.
    """
    session = get_session(request)
    require_config(session, "validating it")
    error = revalidate(session)
    if error is None:
        return []
    return describe_problems(error, MAX_PROBLEMS) or ["The configuration is not valid."]
__FILE_1_EOF__

mkdir -p "$STAGE/gui/templates/gui"
cat > "$STAGE/gui/templates/gui/config_editor.html" <<'__FILE_2_EOF__'
{% extends "gui/base.html" %}
{% block title %}Scheduler — Configuration Editor{% endblock %}
{% block content %}
<h1>Configuration Editor <span class="badge">In progress</span></h1>
<p>Create, inspect, and modify a complete scheduler configuration (Sections 6&ndash;12).</p>

<h2 id="current-configuration">Current configuration</h2>
{% if has_config %}
<p class="status-line" role="status">
    {% if name %}Loaded from or saved as <strong>{{ name }}</strong>.{% else %}Not loaded from a file.{% endif %}
    {% if dirty %}<strong>Unsaved changes.</strong> Save the configuration to keep them.{% else %}No unsaved changes.{% endif %}
</p>
{% else %}
<div class="empty-state" role="status">
    <h2>No configuration loaded</h2>
    <p>Start a new configuration or load one from a file (below) to begin editing.</p>
</div>
{% endif %}

{% if report %}
<div class="alert alert-error" role="alert">
    <p><strong>Error:</strong> {{ report.heading }}</p>
    <ul>
        {% for item in report.items %}<li>{{ item }}</li>{% endfor %}
    </ul>
</div>
{% endif %}

<h2 id="save-validate">Save and validate</h2>
<p class="help">
    Saving checks the whole configuration first, then downloads it as a JSON file. Your browser decides where
    it goes and asks before replacing an existing file. Validating re-checks every rule without saving.
</p>
<form method="post" action="{% url 'gui:config_save' %}" class="edit-form">
    {% csrf_token %}
    <button type="submit" class="btn btn-primary"{% if not has_config %} disabled{% endif %}>Save configuration</button>
</form>
<form method="post" action="{% url 'gui:config_validate' %}" class="edit-form">
    {% csrf_token %}
    <button type="submit" class="btn"{% if not has_config %} disabled{% endif %}>Validate configuration</button>
</form>

<h2 id="new-configuration">Start a new configuration</h2>
<p class="help">
    A new configuration begins with one placeholder room, course, faculty member and class pattern, because the
    scheduler does not accept a completely empty one. Edit or replace them as you build real data.
</p>
<form method="post" action="{% url 'gui:config_new' %}" class="edit-form">
    {% csrf_token %}
    {% include "gui/components/form_fields.html" with form=new_form %}
    <button type="submit" class="btn">Start new configuration</button>
</form>

<h2 id="load-configuration">Load a configuration from a file</h2>
<p class="help">
    The whole file is checked before anything changes. If it has a problem, you will see what is wrong and the
    configuration you have now stays as it is.
</p>
<form method="post" action="{% url 'gui:config_load' %}" enctype="multipart/form-data" class="edit-form">
    {% csrf_token %}
    {% include "gui/components/form_fields.html" with form=load_form %}
    <button type="submit" class="btn btn-primary">Load configuration</button>
</form>

{% if has_config %}
<h2 id="areas">Configuration areas</h2>
<table class="data-table">
    <thead>
        <tr><th scope="col">Area</th><th scope="col">Items</th><th scope="col">Actions</th></tr>
    </thead>
    <tbody>
        {% for area in areas %}
        <tr>
            <td>{{ area.label }}</td>
            <td>{% if area.count is not None %}{{ area.count }}{% else %}&mdash;{% endif %}</td>
            <td class="actions">{% if area.url %}<a href="{{ area.url }}">Open</a>{% else %}Coming soon{% endif %}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% endif %}

<div class="todo-list">
<strong>TODO before this mode is complete:</strong>
<ul>
    <li>CRUD forms for: Rooms, Labs, Courses, Faculty, Class Patterns, Meetings, Global Settings (Section 7) &mdash; Time Slots are done</li>
    <li>Validation errors shown on the form itself; previous valid config preserved on any failure (Section 10)</li>
    <li>Draft vs. valid state separation &mdash; Cancel must leave the stored config unchanged (Section 11)</li>
    <li>Safe deletion &mdash; block or confirm when an item is still referenced elsewhere, and show what references it (Section 12)</li>
    <li>Empty / loading / error states specific to this page (Section 19)</li>
</ul>
</div>
{% endblock %}
__FILE_2_EOF__

mkdir -p "$STAGE/tests"
cat > "$STAGE/tests/test_gui_config_lifecycle.py" <<'__FILE_3_EOF__'
"""
Tests for the Configuration Editor lifecycle actions (Sprint 2 Sections 8, 9,
10, 19, 23.2 and 23.6): New / Load / Save / Validate, the unsaved-changes
confirmation, and "a failed action leaves the current configuration alone".

Same approach as tests/test_gui_timeslots.py: everything runs against the REAL
scheduler library and the shipped example configuration. The controller is
tested directly first (independent of Django's request cycle), then the pages.
"""

import json
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from app.session import Session
from gui import session_store
from gui.controllers import config_controller as ctrl
from gui.controllers.errors import ControllerError

EXAMPLE = "app/examples/config_example.json"

EDITOR_URL = "/configuration/"
NEW_URL = "/configuration/new/"
LOAD_URL = "/configuration/load/"
SAVE_URL = "/configuration/save/"
VALIDATE_URL = "/configuration/validate/"


def example_bytes() -> bytes:
    return Path(EXAMPLE).read_bytes()


def upload(raw: bytes, name: str = "fall.json") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, raw, content_type="application/json")


def message_of(error: ControllerError) -> str:
    return error.message


# ---------------------------------------------------------------------- #
#  Controller (called directly, independent of Django's request cycle)
# ---------------------------------------------------------------------- #
@pytest.fixture
def session(monkeypatch):
    """A Session holding the example config, handed to the controller in place
    of the per-browser lookup."""
    loaded = Session()
    loaded.load(EXAMPLE)
    monkeypatch.setattr(ctrl, "get_session", lambda request: loaded)
    return loaded


@pytest.fixture
def empty_session(monkeypatch):
    empty = Session()
    monkeypatch.setattr(ctrl, "get_session", lambda request: empty)
    return empty


class TestLoad:
    def test_loads_a_valid_file_and_records_its_name(self, empty_session):
        name = ctrl.load_configuration(None, upload(example_bytes()))
        assert name == "fall.json"
        assert empty_session.config is not None
        assert empty_session.config_name == "fall.json"
        assert empty_session.dirty is False

    def test_load_replaces_unsaved_state_and_clears_schedules(self, session):
        session.dirty = True
        session.schedules = ["old schedule"]
        ctrl.load_configuration(None, upload(example_bytes()))
        assert session.dirty is False
        assert session.schedules == []

    def test_invalid_json_is_rejected_and_the_current_config_kept(self, session):
        before = session.config
        with pytest.raises(ControllerError) as info:
            ctrl.load_configuration(None, upload(b"{not json"))
        assert "not valid JSON" in message_of(info.value)
        assert "current configuration was kept" in message_of(info.value)
        assert session.config is before

    def test_json_that_is_not_an_object_is_rejected(self, session):
        before = session.config
        with pytest.raises(ControllerError) as info:
            ctrl.load_configuration(None, upload(b"[1, 2, 3]"))
        assert "JSON object" in message_of(info.value)
        assert session.config is before

    def test_a_file_that_fails_validation_is_rejected_and_the_current_config_kept(self, session):
        data = json.loads(example_bytes())
        data["config"]["rooms"] = []
        before = session.config
        with pytest.raises(ControllerError) as info:
            ctrl.load_configuration(None, upload(json.dumps(data).encode()))
        assert "not a valid configuration" in message_of(info.value)
        assert "current configuration was kept" in message_of(info.value)
        assert session.config is before

    def test_an_empty_file_is_rejected(self, session):
        before = session.config
        with pytest.raises(ControllerError) as info:
            ctrl.load_configuration(None, upload(b"   "))
        assert "empty" in message_of(info.value)
        assert session.config is before

    def test_no_file_is_rejected(self, session):
        with pytest.raises(ControllerError):
            ctrl.load_configuration(None, None)


class TestNew:
    def test_starts_a_fresh_configuration(self, session):
        session.dirty = True
        session.schedules = ["old schedule"]
        ctrl.new_configuration(None)
        assert session.config is not None
        assert session.config_name is None
        assert session.dirty is False
        assert session.schedules == []


class TestSave:
    def test_returns_json_named_after_the_loaded_file_and_clears_the_flag(self, session):
        session.config_name = "fall.json"
        session.dirty = True
        filename, content = ctrl.save_configuration(None)
        assert filename == "fall.json"
        assert "config" in json.loads(content)
        assert session.dirty is False

    def test_uses_a_default_name_when_the_config_has_none(self, empty_session):
        empty_session.new_config()
        filename, _ = ctrl.save_configuration(None)
        assert filename == "scheduler_config.json"

    def test_download_names_are_made_safe(self, session):
        session.config_name = 'my "config" ../v2'
        filename, _ = ctrl.save_configuration(None)
        assert filename.endswith(".json")
        assert '"' not in filename and "/" not in filename

    def test_a_saved_file_loads_back_unchanged(self, session):
        _, content = ctrl.save_configuration(None)
        other = Session()
        other.load_bytes(content.encode("utf-8"), "round-trip.json")
        assert other.dumps() == content

    def test_without_a_configuration_it_explains_what_to_do(self, empty_session):
        with pytest.raises(ControllerError) as info:
            ctrl.save_configuration(None)
        assert "No configuration is loaded" in message_of(info.value)


class TestValidate:
    def test_a_valid_configuration_has_no_problems(self, session):
        assert ctrl.validate_configuration(None) == []

    def test_an_invalid_configuration_lists_plain_language_problems(self, session):
        session.config.config.rooms.clear()  # bypasses edit mode on purpose
        problems = ctrl.validate_configuration(None)
        assert problems
        assert all("Traceback" not in problem for problem in problems)

    def test_without_a_configuration_it_explains_what_to_do(self, empty_session):
        with pytest.raises(ControllerError) as info:
            ctrl.validate_configuration(None)
        assert "No configuration is loaded" in message_of(info.value)


class TestDescribe:
    def test_nothing_loaded(self, empty_session):
        state = ctrl.describe_configuration(None)
        assert state["has_config"] is False
        assert state["counts"] == {}
        assert state["discard_note"] == ""

    def test_counts_match_the_loaded_configuration(self, session):
        state = ctrl.describe_configuration(None)
        assert state["has_config"] is True
        assert state["counts"]["rooms"] == len(session.config.config.rooms)
        assert state["counts"]["courses"] == len(session.config.config.courses)
        assert state["counts"]["faculty"] == len(session.config.config.faculty)
        assert state["counts"]["time_blocks"] > 0

    def test_discard_note_names_everything_that_would_be_lost(self, session):
        session.dirty = True
        session.schedules = ["a", "b"]
        note = ctrl.describe_configuration(None)["discard_note"]
        assert note == "your unsaved changes and the 2 schedules loaded now"


# ---------------------------------------------------------------------- #
#  Pages (Django test client)
# ---------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


def browser_session():
    """The single Session the current test client created."""
    return next(iter(session_store._SESSIONS.values()))


def page(response):
    return response.content.decode()


def test_editor_page_shows_the_actions_and_every_area(client):
    response = client.get(EDITOR_URL)
    assert response.status_code == 200
    text = page(response)
    for label in ("Save configuration", "Validate configuration", "Start new configuration", "Load configuration"):
        assert label in text
    for area in ("Time Slots", "Rooms", "Labs", "Courses", "Faculty", "Class Patterns", "Meetings", "Global Settings"):
        assert area in text


def test_editor_page_shows_the_empty_state_when_nothing_is_loaded(client, monkeypatch):
    monkeypatch.setattr(session_store, "AUTO_LOAD_EXAMPLE", False)
    response = client.get(EDITOR_URL)
    assert response.status_code == 200
    assert "No configuration loaded" in page(response)


def test_loading_a_valid_file_confirms_and_replaces_the_configuration(client):
    client.get(EDITOR_URL)
    response = client.post(LOAD_URL, {"load-config_file": upload(example_bytes())}, follow=True)
    assert "Loaded and validated fall.json" in page(response)
    assert browser_session().config_name == "fall.json"


def test_loading_over_unsaved_changes_needs_confirmation(client):
    client.get(EDITOR_URL)
    before = browser_session().config
    browser_session().dirty = True

    refused = client.post(LOAD_URL, {"load-config_file": upload(example_bytes())})
    assert refused.status_code == 200
    assert "Tick this box to confirm discarding your unsaved changes" in page(refused)
    assert browser_session().config is before
    assert browser_session().dirty is True

    accepted = client.post(
        LOAD_URL, {"load-config_file": upload(example_bytes()), "load-confirm_replace": "on"}, follow=True
    )
    assert "Loaded and validated fall.json" in page(accepted)
    assert browser_session().dirty is False


def test_loading_a_bad_file_shows_the_problem_and_keeps_the_configuration(client):
    client.get(EDITOR_URL)
    before = browser_session().config
    response = client.post(LOAD_URL, {"load-config_file": upload(b"{oops")})
    assert response.status_code == 200
    text = page(response)
    assert "not valid JSON" in text
    assert "current configuration was kept" in text
    assert browser_session().config is before


def test_starting_a_new_configuration_over_unsaved_changes_needs_confirmation(client):
    client.get(EDITOR_URL)
    browser_session().dirty = True

    refused = client.post(NEW_URL, {})
    assert refused.status_code == 200
    assert "Tick this box to confirm discarding your unsaved changes" in page(refused)
    assert browser_session().dirty is True

    accepted = client.post(NEW_URL, {"new-confirm_replace": "on"}, follow=True)
    assert "Started a new configuration" in page(accepted)
    assert browser_session().dirty is False
    assert browser_session().config_name is None


def test_starting_a_new_configuration_with_nothing_to_lose_needs_no_confirmation(client):
    client.get(EDITOR_URL)
    response = client.post(NEW_URL, {}, follow=True)
    assert "Started a new configuration" in page(response)


def test_save_downloads_the_configuration_and_clears_the_unsaved_flag(client):
    client.get(EDITOR_URL)
    browser_session().dirty = True
    response = client.post(SAVE_URL)
    assert response.status_code == 200
    assert "attachment" in response["Content-Disposition"]
    assert ".json" in response["Content-Disposition"]
    assert "config" in json.loads(response.content)
    assert browser_session().dirty is False


def test_save_is_post_only(client):
    response = client.get(SAVE_URL)
    assert response.status_code == 302


def test_save_without_a_configuration_explains_what_to_do(client, monkeypatch):
    monkeypatch.setattr(session_store, "AUTO_LOAD_EXAMPLE", False)
    response = client.post(SAVE_URL, follow=True)
    assert "No configuration is loaded" in page(response)


def test_validate_reports_a_valid_configuration(client):
    response = client.post(VALIDATE_URL, follow=True)
    assert "Configuration is valid" in page(response)


def test_validate_reports_problems_without_changing_anything(client):
    client.get(EDITOR_URL)
    browser_session().config.config.rooms.clear()  # bypasses edit mode on purpose
    response = client.post(VALIDATE_URL)
    assert response.status_code == 200
    assert "The configuration has problems" in page(response)
__FILE_3_EOF__

# ---- 3. patch the existing files (each patch must match exactly once) -------
"$PYTHON" - "$STAGE" <<'__PATCH_EOF__'
import sys
from pathlib import Path

root = Path(sys.argv[1])


def fail(message):
    print(f"PATCH FAILED: {message}", file=sys.stderr)
    sys.exit(1)


def sub(path, old, new):
    target = root / path
    text = target.read_text(encoding="utf-8")
    found = text.count(old)
    if found != 1:
        fail(f"{path}: expected exactly 1 match, found {found} for:\n{old}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def append(path, addition):
    target = root / path
    text = target.read_text(encoding="utf-8")
    target.write_text(text.rstrip("\n") + "\n" + addition, encoding="utf-8")


# ====================================================================== #
#  app/session.py -- load from bytes, dump to text, remember the file name
# ====================================================================== #
sub("app/session.py",
    r'''from pathlib import Path
from typing import Optional
''',
    r'''import json
import tempfile
from pathlib import Path
from typing import Optional
''')

sub("app/session.py",
    r'''        self.config_path: Optional[Path] = None
''',
    r'''        self.config_path: Optional[Path] = None
        # Display name of the file the config was last loaded from or saved as
        # (the web GUI has no real path for an upload, only a name). Used to
        # name the Save download. None for a new, never-saved configuration.
        self.config_name: Optional[str] = None
''')

sub("app/session.py",
    r'''        self.config_path = None
        self.schedules = []
        self.dirty = False
''',
    r'''        self.config_path = None
        self.config_name = None
        self.schedules = []
        self.dirty = False
''')

sub("app/session.py",
    r'''        self.config_path = p
        self.schedules = []
        self.dirty = False
''',
    r'''        self.config_path = p
        self.config_name = p.name
        self.schedules = []
        self.dirty = False
''')

sub("app/session.py",
    r'''        self.config_path = target
        self.dirty = False
''',
    r'''        self.config_path = target
        self.config_name = target.name
        self.dirty = False
''')

sub("app/session.py",
    r'''    def require_config(self) -> CombinedConfig:
''',
    r'''    # ---------------------------------------------------------------- #
    #  Web/GUI helpers (a browser upload is bytes, a download is text) #
    # ---------------------------------------------------------------- #
    def load_bytes(self, raw: bytes, name: str = "the uploaded file") -> None:
        """Load + validate a configuration from raw file bytes, e.g. a
        browser upload. Same all-or-nothing rule as load(): the previous
        config, schedules and dirty flag are only replaced after the
        library has fully validated the new one; any failure raises a
        ConfigError with a readable message and changes nothing.

        The library's own loader only reads paths, so the bytes are written
        to a throwaway folder first; that keeps this on exactly the same
        loading code (and validation) as the CLI's load()."""
        try:
            data = json.loads(raw)
        except UnicodeDecodeError as e:
            raise ConfigError(f"'{name}' is not a text file (it is not valid UTF-8).") from e
        except json.JSONDecodeError as e:
            raise ConfigError(
                f"'{name}' is not valid JSON: {e.msg} (line {e.lineno}, column {e.colno})."
            ) from e
        if not isinstance(data, dict):
            raise ConfigError(f"'{name}' must contain a JSON object, like the files saved by this app.")

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "configuration.json"
            path.write_bytes(raw)
            try:
                new_config = load_config_from_file(CombinedConfig, str(path))
            except ValidationError as e:
                raise ConfigError(f"'{name}' is not a valid configuration.") from e
            except (OSError, ValueError) as e:
                raise ConfigError(f"Could not read '{name}': {e}") from e

        # Only swap state in after a fully successful load+validate.
        self.config = new_config
        self.config_path = None  # an upload has no path on this machine
        self.config_name = Path(name).name or None
        self.schedules = []
        self.dirty = False

    def dumps(self) -> str:
        """The in-memory config as JSON text, through the library's own
        Pydantic serialization (the same text save() writes to disk)."""
        return self.require_config().model_dump_json(indent=2)

    def mark_saved(self, name: Optional[str] = None) -> None:
        """Record that the current config was handed to the user as a file
        (the GUI's Save download): clears the unsaved-changes flag."""
        self.dirty = False
        if name:
            self.config_name = name

    def require_config(self) -> CombinedConfig:
''')


# ====================================================================== #
#  app/commands/configuration.py -- a validate that returns, not prints
# ====================================================================== #
sub("app/commands/configuration.py",
    r'''def validate_config(session):
    """Revalidate the active configuration and report the result."""
    config = session.require_config()
    try:
        type(config).model_validate(config.model_dump())
    except Exception as error:  # noqa: BLE001 -- library validation type is not stable
        print(f"Configuration is INVALID: {error}")
        return
    print("Configuration is valid.")''',
    r'''def revalidate(session):
    """Re-run full validation on the active configuration.

    Returns None when it is valid, otherwise the exception the library
    raised, so the CLI can print it and the GUI can turn it into
    plain-language messages. Raises ConfigError when nothing is loaded."""
    config = session.require_config()
    try:
        type(config).model_validate(config.model_dump())
    except Exception as error:  # noqa: BLE001 -- library validation type is not stable
        return error
    return None


def validate_config(session):
    """Revalidate the active configuration and report the result."""
    error = revalidate(session)
    if error is not None:
        print(f"Configuration is INVALID: {error}")
        return
    print("Configuration is valid.")''')


# ====================================================================== #
#  gui/controllers/errors.py -- a problem list that always says WHERE
# ====================================================================== #
append("gui/controllers/errors.py", r'''

def describe_problems(exc: Exception, limit: int | None = None) -> list[str]:
    """Plain-language problem list for a whole-configuration failure.

    Unlike translate_validation_error() (which attaches errors to form
    fields), every item here names WHERE the problem is, e.g.
    "This field is required. (at config > rooms > 0 > capacity)", because a
    loaded or saved configuration has no form to hang the errors on
    (Section 10: name the affected area). `limit` caps the list and adds
    an "...and N more" line, so a badly broken file stays readable.
    """
    source = exc
    if isinstance(exc, ValidationFailure) and exc.__cause__ is not None:
        source = exc.__cause__

    raw_errors = None
    errors_method = getattr(source, "errors", None)
    if callable(errors_method):
        try:
            raw_errors = list(errors_method())
        except Exception:  # pragma: no cover - defensive, fall back to text
            raw_errors = None

    if not raw_errors:
        text = str(exc).strip()[:300]
        return [text or "The configuration is not valid."]

    items: list[str] = []
    for error in raw_errors:
        location = [str(part) for part in error.get("loc", ())]
        message, _ = _friendly_message(error)
        items.append(f"{message} (at {' > '.join(location)})" if location else message)

    if limit is not None and len(items) > limit:
        extra = len(items) - limit
        items = items[:limit] + [f"...and {extra} more problem{'' if extra == 1 else 's'}."]
    return items
''')


# ====================================================================== #
#  gui/controllers/timeslots.py -- use the shared helpers (same behavior)
# ====================================================================== #
sub("gui/controllers/timeslots.py",
    r'''from app.commands.common import VALID_DAYS, apply_session_edit
from app.commands.timeslots import blocks_overlap
from app.crud import ValidationFailure
from app.session import ConfigError
from gui.constants import DAY_NAMES
from gui.controllers.errors import ControllerError, to_controller_error, translate_validation_error
''',
    r'''from app.commands.common import VALID_DAYS
from app.commands.timeslots import blocks_overlap
from gui.constants import DAY_NAMES
from gui.controllers.common import apply_config_edit, require_config
from gui.controllers.errors import ControllerError, translate_validation_error
''')

sub("gui/controllers/timeslots.py",
    r'''def _require_config(session):
    try:
        return session.require_config()
    except ConfigError as error:
        raise ControllerError(
            "No configuration is loaded. Create or load one before editing time slots."
        ) from error
''',
    r'''def _require_config(session):
    return require_config(session, "editing time slots")
''')

sub("gui/controllers/timeslots.py",
    r'''def _apply(session, config, mutate) -> None:
    try:
        apply_session_edit(session, config, "timeslot", mutate)
    except ValidationFailure as error:
        raise to_controller_error(error, form_fields=TIME_FIELDS + OPTION_FIELDS) from error
''',
    r'''def _apply(session, config, mutate) -> None:
    apply_config_edit(session, config, "timeslot", mutate, form_fields=TIME_FIELDS + OPTION_FIELDS)
''')


# ====================================================================== #
#  gui/forms.py -- New and Load forms with the discard confirmation
# ====================================================================== #
append("gui/forms.py", r'''

class ConfigNewForm(ConfirmReplaceMixin, forms.Form):
    """Configuration Editor: start a new configuration (Section 8).

    Has no inputs of its own. When starting over would discard unsaved
    changes (or loaded schedules), it shows a checkbox that must be ticked;
    `discard_note` says what would be lost, e.g. "your unsaved changes".
    """

    def __init__(self, *args, discard_note="", **kwargs):
        kwargs.setdefault("prefix", "new")  # keeps ids apart from the load form
        super().__init__(*args, **kwargs)
        self.require_confirmation(
            bool(discard_note),
            label=f"Discard {discard_note}",
            help_text="Starting a new configuration replaces the one you have now. Save it first to keep it.",
            error=f"Tick this box to confirm discarding {discard_note}.",
        )


class ConfigLoadForm(ConfirmReplaceMixin, forms.Form):
    """Configuration Editor: load a configuration from a JSON file (Section 8).

    Only checks that a file was chosen and, when there is something to lose,
    that the user agreed to discard it. Whether the file is a usable
    configuration is decided by the scheduler library via the controller.
    """

    config_file = forms.FileField(
        label="Configuration JSON file",
        help_text="A .json configuration file, such as one saved from this page.",
        widget=forms.ClearableFileInput(attrs={"accept": ".json,application/json"}),
    )

    def __init__(self, *args, discard_note="", **kwargs):
        kwargs.setdefault("prefix", "load")
        super().__init__(*args, **kwargs)
        self.require_confirmation(
            bool(discard_note),
            label=f"Discard {discard_note}",
            help_text="Loading a file replaces the configuration you have now. Save it first to keep it.",
            error=f"Tick this box to confirm discarding {discard_note}.",
        )
''')


# ====================================================================== #
#  gui/urls.py
# ====================================================================== #
sub("gui/urls.py",
    r'''    path("configuration/", views.config_editor, name="config_editor"),
''',
    r'''    path("configuration/", views.config_editor, name="config_editor"),
    path("configuration/new/", views.config_new, name="config_new"),
    path("configuration/load/", views.config_load, name="config_load"),
    path("configuration/save/", views.config_save, name="config_save"),
    path("configuration/validate/", views.config_validate, name="config_validate"),
''')


# ====================================================================== #
#  gui/views.py
# ====================================================================== #
sub("gui/views.py",
    r'''from django.shortcuts import redirect, render

from gui.constants import DAY_NAMES
from gui.controllers import schedule_controller
from gui.controllers import timeslots as timeslot_controller
from gui.controllers.errors import ControllerError
from gui.forms import AddTimeBlockForm, ScheduleImportForm, TimeBlockFieldsForm, TimingOptionsForm
''',
    r'''from django.shortcuts import redirect, render
from django.urls import reverse

from gui.constants import DAY_NAMES
from gui.controllers import config_controller, schedule_controller
from gui.controllers import timeslots as timeslot_controller
from gui.controllers.errors import ControllerError
from gui.forms import (
    AddTimeBlockForm,
    ConfigLoadForm,
    ConfigNewForm,
    ScheduleImportForm,
    TimeBlockFieldsForm,
    TimingOptionsForm,
)
''')

sub("gui/views.py",
    r'''def config_editor(request):
    """Configuration Editor mode (Sections 6-12). Placeholder page today;
    see gui/controllers/config_controller.py and crud_controller.py for
    what still needs wiring in."""
    return render(request, "gui/config_editor.html", {"active": "config"})
''',
    r'''# ---------------------------------------------------------------------- #
#  Configuration Editor home + lifecycle (Sections 8-10): New / Load / Save /
#  Validate. Same shape as every action: POST only, call the controller, then
#  redirect with a flash message (success) or re-render with the errors shown
#  (failure) -- the current configuration is never touched by a failure.
# ---------------------------------------------------------------------- #
# One row per configuration area on the editor home page: (count key from
# config_controller.describe_configuration, label, URL name). When an area's
# pages exist, put its URL name here -- that is the only change the home page
# needs to link to it.
_CONFIG_AREAS = (
    ("time_blocks", "Time Slots", "gui:timeslots"),
    ("rooms", "Rooms", None),
    ("labs", "Labs", None),
    ("courses", "Courses", None),
    ("faculty", "Faculty", None),
    ("patterns", "Class Patterns", None),
    ("meetings", "Meetings", None),
    ("settings", "Global Settings", None),
)


def _config_areas(counts):
    return [
        {"label": label, "count": counts.get(key), "url": reverse(url_name) if url_name else None}
        for key, label, url_name in _CONFIG_AREAS
    ]


def _render_config_editor(request, new_form=None, load_form=None, report=None):
    state = config_controller.describe_configuration(request)
    note = state["discard_note"]
    if new_form is None:
        new_form = ConfigNewForm(discard_note=note)
    if load_form is None:
        load_form = ConfigLoadForm(discard_note=note)
    context = {
        "active": "config",
        **state,
        "areas": _config_areas(state["counts"]),
        "new_form": new_form,
        "load_form": load_form,
        "report": report,
    }
    return render(request, "gui/config_editor.html", context)


def _discard_note(request):
    return config_controller.describe_configuration(request)["discard_note"]


def config_editor(request):
    """Configuration Editor home: current status, New / Load / Save /
    Validate, and the list of configuration areas (Sections 6-12)."""
    return _render_config_editor(request)


def config_new(request):
    if request.method != "POST":
        return redirect("gui:config_editor")
    form = ConfigNewForm(request.POST, discard_note=_discard_note(request))
    if form.is_valid():
        try:
            config_controller.new_configuration(request)
        except ControllerError as error:
            _attach_errors(form, error)
        else:
            messages.success(
                request,
                "Started a new configuration. It begins with one placeholder room, course, "
                "faculty member and class pattern; edit or replace them.",
            )
            return redirect("gui:config_editor")
    return _render_config_editor(request, new_form=form)


def config_load(request):
    if request.method != "POST":
        return redirect("gui:config_editor")
    form = ConfigLoadForm(request.POST, request.FILES, discard_note=_discard_note(request))
    if form.is_valid():
        uploaded = form.cleaned_data["config_file"]
        try:
            name = config_controller.load_configuration(request, uploaded)
        except ControllerError as error:
            _attach_errors(form, error)
        else:
            messages.success(request, f"Loaded and validated {name}.")
            return redirect("gui:config_editor")
    return _render_config_editor(request, load_form=form)


def config_save(request):
    """Validate, then send the configuration as a file download (Section 9)."""
    if request.method != "POST":
        return redirect("gui:config_editor")
    try:
        filename, content = config_controller.save_configuration(request)
    except ControllerError as error:
        report = {"heading": "The configuration was not saved.", "items": [item.message for item in error.errors]}
        return _render_config_editor(request, report=report)
    return download_response(filename, content, "application/json; charset=utf-8")


def config_validate(request):
    """Re-check the whole configuration and report the result (Section 10)."""
    if request.method != "POST":
        return redirect("gui:config_editor")
    try:
        problems = config_controller.validate_configuration(request)
    except ControllerError as error:
        messages.error(request, error.message)
        return redirect("gui:config_editor")
    if not problems:
        messages.success(request, "Configuration is valid. Every rule was checked and none are broken.")
        return redirect("gui:config_editor")
    return _render_config_editor(
        request, report={"heading": "The configuration has problems.", "items": problems}
    )
''')
__PATCH_EOF__

# ---- 4. byte-compile everything before touching the repo --------------------
( cd "$STAGE" && find . -name '*.py' -print0 | xargs -0 "$PYTHON" -m py_compile )
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} +

# ---- 5. copy into the repo ------------------------------------------------
cp -R "$STAGE"/. .

echo
echo "Done. Changed files:"
echo "  modified  app/session.py"
echo "  modified  app/commands/configuration.py"
echo "  modified  gui/controllers/errors.py"
echo "  modified  gui/controllers/timeslots.py"
echo "  modified  gui/forms.py"
echo "  modified  gui/urls.py"
echo "  modified  gui/views.py"
echo "  replaced  gui/controllers/config_controller.py"
echo "  replaced  gui/templates/gui/config_editor.html"
echo "  new       gui/controllers/common.py"
echo "  new       tests/test_gui_config_lifecycle.py"
echo
echo "Try it:"
echo "  uv run pytest tests/test_gui_config_lifecycle.py tests/test_gui_timeslots.py tests/test_session.py"
echo "  uv run python manage.py runserver     # then open http://127.0.0.1:8000/configuration/"
echo
echo "Review with:  git status && git diff"
echo "To undo:      git checkout -- app/session.py app/commands/configuration.py gui/controllers/errors.py gui/controllers/timeslots.py gui/forms.py gui/urls.py gui/views.py gui/controllers/config_controller.py gui/templates/gui/config_editor.html && rm gui/controllers/common.py tests/test_gui_config_lifecycle.py"