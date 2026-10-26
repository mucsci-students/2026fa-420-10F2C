#!/usr/bin/env bash
#
# add-ai-chat.sh   (rewritten for the current develop, with the AI assistant from PR #134 merged)
#
# One step: puts the AI chat BUTTON in the bottom-right corner of every page (Sprint 3, Section 3)
# and connects it to Samsong's AI service, instead of the separate "AI Assistant" page and tab.
# Run it on a new branch made from the updated develop, for example feature/ai-chat-foundation.
#
# What you get
#   * A round chat button pinned to the bottom-right corner of the SCREEN on every page.
#   * Hover it (or just to its right) and a small arrow appears; click it and the button slides
#     off the right edge. A small tab stays at the edge to bring it back (remembered per browser).
#   * The chat panel talks to the real AI (gui/ai/service.py): "Working on it..." while a request
#     runs, one request at a time, a clear reply, and the top bar shows "Unsaved changes" when the
#     AI changed the configuration. A change also gets a "Refresh page" button, since the page
#     behind the chat was drawn before the change.
#   * The old AI Assistant page, its menu tab, and its script and styles are removed.
#
# What it changes (nothing is committed for you)
#   new       gui/templates/gui/components/chat_widget.html   the button and the panel
#   new       gui/static/gui/js/chat.js                       how they behave
#   new       tests/test_gui_chat.py                          tests for the button and panel
#   replaced  gui/views_ai.py                                 now only the POST /assistant/ask/ endpoint
#   replaced  tests/test_ai_chat.py                           same tests, aimed at the endpoint instead of the page
#   edited    gui/templates/gui/base.html                     includes the widget and chat.js; menu tab removed
#   edited    gui/urls.py                                     the /assistant/ page route removed
#   edited    gui/static/gui/css/style.css                    chat styles added at the end
#   edited    README.md                                       AI Assistant section describes the button
#   removed   gui/templates/gui/assistant.html, gui/static/gui/js/ai_chat.js,
#             gui/static/gui/css/assistant.css
#
# Usage, from anywhere inside the repository:
#   bash ~/add-ai-chat.sh              apply, then run the AI tests if uv is installed
#   NO_TEST=1 bash ~/add-ai-chat.sh    apply only
#
# Safe to re-run: it stops with a message if the chat button is already there, if you are on
# develop, if the AI assistant is not in your branch yet, or if a file it touches has uncommitted
# changes or is not the version it expects. In every one of those cases it changes NOTHING.
#
# Keep this script OUTSIDE the repository (for example in your home folder) so "git add -A"
# does not commit it.

set -euo pipefail

BASE_HTML="gui/templates/gui/base.html"
URLS="gui/urls.py"
CSS="gui/static/gui/css/style.css"
README="README.md"
NEW_FILES=(
    "gui/templates/gui/components/chat_widget.html"
    "gui/static/gui/js/chat.js"
    "tests/test_gui_chat.py"
)
REPLACED_FILES=(
    "gui/views_ai.py"
    "tests/test_ai_chat.py"
)
REMOVED_FILES=(
    "gui/templates/gui/assistant.html"
    "gui/static/gui/js/ai_chat.js"
    "gui/static/gui/css/assistant.css"
)
TOUCHED=("$BASE_HTML" "$URLS" "$CSS" "$README" "${REPLACED_FILES[@]}" "${REMOVED_FILES[@]}")

die() { echo "ERROR: $*" >&2; exit 1; }

root="$(git rev-parse --show-toplevel 2>/dev/null)" || die "Run this from inside the repository."
cd "$root"

current="$(git branch --show-current)"
case "$current" in
    ""|develop|main|master) die "You are on '${current:-no branch}'. Make a branch first: git checkout develop && git pull origin develop && git checkout -b feature/ai-chat-foundation" ;;
esac

[ -f gui/ai/service.py ] || die "gui/ai/service.py is missing: this branch does not have the AI assistant yet. Update from develop first (git fetch && git merge origin/develop)."

if [ -e "gui/static/gui/js/chat.js" ] || grep -q "chat_widget.html" "$BASE_HTML"; then
    echo "Already applied: the chat button is already in this branch. Nothing to do."
    exit 0
fi
for f in "${NEW_FILES[@]}"; do
    [ ! -e "$f" ] || die "$f already exists, so I will not overwrite it. Move it away or ask for help."
done
for f in "$BASE_HTML" "$URLS" "$CSS" "$README" "${REPLACED_FILES[@]}" "${REMOVED_FILES[@]}"; do
    [ -f "$f" ] || die "Missing $f. Is this the right repository, and is it up to date with develop?"
done

if ! git diff --quiet -- "${TOUCHED[@]}" || ! git diff --cached --quiet -- "${TOUCHED[@]}"; then
    die "Some files this script changes have uncommitted changes. Commit or stash them first: ${TOUCHED[*]}"
fi

PYTHON="$(command -v python3 || command -v python || true)"
[ -n "$PYTHON" ] || die "python3 is needed to edit the existing files."

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/new"

