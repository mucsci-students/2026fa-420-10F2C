// Forms with data-loading="Message" show a busy state on submit and
// ignore a second submit while the first is still running (Sections 13, 19;
// user story 48 / board card #76).
//
// - The banner (#loading-status in base.html) shows the message with a spinner.
// - The pressed button shows the message too (e.g. "Loading…") until the page
//   answers; the server's next page, with its success or error message,
//   replaces the busy state.
// - Downloads don't load a new page, so forms that answer with a file also
//   get data-loading-download. The script sends a random download_token; the
//   server echoes it back in a cookie with the file (gui/views.py:
//   download_response), and when it appears the busy state ends with
//   "Download started."
(function () {
  var TOKEN_FIELD = "download_token";
  var TOKEN_COOKIE = "download_token";
  var POLL_MS = 250;
  var GIVE_UP_MS = 60000;

  function status() {
    return document.getElementById("loading-status");
  }

  function showStatus(html) {
    var box = status();
    if (box) { box.hidden = false; box.innerHTML = html; }
  }

  function reset(form) {
    delete form.dataset.submitting;
    form.removeAttribute("aria-busy");
    form.querySelectorAll("button[type=submit]").forEach(function (b) {
      b.removeAttribute("aria-disabled");
      b.classList.remove("btn-disabled");
      if (b.dataset.loadingLabel !== undefined) {
        b.textContent = b.dataset.loadingLabel;
        delete b.dataset.loadingLabel;
      }
    });
    var box = status();
    if (box) { box.hidden = true; box.textContent = ""; }
  }

  function readCookie(name) {
    var parts = document.cookie ? document.cookie.split("; ") : [];
    for (var i = 0; i < parts.length; i++) {
      var eq = parts[i].indexOf("=");
      if (parts[i].slice(0, eq) === name) return decodeURIComponent(parts[i].slice(eq + 1));
    }
    return null;
  }

  function clearCookie(name) {
    document.cookie = name + "=; Max-Age=0; path=/; SameSite=Lax";
  }

  function tokenInput(form) {
    var input = form.querySelector("input[name=" + TOKEN_FIELD + "]");
    if (!input) {
      input = document.createElement("input");
      input.type = "hidden";
      input.name = TOKEN_FIELD;
      form.appendChild(input);
    }
    return input;
  }

  function waitForDownload(form, token) {
    var started = Date.now();
    var timer = setInterval(function () {
      if (readCookie(TOKEN_COOKIE) === token) {
        clearInterval(timer);
        clearCookie(TOKEN_COOKIE);
        reset(form);
        showStatus("<strong>Download started.</strong> Your browser shows where the file was saved.");
      } else if (Date.now() - started > GIVE_UP_MS) {
        clearInterval(timer);
        reset(form);
        showStatus("<strong>This is taking longer than expected.</strong> Check your browser's downloads, or try again.");
      }
    }, POLL_MS);
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.dataset || !form.dataset.loading) return;
    if (form.dataset.submitting) { event.preventDefault(); return; } // duplicate click
    form.dataset.submitting = "true";
    form.setAttribute("aria-busy", "true");

    var token = null;
    if (form.dataset.loadingDownload !== undefined) {
      token = Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
      clearCookie(TOKEN_COOKIE);
      tokenInput(form).value = token;
    }

    form.querySelectorAll("button[type=submit]").forEach(function (b) {
      b.setAttribute("aria-disabled", "true"); // aria-disabled keeps the button's value in the POST
      b.classList.add("btn-disabled");
    });
    var pressed = event.submitter;
    if (pressed && pressed.tagName === "BUTTON") {
      pressed.dataset.loadingLabel = pressed.textContent;
      pressed.textContent = form.dataset.loading;
    }
    showStatus('<span class="spinner" aria-hidden="true"></span> ' +
      "<strong>" + form.dataset.loading + "</strong> This can take a while; please don't close this page.");

    if (token) waitForDownload(form, token);
  });

  // Back/forward cache can restore a page stuck in the busy state.
  window.addEventListener("pageshow", function () {
    document.querySelectorAll("form[data-loading]").forEach(reset);
  });
})();
