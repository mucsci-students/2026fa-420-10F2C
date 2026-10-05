"""Views for the Faculty Configuration Editor pages.

Views handle HTTP and form binding only. The Faculty controller owns model
construction, reference protection, and complete-configuration validation.
"""

from django.contrib import messages
from django.shortcuts import redirect, render

from gui.controllers import faculty as faculty_controller
from gui.controllers.errors import ControllerError
from gui.forms import FacultyForm, availability_to_text
from gui.views import _attach_errors


def _faculty_form(request, *args, **kwargs):
    """Build a form with preference fields for this configuration's resources."""
    return FacultyForm(*args, **faculty_controller.form_choices(request), **kwargs)


def _render_faculty(request):
    """Render the list page without embedding the lengthy creation form."""
    data = faculty_controller.describe_faculty(request)
    return render(request, "gui/faculty.html", {"active": "config", "data": data})


def _render_faculty_add(request, form=None):
    """Render the dedicated creation page, retaining a rejected bound form."""
    return render(request, "gui/faculty_add.html", {"active": "config", "form": form or _faculty_form(request)})


def faculty(request):
    """Show the current faculty records and the creation action."""
    return _render_faculty(request)


def faculty_add(request):
    """Display or submit the dedicated Faculty creation form."""
    if request.method == "GET":
        return _render_faculty_add(request)
    if request.method != "POST":
        return redirect("gui:faculty")
    form = _faculty_form(request, request.POST)
    if form.is_valid():
        try:
            faculty_controller.add_faculty(request, form.cleaned_data)
        except ControllerError as error:
            _attach_errors(form, error)
        else:
            messages.success(request, f"Faculty member '{form.cleaned_data['name']}' added.")
            return redirect("gui:faculty")
    return _render_faculty_add(request, form=form)


def faculty_edit(request, faculty_name):
    """Display a faculty record for edit or apply its submitted changes."""
    try:
        person = faculty_controller.get_faculty(request, faculty_name)
    except ControllerError as error:
        messages.error(request, error.message)
        return redirect("gui:faculty")

    if request.method == "POST":
        form = _faculty_form(request, request.POST)
        if form.is_valid():
            try:
                faculty_controller.update_faculty(request, faculty_name, form.cleaned_data)
            except ControllerError as error:
                _attach_errors(form, error)
            else:
                messages.success(request, f"Faculty member '{form.cleaned_data['name']}' updated.")
                return redirect("gui:faculty")
    else:
        form = _faculty_form(
            request,
            initial={
                "name": person["name"],
                "minimum_credits": person["minimum_credits"],
                "maximum_credits": person["maximum_credits"],
                "unique_course_limit": person["unique_course_limit"],
                "maximum_days": person["maximum_days"],
                "times": availability_to_text(person["times"]),
                "mandatory_days": person["mandatory_days"],
                "course_preferences": person["course_preferences"],
                "room_preferences": person["room_preferences"],
                "lab_preferences": person["lab_preferences"],
            },
        )
    return render(request, "gui/faculty_edit.html", {"active": "config", "form": form, "faculty": person})


def faculty_delete(request, faculty_name):
    """Show a delete confirmation or remove an unreferenced faculty member."""
    try:
        person = faculty_controller.get_faculty(request, faculty_name)
    except ControllerError as error:
        messages.error(request, error.message)
        return redirect("gui:faculty")

    if request.method == "POST":
        if request.POST.get("action") != "confirm":
            messages.info(request, "Cancelled.")
            return redirect("gui:faculty")
        try:
            faculty_controller.delete_faculty(request, faculty_name)
        except ControllerError as error:
            messages.error(request, error.message)
        else:
            messages.success(request, f"Faculty member '{faculty_name}' deleted.")
        return redirect("gui:faculty")

    return render(request, "gui/faculty_delete.html", {"active": "config", "faculty": person})