# ---------------------------------------------------------------------------------------------
# 1. Everything is prepared in a temp folder first, so a problem leaves every real file untouched.
# ---------------------------------------------------------------------------------------------
cat > "$tmp/new/gui__templates__gui__components__chat_widget.html" <<'WIDGET_EOF'
{% comment %}
    The AI chat: a round button pinned to the bottom-right corner of the screen that opens a chat
    panel (Sprint 3 Section 3). Included once, from base.html.

    Hovering the button (or the space just to its right) shows a small arrow that slides the
    button off the right edge; a small tab stays at the edge to bring it back. See chat.js and
    the "AI chat" block of style.css.

    The button, the arrow and the tab all start hidden and gui/static/gui/js/chat.js reveals them,
    so a browser without JavaScript never shows a chat that cannot work (the same
    progressive-enhancement rule as the rest of the app). The panel posts one request at a time to
    gui:assistant_ask (gui/views_ai.py, which hands it to gui/ai/service.py); it never sees or
    sends an API key.
{% endcomment %}
<div class="chat-widget" data-chat>
    <section id="chat-panel" class="chat-panel" role="dialog" aria-labelledby="chat-title" hidden>
        <header class="chat-panel__header">
            <h2 id="chat-title" class="chat-panel__title">AI assistant</h2>
            <button type="button" class="chat-panel__close" data-chat-close aria-label="Close AI assistant">&times;</button>
        </header>
        <div class="chat-log" data-chat-log role="log" aria-live="polite" aria-relevant="additions">
            {# One line on purpose: chat messages keep their line breaks (pre-wrap), so source indentation would show. #}
            <p class="chat-message chat-message--assistant">Hi! Ask me to look at or change your scheduler configuration. Try &quot;What can you do?&quot;. Changes are applied to the open configuration but not saved to a file until you save it.</p>
        </div>
        <form class="chat-form" data-chat-form method="post" action="{% url 'gui:assistant_ask' %}">
            {% csrf_token %}
            <label class="visually-hidden" for="chat-input">Your request</label>
            <textarea id="chat-input" name="message" rows="2" maxlength="2000" placeholder="Type a request, for example: add a room called Roddy 150"></textarea>
            <button type="submit" class="btn btn-primary" data-chat-send>Send</button>
        </form>
    </section>
    <div class="chat-dock">
        <button type="button" id="chat-launcher" class="chat-launcher" aria-expanded="false" aria-controls="chat-panel" aria-label="Open AI assistant" title="AI assistant" hidden>
            <svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true" focusable="false">
                <path fill="currentColor" d="M4 3h16a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H9l-5 4v-4H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/>
            </svg>
        </button>
        <button type="button" class="chat-hide" data-chat-hide aria-label="Hide AI assistant button" title="Hide (slides to the side)" hidden>&rsaquo;</button>
    </div>
    <button type="button" class="chat-tab" data-chat-show aria-label="Show AI assistant button" title="Show AI assistant" hidden>&lsaquo;</button>
</div>
WIDGET_EOF

cat > "$tmp/new/gui__static__gui__js__chat.js" <<'CHAT_JS_EOF'
/*
 * The AI chat panel (Sprint 3 Section 3). Markup: gui/templates/gui/components/chat_widget.html.
 *
 * What it does
 *   - Reveals the round button (pinned to the bottom-right corner of the screen) and opens /
 *     closes the panel (button, the X, or Escape; focus moves into the panel and back).
 *   - Hide / show: the small arrow next to the button slides it off the right edge of the screen;
 *     the small tab left at the edge slides it back. The choice is remembered in this browser
 *     (localStorage, if it is available) so it holds on every page and after a reload.
 *   - Sends ONE request at a time to the server (POST to gui/views_ai.py, with the CSRF token
 *     from the form), shows "Working on it…" until the answer arrives, then shows the answer.
 *   - Ignores a second send while one is still running (accidental double clicks / Enter).
 *   - Always ends in a clear message: the server's answer, or a plain "could not reach the
 *     server" note. Nothing is reported as done unless the server's answer says so.
 *   - When the AI changed the configuration, the "Unsaved changes" label in the top bar is updated
 *     and the reply gets a "Refresh page" button, because the page behind the chat (a list of
 *     rooms, say) was drawn before the change.
 *
 * Enter sends, Shift+Enter starts a new line. Messages are inserted as text, never as HTML.
 * The panel starts empty on every page load; there is no conversation memory (Section 3).
 *
 * Progressive enhancement: the button, the arrow and the tab all stay hidden without JavaScript.
 */
(function () {
    "use strict";

    var root = document.querySelector("[data-chat]");
    if (!root) {
        return;
    }
    var launcher = root.querySelector("#chat-launcher");
    var panel = root.querySelector("#chat-panel");
    var log = root.querySelector("[data-chat-log]");
    var form = root.querySelector("[data-chat-form]");
    var input = form.querySelector("textarea");
    var sendButton = form.querySelector("[data-chat-send]");
    var closeButton = root.querySelector("[data-chat-close]");
    var hideButton = root.querySelector("[data-chat-hide]");
    var showButton = root.querySelector("[data-chat-show]");
    var pending = false;

    var STORAGE_KEY = "scheduler-chat-tucked";
    var TUCKED = "chat-widget--tucked";
    var NO_MOTION = "chat-widget--no-motion";
    var LABELS = { error: "Problem: ", notice: "Note: " };
    var NETWORK_PROBLEM =
        "Could not reach the server, so nothing was confirmed. Check your configuration before trying again.";

    // -- hide / show ----------------------------------------------------------------------- //
    function readTucked() {
        try {
            return window.localStorage.getItem(STORAGE_KEY) === "1";
        } catch (error) {
            return false;   // storage blocked or unavailable: the button simply starts out
        }
    }

    function saveTucked(tucked) {
        try {
            if (tucked) {
                window.localStorage.setItem(STORAGE_KEY, "1");
            } else {
                window.localStorage.removeItem(STORAGE_KEY);
            }
        } catch (error) {
            // Not remembered; the button still hides and shows for this page.
        }
    }

    function isTucked() {
        return root.classList.contains(TUCKED);
    }

    function setTucked(tucked, remember) {
        if (tucked) {
            setOpen(false);   // a tucked-away button never leaves a panel open
        }
        root.classList.toggle(TUCKED, tucked);
        if (remember) {
            saveTucked(tucked);
        }
    }

    // -- the panel ------------------------------------------------------------------------- //
    function isOpen() {
        return !panel.hidden;
    }

    function setOpen(open) {
        panel.hidden = !open;
        launcher.setAttribute("aria-expanded", open ? "true" : "false");
        launcher.setAttribute("aria-label", open ? "Close AI assistant" : "Open AI assistant");
        if (open) {
            input.focus();
        }
    }

    function addMessage(kind, text) {
        var item = document.createElement("p");
        item.className = "chat-message chat-message--" + kind;
        if (LABELS[kind]) {
            // The label means the kind of message is never conveyed by colour alone.
            var label = document.createElement("strong");
            label.textContent = LABELS[kind];
            item.appendChild(label);
        }
        item.appendChild(document.createTextNode(text));
        log.appendChild(item);
        log.scrollTop = log.scrollHeight;
        return item;
    }

    function setPending(on) {
        pending = on;
        form.setAttribute("aria-busy", on ? "true" : "false");
        sendButton.setAttribute("aria-disabled", on ? "true" : "false");
        sendButton.classList.toggle("btn-disabled", on);
    }

    function show(thinking, result) {
        thinking.remove();
        var body = result && result.body;
        if (!body || typeof body.reply !== "string" || !body.reply) {
            addMessage("error", NETWORK_PROBLEM);
            return;
        }
        var kind = "assistant";
        if (body.busy) {
            kind = "notice";   // an earlier request is still running; nothing was sent to the AI
        } else if (!body.ok) {
            kind = "error";
        }
        var item = addMessage(kind, body.reply);
        if (body.dirty) {
            showUnsaved();
        }
        if (body.changed) {
            addRefreshButton(item);
        }
    }

    // The top bar says "Unsaved changes" once the configuration was changed (here, by the AI).
    function showUnsaved() {
        var status = document.querySelector(".nav-status");
        if (!status) {
            return;
        }
        status.classList.add("nav-status--dirty");
        var strong = document.createElement("strong");
        strong.textContent = "Unsaved changes";
        status.textContent = "Configuration: ";
        status.appendChild(strong);
    }

    function addRefreshButton(item) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "btn btn-small chat-refresh";
        button.textContent = "Refresh page to see the change";
        button.addEventListener("click", function () {
            window.location.reload();
        });
        item.appendChild(button);
        log.scrollTop = log.scrollHeight;
    }

    function submit() {
        if (pending) {
            return;
        }
        var text = input.value.trim();
        if (!text) {
            input.focus();
            return;
        }
        var data = new FormData(form);
        data.set("message", text);

        addMessage("user", text);
        input.value = "";
        setPending(true);
        var thinking = addMessage("status", "Working on it…");

        fetch(form.action, {
            method: "POST",
            body: data,
            credentials: "same-origin",
            headers: { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" }
        })
            .then(function (response) {
                return response.json().then(
                    function (body) {
                        return { ok: response.ok, body: body };
                    },
                    function () {
                        return { ok: false, body: null };
                    }
                );
            })
            .catch(function () {
                return { ok: false, body: null };
            })
            .then(function (result) {
                show(thinking, result);
                setPending(false);
                input.focus();
            });
    }

    // -- wiring ---------------------------------------------------------------------------- //
    launcher.addEventListener("click", function () {
        setOpen(!isOpen());
    });
    closeButton.addEventListener("click", function () {
        setOpen(false);
        launcher.focus();
    });
    hideButton.addEventListener("click", function () {
        setTucked(true, true);
        showButton.focus();
    });
    showButton.addEventListener("click", function () {
        setTucked(false, true);
        launcher.focus();
    });
    root.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && isOpen()) {
            setOpen(false);
            launcher.focus();
        }
    });
    form.addEventListener("submit", function (event) {
        event.preventDefault();
        submit();
    });
    input.addEventListener("keydown", function (event) {
        if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
            event.preventDefault();
            submit();
        }
    });

    // Start in the remembered state without sliding, then allow the slide for later clicks.
    root.classList.add(NO_MOTION);
    root.classList.toggle(TUCKED, readTucked());
    launcher.hidden = false;
    hideButton.hidden = false;
    showButton.hidden = false;
    var nextFrame = window.requestAnimationFrame || function (callback) { window.setTimeout(callback, 16); };
    nextFrame(function () {
        nextFrame(function () {
            root.classList.remove(NO_MOTION);
        });
    });
})();
CHAT_JS_EOF

