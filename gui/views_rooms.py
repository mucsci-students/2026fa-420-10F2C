"""
Views for the Rooms pages (Configuration Editor, Section 7, Rooms row).

Same shape as the Time Slots views in gui/views.py: parse the request, call the
controller (gui/controllers/rooms.py), then either redirect with a flash
message (success) or re-render the same page with the errors on the form
(failure), so the user's input is kept and the configuration is untouched.
Rooms are identified by name in the URL.
"""

from django.contrib import messages
from django.shortcuts import redirect, render

from gui.controllers import rooms as room_controller
from gui.controllers.errors import ControllerError
from gui.forms import RoomForm, availability_to_text
from gui.views import _attach_errors


def _render_rooms(request, add_form=None):
    data = room_controller.describe_rooms(request)
    context = {"active": "config", "data": data}
    if data["has_config"]:
        if add_form is None:
            add_form = RoomForm()
        context["add_form"] = add_form
    return render(request, "gui/rooms.html", context)


def rooms(request):
    """Rooms page: the current rooms and a form to add one."""
    return _render_rooms(request)


def room_add(request):
    if request.method != "POST":
        return redirect("gui:rooms")
    form = RoomForm(request.POST)
    if form.is_valid():
        try:
            room_controller.add_room(request, form.cleaned_data)
        except ControllerError as error:
            _attach_errors(form, error)
        else:
            messages.success(request, f"Room '{form.cleaned_data['name']}' added.")
            return redirect("gui:rooms")
    return _render_rooms(request, add_form=form)


def room_edit(request, room_name):
    try:
        room = room_controller.get_room(request, room_name)
    except ControllerError as error:
        messages.error(request, error.message)
        return redirect("gui:rooms")

    if request.method == "POST":
        form = RoomForm(request.POST)
        if form.is_valid():
            try:
                room_controller.update_room(request, room_name, form.cleaned_data)
            except ControllerError as error:
                _attach_errors(form, error)
            else:
                messages.success(request, f"Room '{form.cleaned_data['name']}' updated.")
                return redirect("gui:rooms")
    else:
        form = RoomForm(
            initial={
                "name": room["name"],
                "capacity": room["capacity"],
                "features": ", ".join(room["features"]),
                "times": availability_to_text(room["times"]),
            }
        )
    return render(request, "gui/room_edit.html", {"active": "config", "form": form, "room": room})


def room_delete(request, room_name):
    """Confirmation page (GET) and the confirm/cancel actions (POST).

    A room that a course or faculty member still uses cannot be deleted; the
    page lists what uses it instead (Section 12).
    """
    try:
        room = room_controller.get_room(request, room_name)
    except ControllerError as error:
        messages.error(request, error.message)
        return redirect("gui:rooms")

    if request.method == "POST":
        if request.POST.get("action") != "confirm":
            messages.info(request, "Cancelled.")
            return redirect("gui:rooms")
        try:
            room_controller.delete_room(request, room_name)
        except ControllerError as error:
            messages.error(request, error.message)
        else:
            messages.success(request, f"Room '{room_name}' deleted.")
        return redirect("gui:rooms")

    return render(request, "gui/room_delete.html", {"active": "config", "room": room})
