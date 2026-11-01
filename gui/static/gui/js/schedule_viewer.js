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

  // -- Rooms & labs / Faculty checkbox popup ---------------------------------------------------- //
  // Works without JavaScript (a <details> with a plain GET form). This adds search, Tick all /
  // Untick all, a live count on the button, and closing on Escape or a click outside.
  function setUpPicker() {
    var picker = document.querySelector(".resource-picker");
    if (!picker) { return; }
    var summary = picker.querySelector("summary");
    var tools = picker.querySelector(".resource-picker__tools");
    var search = picker.querySelector(".resource-picker__search");
    var apply = picker.querySelector(".resource-picker__apply");
    var noMatch = picker.querySelector(".resource-picker__nomatch");
    var options = Array.prototype.slice.call(picker.querySelectorAll(".resource-picker__option"));
    var boxes = options.map(function (o) { return o.querySelector("input"); });
    tools.hidden = false;

    function updateCount() {
      var n = boxes.filter(function (b) { return b.checked; }).length;
      apply.textContent = n ? "Show " + n + " selected" : "Show all";
    }

    function visible(o) { return !o.hidden; }

    picker.addEventListener("change", updateCount);
    picker.querySelectorAll("[data-picker]").forEach(function (button) {
      button.addEventListener("click", function () {
        var tick = button.dataset.picker === "all";
        // Only the rows the search is showing, so "Tick all" after searching "Roddy" picks those.
        options.filter(visible).forEach(function (o) { o.querySelector("input").checked = tick; });
        updateCount();
      });
    });

    search.addEventListener("input", function () {
      var q = search.value.trim().toLowerCase();
      options.forEach(function (o) {
        o.hidden = q !== "" && o.textContent.toLowerCase().indexOf(q) === -1;
      });
      var any = false;
      picker.querySelectorAll(".resource-picker__group").forEach(function (g) {
        var shown = Array.prototype.some.call(g.querySelectorAll(".resource-picker__option"), visible);
        g.hidden = !shown;
        any = any || shown;
      });
      noMatch.hidden = any;
    });
    search.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); } // Enter in the search box doesn't submit
    });

    picker.addEventListener("toggle", function () {
      if (picker.open) { search.focus(); }
    });
    picker.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && picker.open) {
        picker.open = false;
        summary.focus();
      }
    });

    updateCount();
    if (picker.open) {
      search.focus({ preventScroll: true });
      // Drop &pick=1 so a reload or the Back button doesn't pop it open again.
      if (window.history && window.history.replaceState) {
        var url = new URL(window.location.href);
        url.searchParams.delete("pick");
        window.history.replaceState(window.history.state, "", url);
      }
    }
  }

  // One document-level listener (not one per setUp) closes the popup on a click outside it.
  document.addEventListener("click", function (e) {
    var picker = document.querySelector(".resource-picker[open]");
    if (picker && !picker.contains(e.target)) { picker.open = false; }
  });

  function setUpAll() {
    setUp();
    setUpPicker();
  }

  setUpAll();
  document.addEventListener("scheduler:content-updated", setUpAll);
})();