cat > "$tmp/new/tests__test_gui_chat.py" <<'TEST_GUI_EOF'
"""
Tests for the AI chat button and panel (Sprint 3 Section 3).

What the AI answers is covered in test_ai_chat.py. These cover the screen: the button and panel
are on every page, the form posts to the AI endpoint, the button can be hidden and brought back,
and it is pinned to the corner of the screen.
"""

from pathlib import Path

import pytest

ASK = "/assistant/ask/"
PAGES = ["/", "/configuration/", "/generate/", "/schedules/"]
ROOT = Path(__file__).resolve().parent.parent


# -- the button and panel are on every page ------------------------------------ #
@pytest.mark.parametrize("path", PAGES)
def test_every_page_carries_the_chat_button_and_panel(client, path):
    text = client.get(path).content.decode()
    assert 'id="chat-launcher"' in text
    assert "data-chat-form" in text
    assert f'action="{ASK}"' in text


def test_the_chat_script_is_loaded_and_the_button_starts_hidden(client):
    text = client.get("/").content.decode()
    assert "gui/js/chat.js" in text
    launcher = text.split('id="chat-launcher"', 1)[1].split(">", 1)[0]
    assert "hidden" in launcher  # revealed by chat.js, so it never shows without JavaScript


def test_the_request_box_is_labelled_and_limited_to_the_server_limit(client):
    text = client.get("/").content.decode()
    assert 'for="chat-input"' in text and 'id="chat-input"' in text
    assert 'maxlength="2000"' in text


