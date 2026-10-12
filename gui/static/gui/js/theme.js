// Dark mode: use the saved choice, else the system preference. A nav button toggles it.
(function () {
  var KEY = "scheduler-theme";
  var root = document.documentElement;

  function saved() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }
  function preferred() {
    if (saved()) return saved();
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark" : "light";
  }
  function apply(theme) {
    root.setAttribute("data-theme", theme);
    var button = document.getElementById("theme-toggle");
    if (button) {
      button.textContent = theme === "dark" ? "Light mode" : "Dark mode";
      button.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
    }
  }

  apply(preferred()); // runs before first paint

  document.addEventListener("DOMContentLoaded", function () {
    apply(root.getAttribute("data-theme"));
    var button = document.getElementById("theme-toggle");
    if (!button) return;
    button.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      try { localStorage.setItem(KEY, next); } catch (e) {}
      apply(next);
    });
  });
})();