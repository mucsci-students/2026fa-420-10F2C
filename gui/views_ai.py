"""
Behind the AI chat button (Sprint 3). Thin like every other view: it reads the request text,
hands it to gui.ai.service, and returns the reply as JSON.

    POST /assistant/ask/   one request from the chat panel (components/chat_widget.html,
                           js/chat.js). 409 when the browser's previous request is still running.

The API key stays on the server: the browser only ever sees the reply text.
"""

from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from gui.ai import service
from gui.session_store import get_session


@require_POST
def assistant_ask(request):
    reply = service.handle_request(request, request.POST.get("message", ""))
    return JsonResponse(
        {
            "ok": reply.ok,
            "reply": reply.message,
            "changed": reply.changed,
            "busy": reply.busy,
            "dirty": bool(get_session(request).dirty),
        },
        status=409 if reply.busy else 200,
    )