# -- the button can be hidden and brought back ---------------------------------- #
@pytest.mark.parametrize("path", PAGES)
def test_every_page_has_the_hide_arrow_and_the_show_tab(client, path):
    text = client.get(path).content.decode()
    assert "data-chat-hide" in text   # the arrow beside the button that slides it away
    assert "data-chat-show" in text   # the tab that stays at the screen edge to bring it back


def test_the_hide_arrow_and_show_tab_start_hidden_and_are_labelled(client):
    text = client.get("/").content.decode()
    arrow = text.split("data-chat-hide", 1)[1].split(">", 1)[0]
    tab = text.split("data-chat-show", 1)[1].split(">", 1)[0]
    assert "hidden" in arrow and "hidden" in tab   # chat.js reveals them, so no-JavaScript pages stay clean
    assert 'aria-label="Hide AI assistant button"' in arrow
    assert 'aria-label="Show AI assistant button"' in tab


def test_the_button_is_pinned_to_the_screen_corner_and_can_slide_away():
    css = (ROOT / "gui/static/gui/css/style.css").read_text(encoding="utf-8")
    widget = css.split(".chat-widget {", 1)[1].split("}", 1)[0]
    assert "position: fixed" in widget and "bottom:" in widget and "right:" in widget
    assert ".chat-widget--tucked .chat-dock" in css   # the slid-away state exists


# -- the script's side of a reply ----------------------------------------------- #
def test_the_script_updates_the_top_bar_and_offers_a_refresh_after_a_change():
    script = (ROOT / "gui/static/gui/js/chat.js").read_text(encoding="utf-8")
    assert "if (body.dirty)" in script and "Unsaved changes" in script
    assert "if (body.changed)" in script and "window.location.reload()" in script
    assert "body.busy" in script   # a refused duplicate is shown as a note, not as a failure
    assert "innerHTML" not in script   # messages are inserted as text, never as HTML
TEST_GUI_EOF

cat > "$tmp/new/gui__views_ai.py" <<'VIEWS_AI_EOF'
"""
Behind the AI chat button (Sprint 3). Thin like every other view: it reads the request text,
hands it to gui.ai.service, and returns the reply as JSON.

    POST /assistant/ask/   one request from the chat panel (components/chat_widget.html,
                           js/chat.js). 409 when the browser's previous request is still running.

The API key stays on the server: the browser only ever sees the reply text.
"""

from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from gui.ai import service
from gui.session_store import get_session


@require_POST
def assistant_ask(request):
    reply = service.handle_request(request, request.POST.get("message", ""))
    return JsonResponse(
        {
            "ok": reply.ok,
            "reply": reply.message,
            "changed": reply.changed,
            "busy": reply.busy,
            "dirty": bool(get_session(request).dirty),
        },
        status=409 if reply.busy else 200,
    )
VIEWS_AI_EOF

cat > "$tmp/new/tests__test_ai_chat.py" <<'TEST_AI_EOF'
"""
Tests for the AI chat button's endpoint and one request from start to finish
(Sprint 3 user stories 2, 3 and 6). The button and panel themselves are covered in test_gui_chat.py.

The real AI is replaced by FakeRunner, which calls the tools a model would
have picked for each request (or just answers with text). Everything after
that is real: the endpoint, gui.ai.service, the tools, the controllers and the
scheduler library. No OpenAI connection or API key is used.
"""

import logging
import threading

import pytest

from gui import session_store
from gui.ai import runner as runner_module
from gui.ai import service

ASK_URL = "/assistant/ask/"
PAGE_URL = "/"

ADD_140 = "Add a room named RODDY140 with capacity 30"
ADD_141 = "Add a room named RODDY141 with capacity 25"
WHAT_140 = "What is the capacity of RODDY140?"

SCRIPT = {
    ADD_140: [("add_room", {"name": "RODDY140", "capacity": 30})],
    ADD_141: [("add_room", {"name": "RODDY141", "capacity": 25})],
    WHAT_140: [("get_room", {"name": "RODDY140"})],
    "List all rooms": [("list_rooms", {})],
    "What can you do?": [("describe_capabilities", {})],
    "Add two rooms": [
        ("add_room", {"name": "RODDY150", "capacity": 35}),
        ("add_room", {"name": "RODDY151", "capacity": 40}),
    ],
    "Hello": "Hi! Ask me about rooms, labs, courses and more.",
    "Add a room named RODDY150": "Room RODDY150 has been added.",  # text only, no tool
}


class FakeRequest:
    """Enough of a request for gui.ai.service: just a session dict."""

    def __init__(self):
        self.session = {}


class FakeRunner:
    """Stands in for the AI: calls the scripted tools for each request."""

    def __init__(self, script=SCRIPT, during=None):
        self.script = script
        self.during = during  # optional hook run while the "AI" is working
        self.requests = []

    def run(self, text, toolbox):
        self.requests.append(text)
        if self.during:
            self.during(toolbox)
        step = self.script[text]
        if isinstance(step, str):
            return step
        for name, args in step:
            toolbox.call(name, args)
        return ""


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


@pytest.fixture
def fake(monkeypatch):
    runner = FakeRunner()
    monkeypatch.setattr(service, "get_runner", lambda: runner)
    return runner


def ask(client, text):
    response = client.post(ASK_URL, {"message": text})
    return response.status_code, response.json()


def browser_session():
    return next(iter(session_store._SESSIONS.values()))


def rooms_named(name):
    return [room for room in browser_session().config.config.rooms if room.name == name]


def capacity(name):
    (room,) = rooms_named(name)
    return room.capacity


