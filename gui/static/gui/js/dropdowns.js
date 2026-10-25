/*
 * Smooth open and close for the dropdowns on the Courses, Labs, Rooms and Faculty pages: the
 * "Used by" lists and the faculty "Availability and preferences" panels.
 *
 * Progressive enhancement. Without JavaScript, in a browser that cannot animate, or when the visitor
 * asks for reduced motion, this file does nothing and the dropdowns open and close instantly, exactly
 * as the browser always does. Keyboard use works the same: Enter and Space on a summary click it.
 *
 * Markup it looks for: <details class="usage"> or <details class="item-card__more">, with the
 * <summary> first and the content after it.
 */
(function () {
    "use strict";

    var SUMMARY = "details.usage > summary, details.item-card__more > summary";
    var DURATION = 240;
    var EASING = "cubic-bezier(0.2, 0, 0, 1)";
    var running = new WeakMap();
    var reduced = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;

    function canAnimate() {
        return typeof Element.prototype.animate === "function" && !(reduced && reduced.matches);
    }

    function contentOf(details) {
        return Array.prototype.filter.call(details.children, function (child) {
            return child.tagName !== "SUMMARY";
        });
    }

    function heightWhen(details, open) {
        details.open = open;
        return details.getBoundingClientRect().height;
    }

    // Leaves the dropdown exactly as the browser would have: open or closed, with nothing left over.
    function settle(details, opening) {
        details.open = opening;
        details.classList.remove("is-closing");
        details.style.clipPath = "";
        running.delete(details);
    }

    function toggle(details) {
        var state = running.get(details);
        var from = details.getBoundingClientRect().height;
        var opening = state ? !state.opening : !details.open;
        if (state) {
            state.animations.forEach(function (animation) {
                animation.cancel();
            });
        }

        var openHeight = heightWhen(details, true);
        var closedHeight = heightWhen(details, false);
        details.open = true; // stays open while it plays; settle() sets the final state

        details.classList.toggle("is-closing", !opening);
        // Clips the bottom edge as it grows and shrinks, but leaves room at the sides and top so the
        // arrow beside the last chip and the keyboard focus ring are never cut off.
        details.style.clipPath = "inset(-4px -3rem 0 -3rem)";

        var height = details.animate(
            { height: [from + "px", (opening ? openHeight : closedHeight) + "px"] },
            { duration: DURATION, easing: EASING }
        );
        var fades = contentOf(details).map(function (element) {
            return element.animate(
                { opacity: opening ? [0, 1] : [1, 0] },
                { duration: DURATION, easing: "ease" }
            );
        });

        running.set(details, { animations: [height].concat(fades), opening: opening });
        height.onfinish = function () {
            settle(details, opening);
        };
    }

    document.addEventListener("click", function (event) {
        var summary = event.target.closest ? event.target.closest(SUMMARY) : null;
        if (!summary) {
            return;
        }
        if (!canAnimate()) {
            return;
        }
        // Footers laid out with display: contents animate through CSS (::details-content); there is no box to animate here.
        if (window.getComputedStyle(summary.parentNode).display === "contents") {
            return;
        }
        event.preventDefault();
        toggle(summary.parentNode);
    });
})();
