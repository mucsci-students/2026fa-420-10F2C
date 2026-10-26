// AI Assistant chat (Sprint 3 user stories 2 and 3).
//
// Progressive enhancement: without JavaScript the form posts to
// /assistant/ask/ and the page comes back with the reply. With it:
//   * the request is added to the conversation and stays visible, with a
//     "Processing" status under it, as soon as it is sent (story 2);
//   * while it runs, more submits (button or Enter) are ignored, so only one
//     request reaches the server (story 3); the server refuses duplicates too;
//   * when it finishes, success or failure, the status is replaced by the
//     reply and the input takes a new request.
(function () {
  "use strict";

  var form = document.querySelector("form[data-ai-form]");
  if (!form || typeof window.fetch !== "function") { return; }

  var input = form.querySelector("[name=message]");
  var button = form.querySelector("button[type=submit]");
  var hint = form.querySelector("[data-ai-hint]");
  var hintText = hint ? hint.textContent : "";
  var log = document.getElementById("ai-log");
  var empty = document.querySelector("[data-ai-empty]");
  var busy = false;

  var PROCESSING = "Processing your request…";
  var NO_ANSWER = "Couldn't get an answer from the server. Check the configuration before trying again.";

  function token() {
    var field = form.querySelector("input[name=csrfmiddlewaretoken]");
    return field ? field.value : "";
  }

  function setHint(text, isError) {
    if (!hint) { return; }
    hint.textContent = text;
    hint.classList.toggle("ai-hint--error", Boolean(isError));
  }

  function setBusy(on) {
    busy = on;
    input.readOnly = on;
    button.disabled = on;
    form.setAttribute("aria-busy", on ? "true" : "false");
  }

  function line(className, label, text) {
    var p = document.createElement("p");
    p.className = className;
    var strong = document.createElement("strong");
    strong.textContent = label;
    var span = document.createElement("span");
    span.textContent = text;
    p.appendChild(strong);
    p.appendChild(document.createTextNode(" "));
    p.appendChild(span);
    return p;
  }

  function addEntry(text) {
    var item = document.createElement("li");
    item.className = "ai-entry";
    item.appendChild(line("ai-entry__request", "You:", text));

    var status = document.createElement("p");
    status.className = "ai-entry__reply ai-entry__reply--processing";
    status.setAttribute("role", "status");
    status.setAttribute("data-ai-processing", "");
    var spinner = document.createElement("span");
    spinner.className = "spinner";
    spinner.setAttribute("aria-hidden", "true");
    var label = document.createElement("span");
    label.textContent = PROCESSING;
    status.appendChild(spinner);
    status.appendChild(label);
    item.appendChild(status);

    log.appendChild(item);
    if (empty) { empty.hidden = true; }
    item.scrollIntoView({ block: "nearest" });
    return status;
  }

  function finish(status, ok, text) {
    var reply = line(
      "ai-entry__reply " + (ok ? "ai-entry__reply--ok" : "ai-entry__reply--error"),
      ok ? "Assistant:" : "Error:",
      text
    );
    status.replaceWith(reply);
  }

  function showDirty() {
    var nav = document.querySelector(".nav-status");
    if (!nav) { return; }
    nav.classList.add("nav-status--dirty");
    nav.innerHTML = "Configuration: <strong>Unsaved changes</strong>";
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (busy) { return; } // story 3: a second submit while one is running is ignored

    var text = input.value.trim();
    if (!text) {
      setHint("Type a request first.", true);
      input.focus();
      return;
    }
    setHint(hintText, false);

    var body = new FormData(form);
    setBusy(true);
    var status = addEntry(text);
    input.value = "";

    fetch(form.action, {
      method: "POST",
      body: body,
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": token() },
    })
      .then(function (response) {
        return response.json().catch(function () { return null; });
      })
      .then(function (data) {
        if (!data || typeof data.reply !== "string") {
          finish(status, false, NO_ANSWER);
          return;
        }
        finish(status, Boolean(data.ok), data.reply);
        if (data.dirty) { showDirty(); }
      })
      .catch(function () {
        finish(status, false, NO_ANSWER);
      })
      .then(function () {
        setBusy(false);
        input.focus();
      });
  });
})();
