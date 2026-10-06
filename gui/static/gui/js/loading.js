// Forms with data-loading="Message" show a busy state on submit and
// ignore a second submit while the first is still running (Sections 13, 19).
(function () {
  function reset(form) {
    delete form.dataset.submitting;
    form.removeAttribute("aria-busy");
    form.querySelectorAll("button[type=submit]").forEach(function (b) {
      b.removeAttribute("aria-disabled");
      b.classList.remove("btn-disabled");
    });
    var status = document.getElementById("loading-status");
    if (status) { status.hidden = true; status.textContent = ""; }
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.dataset || !form.dataset.loading) return;
    if (form.dataset.submitting) { event.preventDefault(); return; } // duplicate click
    form.dataset.submitting = "true";
    form.setAttribute("aria-busy", "true");
    form.querySelectorAll("button[type=submit]").forEach(function (b) {
      b.setAttribute("aria-disabled", "true"); // aria-disabled keeps the button's value in the POST
      b.classList.add("btn-disabled");
    });
    var status = document.getElementById("loading-status");
    if (status) {
      status.hidden = false;
      status.innerHTML = '<span class="spinner" aria-hidden="true"></span> ' +
        "<strong>" + form.dataset.loading + "</strong> This can take a while; please don't close this page.";
    }
  });

  // Back/forward cache can restore a page stuck in the busy state.
  window.addEventListener("pageshow", function () {
    document.querySelectorAll("form[data-loading]").forEach(reset);
  });
})();