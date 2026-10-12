/*
 * Small progressive enhancement for long lists. Without JavaScript every page
 * works exactly the same; the search box simply stays hidden.
 *
 * Markup it looks for:
 *   <div data-filter-box hidden>
 *     <input type="search" data-filter-input="#list-id" data-filter-status="#status-id">
 *     <p id="status-id" aria-live="polite"></p>
 *   </div>
 *   <div id="list-id"> ... elements marked data-filter-item ... </div>
 */
(function () {
    "use strict";

    function normalise(text) {
        return (text || "").toLowerCase().replace(/\s+/g, " ").trim();
    }

    function setUp(input) {
        var list = document.querySelector(input.getAttribute("data-filter-input"));
        if (!list) {
            return;
        }
        var items = Array.prototype.slice.call(list.querySelectorAll("[data-filter-item]"));
        var statusSelector = input.getAttribute("data-filter-status");
        var status = statusSelector ? document.querySelector(statusSelector) : null;
        var box = input.closest("[data-filter-box]");
        var texts = items.map(function (item) {
            return normalise(item.textContent);
        });

        function apply() {
            var query = normalise(input.value);
            var shown = 0;
            items.forEach(function (item, index) {
                var match = query === "" || texts[index].indexOf(query) !== -1;
                item.hidden = !match;
                if (match) {
                    shown += 1;
                }
            });
            if (status) {
                status.textContent = query === "" ? "" : "Showing " + shown + " of " + items.length + ".";
            }
        }

        input.addEventListener("input", apply);
        if (box) {
            box.hidden = false;
        }
    }

    function init() {
        var inputs = document.querySelectorAll("[data-filter-input]");
        Array.prototype.forEach.call(inputs, setUp);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
