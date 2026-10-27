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
 *   - Live page: when the AI changed something (the configuration, the open configuration, the
 *     schedules), the page behind the chat is fetched again and its content is swapped in place, so
 *     the new rooms or schedules appear with no reload (the chat stays open, scroll position, open
 *     dropdowns and the list filter are kept; other scripts are told through the
 *     "scheduler:content-updated" event). The top bar's "Unsaved changes" label follows. The page is
 *     NOT swapped while you have typed something into one of its forms (that would throw it away), or
 *     while this page is running a generation; then the reply offers a "Refresh page" button.
 *   - Chats are kept on the server (data-chat-url ...): the saved chat is drawn again on every page and
 *     after a reload, "New chat" starts a fresh one (the old ones stay in the picker), "Delete" removes
 *     one. A request that is still running when the page changes is picked up again.
 *   - Schedule generation: while a request runs, the "Working on it" line asks the server how far a
 *     generation is (data-status-url, once a second) and shows "found 2 of 10". When schedules were
 *     generated, the reply links to the Schedule Viewer (data-viewer-url).
 *   - Quick replies: a reply can carry a few short suggestions ("Go ahead and generate", "Cancel").
 *     They show as buttons under that reply; clicking one sends its text as an ordinary new message.
 *
 * Enter sends, Shift+Enter starts a new line. Messages are inserted as text, never as HTML.
 * Whether the panel is open is remembered for this tab (sessionStorage, if it is available).
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
    var toolbar = root.querySelector("[data-chat-toolbar]");
    var picker = root.querySelector("[data-chat-picker]");
    var newButton = root.querySelector("[data-chat-new]");
    var deleteButton = root.querySelector("[data-chat-delete]");
    var greeting = log.firstElementChild;   // the static hello; every chat starts with it
    var chatUrl = root.getAttribute("data-chat-url");
    var newUrl = root.getAttribute("data-chat-new-url");
    var switchUrl = root.getAttribute("data-chat-switch-url");
    var deleteUrl = root.getAttribute("data-chat-delete-url");
    var statusUrl = root.getAttribute("data-status-url");
    var viewerUrl = root.getAttribute("data-viewer-url");
    var progressTimer = null;
    var resumeTimer = null;
    var deleteTimer = null;
    var pending = false;
    var activeChat = null;

    var STORAGE_KEY = "scheduler-chat-tucked";
    var TUCKED = "chat-widget--tucked";
    var NO_MOTION = "chat-widget--no-motion";
    var LABELS = { error: "Problem: ", notice: "Note: " };
    var NETWORK_PROBLEM =
        "Could not reach the server, so nothing was confirmed. Check your configuration before trying again.";
    var EMPTY_PROMPT = "Type a request first.";
    var PROGRESS_MS = 1000;
    var OPEN_KEY = "scheduler-chat-open";
    var UPDATED_EVENT = "scheduler:content-updated";

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

    function readOpen() {
        try {
            return window.sessionStorage.getItem(OPEN_KEY) === "1";
        } catch (error) {
            return false;
        }
    }

    function saveOpen(open) {
        try {
            if (open) {
                window.sessionStorage.setItem(OPEN_KEY, "1");
            } else {
                window.sessionStorage.removeItem(OPEN_KEY);
            }
        } catch (error) {
            // Not remembered; the panel still opens and closes for this page.
        }
    }

    // quiet: restoring the remembered state on a page load, which must not move the keyboard focus.
    function setOpen(open, quiet) {
        panel.hidden = !open;
        launcher.setAttribute("aria-expanded", open ? "true" : "false");
        launcher.setAttribute("aria-label", open ? "Close AI assistant" : "Open AI assistant");
        if (open && !quiet) {
            input.focus();
        }
        if (!quiet) {
            saveOpen(open);
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
        [picker, newButton, deleteButton].forEach(function (control) {
            if (control) {
                control.disabled = on;   // a reply must never land in a different chat
            }
        });
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
        if (body.generated) {
            offerViewer(item);   // new schedules: the Schedule Viewer shows them as they are
        }
        if (body.suggestions && body.suggestions.length) {
            addSuggestions(item, body.suggestions);
        }
        if (body.changed || body.refresh || body.generated) {
            liveUpdate(item);   // the page behind the chat was drawn before the change: update it in place
        }
        refreshChats();   // the first message gives a new chat its title in the picker
    }

    // Schedules were generated: link to the Schedule Viewer (when it is already open, liveUpdate shows them).
    function offerViewer(item) {
        if (!viewerUrl || window.location.pathname === viewerUrl) {
            return;
        }
        var link = document.createElement("a");
        link.className = "btn btn-small chat-refresh";
        link.href = viewerUrl;
        link.textContent = "Open the Schedule Viewer";
        item.appendChild(link);
        log.scrollTop = log.scrollHeight;
    }

    // Short replies under the newest message. A click sends the text like anything typed.
    function addSuggestions(item, suggestions) {
        var row = document.createElement("span");
        row.className = "chat-suggestions";
        suggestions.forEach(function (text) {
            if (typeof text !== "string" || !text) {
                return;
            }
            var chip = document.createElement("button");
            chip.type = "button";
            chip.className = "btn btn-small chat-suggestion";
            chip.textContent = text;
            chip.addEventListener("click", function () {
                if (pending) {
                    return;
                }
                input.value = text;
                submit();
            });
            row.appendChild(chip);
        });
        if (row.childNodes.length) {
            item.appendChild(row);
            log.scrollTop = log.scrollHeight;
        }
    }

    function clearSuggestions() {
        var rows = log.querySelectorAll(".chat-suggestions");
        for (var index = 0; index < rows.length; index++) {
            rows[index].remove();   // only the newest message offers quick replies
        }
    }

    // -- progress of a schedule generation ------------------------------------------------------ //
    function describeProgress(status) {
        var text;
        if (!status.found) {
            text = "Generating schedules… the solver is working on the first one";
        } else if (status.limit) {
            text = "Generating schedules… found " + status.found + " of " + status.limit;
        } else {
            text = "Generating schedules… found " + status.found;
        }
        // Whole steps of 5 seconds, so the line (read aloud by a screen reader) does not change every second.
        return text + " (" + Math.floor((status.elapsed || 0) / 5) * 5 + "s)";
    }

    function startProgress(thinking) {
        stopProgress();
        if (!statusUrl || typeof window.fetch !== "function") {
            return;
        }
        progressTimer = window.setInterval(function () {
            fetch(statusUrl, { credentials: "same-origin", headers: { Accept: "application/json" } })
                .then(function (response) {
                    return response.ok ? response.json() : null;
                })
                .then(function (status) {
                    if (progressTimer === null || !status || status.state !== "running") {
                        return;   // nothing is generating (an ordinary request): keep "Working on it…"
                    }
                    var text = describeProgress(status);
                    if (thinking.textContent !== text) {
                        thinking.textContent = text;
                    }
                })
                .catch(function () {
                    // Progress is a courtesy; the request itself still ends with a clear answer.
                });
        }, PROGRESS_MS);
    }

    function stopProgress() {
        if (progressTimer !== null) {
            window.clearInterval(progressTimer);
            progressTimer = null;
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

    // -- the page behind the chat, updated in place ------------------------------------------------- //
    function fieldsChanged(main) {
        var fields = main.querySelectorAll("input, textarea, select");
        for (var index = 0; index < fields.length; index++) {
            var field = fields[index];
            var type = (field.type || "").toLowerCase();
            if (field.hasAttribute("data-filter-input") || type === "hidden" || type === "submit" ||
                type === "button" || type === "file") {
                continue;
            }
            if (type === "checkbox" || type === "radio") {
                if (field.checked !== field.defaultChecked) {
                    return true;
                }
            } else if (field.tagName === "SELECT") {
                for (var option = 0; option < field.options.length; option++) {
                    if (field.options[option].selected !== field.options[option].defaultSelected) {
                        return true;
                    }
                }
            } else if (field.value !== field.defaultValue) {
                return true;
            }
        }
        return false;
    }

    function openDropdowns(main) {
        var open = [];
        main.querySelectorAll("details[open]").forEach(function (details) {
            var summary = details.querySelector("summary");
            open.push(summary ? summary.textContent.trim() : "");
        });
        return open;
    }

    function reopenDropdowns(main, open) {
        main.querySelectorAll("details").forEach(function (details) {
            var summary = details.querySelector("summary");
            if (summary && open.indexOf(summary.textContent.trim()) !== -1) {
                details.open = true;
            }
        });
    }

    function filterValues(main) {
        var values = {};
        main.querySelectorAll("[data-filter-input]").forEach(function (box) {
            if (box.id && box.value) {
                values[box.id] = box.value;
            }
        });
        return values;
    }

    function restoreFilters(main, values) {
        Object.keys(values).forEach(function (id) {
            var box = document.getElementById(id);
            if (box) {
                box.value = values[id];
                box.dispatchEvent(new Event("input", { bubbles: true }));
            }
        });
    }

    function replaceContent(main, fresh) {
        var nodes = Array.prototype.slice.call(fresh.childNodes).map(function (node) {
            return document.adoptNode(node);
        });
        while (main.firstChild) {
            main.removeChild(main.firstChild);
        }
        nodes.forEach(function (node) {
            main.appendChild(node);
        });
    }

    function syncTopBar(doc) {
        var next = doc.querySelector(".nav-status");
        var current = document.querySelector(".nav-status");
        if (next && current) {
            current.className = next.className;
            current.textContent = next.textContent.replace(/\s+/g, " ").trim();
            var strong = next.querySelector("strong");
            if (strong) {
                var label = document.createElement("strong");
                label.textContent = strong.textContent;
                current.textContent = "Configuration: ";
                current.appendChild(label);
            }
        }
        if (doc.title) {
            document.title = doc.title;
        }
    }

    // Fetch the page again and swap its content in. Resolves true when the page now shows the change.
    function updatePage() {
        var main = document.getElementById("main");
        var running = document.getElementById("generation-progress");
        if (!main || typeof window.fetch !== "function" || typeof window.DOMParser === "undefined") {
            return Promise.resolve(false);
        }
        if (fieldsChanged(main) || (running && !running.hidden)) {
            return Promise.resolve(false);   // never throw away what the user typed, or a run this page is showing
        }
        return fetch(window.location.href, {
            credentials: "same-origin",
            headers: { Accept: "text/html", "X-Requested-With": "XMLHttpRequest" }
        })
            .then(function (response) {
                if (response.redirected && new URL(response.url).pathname !== window.location.pathname) {
                    window.location.assign(response.url);   // this page is no longer where it was
                    return null;
                }
                return response.text();
            })
            .then(function (html) {
                if (html === null) {
                    return true;
                }
                var doc = new DOMParser().parseFromString(html, "text/html");
                var fresh = doc.getElementById("main");
                var now = document.getElementById("main");
                if (!fresh || !now || fieldsChanged(now)) {
                    return false;
                }
                var scroll = window.scrollY;
                var dropdowns = openDropdowns(now);
                var filters = filterValues(now);
                replaceContent(now, fresh);
                reopenDropdowns(now, dropdowns);
                syncTopBar(doc);
                document.dispatchEvent(new CustomEvent(UPDATED_EVENT));   // page scripts wire the new content ...
                restoreFilters(now, filters);   // ... so the kept filter text is applied to it
                window.scrollTo(0, scroll);
                return true;
            })
            .catch(function () {
                return false;
            });
    }

    // The reply says something changed behind the page: update it, or say how to see the change.
    function liveUpdate(item) {
        return updatePage().then(function (done) {
            if (done) {
                return;
            }
            if (!item) {
                item = addMessage("notice", "The page behind the chat may be out of date.");
            }
            addRefreshButton(item);
        });
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

    // -- saved chats ------------------------------------------------------------------------------- //
    function csrfData(extra) {
        var data = new FormData();
        var token = form.querySelector("input[name=csrfmiddlewaretoken]");
        data.set("csrfmiddlewaretoken", token ? token.value : "");
        Object.keys(extra || {}).forEach(function (key) {
            data.set(key, extra[key]);
        });
        return data;
    }

    function chatRequest(url, extra) {
        var options = { credentials: "same-origin", headers: { Accept: "application/json" } };
        if (extra) {
            options.method = "POST";
            options.body = csrfData(extra);
        }
        return fetch(url, options).then(function (response) {
            return response.json().then(function (body) {
                return { ok: response.ok, body: body };
            });
        });
    }

    function updatePicker(state) {
        if (!picker) {
            return;
        }
        while (picker.firstChild) {
            picker.removeChild(picker.firstChild);
        }
        state.chats.forEach(function (chat) {
            var option = document.createElement("option");
            option.value = chat.id;
            option.textContent = chat.title;
            option.selected = chat.active;
            picker.appendChild(option);
        });
        deleteButton.disabled = pending;
    }

    function renderChat(state) {
        activeChat = state.active;
        while (log.lastChild && log.lastChild !== greeting) {
            log.removeChild(log.lastChild);
        }
        state.messages.forEach(function (message, index) {
            var kind = message.kind === "user" ? "user" : (message.kind === "error" ? "error" : "assistant");
            var item = addMessage(kind, message.text);
            if (message.generated) {
                offerViewer(item);
            }
            if (index === state.messages.length - 1 && message.suggestions && message.suggestions.length) {
                addSuggestions(item, message.suggestions);
            }
        });
        updatePicker(state);
        log.scrollTop = log.scrollHeight;
    }

    // Only the list (not the lines): the picker's titles after a message was sent.
    function refreshChats() {
        if (!chatUrl) {
            return;
        }
        chatRequest(chatUrl).then(function (result) {
            if (result.ok && result.body && result.body.chats) {
                updatePicker(result.body);
            }
        }).catch(function () {
            // The picker is a courtesy; the conversation itself is already on screen.
        });
    }

    function stopResuming() {
        if (resumeTimer !== null) {
            window.clearInterval(resumeTimer);
            resumeTimer = null;
        }
    }

    // A request was still running when the page changed: show that, and draw the answer when it is done.
    function resumeRunning() {
        stopResuming();
        stopProgress();
        var thinking = addMessage("status", "Working on it…");
        setPending(true);
        startProgress(thinking);
        resumeTimer = window.setInterval(function () {
            chatRequest(chatUrl).then(function (result) {
                if (resumeTimer === null || !result.body || result.body.busy) {
                    return;
                }
                stopResuming();
                stopProgress();
                renderChat(result.body);
                setPending(false);
                liveUpdate(null);   // whatever it did, the page behind the chat should match
            }).catch(function () {
                // Try again on the next tick.
            });
        }, PROGRESS_MS);
    }

    function applyChat(result) {
        if (!result.body || !result.body.chats) {
            addMessage("error", NETWORK_PROBLEM);
            return;
        }
        stopResuming();
        stopProgress();
        setPending(false);
        renderChat(result.body);
        if (result.body.busy) {
            resumeRunning();
        } else if (result.body.error) {
            addMessage("notice", result.body.error);
        }
    }

    function loadChats() {
        if (!chatUrl || typeof window.fetch !== "function") {
            return;
        }
        chatRequest(chatUrl).then(function (result) {
            if (!result.body || !result.body.chats) {
                return;
            }
            toolbar.hidden = false;
            renderChat(result.body);
            if (result.body.busy) {
                resumeRunning();
            }
        }).catch(function () {
            // No saved chat could be loaded: the panel still works for new messages.
        });
    }

    function chatAction(url, extra) {
        if (pending) {
            return;
        }
        chatRequest(url, extra).then(applyChat).catch(function () {
            addMessage("error", NETWORK_PROBLEM);
        });
    }

    // Delete asks twice (no pop-up): the first click changes the label, the second one deletes.
    function resetDelete() {
        if (deleteTimer !== null) {
            window.clearTimeout(deleteTimer);
            deleteTimer = null;
        }
        deleteButton.textContent = "Delete";
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

        clearSuggestions();
        addMessage("user", text);
        input.value = "";
        setPending(true);
        var thinking = addMessage("status", "Working on it…");
        startProgress(thinking);

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
                stopProgress();
                show(thinking, result);
                setPending(false);
                input.focus();
            });
    }

    // -- wiring ---------------------------------------------------------------------------- //
    launcher.addEventListener("click", function () {
        setOpen(!isOpen());
    });
    if (toolbar) {
        newButton.addEventListener("click", function () {
            resetDelete();
            chatAction(newUrl, {});
            input.focus();
        });
        picker.addEventListener("change", function () {
            resetDelete();
            if (picker.value && picker.value !== activeChat) {
                chatAction(switchUrl, { id: picker.value });
            }
        });
        deleteButton.addEventListener("click", function () {
            if (pending || !activeChat) {
                return;
            }
            if (deleteTimer === null) {
                deleteButton.textContent = "Really delete?";
                deleteTimer = window.setTimeout(resetDelete, 4000);
                return;
            }
            resetDelete();
            chatAction(deleteUrl, { id: activeChat });
        });
    }
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
    if (readOpen() && !isTucked()) {
        setOpen(true, true);   // the panel was open on the page before this one
    }
    loadChats();
})();
