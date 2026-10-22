"""
The one delete flow shared by Rooms, Labs, Faculty, Courses and Class Patterns
(Sprint 2 Sections 11, 12, 20).

Every delete page works the same way, so the five *_delete views only say
which controller to call and where to go afterwards:

    GET   the review page: what else will change, and, when course sections
          would have to be deleted too, the tick-box that confirms it
    POST  action=cancel   -> back to the list, nothing changed
          action=confirm  -> run the controller; on a problem the SAME page is
                             shown again with the reasons, on success the user
                             returns to the list with a message that also
                             offers Undo

The page is a plain HTML form (no JavaScript needed). Deleting never puts a
different record in the deleted one's place, so there is nothing to choose
besides that one tick-box.
"""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect, render

from gui.controllers.errors import ControllerError


def flash_notices(request, notices) -> None:
    """Tell the user what a cascade did, one message per change."""
    for notice in notices:
        messages.info(request, notice)


def delete_page(request, *, template, context, list_url, done_text, delete):
    """Run the shared review / confirm / cancel flow.

    context    template context for the page; must contain "plan"
    list_url   url name to return to
    done_text  success message
    delete     callable(confirmed) -> list of notices; `confirmed` is whether the
               "also delete those sections" box was ticked. Raises
               ControllerError for anything the user can fix
    """
    if request.method == "POST":
        if request.POST.get("action") != "confirm":
            messages.info(request, "Cancelled.")
            return redirect(list_url)
        confirmed = request.POST.get("confirm_extra") in ("on", "1", "true", "yes")
        try:
            notices = delete(confirmed)
        except ControllerError as error:
            # Stay on the page so the user sees why.
            page = dict(context)
            page.update(errors=error.errors, confirm_checked=confirmed)
            return render(request, template, page)
        messages.success(request, done_text)
        flash_notices(request, notices)
        return redirect(list_url)
    return render(request, template, dict(context))
