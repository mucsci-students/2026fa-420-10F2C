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
from gui.controllers import config_controller
from gui.controllers.errors import ControllerError
from gui.session_store import get_session


@require_POST
def assistant_ask(request):
    reply = service.handle_request(request, request.POST.get("message", ""))
    response = JsonResponse(
        {
            "ok": reply.ok,
            "reply": reply.message,
            "changed": reply.changed,
            "busy": reply.busy,
            "dirty": bool(get_session(request).dirty),
            "actions": [result.action for result in reply.results if result.ok and result.action is not None],
        },
        status=409 if reply.busy else 200,
    )
    response["Cache-Control"] = "no-store"
    return response


@require_POST
def configuration_save_begin(request):
    try:
        config_controller.begin_save(
            request, request.POST.get("token", ""), request.POST.get("filename", ""),
        )
    except ControllerError as error:
        return JsonResponse({"ok": False, "error": error.message}, status=400)
    return JsonResponse({"ok": True})


@require_POST
def configuration_save_complete(request):
    try:
        result = config_controller.complete_save(
            request, request.POST.get("token", ""), request.POST.get("filename", ""),
        )
    except ControllerError as error:
        return JsonResponse({"ok": False, "error": error.message}, status=400)
    return JsonResponse(result)


@require_POST
def configuration_save_cancel(request):
    try:
        config_controller.cancel_save(request, request.POST.get("token", ""))
    except ControllerError as error:
        return JsonResponse({"ok": False, "error": error.message}, status=400)
    return JsonResponse({"ok": True})
