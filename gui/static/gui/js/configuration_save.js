(function () {
    "use strict";

    var settings = document.body.dataset;
    var unsupported = "Saving requires a browser with the File System Access API, such as desktop Chrome or Edge, on localhost or HTTPS. Nothing was saved; existing unsaved changes remain.";

    function note(parent, text) {
        var message = document.createElement("span");
        message.setAttribute("role", "status");
        message.textContent = text;
        parent.appendChild(message);
        return message;
    }

    function supported() {
        return window.isSecureContext && typeof window.showSaveFilePicker === "function";
    }

    async function post(url, values) {
        var data = new FormData();
        Object.keys(values).forEach(function (key) { data.set(key, values[key]); });
        var csrf = document.querySelector("input[name=csrfmiddlewaretoken]");
        if (!csrf) { throw new Error("Missing security token. Reload the page before trying again."); }
        data.set("csrfmiddlewaretoken", csrf.value);
        var response = await fetch(url, { method: "POST", body: data, credentials: "same-origin" });
        var body = await response.json();
        if (!response.ok) { throw new Error(body.error || "The server could not complete this operation."); }
        return body;
    }

    function updateStatus(result) {
        var status = document.querySelector(".nav-status");
        if (status) {
            status.classList.toggle("nav-status--dirty", result.dirty);
            status.textContent = result.dirty ? "Configuration: Unsaved changes" : "Configuration: no unsaved changes";
        }
        var detail = document.querySelector("[data-configuration-status]");
        if (detail && result.current_snapshot) {
            detail.textContent = result.dirty
                ? "Saved '" + result.filename + "'. Current configuration still has unsaved changes."
                : "Saved as '" + result.filename + "'. No unsaved changes.";
            detail.parentElement.classList.toggle("status-card--dirty", result.dirty);
        }
    }

    function button(parent, label, handler) {
        var element = document.createElement("button");
        element.type = "button";
        element.className = "btn btn-small";
        element.textContent = label;
        element.addEventListener("click", handler);
        parent.appendChild(element);
        return element;
    }

    function saveAction(parent, action) {
        if (!supported()) {
            note(parent, unsupported);
            return;
        }
        var status = note(parent, "Not saved yet. Choose a destination with Save JSON.");
        var busy = false;
        var writtenName = null;
        var saveButton;
        var cancelButton;

        async function acknowledge() {
            var result = await post(settings.saveComplete, { token: action.token, filename: writtenName });
            updateStatus(result);
            status.textContent = "Saved '" + writtenName + "'." +
                (result.dirty ? " Newer or different configuration changes remain unsaved." : " No unsaved changes.");
            saveButton.disabled = true;
            cancelButton.disabled = true;
        }

        saveButton = button(parent, "Save JSON", async function () {
            if (busy) { return; }
            busy = true;
            saveButton.disabled = true;
            cancelButton.disabled = true;
            var stream = null;
            try {
                if (writtenName) {
                    await acknowledge();
                    return;
                }
                var handle = await window.showSaveFilePicker({
                    suggestedName: action.filename,
                    types: [{ description: "JSON configuration", accept: { "application/json": [".json"] } }]
                });
                if (!/\.json$/i.test(handle.name) || /[/\\\x00-\x1f]/.test(handle.name)) {
                    throw new Error("Choose a JSON filename without path characters.");
                }
                if (!window.confirm("Write '" + handle.name + "'? If this file already exists, its contents will be replaced. Choose Cancel to leave it unchanged.")) {
                    await post(settings.saveCancel, { token: action.token });
                    status.textContent = "Save cancelled. No file contents were written.";
                    return;
                }
                await post(settings.saveBegin, { token: action.token, filename: handle.name });
                stream = await handle.createWritable();
                await stream.write(action.content);
                await stream.close();
                stream = null;
                writtenName = handle.name;
                await acknowledge();
            } catch (error) {
                if (stream) {
                    try {
                        await stream.abort();
                    } catch (abortError) {
                        status.textContent = "The write could not be confirmed or aborted. Check the target file. Saved status was not updated.";
                        return;
                    }
                }
                if (writtenName) {
                    status.textContent = "The file write completed, but saved status could not be confirmed: " + error.message +
                        " Retry confirmation only; the file will not be written again.";
                    saveButton.textContent = "Retry saved-status confirmation";
                    saveButton.disabled = false;
                } else if (error.name === "AbortError") {
                    try {
                        await post(settings.saveCancel, { token: action.token });
                        status.textContent = "Save cancelled. Saved status was not changed.";
                    } catch (cancelError) {
                        status.textContent = "Save cancelled, but the pending request could not be cleared: " + cancelError.message;
                    }
                } else {
                    status.textContent = "Save could not be confirmed: " + error.message +
                        " Saved status was not changed. Check the target file before starting a new save.";
                    cancelButton.disabled = false;
                }
            } finally {
                busy = false;
            }
        });

        cancelButton = button(parent, "Cancel save", async function () {
            if (busy) { return; }
            busy = true;
            saveButton.disabled = true;
            cancelButton.disabled = true;
            try {
                await post(settings.saveCancel, { token: action.token });
                status.textContent = "Save cancelled. No file contents were written.";
            } catch (error) {
                status.textContent = "Could not cancel the pending save: " + error.message;
                cancelButton.disabled = false;
            } finally {
                busy = false;
            }
        });
    }

    function addAction(parent, action) {
        if (action.kind === "save") {
            saveAction(parent, action);
        } else if (action.kind === "configuration") {
            [["New Configuration", "#new-configuration"], ["Load Configuration", "#load-configuration"]].forEach(function (entry) {
                var link = document.createElement("a");
                link.className = "btn btn-small";
                link.textContent = entry[0];
                link.href = settings.configEditor + entry[1];
                parent.appendChild(link);
            });
        }
    }

    document.addEventListener("submit", async function (event) {
        var form = event.target;
        if (!form.matches("[data-configuration-save]")) { return; }
        event.preventDefault();
        if (form.dataset.preparing) { return; }
        var output = document.getElementById("configuration-save-result");
        if (!output) {
            output = document.createElement("div");
            output.id = "configuration-save-result";
            form.parentElement.appendChild(output);
        }
        if (!supported()) {
            note(output, unsupported);
            return;
        }
        form.dataset.preparing = "true";
        form.setAttribute("aria-busy", "true");
        var preparing = note(output, "Preparing the current configuration...");
        try {
            var prepared = await post(settings.savePrepare, {});
            addAction(output, Object.assign({ kind: "save" }, prepared));
        } catch (error) {
            note(output, "Could not prepare the save: " + error.message + " Saved status was not changed.");
        } finally {
            delete form.dataset.preparing;
            form.removeAttribute("aria-busy");
            preparing.remove();
        }
    });

    window.ConfigurationSave = { addAction: addAction };
})();
