"""
Views for the Global Settings page (Configuration Editor, Section 7, Global
settings row): the saved generation limit and optimizer flags.

Same shape as the other configuration pages: parse the request, call the
controller (gui/controllers/settings.py), then either redirect with flash
messages (success) or re-render the page with the errors on the form (failure),
so the user's input is kept and the configuration is untouched.
"""

from django.contrib import messages
from django.shortcuts import redirect, render

from gui.controllers import settings as settings_controller
from gui.controllers.errors import ControllerError
from gui.forms import GlobalSettingsForm
from gui.views import _attach_errors


def _render_settings(request, form=None):
    data = settings_controller.describe_settings(request)
    context = {"active": "config", "data": data}
    if data["has_config"]:
        if form is None:
            form = GlobalSettingsForm(
                flag_choices=data["flag_choices"],
                initial={"limit": data["limit"], "optimizer_flags": data["enabled_flags"]},
            )
        context["form"] = form
    return render(request, "gui/settings.html", context)


def global_settings(request):
    """Global Settings page: the current values and a form to change them."""
    return _render_settings(request)


def settings_update(request):
    if request.method != "POST":
        return redirect("gui:settings")
    choices = settings_controller.describe_settings(request).get("flag_choices", [])
    form = GlobalSettingsForm(request.POST, flag_choices=choices)
    if form.is_valid():
        try:
            changes = settings_controller.update_settings(request, form.cleaned_data)
        except ControllerError as error:
            _attach_errors(form, error)
        else:
            if changes:
                for text in changes:
                    messages.success(request, text)
            else:
                messages.info(request, "No changes to save.")
            return redirect("gui:settings")
    return _render_settings(request, form=form)


def settings_reset_limit(request):
    """Put the generation limit back to the default."""
    if request.method != "POST":
        return redirect("gui:settings")
    try:
        changes = settings_controller.reset_generation_limit(request)
    except ControllerError as error:
        messages.error(request, error.message)
    else:
        if changes:
            messages.success(request, changes[0])
        else:
            messages.info(
                request,
                f"The generation limit is already the default ({settings_controller.DEFAULT_LIMIT}).",
            )
    return redirect("gui:settings")
