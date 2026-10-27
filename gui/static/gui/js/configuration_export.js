/*
 * The chat's side of saving a configuration and starting a new one (Sprint 3).
 * Markup: gui/templates/gui/components/chat_widget.html. Server side: gui/ai/lifecycle.py.
 *
 * What it does
 *   - "Save JSON": submits the hidden #config-export-form, a plain form post to the same Save view
 *     the Configuration Editor's Save button uses. The server answers with an ordinary file
 *     download (Content-Disposition: attachment), which every browser handles the same way, so
 *     there is nothing here that needs a special browser feature. Submitting it inside the click
 *     keeps the download a direct result of the user's action. loading.js watches for the
 *     download's cookie, exactly as it does for the editor's button.
 *   - A new configuration that would discard unsaved changes or schedules gets three buttons:
 *     Save JSON, Discard and Continue, Cancel. Only "Discard and Continue" replaces anything, and
 *     only through the server's single-use token (gui/controllers/config_controller.py).
 *   - Every message says that a download is only started: the page cannot see whether the browser
 *     finished it.
 *
 * chat.js calls ConfigurationExport.addAction() for each action the server sends with a reply and
 * passes a small `chat` object (addMessage, offerRefresh, showUnsaved) so this file never touches
 * the chat panel's markup itself. Messages are inserted as text, never as HTML.
 */
(function () {
    "use strict";

    var root = document.querySelector("[data-chat]");
    var exportForm = document.getElementById("config-export-form");
    if (!root || !exportForm) {
        return;
    }

    var DOWNLOAD_NOTE = "Your browser decides where the file goes, and this app can't tell whether the download finished.";
    var NETWORK_PROBLEM =
        "Could not reach the server, so nothing was confirmed. Check your configuration before trying again.";

    function element(tag, className, text) {
        var node = document.createElement(tag);
        node.className = className;
        if (text) {
            node.textContent = text;
        }
        return node;
    }

    function button(row, label, primary, onClick) {
        var item = element("button", "btn btn-small" + (primary ? " btn-primary" : ""), label);
        item.type = "button";
        item.addEventListener("click", onClick);
        row.appendChild(item);
        return item;
    }

    // One download path for the chat: the same view and the same standard download as the editor.
    // Returns "invalid" when the File name box holds something the browser rejects (nothing is sent),
    // "busy" while an earlier download is still starting (loading.js ignores a second click), else "started".
    function startDownload(input) {
        if (!input.reportValidity()) {
            return "invalid";
        }
        if (exportForm.dataset.submitting) {
            return "busy";
        }
        exportForm.elements.filename.value = input.value.trim();
        if (typeof exportForm.requestSubmit === "function") {
            exportForm.requestSubmit();   // fires "submit", which loading.js uses to show the download state
        } else {
            exportForm.submit();
        }
        return "started";
    }

    // Says in the chat what the click did. "invalid" says nothing: the box shows the browser's own message.
    function announceDownload(chat, result, extra) {
        if (result === "started") {
            chat.addMessage("assistant", "Download requested. " + DOWNLOAD_NOTE + (extra || ""));
        } else if (result === "busy") {
            chat.addMessage("notice", "A download is already starting. Wait a moment, then click Save JSON again.");
        }
    }

    // The File name box, with the same pattern and length the editor's box and the server use.
    // Enter in the box does what the Save JSON button next to it does (the box is not inside a form).
    function fileNameBox(parent, action, onEnter) {
        var label = element("label", "chat-filename", "File name");
        var input = element("input", "");
        input.type = "text";
        input.value = action.filename || "";
        input.maxLength = action.maxlength;
        input.setAttribute("pattern", action.pattern);
        input.title = "A file name only, with no folders. .json is added if it is missing.";
        input.autocomplete = "off";
        input.addEventListener("keydown", function (event) {
            if (event.key === "Enter" && !event.isComposing) {
                event.preventDefault();
                onEnter();
            }
        });
        label.appendChild(input);
        parent.appendChild(label);
        return input;
    }

    function post(url, token) {
        var data = new FormData();
        data.set("csrfmiddlewaretoken", exportForm.elements.csrfmiddlewaretoken.value);
        data.set("token", token);
        return fetch(url, {
            method: "POST",
            body: data,
            credentials: "same-origin",
            headers: { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" }
        })
            .then(function (response) {
                return response.json().then(
                    function (body) { return body; },
                    function () { return null; }
                );
            })
            .catch(function () { return null; });
    }

    function exportAction(parent, action, chat) {
        var input = fileNameBox(parent, action, save);
        var row = element("span", "chat-actions");

        function save() {
            announceDownload(chat, startDownload(input));
        }

        button(row, "Save JSON", true, save);
        parent.appendChild(row);
    }

    function replaceAction(parent, action, chat) {
        var input = fileNameBox(parent, action, save);   // Enter saves a copy; it never discards anything
        var row = element("span", "chat-actions");
        var status = element("span", "chat-action-status");
        var buttons = [];
        var deciding = false;

        function save() {
            announceDownload(
                chat,
                startDownload(input),
                " Nothing was replaced: choose Discard and Continue or Cancel on the warning above."
            );
        }

        function setDisabled(disabled) {
            buttons.forEach(function (item) { item.disabled = disabled; });
            input.disabled = disabled;
        }

        function decide(url) {
            if (deciding) {
                return;
            }
            deciding = true;
            setDisabled(true);
            post(url, action.token).then(function (body) {
                deciding = false;
                if (!body || typeof body.message !== "string") {
                    status.textContent = NETWORK_PROBLEM;
                    setDisabled(false);   // the server may not have seen it, so the choice stays open
                    return;
                }
                // The warning is single use: whatever the server answered, the buttons stay off.
                var item = chat.addMessage(body.ok ? "assistant" : "error", body.message);
                if (body.dirty) {
                    chat.showUnsaved();
                }
                if (body.changed) {
                    chat.offerRefresh(item);   // the page behind the chat still shows the old configuration
                }
            });
        }

        buttons.push(button(row, "Save JSON", false, save));
        buttons.push(button(row, "Discard and Continue", false, function () { decide(root.dataset.newConfirm); }));
        buttons.push(button(row, "Cancel", false, function () { decide(root.dataset.newCancel); }));
        parent.appendChild(row);
        parent.appendChild(status);
    }

    function configurationAction(parent) {
        var row = element("span", "chat-actions");
        [["New Configuration", "#new-configuration"], ["Load Configuration", "#load-configuration"]].forEach(function (entry) {
            var link = element("a", "btn btn-small", entry[0]);
            link.href = root.dataset.configEditor + entry[1];
            row.appendChild(link);
        });
        parent.appendChild(row);
    }

    window.ConfigurationExport = {
        addAction: function (parent, action, chat) {
            if (action.kind === "export") {
                exportAction(parent, action, chat);
            } else if (action.kind === "replace") {
                replaceAction(parent, action, chat);
            } else if (action.kind === "configuration") {
                configurationAction(parent);
            } else if (action.kind === "refresh") {
                chat.offerRefresh(parent);
            }
        }
    };
})();
