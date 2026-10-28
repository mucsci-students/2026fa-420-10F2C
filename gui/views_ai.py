"""
Behind the AI chat button (Sprint 3). Thin like every other view: it reads the request text,
hands it to gui.ai.service, and returns the reply as JSON.

    POST /assistant/ask/                    one request from the chat panel (components/chat_widget.html,
                                            js/chat.js). 409 when the browser's previous request is
                                            still running.
    POST /configuration/new/confirm/        the chat's "Discard and Continue" for a new configuration
    POST /configuration/new/cancel/         the chat's "Cancel"

Saving is not here: the chat's Save JSON button posts to the same gui:config_save view as the
Configuration Editor's Save button, so there is a single export.

The API key stays on the server: the browser only ever sees the reply text.
"""

from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from gui.ai import service
from gui.controllers import config_controller
from gui.controllers.errors import ControllerError
from gui.session_store import get_session


def _dirty(request) -> bool:
    return bool(get_session(request).dirty)


def _json(payload: dict, status: int = 200) -> JsonResponse:
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "no-store"
    return response


@require_POST
def assistant_ask(request):
    reply = service.handle_request(request, request.POST.get("message", ""))
    return _json(
        {
            "ok": reply.ok,
            "reply": reply.message,
            "changed": reply.changed,
            "busy": reply.busy,
            "dirty": _dirty(request),
            "actions": [
                result.action
                for result in reply.results
                if result.ok and result.action is not None
            ],
        },
        status=409 if reply.busy else 200,
    )


@require_POST
def configuration_new_confirm(request):
    """The chat's "Discard and Continue": replace the configuration the user was warned about."""
    try:
        config_controller.confirm_new_configuration(
            request, request.POST.get("token", "")
        )
    except ControllerError as error:
        return _json(
            {
                "ok": False,
                "message": error.message,
                "changed": False,
                "dirty": _dirty(request),
            },
            400,
        )
    return _json(
        {
            "ok": True,
            "message": f"{config_controller.STARTED_NEW} {config_controller.RESTORE_HINT}",
            "changed": True,
            "dirty": _dirty(request),
        }
    )


@require_POST
def configuration_new_cancel(request):
    """The chat's "Cancel": forget the warning. Nothing about the configuration changes."""
    try:
        config_controller.cancel_new_configuration(
            request, request.POST.get("token", "")
        )
    except ControllerError as error:
        return _json(
            {
                "ok": False,
                "message": error.message,
                "changed": False,
                "dirty": _dirty(request),
            },
            400,
        )
    return _json(
        {
            "ok": True,
            "message": "Cancelled. Your configuration and schedules were not changed.",
            "changed": False,
            "dirty": _dirty(request),
        }
    )
