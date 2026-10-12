"""
Error pages (Sprint 2 Sections 4, 10, 19; user story 49, board card #77).

Ordinary user errors (bad input, a file that won't load, a change the
scheduler rejects) are shown on the page the user is on, next to the field
or form. This module covers what is left: problems nobody expected.

* page_not_found / server_error are Django's handler404 / handler500
  (config/urls.py). Django uses them when DEBUG is False.
* friendly_error_response() is what gui/middleware.py shows when a view
  crashes. The middleware runs with DEBUG on as well, so users never see a
  traceback page.

Every error page is a normal app page (navigation, mode links) in plain
language with a next step. The technical details go to the server log with
a short reference code that is also shown on the page.
"""

from __future__ import annotations

import html

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render

ERROR_TEMPLATE = "gui/error.html"
NOT_FOUND_TEMPLATE = "gui/not_found.html"

# Used only if the error page itself can't be drawn (for example when the
# template system is the thing that broke). No template, no context.
_FALLBACK_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Scheduler — Something went wrong</title></head>
<body>
<h1>Something went wrong</h1>
<p><strong>Error:</strong> The app hit an unexpected problem and couldn't finish that action.</p>
<p>The last action may not have been applied. Go to the <a href="/">home page</a> and try again.</p>
{reference}
</body></html>
"""


def friendly_error_response(request, reference: str | None = None, exception: Exception | None = None) -> HttpResponse:
    """A 500 page in plain language. `reference` matches the log entry;
    the exception's type and message are only shown when DEBUG is on, in a
    collapsed "Technical details" section (never a traceback)."""
    details = None
    if settings.DEBUG and exception is not None:
        details = f"{type(exception).__name__}: {exception}"
    try:
        return render(
            request,
            ERROR_TEMPLATE,
            {"reference": reference, "details": details},
            status=500,
        )
    except Exception:  # the error page must not fail too
        ref = f"<p>Reference: <code>{html.escape(reference)}</code></p>" if reference else ""
        return HttpResponse(_FALLBACK_HTML.format(reference=ref), status=500, content_type="text/html; charset=utf-8")


def page_not_found(request, exception=None):
    """handler404: an unknown address or a missing item (Http404)."""
    try:
        return render(request, NOT_FOUND_TEMPLATE, {"path": request.path}, status=404)
    except Exception:
        return HttpResponse(
            "<!DOCTYPE html><title>Page not found</title><h1>Page not found</h1>"
            '<p>That page doesn\'t exist. Go to the <a href="/">home page</a>.</p>',
            status=404,
            content_type="text/html; charset=utf-8",
        )


def server_error(request):
    """handler500 (DEBUG off): Django calls this without the exception."""
    return friendly_error_response(request)
