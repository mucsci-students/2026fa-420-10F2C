"""
Views for locking sections (selective regeneration).

Every change is POST-only. After acting, the user is sent back to the page they pressed the
button on (the Schedule Viewer with the same schedule, view and filters, or the Schedule
Generator); the "next" address is only trusted when it points at this same site.

The confirmation after a lock uses the "info" style on purpose: a green "success" message can show
an Undo button for the configuration, and locking does not touch the configuration.
"""

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from gui.controllers import locks as lock_controller
from gui.controllers.errors import ControllerError


def _back(request, default="gui:schedule_viewer"):
    source = request.POST if request.method == "POST" else request.GET
    target = source.get("next", "")
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(target)
    return redirect(default)


def _schedule_number(request) -> int:
    raw = request.POST.get("schedule", "")
    if not raw.isdigit():
        raise ControllerError(
            "Open the schedule you want to lock from first, then try again."
        )
    return int(raw)


def lock(request):
    """Lock one section (section=...) or all of one instructor's sections (faculty=...)."""
    if request.method != "POST":
        return redirect("gui:schedule_viewer")
    try:
        number = _schedule_number(request)
        section = request.POST.get("section", "")
        faculty = request.POST.get("faculty", "")
        if section:
            text = lock_controller.lock_section(request, number, section)
        elif faculty:
            text = lock_controller.lock_faculty(request, number, faculty)
        else:
            raise ControllerError("Choose a section to lock.")
    except ControllerError as error:
        messages.error(request, error.message)
    else:
        messages.info(request, text)
    return _back(request)


def unlock(request):
    """Unlock one section (section=...) or all of one instructor's locked sections (faculty=...)."""
    if request.method != "POST":
        return redirect("gui:schedule_viewer")
    try:
        section = request.POST.get("section", "")
        faculty = request.POST.get("faculty", "")
        if section:
            text = lock_controller.unlock_section(request, section)
        elif faculty:
            text = lock_controller.unlock_faculty(request, faculty)
        else:
            raise ControllerError("Choose a section to unlock.")
    except ControllerError as error:
        messages.error(request, error.message)
    else:
        messages.info(request, text)
    return _back(request)


def locks_clear(request):
    """Unlock everything, after a confirmation page.

    GET shows "Unlock all N sections?" with Unlock and Cancel. POST with action=confirm unlocks;
    anything else keeps the locks. With nothing locked there is nothing to confirm.
    """
    count = lock_controller.lock_count(request)
    if count == 0:
        messages.info(request, "Nothing is locked.")
        return _back(request)

    if request.method == "POST":
        noun = "section" if count == 1 else "sections"
        if request.POST.get("action") != "confirm":
            messages.info(
                request, f"Cancelled. Your {count} locked {noun} stay locked."
            )
            return _back(request)
        cleared = lock_controller.clear_all(request)
        noun = "section" if cleared == 1 else "sections"
        messages.info(
            request,
            f"Unlocked {cleared} {noun}. They can change the next time you generate schedules.",
        )
        return _back(request)

    return render(
        request,
        "gui/locks_clear.html",
        {
            "active": "viewer",
            "locked_total": count,
            "lock_next": request.GET.get("next", ""),
        },
    )
