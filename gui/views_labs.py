"""
Views for the Labs pages (Configuration Editor, Section 7, Labs row).

Same shape as the Time Slots views in gui/views.py: parse the request, call the
controller (gui/controllers/labs.py), then either redirect with a flash
message (success) or re-render the same page with the errors on the form
(failure), so the user's input is kept and the configuration is untouched.
Labs are identified by name in the URL.
"""

from django.contrib import messages
from django.shortcuts import redirect, render

from gui.controllers import labs as lab_controller
from gui.controllers.errors import ControllerError
from gui.forms import LabForm, availability_to_text
from gui.rename_confirmation import RenameConfirmationError, load_rename_confirmation
from gui.views import _attach_errors
from gui.views_rename import render_rename_confirmation


def _render_labs(request, add_form=None):
    data = lab_controller.describe_labs(request)
    context = {"active": "config", "data": data}
    if data["has_config"]:
        if add_form is None:
            add_form = LabForm()
        context["add_form"] = add_form
    return render(request, "gui/labs.html", context)


def labs(request):
    """Labs page: the current labs and a form to add one."""
    return _render_labs(request)


def lab_add(request):
    if request.method != "POST":
        return redirect("gui:labs")
    form = LabForm(request.POST)
    if form.is_valid():
        try:
            lab_controller.add_lab(request, form.cleaned_data)
        except ControllerError as error:
            _attach_errors(form, error)
        else:
            messages.success(request, f"Lab '{form.cleaned_data['name']}' added.")
            return redirect("gui:labs")
    return _render_labs(request, add_form=form)


def lab_edit(request, lab_name):
    try:
        lab = lab_controller.get_lab(request, lab_name)
    except ControllerError as error:
        messages.error(request, error.message)
        return redirect("gui:labs")

    if request.method == "POST":
        form = LabForm(request.POST)
        if form.is_valid():
            try:
                impact = lab_controller.rename_impact(request, lab_name, form.cleaned_data)
            except ControllerError as error:
                _attach_errors(form, error)
            else:
                if impact["references"]:
                    return render_rename_confirmation(
                        request,
                        resource_key="lab",
                        resource_label="lab",
                        collection_label="Labs",
                        list_url_name="gui:labs",
                        identifier=lab_name,
                        old_name=lab_name,
                        new_name=impact["new_name"],
                        references=impact["references"],
                        form_data=form.cleaned_data,
                        confirm_url_name="gui:lab_rename_confirm",
                        cancel_url_name="gui:lab_edit",
                    )
                try:
                    lab_controller.update_lab(request, lab_name, form.cleaned_data)
                except ControllerError as error:
                    _attach_errors(form, error)
                else:
                    messages.success(request, f"Lab '{form.cleaned_data['name']}' updated.")
                    return redirect("gui:labs")
    else:
        form = LabForm(
            initial={
                "name": lab["name"],
                "capacity": lab["capacity"],
                "features": ", ".join(lab["features"]),
                "times": availability_to_text(lab["times"]),
            }
        )
    return render(request, "gui/lab_edit.html", {"active": "config", "form": form, "lab": lab})


def lab_rename_confirm(request, lab_name):
    """Apply a reviewed lab rename and its references after confirmation."""
    if request.method != "POST":
        return redirect("gui:lab_edit", lab_name=lab_name)
    try:
        form_data = load_rename_confirmation(request.POST.get("confirmation_token", ""), "lab", lab_name)
    except RenameConfirmationError as error:
        messages.error(request, str(error))
        return redirect("gui:lab_edit", lab_name=lab_name)
    try:
        lab_controller.rename_lab_and_update_references(request, lab_name, form_data)
    except ControllerError as error:
        messages.error(request, error.message)
        return redirect("gui:lab_edit", lab_name=lab_name)
    messages.success(request, f"Lab '{form_data['name']}' and associated references updated.")
    return redirect("gui:labs")


def lab_delete(request, lab_name):
    """Confirmation page (GET) and the confirm/cancel actions (POST).

    A lab that a course or faculty member still uses cannot be deleted; the
    page lists what uses it instead (Section 12).
    """
    try:
        lab = lab_controller.get_lab(request, lab_name)
    except ControllerError as error:
        messages.error(request, error.message)
        return redirect("gui:labs")

    if request.method == "POST":
        if request.POST.get("action") != "confirm":
            messages.info(request, "Cancelled.")
            return redirect("gui:labs")
        try:
            lab_controller.delete_lab(request, lab_name)
        except ControllerError as error:
            messages.error(request, error.message)
        else:
            messages.success(request, f"Lab '{lab_name}' deleted.")
        return redirect("gui:labs")

    return render(request, "gui/lab_delete.html", {"active": "config", "lab": lab})