# ---------------------------------------------------------------------- #
#  The endpoint
# ---------------------------------------------------------------------- #
def test_the_endpoint_only_accepts_post(client):
    assert client.get(ASK_URL).status_code == 405


def test_a_post_from_another_site_is_refused():
    from django.test import Client

    strict = Client(enforce_csrf_checks=True)
    assert strict.post(ASK_URL, {"message": "List all rooms"}).status_code == 403


def test_the_separate_assistant_page_is_gone(client):
    assert client.get("/assistant/").status_code == 404
    assert "AI Assistant</a>" not in client.get("/").content.decode()  # no tab; the button replaces it


def test_the_page_never_contains_the_api_key(client, monkeypatch, fake):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    assert "sk-test" not in client.get(PAGE_URL).content.decode()
    _, body = ask(client, "List all rooms")
    assert "sk-test" not in str(body)


# ---------------------------------------------------------------------- #
#  Story 2: a result always replaces the processing status
# ---------------------------------------------------------------------- #
def test_story_2_success_comes_back_as_a_result_message(client, fake):
    status, body = ask(client, ADD_140)
    assert status == 200
    assert body["ok"] is True and body["changed"] is True
    assert "Room 'RODDY140' added with capacity 30." in body["reply"]
    assert "applied but not yet saved" in body["reply"]
    assert body["dirty"] is True


def test_story_2_failure_also_comes_back_as_a_result_message(client, fake):
    ask(client, ADD_140)
    status, body = ask(client, ADD_140)  # duplicate name this time
    assert status == 200
    assert body["ok"] is False and body["changed"] is False
    assert "already exists" in body["reply"] and "not changed" in body["reply"]


def test_story_2_the_next_request_is_accepted_after_a_failure(client, fake):
    ask(client, ADD_140)
    ask(client, ADD_140)
    status, body = ask(client, ADD_141)
    assert status == 200 and body["ok"] is True
    assert fake.requests == [ADD_140, ADD_140, ADD_141]


def test_story_2_the_next_request_is_accepted_after_the_ai_service_fails(client, monkeypatch):
    class Broken:
        def run(self, text, toolbox):
            raise ConnectionError("network down")

    monkeypatch.setattr(service, "get_runner", lambda: Broken())
    _, body = ask(client, ADD_140)
    assert body["ok"] is False
    assert "couldn't finish" in body["reply"] and "not changed" in body["reply"]
    assert rooms_named("RODDY140") == []

    monkeypatch.setattr(service, "get_runner", lambda: FakeRunner())
    _, body = ask(client, ADD_140)
    assert body["ok"] is True


def test_empty_request_is_not_sent_to_the_ai(client, fake):
    status, body = ask(client, "   ")
    assert status == 200 and body["ok"] is False
    assert body["reply"] == "Type a request first."
    assert fake.requests == []


def test_the_script_shows_working_status_and_guards_resubmits():
    """The browser half of stories 2 and 3 lives in chat.js; check the
    pieces the tests in this file cannot run are really there."""
    from pathlib import Path

    script = (Path(__file__).resolve().parent.parent / "gui/static/gui/js/chat.js").read_text()
    assert "Working on it" in script
    assert "if (pending) {" in script
    assert "sendButton.classList.toggle" in script
    assert "thinking.remove()" in script


# ---------------------------------------------------------------------- #
#  Story 3: a second submit while one is running is refused
# ---------------------------------------------------------------------- #
def test_story_3_double_submit_reaches_the_ai_once(client, monkeypatch):
    second = {}

    def submit_again(toolbox):
        # The user presses Enter again while the first request is still running.
        second["reply"] = service.handle_request(toolbox.request, ADD_140)

    runner = FakeRunner(during=submit_again)
    monkeypatch.setattr(service, "get_runner", lambda: runner)
    _, body = ask(client, ADD_140)

    assert body["ok"] is True
    assert second["reply"].busy and not second["reply"].ok
    assert second["reply"].message == service.BUSY_MESSAGE
    assert runner.requests == [ADD_140]  # only one request was sent to the AI
    assert len(rooms_named("RODDY140")) == 1


def test_story_3_busy_reply_from_the_endpoint(client, monkeypatch, fake):
    client.get(PAGE_URL)
    key = id(browser_session())
    service._BUSY.add(key)
    try:
        status, body = ask(client, ADD_140)
    finally:
        service._BUSY.discard(key)
    assert status == 409 and body["busy"] is True
    assert fake.requests == []
    assert rooms_named("RODDY140") == []


