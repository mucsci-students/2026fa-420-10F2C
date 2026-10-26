"""
AI Assistant page (Sprint 3). Thin like every other view: it reads the
request text, hands it to gui.ai.service, and shows the reply.

    GET  /assistant/       the chat page
    POST /assistant/ask/   one request. The page's script posts here and gets
                           JSON back; without JavaScript the form posts here
                           and the page is shown again with the reply.

The API key stays on the server: the browser only ever sees the reply text.
"""

from __future__ import annotations

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from gui.ai import service
from gui.session_store import get_session


def _wants_json(request) -> bool:
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


@require_GET
def assistant(request):
    return render(request, "gui/assistant.html", {"active": "assistant"})


@require_POST
def assistant_ask(request):
    text = request.POST.get("message", "")
    reply = service.handle_request(request, text)

    if _wants_json(request):
        status = 409 if reply.busy else 200
        return JsonResponse(
            {
                "ok": reply.ok,
                "reply": reply.message,
                "changed": reply.changed,
                "busy": reply.busy,
                "dirty": bool(get_session(request).dirty),
            },
            status=status,
        )
    return render(
        request,
        "gui/assistant.html",
        {"active": "assistant", "sent": text.strip(), "reply": reply},
    )
