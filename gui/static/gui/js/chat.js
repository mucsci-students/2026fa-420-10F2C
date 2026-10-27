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
    var EMPTY_PROMPT = "Type a request first.";

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
            var old = log.querySelector("[data-chat-empty]");
            if (old) {
                old.remove(); //don't stack repeated prompts
            }
            addMessage("notice", EMPTY_PROMPT).setAttribute("data-chat-empty", "");
            input.value = "";
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