def test_story_3_two_threads_at_once_only_one_runs(monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls = []

    class Slow:
        def run(self, text, toolbox):
            calls.append(text)
            started.set()
            release.wait(5)
            toolbox.call("add_room", {"name": "RODDY140", "capacity": 30})
            return ""

    monkeypatch.setattr(service, "get_runner", lambda: Slow())
    request = FakeRequest()
    first = {}
    worker = threading.Thread(target=lambda: first.setdefault("reply", service.handle_request(request, ADD_140)))
    worker.start()
    assert started.wait(5)
    again = service.handle_request(request, ADD_140)  # same browser, while the first is running
    release.set()
    worker.join(5)

    assert again.busy
    assert first["reply"].ok
    assert calls == [ADD_140]
    names = [room.name for room in session_store.get_session(request).config.config.rooms]
    assert names.count("RODDY140") == 1


def test_one_browser_being_busy_does_not_block_another(client, fake):
    other = FakeRequest()
    key = id(session_store.get_session(other))
    service._BUSY.add(key)
    try:
        status, body = ask(client, ADD_140)
    finally:
        service._BUSY.discard(key)
    assert status == 200 and body["busy"] is False and body["ok"] is True


# ---------------------------------------------------------------------- #
#  Story 6: every request uses the current state, on its own
# ---------------------------------------------------------------------- #
def test_story_6_the_ai_sees_a_manual_edit(client, fake):
    ask(client, ADD_140)
    response = client.post(
        "/configuration/rooms/RODDY140/edit/",
        {"name": "RODDY140", "capacity": "40", "features": "", "times": ""},
        follow=True,
    )
    assert response.status_code == 200 and capacity("RODDY140") == 40

    _, body = ask(client, WHAT_140)
    assert "capacity 40" in body["reply"]


def test_story_6_requests_are_independent(client, fake):
    ask(client, ADD_140)
    _, body = ask(client, ADD_141)
    assert body["ok"] is True
    assert capacity("RODDY141") == 25
    assert capacity("RODDY140") == 30
    assert fake.requests[-1] == ADD_141  # only the new request text is sent


# ---------------------------------------------------------------------- #
#  Replies are built from what really happened
# ---------------------------------------------------------------------- #
def test_text_only_reply_is_shown_but_changes_nothing(client, fake):
    _, body = ask(client, "Add a room named RODDY150")
    assert body["changed"] is False
    assert rooms_named("RODDY150") == []
    assert body["dirty"] is False


def test_plain_answer_without_tools(client, fake):
    _, body = ask(client, "Hello")
    assert body["ok"] is True and body["reply"].startswith("Hi!")


def test_two_changes_in_one_request_are_both_reported(client, fake):
    _, body = ask(client, "Add two rooms")
    assert "RODDY150" in body["reply"] and "RODDY151" in body["reply"]
    assert "The changes are applied but not yet saved to a file." in body["reply"]


def test_what_can_you_do(client, fake):
    client.get(PAGE_URL)
    before = browser_session().config.model_dump_json()
    _, body = ask(client, "What can you do?")
    assert body["ok"] is True and body["changed"] is False
    assert "View, add, change, and delete rooms" in body["reply"]
    assert "Validate the configuration, save it, and generate schedules" in body["reply"]
    assert browser_session().config.model_dump_json() == before


def test_list_all_rooms_with_no_configuration(client, fake, monkeypatch):
    monkeypatch.setattr(session_store, "AUTO_LOAD_EXAMPLE", False)
    _, body = ask(client, "List all rooms")
    assert body["ok"] is False
    assert "There is no configuration yet. Load or create one first" in body["reply"]


# ---------------------------------------------------------------------- #
#  Setup problems
# ---------------------------------------------------------------------- #
def test_missing_api_key_explains_how_to_set_it(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _, body = ask(client, "List all rooms")
    assert body["ok"] is False
    assert "OPENAI_API_KEY" in body["reply"] and "Nothing was changed" in body["reply"]
    assert client.get("/configuration/rooms/").status_code == 200  # the rest of the app still works


def test_model_setting_defaults_to_gpt_6_luna(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert runner_module.model_name() == "gpt-6-luna"
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test-mini")
    assert runner_module.model_name() == "gpt-test-mini"


def test_service_failure_is_logged_without_details(client, monkeypatch, caplog):
    class Broken:
        def run(self, text, toolbox):
            raise RuntimeError("Incorrect API key provided: sk-secret-123")

    monkeypatch.setattr(service, "get_runner", lambda: Broken())
    with caplog.at_level(logging.WARNING, logger="gui.ai"):
        _, body = ask(client, "List all rooms")
    assert "sk-secret" not in body["reply"]
    assert "sk-secret" not in caplog.text
    assert "RuntimeError" in caplog.text
TEST_AI_EOF

cat > "$tmp/chat.css" <<'CHAT_CSS_EOF'
/* ------------------------------------------------------------------ *
 * AI chat (Sprint 3 Section 3). The round button is pinned to the    *
 * bottom-right corner of the SCREEN, so it stays in view while the   *
 * page scrolls. Hovering it (or the space just to its right) shows a *
 * small "hide" arrow; the button then slides off the right edge and  *
 * a small tab stays behind to bring it back.                         *
 * Markup: components/chat_widget.html; behaviour: js/chat.js.        *
 * ------------------------------------------------------------------ */
.chat-widget {
    position: fixed;
    right: 1.25rem;
    bottom: 1.25rem;
    z-index: 50;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 0.75rem;
    /* The box itself never blocks clicks on the page behind it; only its parts below do. */
    pointer-events: none;
}
.chat-panel,
.chat-dock,
.chat-tab { pointer-events: auto; }

/* The dock holds the round button and the hide arrow. It reaches the screen edge, so hovering
   just to the right of the button counts as hovering the button. */
.chat-dock {
    position: relative;
    display: flex;
    align-items: center;
    margin-right: -1.25rem;
    padding-right: 1.25rem;
    transition: transform 0.25s ease, visibility 0s linear 0s;
}
.chat-widget--tucked .chat-dock {
    transform: translateX(calc(100% + 1.5rem));
    visibility: hidden;   /* off screen and out of the tab order */
    transition: transform 0.25s ease, visibility 0s linear 0.25s;
}

.chat-launcher {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 3.5rem;
    height: 3.5rem;
    padding: 0;
    border: 0;
    border-radius: 50%;
    background: var(--accent);
    color: #fff;
    box-shadow: var(--shadow-hover);
    cursor: pointer;
}
.chat-launcher:hover { background: var(--accent-strong); }
.chat-launcher:focus-visible,
.chat-hide:focus-visible,
.chat-tab:focus-visible,
.chat-panel__close:focus-visible,
.chat-form textarea:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 2px;
}
.chat-launcher[hidden],
.chat-hide[hidden],
.chat-tab[hidden],
.chat-panel[hidden] { display: none; }

/* The hide arrow: invisible until the dock is hovered or focused. */
.chat-hide {
    position: absolute;
    right: 0.05rem;
    top: 50%;
    width: 1.1rem;
    height: 2.2rem;
    margin-top: -1.1rem;
    padding: 0;
    border: 0;
    border-radius: var(--radius-sm);
    background: var(--header-bg);
    color: #fff;
    font-size: 1.1rem;
    line-height: 1;
    cursor: pointer;
    opacity: 0;
    transition: opacity 0.15s ease;
}
.chat-dock:hover .chat-hide,
.chat-dock:focus-within .chat-hide,
.chat-hide:focus-visible { opacity: 1; }
/* Touch screens cannot hover, so the arrow is always faintly visible there. */
@media (hover: none) { .chat-hide { opacity: 0.85; } }

/* The tab left at the screen edge while the button is tucked away. */
.chat-tab {
    position: absolute;
    right: -1.25rem;
    bottom: 0.65rem;
    width: 1.5rem;
    height: 2.5rem;
    padding: 0 0 0 0.15rem;
    border: 0;
    border-radius: var(--radius) 0 0 var(--radius);
    background: var(--accent);
    color: #fff;
    font-size: 1.1rem;
    line-height: 1;
    cursor: pointer;
    box-shadow: var(--shadow-hover);
    visibility: hidden;
    transform: translateX(100%);
    transition: transform 0.25s ease 0.1s, visibility 0s linear 0.35s;
}
.chat-tab:hover { background: var(--accent-strong); }
.chat-widget--tucked .chat-tab {
    visibility: visible;
    transform: translateX(0);
    transition: transform 0.25s ease 0.1s, visibility 0s linear 0s;
}

/* No sliding on page load (the saved choice is applied instantly) or when the visitor asks for
   less motion. */
.chat-widget--no-motion .chat-dock,
.chat-widget--no-motion .chat-tab { transition: none; }
@media (prefers-reduced-motion: reduce) {
    .chat-dock,
    .chat-tab,
    .chat-hide { transition: none; }
}

.chat-panel {
    display: flex;
    flex-direction: column;
    width: min(24rem, calc(100vw - 2.5rem));
    height: min(32rem, 70vh);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius);
    background: var(--surface);
    color: var(--text);
    box-shadow: var(--shadow-hover);
    overflow: hidden;
}
.chat-panel__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.6rem 0.85rem;
    background: var(--header-bg);
    color: #fff;
}
.chat-panel__title { margin: 0; font-size: 1rem; }
.chat-panel__close {
    border: 0;
    background: transparent;
    color: inherit;
    font-size: 1.5rem;
    line-height: 1;
    padding: 0 0.25rem;
    cursor: pointer;
}
.chat-log {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    padding: 0.75rem;
    overflow-y: auto;
    background: var(--surface-alt);
}
.chat-message {
    max-width: 85%;
    margin: 0;
    padding: 0.5rem 0.7rem;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--surface);
    overflow-wrap: anywhere;
    white-space: pre-wrap;
}
.chat-message--user {
    align-self: flex-end;
    background: var(--accent-soft);
    border-color: var(--accent);
}
.chat-message--status { color: var(--muted); font-style: italic; border-style: dashed; }
.chat-message--notice { background: var(--warn-soft); border-color: var(--warn); color: var(--warn-text); }
.chat-message--error { background: var(--danger-soft); border-color: var(--danger); }
.chat-form {
    display: flex;
    align-items: flex-end;
    gap: 0.5rem;
    margin: 0;
    padding: 0.6rem;
    border-top: 1px solid var(--border);
}
.chat-form textarea {
    flex: 1;
    min-height: 2.6rem;
    max-height: 8rem;
    padding: 0.4rem 0.6rem;
    border: 1px solid #9ca3af;
    border-radius: var(--radius-sm);
    background: var(--surface);
    color: var(--text);
    font: inherit;
    resize: vertical;
}

