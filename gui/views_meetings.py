"""
Views for the Meetings pages (Configuration Editor, Section 7, Meetings row).

Same shape as the Class Patterns, Rooms and Time Slots views. A meeting belongs
to a class pattern, so each one is identified by (pattern_index, meeting_index)
in the URL, and the add form asks which pattern it goes on.
"""

from django.contrib import messages
from django.shortcuts import redirect, render

from gui.controllers import meetings as meeting_controller
from gui.controllers.errors import ControllerError
from gui.forms import AddMeetingForm, MeetingFieldsForm
from gui.views import _attach_errors, _flash_warnings


def _render_meetings(request, add_form=None):
    data = meeting_controller.describe_meetings(request)
    context = {"active": "config", "data": data}
    if data["has_config"]:
        if add_form is None:
            add_form = AddMeetingForm(
                pattern_choices=data["pattern_choices"],
                initial={"duration": 50, "delivery": "in_person"},
            )
        context["add_form"] = add_form
    return render(request, "gui/meetings.html", context)


def meetings(request):
    """Meetings page: every pattern's meetings and a form to add one."""
    return _render_meetings(request)


def meeting_add(request):
    if request.method != "POST":
        return redirect("gui:meetings")
    choices = meeting_controller.describe_meetings(request).get("pattern_choices", [])
    form = AddMeetingForm(request.POST, pattern_choices=choices)
    if form.is_valid():
        try:
            warnings = meeting_controller.add_meeting(request, form.cleaned_data["pattern"], form.cleaned_data)
        except ControllerError as error:
            _attach_errors(form, error)
        else:
            messages.success(request, "Meeting added.")
            _flash_warnings(request, warnings)
            return redirect("gui:meetings")
    return _render_meetings(request, add_form=form)


def meeting_edit(request, pattern_index, meeting_index):
    try:
        meeting = meeting_controller.get_meeting(request, pattern_index, meeting_index)
    except ControllerError as error:
        messages.error(request, error.message)
        return redirect("gui:meetings")

    if request.method == "POST":
        form = MeetingFieldsForm(request.POST)
        if form.is_valid():
            try:
                warnings = meeting_controller.update_meeting(
                    request, pattern_index, meeting_index, form.cleaned_data
                )
            except ControllerError as error:
                _attach_errors(form, error)
            else:
                messages.success(request, "Meeting updated.")
                _flash_warnings(request, warnings)
                return redirect("gui:meetings")
    else:
        form = MeetingFieldsForm(
            initial={
                "day": meeting["day"],
                "duration": meeting["duration"],
                "lab": meeting["lab"],
                "delivery": meeting["delivery"],
                "start_time": meeting["start_time"] or None,
            }
        )
    return render(request, "gui/meeting_edit.html", {"active": "config", "form": form, "meeting": meeting})


def meeting_delete(request, pattern_index, meeting_index):
    """Confirmation page (GET) and the confirm/cancel actions (POST).

    A pattern's only meeting cannot be deleted; the page says so instead of
    offering the button (user story 27).
    """
    try:
        meeting = meeting_controller.get_meeting(request, pattern_index, meeting_index)
    except ControllerError as error:
        messages.error(request, error.message)
        return redirect("gui:meetings")

    if request.method == "POST":
        if request.POST.get("action") != "confirm":
            messages.info(request, "Cancelled.")
            return redirect("gui:meetings")
        try:
            warnings = meeting_controller.delete_meeting(request, pattern_index, meeting_index)
        except ControllerError as error:
            messages.error(request, error.message)
        else:
            messages.success(request, "Meeting removed.")
            _flash_warnings(request, warnings)
        return redirect("gui:meetings")

    return render(request, "gui/meeting_delete.html", {"active": "config", "meeting": meeting})
