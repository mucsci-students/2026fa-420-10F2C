// Live progress for schedule generation (Sections 13 and 19).
//
// Progressive enhancement: without JavaScript the generator form still posts
// to /generate/ and waits for the result. With it, the form starts a
// background run (POST data-start-url), then polls data-status-url and fills
// the <progress> bar until the run finishes, then follows the server's
// "redirect". The Cancel button posts to data-cancel-url.
//
// Two places start a run, and both use the one progress panel on the page:
//   * the Schedule Generator: form[data-generation-form], with the override fields;
//   * the Schedule Viewer: form[data-regenerate-form], "Generate again" with the
//     saved settings. Its panel sits inside the lock banner and carries
//     data-return-url, so the run ends back in the viewer (the server's own
//     redirect would send a failed run to the generator page).
// While a run is going the page is marked busy: elements with
// data-hide-while-generating are hidden, the lock buttons are switched off (the
// run keeps the locks it started with) and the calendar is dimmed.
(function () {
  "use strict";

  function start() {
    var panel = document.getElementById("generation-progress");
    if (!panel || typeof window.fetch !== "function") { return; }

    var forms = Array.prototype.slice.call(
      document.querySelectorAll("form[data-generation-form], form[data-regenerate-form]")
    );
    var bar = panel.querySelector("progress");
    var text = panel.querySelector("[data-progress-text]");
    var cancel = panel.querySelector("[data-progress-cancel]");
    var announce = panel.querySelector("[data-progress-announce]");
    var errors = document.getElementById("generation-errors");

    var POLL_MS = 500;
    var RETRY_MS = 1000;
    var MAX_FAILURES = 10;
    var failures = 0;
    var timer = null;
    var starting = false;

    function token() {
      var input = document.querySelector("input[name=csrfmiddlewaretoken]");
      return input ? input.value : "";
    }

    function request(url, options) {
      options = options || {};
      options.credentials = "same-origin";
      options.headers = Object.assign(
        { "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": token() },
        options.headers || {}
      );
      return fetch(url, options).then(function (response) {
        return response.json().then(function (body) {
          return { ok: response.ok, status: response.status, body: body };
        });
      });
    }

    function say(message) { if (announce) { announce.textContent = message; } }

    function showErrors(list) {
      if (!errors) { return; }
      errors.textContent = "Error: " + (list && list.length ? list.join(" ") : "Something went wrong.");
      errors.hidden = false;
    }

    function hideErrors() {
      if (errors) { errors.hidden = true; errors.textContent = ""; }
    }

    // Every start button on the page (the generator's, and each "Generate again").
    function setStarting(on) {
      forms.forEach(function (form) {
        var button = form.querySelector("button[type=submit]");
        if (!button) { return; }
        if (button.dataset.idleLabel === undefined) { button.dataset.idleLabel = button.textContent; }
        if (on) {
          button.disabled = true;
          button.setAttribute("aria-disabled", "true");
          button.textContent = "Generating…";
        } else {
          button.disabled = false;
          button.removeAttribute("aria-disabled");
          button.textContent = button.dataset.idleLabel;
        }
      });
    }

    // While a run is going: hide what does not apply, freeze the locks, dim the old schedules.
    function setBusy(on) {
      document.documentElement.classList.toggle("is-generating", on);
      Array.prototype.forEach.call(document.querySelectorAll("[data-hide-while-generating]"), function (element) {
        element.hidden = on;
      });
      Array.prototype.forEach.call(document.querySelectorAll("button[form=lock-form]"), function (button) {
        button.disabled = on;
        if (on) { button.setAttribute("aria-disabled", "true"); }
        else { button.removeAttribute("aria-disabled"); }
      });
    }

    function plural(n, word) { return n + " " + word + (n === 1 ? "" : "s"); }

    function describe(s) {
      var elapsed = Math.round(s.elapsed || 0) + "s elapsed";
      if (s.cancel_requested) {
        return "Cancelling… waiting for the solver to finish the schedule it is working on. " + elapsed;
      }
      if (!s.found) { return "Solving for the first schedule… " + elapsed; }
      if (s.limit) {
        return "Found " + s.found + " of " + plural(s.limit, "schedule") + " (" + s.percent + "%) · " + elapsed;
      }
      return "Found " + plural(s.found, "schedule") + " · " + elapsed;
    }

    function render(s) {
      panel.hidden = false;
      if (typeof s.percent === "number" && s.found) { bar.value = s.percent; }
      else { bar.removeAttribute("value"); } // indeterminate until the first schedule / when there is no limit
      text.textContent = describe(s);
      if (cancel) { cancel.disabled = !!s.cancel_requested; }
    }

    function schedule(ms) { timer = setTimeout(tick, ms); }

    function stop() { if (timer) { clearTimeout(timer); timer = null; } }

    function finished(s) {
      stop();
      if (typeof s.percent === "number") { bar.value = s.percent; }
      text.textContent = s.message || "Finished.";
      say("Schedule generation finished.");
      var next = panel.dataset.returnUrl || s.redirect || window.location.pathname;
      setTimeout(function () { window.location.assign(next); }, 400);
    }

    function tick() {
      request(panel.dataset.statusUrl).then(function (res) {
        if (!res.ok) { throw new Error("status " + res.status); }
        failures = 0;
        var s = res.body;
        if (s.state === "running") { render(s); schedule(POLL_MS); }
        else { finished(s); }
      }).catch(function () {
        failures += 1;
        if (failures >= MAX_FAILURES) {
          stop();
          text.textContent = "Progress is unavailable. Reload this page to check on the generation.";
          showErrors(["Lost contact with the server."]);
        } else {
          text.textContent = "Lost contact with the server; retrying…";
          schedule(RETRY_MS);
        }
      });
    }

    function begin(initial) {
      hideErrors();
      failures = 0;
      setBusy(true);
      render(initial);
      schedule(POLL_MS);
    }

    forms.forEach(function (form) {
      if (form.dataset.wired === "true") { return; }
      form.dataset.wired = "true";
      // Runs on the form itself, before loading.js sees the event on document.
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        event.stopPropagation();
        if (starting) { return; }
        starting = true;
        hideErrors();
        setStarting(true);
        request(form.dataset.startUrl, { method: "POST", body: new FormData(form) }).then(function (res) {
          starting = false;
          if (!res.ok || !res.body.started) {
            setStarting(false);
            showErrors(res.body.errors);
            return;
          }
          say("Schedule generation started.");
          begin(res.body.status);
          // A button far down the page (the lock card) starts a run whose progress is at the top.
          if (form.hasAttribute("data-regenerate-form") && panel.scrollIntoView) {
            panel.scrollIntoView({ block: "nearest" });
          }
        }).catch(function () {
          starting = false;
          setStarting(false);
          showErrors(["Could not start generation. Check that the server is still running and try again."]);
        });
      });
    });

    if (cancel && cancel.dataset.wired !== "true") {
      cancel.dataset.wired = "true";
      cancel.addEventListener("click", function () {
        cancel.disabled = true;
        request(panel.dataset.cancelUrl, { method: "POST" }).then(function (res) {
          if (res.ok) { render(res.body.status); say("Cancelling schedule generation."); }
          else { cancel.disabled = false; showErrors(res.body.errors); }
        }).catch(function () {
          cancel.disabled = false;
          showErrors(["Could not reach the server to cancel."]);
        });
      });
    }

    // Back/forward cache can restore a finished page; start clean.
    if (!window.__generationPageshow) {
      window.__generationPageshow = true;
      window.addEventListener("pageshow", function (event) {
        if (event.persisted) { window.location.reload(); }
      });
    }

    // A run is already going (page reload, second tab): pick up where it is.
    if (panel.dataset.active === "true") {
      setStarting(true);
      begin({ found: 0, limit: null, percent: null, elapsed: 0, cancel_requested: false });
      stop();
      tick();
    }
  }

  start();
  // The AI chat swaps the page content in place; the new form and panel need wiring again.
  document.addEventListener("scheduler:content-updated", start);
})();