.chat-refresh { display: block; margin-top: 0.5rem; }

html[data-theme="dark"] .chat-panel { background: #18181b; color: #f3f4f6; border-color: #52525b; }
html[data-theme="dark"] .chat-panel__header { background: #000; }
html[data-theme="dark"] .chat-hide { background: #27272a; border: 1px solid #52525b; }
/* Dark mode turns --accent into a light blue meant for text; solid buttons need the darker blue
   (the same fix .btn-primary uses), or the white icon is hard to see. */
html[data-theme="dark"] .chat-launcher,
html[data-theme="dark"] .chat-tab { background: #2563eb; }
html[data-theme="dark"] .chat-launcher:hover,
html[data-theme="dark"] .chat-tab:hover { background: #1d4ed8; }
html[data-theme="dark"] .chat-log { background: #0b0b0c; }
html[data-theme="dark"] .chat-message { background: #18181b; border-color: #52525b; }
html[data-theme="dark"] .chat-message--user { background: #172554; border-color: #60a5fa; }
html[data-theme="dark"] .chat-message--status { color: #a1a1aa; }
html[data-theme="dark"] .chat-message--notice { background: #451a03; border-color: #f59e0b; color: #fde68a; }
html[data-theme="dark"] .chat-message--error { background: #450a0a; border-color: #f87171; }
html[data-theme="dark"] .chat-form { border-top-color: #3f3f46; }
html[data-theme="dark"] .chat-form textarea { background: #18181b; color: #f3f4f6; border-color: #52525b; }

@media print { .chat-widget { display: none; } }
CHAT_CSS_EOF

# The edits to existing files. Each anchor must appear exactly once, and each file being replaced
# or removed must be exactly the version this script was written for, or nothing is changed.
"$PYTHON" - "$tmp" <<'PY_EOF'
import hashlib
import os
import sys

tmp = sys.argv[1]
out_dir = os.path.join(tmp, "edited")
os.makedirs(out_dir, exist_ok=True)

EXPECTED = {
    "gui/views_ai.py": "b1b4724f2dbd35fd64aa32ed19eec0f7d38e557083962acfb6170f807ab6d5db",
    "tests/test_ai_chat.py": "453482b6a3847dead8de6d9956238c0f336b9afe85b0adc8e669c37a4690a2ef",
    "gui/templates/gui/assistant.html": "e1e245a9b89dff2bc3352aed933b0b7cc8fa7e39875d3d2ac99d3d57c07244dc",
    "gui/static/gui/js/ai_chat.js": "562db5b0ce33aa128e0fb6250c61115c4a65f5e895338449b2970029929871f5",
    "gui/static/gui/css/assistant.css": "358257b7077a21a6c8e70fbea69c9b881a114b8a84bc8a9db8872d150ad78a64",
}
README_EDITS = [
    ('Open **AI Assistant** in the top menu and type a request in everyday language, for example:',
     'Click the round chat button in the bottom-right corner of any page and type a request in everyday language. Hover the button and click the small arrow to slide it out of the way; a small tab at the screen edge brings it back. For example:'),
    ('- Your request stays on screen with a **"Processing your request…"** status. When the request finishes, the status is replaced by the result, and the chat box takes a new request.',
     '- Your request stays on screen with a **"Working on it…"** status. When the request finishes, the status is replaced by the result, and the chat box takes a new request. If the AI changed the configuration, the top bar shows **Unsaved changes** and the reply has a **Refresh page** button, because the page behind the chat was drawn before the change.'),
    ('- While a request is running, the Send button and the chat box are locked, so a double click or a second Enter is ignored.',
     '- While a request is running, Send and Enter are ignored, so a double click or a second Enter does nothing.'),
    ('`gui/views_ai.py` is the page.',
     '`gui/views_ai.py` is the endpoint the chat button posts to; the button itself is `templates/gui/components/chat_widget.html` with `static/gui/js/chat.js`.'),

]


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def replace_once(text, old, new, where):
    if text.count(old) != 1:
        sys.exit(f"Could not find the expected place to edit in {where}, so nothing was changed.")
    return text.replace(old, new)


for path, digest in EXPECTED.items():
    with open(path, "rb") as handle:
        if hashlib.sha256(handle.read()).hexdigest() != digest:
            sys.exit(f"{path} is not the version this script expects (develop changed it?), so nothing was changed. "
                     "Send me this message and I will update the script.")

page = read("gui/templates/gui/base.html")
page = replace_once(
    page,
    "    <a href=\"{% url 'gui:assistant' %}\" class=\"{% if active == 'assistant' %}active{% endif %}\">AI Assistant</a>\n",
    "",
    "base.html (menu tab)",
)
page = replace_once(
    page,
    "</main>\n<script src=\"{% static 'gui/js/loading.js' %}\" defer></script>",
    "</main>\n{% include \"gui/components/chat_widget.html\" %}\n"
    "<script src=\"{% static 'gui/js/loading.js' %}\" defer></script>\n"
    "<script src=\"{% static 'gui/js/chat.js' %}\" defer></script>",
    "base.html (script tags)",
)

routes = replace_once(
    read("gui/urls.py"),
    '    path("assistant/", views_ai.assistant, name="assistant"),\n',
    "",
    "urls.py",
)

styles = read("gui/static/gui/css/style.css")
if not styles.endswith("\n"):
    styles += "\n"
styles += "\n" + read(os.path.join(tmp, "chat.css"))

readme = read("README.md")
for old, new in README_EDITS:
    readme = replace_once(readme, old, new, "README.md")

for name, text in (("base.html", page), ("urls.py", routes), ("style.css", styles), ("README.md", readme)):
    with open(os.path.join(out_dir, name), "w", encoding="utf-8") as handle:
        handle.write(text)
PY_EOF

# ---------------------------------------------------------------------------------------------
# 2. Everything above succeeded, so now write the real files.
# ---------------------------------------------------------------------------------------------
for f in "${NEW_FILES[@]}" "${REPLACED_FILES[@]}"; do
    mkdir -p "$(dirname "$f")"
    cp "$tmp/new/${f//\//__}" "$f"
done
cp "$tmp/edited/base.html" "$BASE_HTML"
cp "$tmp/edited/urls.py" "$URLS"
cp "$tmp/edited/style.css" "$CSS"
cp "$tmp/edited/README.md" "$README"
rm -f "${REMOVED_FILES[@]}"

echo "Done:"
git status --short

if command -v node >/dev/null 2>&1; then
    node --check gui/static/gui/js/chat.js && echo "chat.js: syntax OK"
fi

status=0
if [ "${NO_TEST:-0}" != "1" ] && command -v uv >/dev/null 2>&1; then
    echo
    echo "Running the AI and chat tests..."
    uv run pytest tests/test_gui_chat.py tests/test_ai_chat.py tests/test_ai_tools.py tests/test_ai_langchain.py -q || status=$?
    if [ "$status" -ne 0 ]; then
        echo
        echo "Some tests failed. The files are changed but NOT committed; send the output above to get it fixed." >&2
    fi
fi

echo
echo "Next: look at it with  uv run python manage.py runserver  then open http://127.0.0.1:8000/"
echo "(set OPENAI_API_KEY first if you want real answers: read -rs OPENAI_API_KEY; export OPENAI_API_KEY)"
echo "Hover the round button (or just to its right) and click the small arrow to hide it."
echo "When you are happy:"
echo "  git add -A && git commit -m \"Move the AI assistant into a chat button at the bottom right\""
exit "$status"