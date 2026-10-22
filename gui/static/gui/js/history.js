/*
 * Keyboard shortcuts for Undo / Redo on the Configuration Editor pages.
 *
 *   Ctrl+Z  (Cmd+Z on a Mac)           press the Undo button
 *   Ctrl+Y  or  Ctrl+Shift+Z           press the Redo button
 *
 * Progressive enhancement only: the buttons work without JavaScript. The
 * shortcuts are ignored while typing in a form field, so they never take over
 * the browser's own text undo, and they do nothing when the button is disabled.
 */
(function () {
    "use strict";

    function typingInAField(target) {
        if (!target || !target.tagName) {
            return false;
        }
        var tag = target.tagName.toLowerCase();
        return tag === "input" || tag === "textarea" || tag === "select" || target.isContentEditable === true;
    }

    document.addEventListener("keydown", function (event) {
        if (event.defaultPrevented || event.altKey || !(event.ctrlKey || event.metaKey)) {
            return;
        }
        if (typingInAField(event.target)) {
            return;
        }
        var key = (event.key || "").toLowerCase();
        var action = null;
        if (key === "z" && !event.shiftKey) {
            action = "undo";
        } else if (key === "y" || (key === "z" && event.shiftKey)) {
            action = "redo";
        }
        if (!action) {
            return;
        }
        var button = document.querySelector('.history-bar [data-history-action="' + action + '"]');
        if (!button || button.disabled) {
            return;
        }
        event.preventDefault();
        button.click();
    });
})();
