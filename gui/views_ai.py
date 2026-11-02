"""
Behind the AI chat button (Sprint 3). Thin like every other view: it reads the request text,
hands it to gui.ai.service, and returns the reply as JSON.

    POST /assistant/ask/      one request from the chat panel (components/chat_widget.html,
                              js/chat.js). 409 when the browser's previous request is still running.
    POST /assistant/new/      Discard and Continue / Cancel on the chat's "start a new configuration" warning.
    GET  /assistant/chat/     the saved chats of this browser and the open chat's lines, so the panel can
                              draw them again after a page change or reload (js/chat.js).
    POST /assistant/chat/new/ | switch/ | delete/   start a new chat, open an older one, remove one.
                              409 while a request is still running, so a reply never lands in another chat.
    GET  /assistant/status/   how far a schedule generation is, for the chat's progress line while
                              the request that started it is still running. Read-only: unlike
                              /generate/status/ it never collects the result or queues a message.

The API key stays on the server: the browser only ever sees the reply text.
"""

from __future__ import annotations

from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from gui.ai import chats, lifecycle, service
from gui.controllers import schedule_controller
from gui.session_store import get_session


@require_POST
def assistant_ask(request):
    reply = service.handle_request(request, request.POST.get("message", ""))
    count = schedule_controller.schedule_count(request)
    generated = bool(reply.ok and reply.schedules_changed and count)
    if generated:
        # Shown on the next full page, so the confirmation survives the Schedule Viewer reloading.
        noun = "schedule" if count == 1 else "schedules"
        messages.success(request, f"The AI assistant generated {count} {noun}.")
    return JsonResponse(
        {
            "ok": reply.ok,
            "reply": reply.message,
            "changed": reply.changed,
            "busy": reply.busy,
            "dirty": bool(get_session(request).dirty),
            "generated": generated,
            "schedule_count": count,
            "refresh": reply.refresh,
            "suggestions": list(reply.suggestions),
            "action": reply.action,
        },
        status=409 if reply.busy else 200,
    )


@require_POST
def assistant_new_configuration(request):
    """Discard and Continue / Cancel on the chat's new-configuration warning (gui/ai/lifecycle.py).

    The warning's token is checked, so only the warning that was just shown can discard anything."""
    session = get_session(request)
    if service.is_busy(request):
        return JsonResponse(
            {"ok": False, "reply": service.BUSY_MESSAGE, "busy": True}, status=409
        )
    result = lifecycle.choose_new_configuration(
        request, request.POST.get("choice", ""), request.POST.get("token", "")
    )
    chats.record(session, "assistant" if result.ok else "error", result.message)
    return JsonResponse(
        {
            "ok": result.ok,
            "reply": result.message,
            "changed": False,
            "busy": False,
            "dirty": bool(session.dirty),
            "generated": False,
            "schedule_count": schedule_controller.schedule_count(request),
            "refresh": result.refresh,
            "suggestions": [],
            "action": None,
        }
    )


@require_GET
def assistant_status(request):
    status = schedule_controller.generation_status(request)
    keys = ("state", "found", "limit", "percent", "elapsed", "cancel_requested")
    return JsonResponse({key: status[key] for key in keys if key in status})


def _chat_state(request, status: int = 200, error: str = ""):
    payload = chats.state(get_session(request), busy=service.is_busy(request))
    if error:
        payload["error"] = error
    return JsonResponse(payload, status=status)


@require_GET
def assistant_chat(request):
    return _chat_state(request)


def _refuse_while_busy(request):
    if service.is_busy(request):
        return _chat_state(
            request, 409, "A request is still running. Wait for it to finish."
        )
    return None


@require_POST
def assistant_chat_new(request):
    refused = _refuse_while_busy(request)
    if refused:
        return refused
    chats.new_chat(get_session(request))
    return _chat_state(request)


@require_POST
def assistant_chat_switch(request):
    refused = _refuse_while_busy(request)
    if refused:
        return refused
    if not chats.switch_chat(get_session(request), request.POST.get("id", "")):
        return _chat_state(request, 404, "That chat no longer exists.")
    return _chat_state(request)


@require_POST
def assistant_chat_delete(request):
    refused = _refuse_while_busy(request)
    if refused:
        return refused
    if not chats.delete_chat(get_session(request), request.POST.get("id", "")):
        return _chat_state(request, 404, "That chat no longer exists.")
    return _chat_state(request)
