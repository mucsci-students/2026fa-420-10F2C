"""
JSON endpoints behind the live progress bar on the Schedule Generator
(Sections 13 and 19). Like every view in this project they stay thin: parse
the request, call schedule_controller, return the answer.

    POST /generate/start/    start a background run from the override form
    GET  /generate/status/   progress; the first poll after a run finishes
                             also queues the user-facing message and says
                             where to go next
    POST /generate/cancel/   ask the running generation to stop

The plain form POST to /generate/ still works without JavaScript.
"""

from __future__ import annotations

from django.contrib import messages
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from app import schedule_ops
from gui.controllers import schedule_controller, settings as settings_controller
from gui.controllers.errors import ControllerError
from gui.forms import GenerationOverrideForm

_MESSAGE_LEVELS = {
    "success": messages.SUCCESS,
    "warning": messages.WARNING,
    "error": messages.ERROR,
}


def _controller_problems(error: ControllerError) -> list[str]:
    return [item.message for item in error.errors]


def _form_problems(form) -> list[str]:
    problems = []
    for name, errors in form.errors.items():
        field = form.fields.get(name)
        label = field.label if field is not None and field.label else None
        for text in errors:
            problems.append(f"{label}: {text}" if label else str(text))
    return problems


@require_POST
def generation_start(request):
    data = settings_controller.describe_settings(request)
    form = GenerationOverrideForm(
        request.POST, flag_choices=data.get("flag_choices", ())
    )
    if not form.is_valid():
        return JsonResponse(
            {"started": False, "errors": _form_problems(form)}, status=400
        )

    try:
        status = schedule_controller.start_generation(
            request,
            limit_override=form.cleaned_data["limit"],
            optimizer_overrides=form.cleaned_data["optimizer_flags"],
        )
    except ControllerError as error:
        busy = error.message == schedule_controller.BUSY_MESSAGE
        return JsonResponse(
            {"started": False, "errors": _controller_problems(error)},
            status=409 if busy else 400,
        )
    return JsonResponse({"started": True, "status": status})


@require_GET
def generation_status(request):
    status = schedule_controller.generation_status(request)
    generator_url = reverse("gui:schedule_generator")

    if status["state"] == "running":
        return JsonResponse(status)
    if status["state"] == "idle":
        status["redirect"] = generator_url
        return JsonResponse(status)

    # Finished: report the outcome exactly once, then send the browser on.
    result = schedule_controller.collect_generation_result(request)
    redirect_url = generator_url
    if result is not None:
        level, text = schedule_controller.describe_outcome(result)
        messages.add_message(request, _MESSAGE_LEVELS[level], text)
        status["message"] = text
        if result.outcome == schedule_ops.GenerationOutcome.SUCCESS:
            redirect_url = reverse("gui:schedule_viewer")
    status["redirect"] = redirect_url
    return JsonResponse(status)


@require_POST
def generation_cancel(request):
    try:
        status = schedule_controller.cancel_generation(request)
    except ControllerError as error:
        return JsonResponse({"errors": _controller_problems(error)}, status=409)
    return JsonResponse({"status": status})
