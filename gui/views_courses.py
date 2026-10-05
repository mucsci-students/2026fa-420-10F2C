"""Views for the Course Configuration Editor pages.

Views bind HTTP requests to CourseForm and delegate all scheduler mutations to
gui.controllers.courses. Course URLs use a list index because multiple rows may
share the same course ID as separate sections.
"""

from django.contrib import messages
from django.shortcuts import redirect, render

from gui.controllers import courses as course_controller
from gui.controllers.errors import ControllerError
from gui.forms import CourseForm
from gui.views import _attach_errors


def _course_form(request, *args, course_index=None, **kwargs):
    """Build CourseForm with names supplied by the controller's read model."""
    return CourseForm(*args, **course_controller.form_choices(request, course_index), **kwargs)


def _render_courses(request):
    """Render the list page without embedding the long creation form."""
    data = course_controller.describe_courses(request)
    return render(request, "gui/courses.html", {"active": "config", "data": data})


def _render_course_add(request, form=None):
    """Render the dedicated creation page, keeping a rejected bound form."""
    return render(request, "gui/course_add.html", {"active": "config", "form": form or _course_form(request)})


def courses(request):
    """Show current course sections and the action to create a new section."""
    return _render_courses(request)


def course_add(request):
    """Display or submit a dedicated Course creation form."""
    if request.method == "GET":
        return _render_course_add(request)
    if request.method != "POST":
        return redirect("gui:courses")
    form = _course_form(request, request.POST)
    if form.is_valid():
        try:
            course_controller.add_course(request, form.cleaned_data)
        except ControllerError as error:
            _attach_errors(form, error)
        else:
            messages.success(request, f"Course '{form.cleaned_data['course_id']}' added.")
            return redirect("gui:courses")
    return _render_course_add(request, form=form)


def course_edit(request, course_index):
    """Display an indexed section for edit or commit its validated changes."""
    try:
        course = course_controller.get_course(request, course_index)
    except ControllerError as error:
        messages.error(request, error.message)
        return redirect("gui:courses")

    if request.method == "POST":
        form = _course_form(request, request.POST, course_index=course_index)
        if form.is_valid():
            try:
                course_controller.update_course(request, course_index, form.cleaned_data)
            except ControllerError as error:
                _attach_errors(form, error)
            else:
                messages.success(request, f"Course '{form.cleaned_data['course_id']}' updated.")
                return redirect("gui:courses")
    else:
        form = _course_form(
            request,
            course_index=course_index,
            initial={
                "course_id": course["course_id"],
                "section_id": course["section_id"],
                "credits": course["credits"],
                "capacity": course["capacity"],
                "room": course["room"],
                "lab": course["lab"],
                "conflicts": course["conflicts"],
                "faculty": course["faculty"],
                "modality": course["modality"],
                "required_room_features": ", ".join(course["required_room_features"]),
                "required_lab_features": ", ".join(course["required_lab_features"]),
                "reserve_room_during_lab": course["reserve_room_during_lab"],
            },
        )
    return render(request, "gui/course_edit.html", {"active": "config", "form": form, "course": course})


def course_delete(request, course_index):
    """Show a deletion confirmation or remove an unreferenced course section."""
    try:
        course = course_controller.get_course(request, course_index)
    except ControllerError as error:
        messages.error(request, error.message)
        return redirect("gui:courses")

    if request.method == "POST":
        if request.POST.get("action") != "confirm":
            messages.info(request, "Cancelled.")
            return redirect("gui:courses")
        try:
            course_controller.delete_course(request, course_index)
        except ControllerError as error:
            messages.error(request, error.message)
        else:
            messages.success(request, f"Course '{course['label']}' deleted.")
        return redirect("gui:courses")

    return render(request, "gui/course_delete.html", {"active": "config", "course": course})