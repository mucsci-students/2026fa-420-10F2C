"""
Views for Undo / Redo / History / Restore previous (Sprint 2 Sections 8, 11, 12, 20).

Every action is POST-only (it changes data). After acting, the user is sent
back to the page they pressed the button on, so a restored item reappears
where they were looking; the "next" address is only trusted when it points at
this same site. Each form also carries the history `token` it was drawn from,
so a stale page cannot undo the wrong thing.
"""

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from gui.controllers import history_controller
from gui.controllers.errors import ControllerError


def _back(request, default="gui:config_editor"):
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(target)
    return redirect(default)


def _token(request):
    return request.POST.get("token") or None


def undo(request):
    if request.method != "POST":
        return redirect("gui:config_editor")
    try:
        label = history_controller.undo(request, _token(request))
    except ControllerError as error:
        messages.error(request, error.message)
    else:
        messages.success(request, f"Undid: {label}. The configuration is back to how it was before that change.")
    return _back(request)


def redo(request):
    if request.method != "POST":
        return redirect("gui:config_editor")
    try:
        label = history_controller.redo(request, _token(request))
    except ControllerError as error:
        messages.error(request, error.message)
    else:
        messages.success(request, f"Redid: {label}.")
    return _back(request)


def history_page(request):
    """The full change history, with a "go back to here" button on every entry."""
    state = history_controller.describe_history(request)
    return render(request, "gui/history.html", {"active": "config", "history": state})


def history_goto(request):
    if request.method != "POST":
        return redirect("gui:history")
    try:
        labels = history_controller.go_to(request, request.POST.get("entry"), _token(request))
    except ControllerError as error:
        messages.error(request, error.message)
    else:
        count = len(labels)
        messages.success(
            request,
            f"Went back {count} change{'s' if count != 1 else ''} (latest: {labels[0]})."
            if request.POST.get("direction") != "forward"
            else f"Re-applied {count} change{'s' if count != 1 else ''} (latest: {labels[-1]}).",
        )
    return _back(request, default="gui:history")


def restore_previous(request):
    if request.method != "POST":
        return redirect("gui:config_editor")
    try:
        name = history_controller.restore_previous(request)
    except ControllerError as error:
        messages.error(request, error.message)
    else:
        messages.success(
            request,
            f"Restored {name}. The configuration you were just using is kept, so you can switch back.",
        )
    return _back(request)
