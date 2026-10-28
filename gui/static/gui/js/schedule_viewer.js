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

  setUp();
  document.addEventListener("scheduler:content-updated", setUp);
})();
