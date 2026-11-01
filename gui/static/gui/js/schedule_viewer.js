(function () {
  "use strict";
  var onScroll = null;

  function setUp() {
    // Run again when the AI chat swaps the page content in place: drop what the last run left behind.
    var old = document.getElementById("schedule-tooltip");
    if (old) { old.remove(); }
    if (onScroll) { window.removeEventListener("scroll", onScroll, true); onScroll = null; }
    var grid = document.querySelector(".schedule-grid");
    if (!grid) { return; }
    var blocks = Array.prototype.slice.call(grid.querySelectorAll(".schedule-grid__meeting"));

    var tip = document.createElement("div");
    tip.id = "schedule-tooltip";
    tip.className = "schedule-tooltip";
    tip.setAttribute("role", "tooltip");
    tip.hidden = true;
    document.body.appendChild(tip);

    function fill(b) {
      tip.textContent = "";
      var title = document.createElement("strong");
      title.textContent = b.dataset.course;
      tip.appendChild(title);
      [["Faculty", b.dataset.faculty], ["Room / lab", b.dataset.location],
       ["When", b.dataset.when], ["Type", b.dataset.type]].forEach(function (pair) {
        var line = document.createElement("div");
        var key = document.createElement("span");
        key.className = "schedule-tooltip__key";
        key.textContent = pair[0] + ": ";
        line.appendChild(key);
        line.appendChild(document.createTextNode(pair[1]));
        tip.appendChild(line);
      });
    }

    function show(b) {
      fill(b);
      tip.hidden = false;
      var r = b.getBoundingClientRect(), t = tip.getBoundingClientRect();
      var left = Math.min(Math.max(8, r.left + r.width / 2 - t.width / 2), window.innerWidth - t.width - 8);
      var top = r.bottom + 6;
      if (top + t.height > window.innerHeight - 8) { top = Math.max(8, r.top - t.height - 6); }
      tip.style.left = left + "px";
      tip.style.top = top + "px";
      b.setAttribute("aria-describedby", "schedule-tooltip");
    }

    function hide(b) {
      tip.hidden = true;
      if (b) { b.removeAttribute("aria-describedby"); }
    }

    var active = null;
    function toggle(b) {
      active = active === b.dataset.key ? null : b.dataset.key;
      grid.classList.toggle("has-highlight", active !== null);
      blocks.forEach(function (x) {
        x.classList.toggle("is-highlighted", active !== null && x.dataset.key === active);
      });
    }

    blocks.forEach(function (b) {
      b.removeAttribute("title"); // replaced by the tooltip above
      b.addEventListener("mouseenter", function () { show(b); });
      b.addEventListener("mouseleave", function () { hide(b); });
      b.addEventListener("focus", function () { show(b); });
      b.addEventListener("blur", function () { hide(b); });
      b.addEventListener("click", function () { toggle(b); });
      b.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(b); }
        if (e.key === "Escape") { hide(b); }
      });
    });
    onScroll = function () { tip.hidden = true; };
    window.addEventListener("scroll", onScroll, true);
  }

  // -- Rooms & labs / Faculty checkbox bar ------------------------------------------------------ //
  // Without JavaScript the bar is a plain GET form with an Apply button. With it, ticking or
  // unticking a box redraws the calendar straight away: the page is fetched with the new
  // ?resource= values and only the parts that change are swapped in (the calendar, the bar's
  // status line and the Previous/Next links), so the scroll position and the bar stay put.
  var SWAPPED = ["schedule-grid-wrap", "resource-bar-status", "schedule-pager"];
  var pending = null;

  function refresh(bar) {
    var url = window.location.pathname + "?" + new URLSearchParams(new FormData(bar)).toString();
    if (pending) { pending.abort(); } // a newer tick wins over one still loading
    var request = pending = new AbortController();
    bar.setAttribute("aria-busy", "true");
    fetch(url, { signal: request.signal, credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) { throw new Error("HTTP " + response.status); }
        return response.text();
      })
      .then(function (html) {
        var page = new DOMParser().parseFromString(html, "text/html");
        SWAPPED.forEach(function (id) {
          var now = document.getElementById(id);
          var next = page.getElementById(id);
          if (now && next) { now.replaceWith(document.importNode(next, true)); }
        });
        if (window.history && window.history.replaceState) {
          window.history.replaceState(window.history.state, "", url);
        }
        setUp(); // tooltips and highlighting for the new blocks
      })
      .catch(function (error) {
        if (error.name !== "AbortError") { window.location.href = url; } // fall back to a normal load
      })
      .finally(function () {
        if (pending === request) {
          pending = null;
          bar.removeAttribute("aria-busy");
        }
      });
  }

  function setUpBar() {
    var bar = document.querySelector("[data-resource-bar]");
    if (!bar || bar.dataset.ready) { return; }
    bar.dataset.ready = "1";
    bar.addEventListener("change", function () { refresh(bar); });
    // "Show all" just unticks everything, so it updates in place like a tick does.
    bar.addEventListener("click", function (e) {
      if (!e.target.closest(".resource-bar__clear")) { return; }
      e.preventDefault();
      bar.querySelectorAll('input[name="resource"]').forEach(function (box) { box.checked = false; });
      refresh(bar);
    });
    bar.addEventListener("submit", function (e) { e.preventDefault(); refresh(bar); });
  }

  function setUpAll() {
    setUp();
    setUpBar();
  }

  setUpAll();
  document.addEventListener("scheduler:content-updated", setUpAll);
})();
