"""
Views for the Class Patterns pages (Configuration Editor, Section 7, Class
patterns row).

Same shape as the Rooms and Time Slots views: parse the request, call the
controller (gui/controllers/patterns.py), then either redirect with a flash
message (success) or re-render the same page with the errors on the form
(failure), so the user's input is kept and the configuration is untouched.
Patterns have no name, so they are identified by their position in the URL.
"""

from django.contrib import messages
from django.shortcuts import redirect, render

from gui.controllers import patterns as pattern_controller
from gui.controllers.errors import ControllerError
from gui.forms import AddClassPatternForm, ClassPatternFieldsForm
from gui.views import _attach_errors, _flash_warnings


def _render_patterns(request, add_form=None):
    data = pattern_controller.describe_patterns(request)
    context = {"active": "config", "data": data}
    if data["has_config"]:
        if add_form is None:
            add_form = AddClassPatternForm(initial={"enabled": True, "meeting_duration": 50})
        context["add_form"] = add_form
    return render(request, "gui/patterns.html", context)


def patterns(request):
    """Class Patterns page: the current patterns and a form to add one."""
    return _render_patterns(request)


def pattern_add(request):
    if request.method != "POST":
        return redirect("gui:patterns")
    form = AddClassPatternForm(request.POST)
    if form.is_valid():
        try:
            warnings = pattern_controller.add_pattern(request, form.cleaned_data)
        except ControllerError as error:
            _attach_errors(form, error)
        else:
            messages.success(request, "Class pattern added.")
            _flash_warnings(request, warnings)
            return redirect("gui:patterns")
    return _render_patterns(request, add_form=form)


def pattern_edit(request, pattern_index):
    try:
        pattern = pattern_controller.get_pattern(request, pattern_index)
    except ControllerError as error:
        messages.error(request, error.message)
        return redirect("gui:patterns")

    if request.method == "POST":
        form = ClassPatternFieldsForm(request.POST)
        if form.is_valid():
            try:
                warnings = pattern_controller.update_pattern(request, pattern_index, form.cleaned_data)
            except ControllerError as error:
                _attach_errors(form, error)
            else:
                messages.success(request, "Class pattern updated.")
                _flash_warnings(request, warnings)
                return redirect("gui:patterns")
    else:
        form = ClassPatternFieldsForm(
            initial={
                "credits": pattern["credits"],
                "start_time": pattern["start_time"] or None,
                "enabled": pattern["enabled"],
            }
        )
    return render(request, "gui/pattern_edit.html", {"active": "config", "form": form, "pattern": pattern})


def pattern_delete(request, pattern_index):
    """Confirmation page (GET) and the confirm/cancel actions (POST)."""
    try:
        pattern = pattern_controller.get_pattern(request, pattern_index)
    except ControllerError as error:
        messages.error(request, error.message)
        return redirect("gui:patterns")

    if request.method == "POST":
        if request.POST.get("action") != "confirm":
            messages.info(request, "Cancelled.")
            return redirect("gui:patterns")
        try:
            warnings = pattern_controller.delete_pattern(request, pattern_index)
        except ControllerError as error:
            messages.error(request, error.message)
        else:
            messages.success(request, "Class pattern removed.")
            _flash_warnings(request, warnings)
        return redirect("gui:patterns")

    return render(request, "gui/pattern_delete.html", {"active": "config", "pattern": pattern})
