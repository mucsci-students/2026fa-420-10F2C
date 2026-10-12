"""
Friendly error pages for unexpected crashes (Sprint 2 Section 19: "Unexpected
errors must be presented in user-friendly language. Technical details may
additionally be recorded in logs"; user story 49, board card #77).

If a view raises an exception nobody planned for, this middleware:

1. writes the full traceback to the server log with a short reference code;
2. shows gui/error.html instead: plain language, the reference code, and
   links back into the app, so the user can carry on without restarting.

Http404 gets the friendly "Page not found" page instead. Errors a user can fix
never reach this point: controllers raise ControllerError and views show those
on the form (Sections 10, 11).
"""

from __future__ import annotations

import logging
import uuid

from django.http import Http404

from gui.views_errors import friendly_error_response, page_not_found

logger = logging.getLogger("gui.errors")


def new_reference() -> str:
    """Short code shown on the error page and written to the log."""
    return uuid.uuid4().hex[:8]


class FriendlyErrorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, Http404):
            return page_not_found(request, exception)
        reference = new_reference()
        logger.error(
            "Unexpected error %s on %s %s",
            reference,
            request.method,
            request.get_full_path(),
            exc_info=exception,
        )
        return friendly_error_response(request, reference, exception)
