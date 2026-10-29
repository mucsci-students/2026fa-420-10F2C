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

  // Letters and digits only, lower case: "cmsc140" finds "CMSC 140.01", "roddy 1" finds "Roddy 136".
  function normalize(text) { return text.toLowerCase().replace(/[^a-z0-9]+/g, ""); }

  // The picker is a plain <select multiple> in the page (it works without JavaScript). Here it
  // becomes a searchable list of checkboxes: type to narrow the list, tick as many as you like,
  // then Apply (or press Enter) to reload the calendar with those items.
  function buildPicker(select) {
    var form = select.form;
    if (!form || select.dataset.enhanced) { return; }
    select.dataset.enhanced = "1";
    var allText = form.dataset.pickerAll || "All";
    var label = form.querySelector('label[for="' + select.id + '"]');

    var options = Array.prototype.map.call(select.options, function (o) {
      return { value: o.value, text: o.textContent, key: normalize(o.textContent + " " + o.value), checked: o.selected, input: null, item: null };
    });

    var wrap = document.createElement("div");
    wrap.className = "combo";
    var trigger = document.createElement("button");
    trigger.type = "button";
    trigger.id = select.id;
    trigger.className = "btn combo__trigger";
    trigger.setAttribute("aria-haspopup", "true");
    trigger.setAttribute("aria-expanded", "false");
    var triggerText = document.createElement("span");
    triggerText.className = "combo__trigger-text";
    var caret = document.createElement("span");
    caret.setAttribute("aria-hidden", "true");
    caret.textContent = "▾";
    trigger.appendChild(triggerText);
    trigger.appendChild(caret);

    var panel = document.createElement("div");
    panel.className = "combo__panel";
    panel.hidden = true;
    panel.setAttribute("role", "group");
    panel.setAttribute("aria-label", label ? label.textContent : "Choose items");
    var search = document.createElement("input");
    search.type = "search";
    search.className = "combo__search";
    search.placeholder = "Type to filter…";
    search.setAttribute("aria-label", "Type to filter the list");
    search.autocomplete = "off";
    var list = document.createElement("ul");
    list.className = "combo__list";
    var empty = document.createElement("p");
    empty.className = "combo__empty";
    empty.setAttribute("role", "status");
    empty.hidden = true;
    empty.textContent = "Nothing matches.";

    options.forEach(function (o) {
      var item = document.createElement("li");
      item.className = "combo__item";
      var box = document.createElement("input");
      box.type = "checkbox";
      box.name = select.name;
      box.value = o.value;
      box.checked = o.checked;
      var text = document.createElement("span");
      text.textContent = o.text;
      var row = document.createElement("label");
      row.className = "combo__option";
      row.appendChild(box);
      row.appendChild(text);
      item.appendChild(row);
      list.appendChild(item);
      o.input = box;
      o.item = item;
      box.addEventListener("change", function () { o.checked = box.checked; summarize(); });
    });

    var footer = document.createElement("div");
    footer.className = "combo__footer";
    var group = document.createElement("div");
    group.className = "combo__footer-group";
    function smallButton(text, type, extra) {
      var b = document.createElement("button");
      b.type = type;
      b.className = "btn btn-small" + (extra ? " " + extra : "");
      b.textContent = text;
      return b;
    }
    var selectShown = smallButton("Select shown", "button");
    var clear = smallButton("Clear", "button");
    var apply = smallButton("Apply", "submit", "btn-primary");
    group.appendChild(selectShown);
    group.appendChild(clear);
    footer.appendChild(group);
    footer.appendChild(apply);

    panel.appendChild(search);
    panel.appendChild(list);
    panel.appendChild(empty);
    panel.appendChild(footer);
    wrap.appendChild(trigger);
    wrap.appendChild(panel);

    function summarize() {
      var names = options.filter(function (o) { return o.input.checked; }).map(function (o) { return o.text; });
      var shown = !names.length ? allText : names.length <= 2 ? names.join(", ") : names.length + " selected";
      triggerText.textContent = shown;
      trigger.title = names.length ? names.join(", ") : allText;
    }

    function visibleOptions() { return options.filter(function (o) { return !o.item.hidden; }); }

    function filter() {
      var tokens = search.value.split(/\s+/).map(normalize).filter(Boolean);
      options.forEach(function (o) {
        o.item.hidden = !tokens.every(function (t) { return o.key.indexOf(t) !== -1; });
      });
      empty.hidden = visibleOptions().length > 0;
    }

    function setOpen(open, returnFocus) {
      panel.hidden = !open;
      trigger.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) { search.value = ""; filter(); search.focus(); }
      else if (returnFocus) { trigger.focus(); }
    }

    trigger.addEventListener("click", function () { setOpen(panel.hidden, false); });
    search.addEventListener("input", filter);
    search.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") {
        var first = visibleOptions()[0];
        if (first) { e.preventDefault(); first.input.focus(); }
      }
    });
    list.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") { return; }
      var shown = visibleOptions();
      var at = shown.map(function (o) { return o.input; }).indexOf(document.activeElement);
      if (at === -1) { return; }
      e.preventDefault();
      var next = e.key === "ArrowDown" ? at + 1 : at - 1;
      if (next < 0) { search.focus(); } else if (next < shown.length) { shown[next].input.focus(); }
    });
    panel.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { e.stopPropagation(); setOpen(false, true); }
    });
    selectShown.addEventListener("click", function () {
      visibleOptions().forEach(function (o) { o.input.checked = true; o.checked = true; });
      summarize();
    });
    clear.addEventListener("click", function () {
      options.forEach(function (o) { o.input.checked = false; o.checked = false; });
      summarize();
      search.focus();
    });
    function onOutside(e) {
      if (!document.body.contains(wrap)) { document.removeEventListener("click", onOutside); return; }
      if (!panel.hidden && !wrap.contains(e.target)) { setOpen(false, false); }
    }
    document.addEventListener("click", onOutside);

    // The native list and its Show button give way to the searchable one.
    select.disabled = true;
    select.style.display = "none";
    select.removeAttribute("id");
    if (label) { label.setAttribute("for", trigger.id); }
    var show = form.querySelector("[data-picker-apply]");
    if (show) { show.remove(); }
    select.parentNode.insertBefore(wrap, select.nextSibling);
    summarize();
  }

  function setUpToolbar() {
    var select = document.getElementById("resource-picker");
    if (select && select.tagName === "SELECT") { buildPicker(select); }
    Array.prototype.forEach.call(document.querySelectorAll(".messages .alert-success"), function (alert) {
      if (alert.querySelector(".alert__dismiss")) { return; }
      var close = document.createElement("button");
      close.type = "button";
      close.className = "alert__dismiss";
      close.setAttribute("aria-label", "Dismiss message");
      close.textContent = "\u00d7";
      close.addEventListener("click", function () { alert.remove(); });
      alert.appendChild(close);
    });
  }

  function init() {
    setUp();
    setUpToolbar();
  }

  init();
  document.addEventListener("scheduler:content-updated", init);
})();
