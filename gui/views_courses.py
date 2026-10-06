"""
Views for the Courses pages (Configuration Editor, Section 7, Courses row).

Same shape as the Rooms, Class Patterns and Faculty views: parse the request,
call the controller (gui/controllers/courses.py), then either redirect with a
flash message (success) or re-render the same page with the errors on the form
(failure), so the user's input is kept and the configuration is untouched.

Courses have no unique name (sections share a course ID), so they are
identified by their position in the URL. The edit and delete forms also post
back the course ID the page showed ("expected_course_id"), so a list that
changed in the meantime is refused instead of editing the wrong section.
"""

from django.contrib import messages
from django.shortcuts import redirect, render

from gui.controllers import courses as course_controller
from gui.controllers.errors import ControllerError
from gui.forms import CourseForm
from gui.views import _attach_errors, _flash_warnings

_FORM_FIELDS = [
    "course_id",
    "section_id",
    "credits",
    "capacity",
    "modality",
    "room",
    "lab",
    "conflicts",
    "faculty",
    "required_room_features",
    "required_lab_features",
    "reserve_room_during_lab",
]


def _course_form(request, *args, course_index=None, **kwargs):
    """A CourseForm whose pickers list this configuration's rooms, labs, etc."""
    return CourseForm(*args, **course_controller.form_choices(request, course_index), **kwargs)


def courses(request):
    """Courses page: every section, with edit/delete actions."""
    data = course_controller.describe_courses(request)
    return render(request, "gui/courses.html", {"active": "config", "data": data})


def course_add(request):
    """Display (GET) or submit (POST) the Add course page."""
    if not course_controller.describe_courses(request)["has_config"]:
        return redirect("gui:courses")  # the list page shows the empty state
    if request.method == "POST":
        form = _course_form(request, request.POST)
        if form.is_valid():
            try:
                notices = course_controller.add_course(request, form.cleaned_data)
            except ControllerError as error:
                _attach_errors(form, error)
            else:
                messages.success(request, f"Course '{form.cleaned_data['course_id']}' added.")
                _flash_warnings(request, notices)
                return redirect("gui:courses")
    else:
        form = _course_form(request, initial={"modality": "in_person", "reserve_room_during_lab": True})
    return render(request, "gui/course_add.html", {"active": "config", "form": form})


def course_edit(request, course_index):
    try:
        course = course_controller.get_course(request, course_index)
    except ControllerError as error:
        messages.error(request, error.message)
        return redirect("gui:courses")

    if request.method == "POST":
        form = _course_form(request, request.POST, course_index=course_index)
        if form.is_valid():
            try:
                notices = course_controller.update_course(
                    request,
                    course_index,
                    form.cleaned_data,
                    expected_course_id=request.POST.get("expected_course_id") or None,
                )
            except ControllerError as error:
                _attach_errors(form, error)
            else:
                messages.success(request, f"Course '{form.cleaned_data['course_id']}' updated.")
                _flash_warnings(request, notices)
                return redirect("gui:courses")
    else:
        form = _course_form(
            request,
            course_index=course_index,
            initial={name: course[name] for name in _FORM_FIELDS},
        )
    return render(request, "gui/course_edit.html", {"active": "config", "form": form, "course": course})


def course_delete(request, course_index):
    """Confirmation page (GET) and the confirm/cancel actions (POST).

    The last section of a course ID that another course or a faculty
    preference still names cannot be deleted; the page lists those instead
    (Section 12).
    """
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
            course_controller.delete_course(
                request,
                course_index,
                expected_course_id=request.POST.get("expected_course_id") or None,
            )
        except ControllerError as error:
            messages.error(request, error.message)
        else:
            messages.success(request, f"Course '{course['display']}' deleted.")
        return redirect("gui:courses")

    return render(request, "gui/course_delete.html", {"active": "config", "course": course})
