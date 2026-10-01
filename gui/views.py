"""
View layer (Section 20: View = "GUI pages, forms, tables, components,
dialogs, navigation, and user-facing messages"). Views stay thin: parse the
request, call a controller, render a template with what the controller
returns. Scheduler-domain logic and validation stay out of this file --
see gui/controllers/ and app/.

index/config_editor/schedule_generator/schedule_viewer below render real
pages today (not stubs) so navigation (Section 4) works end to end; each
non-home page's template lists what that mode still needs (see
gui/templates/gui/*.html). As controllers/forms get implemented, these
view functions will start calling them instead of just rendering a static
template.
"""

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from gui.constants import DAY_NAMES
from gui.controllers import config_controller, schedule_controller
from gui.controllers import timeslots as timeslot_controller
from gui.controllers.errors import ControllerError
from gui.forms import (
    AddTimeBlockForm,
    ConfigLoadForm,
    ConfigNewForm,
    ScheduleImportForm,
    TimeBlockFieldsForm,
    TimingOptionsForm,
)


def index(request):
    """Welcome screen -- links to the three required modes (Section 1)."""
    return render(request, "gui/index.html", {"active": "home"})


# ---------------------------------------------------------------------- #
#  Configuration Editor home + lifecycle (Sections 8-10): New / Load / Save /
#  Validate. Same shape as every action: POST only, call the controller, then
#  redirect with a flash message (success) or re-render with the errors shown
#  (failure) -- the current configuration is never touched by a failure.
# ---------------------------------------------------------------------- #
# One row per configuration area on the editor home page: (count key from
# config_controller.describe_configuration, label, URL name). When an area's
# pages exist, put its URL name here -- that is the only change the home page
# needs to link to it.
_CONFIG_AREAS = (
    ("time_blocks", "Time Slots", "gui:timeslots"),
    ("rooms", "Rooms", "gui:rooms"),
    ("labs", "Labs", "gui:labs"),
    ("courses", "Courses", None),
    ("faculty", "Faculty", None),
    ("patterns", "Class Patterns", None),
    ("meetings", "Meetings", None),
    ("settings", "Global Settings", None),
)


def _config_areas(counts):
    return [
        {"label": label, "count": counts.get(key), "url": reverse(url_name) if url_name else None}
        for key, label, url_name in _CONFIG_AREAS
    ]


def _render_config_editor(request, new_form=None, load_form=None, report=None):
    state = config_controller.describe_configuration(request)
    note = state["discard_note"]
    if new_form is None:
        new_form = ConfigNewForm(discard_note=note)
    if load_form is None:
        load_form = ConfigLoadForm(discard_note=note)
    context = {
        "active": "config",
        **state,
        "areas": _config_areas(state["counts"]),
        "new_form": new_form,
        "load_form": load_form,
        "report": report,
    }
    return render(request, "gui/config_editor.html", context)


def _discard_note(request):
    return config_controller.describe_configuration(request)["discard_note"]


def config_editor(request):
    """Configuration Editor home: current status, New / Load / Save /
    Validate, and the list of configuration areas (Sections 6-12)."""
    return _render_config_editor(request)


def config_new(request):
    if request.method != "POST":
        return redirect("gui:config_editor")
    form = ConfigNewForm(request.POST, discard_note=_discard_note(request))
    if form.is_valid():
        try:
            config_controller.new_configuration(request)
        except ControllerError as error:
            _attach_errors(form, error)
        else:
            messages.success(
                request,
                "Started a new configuration. It begins with one placeholder room, course, "
                "faculty member and class pattern; edit or replace them.",
            )
            return redirect("gui:config_editor")
    return _render_config_editor(request, new_form=form)


def config_load(request):
    if request.method != "POST":
        return redirect("gui:config_editor")
    form = ConfigLoadForm(request.POST, request.FILES, discard_note=_discard_note(request))
    if form.is_valid():
        uploaded = form.cleaned_data["config_file"]
        try:
            name = config_controller.load_configuration(request, uploaded)
        except ControllerError as error:
            _attach_errors(form, error)
        else:
            messages.success(request, f"Loaded and validated {name}.")
            return redirect("gui:config_editor")
    return _render_config_editor(request, load_form=form)


def config_save(request):
    """Validate, then send the configuration as a file download (Section 9)."""
    if request.method != "POST":
        return redirect("gui:config_editor")
    try:
        filename, content = config_controller.save_configuration(request)
    except ControllerError as error:
        report = {"heading": "The configuration was not saved.", "items": [item.message for item in error.errors]}
        return _render_config_editor(request, report=report)
    return download_response(filename, content, "application/json; charset=utf-8")


def config_validate(request):
    """Re-check the whole configuration and report the result (Section 10)."""
    if request.method != "POST":
        return redirect("gui:config_editor")
    try:
        problems = config_controller.validate_configuration(request)
    except ControllerError as error:
        messages.error(request, error.message)
        return redirect("gui:config_editor")
    if not problems:
        messages.success(request, "Configuration is valid. Every rule was checked and none are broken.")
        return redirect("gui:config_editor")
    return _render_config_editor(
        request, report={"heading": "The configuration has problems.", "items": problems}
    )


def schedule_generator(request):
    """Schedule Generator mode (Sections 13-14). Placeholder page today;
    see gui/controllers/schedule_controller.py."""
    return render(request, "gui/schedule_generator.html", {"active": "generator"})


def schedule_viewer(request, import_form=None):
    """Schedule Viewer mode (Sections 15-18). Loading schedules from JSON
    works; navigation, room/faculty views, and export are still to come
    (see gui/controllers/schedule_controller.py)."""
    count = schedule_controller.schedule_count(request)
    if import_form is None:
        import_form = ScheduleImportForm(schedule_count=count)
    return render(
        request,
        "gui/schedule_viewer.html",
        {"active": "viewer", "schedule_count": count, "import_form": import_form},
    )


def schedule_import(request):
    """Load schedules from an uploaded JSON file (Section 17).

    Success: redirect to the viewer with a message. Failure: re-render the
    viewer with the errors on the upload form; the schedules already loaded
    are untouched (the controller only replaces them after a full check).
    """
    if request.method != "POST":
        return redirect("gui:schedule_viewer")
    form = ScheduleImportForm(
        request.POST, request.FILES, schedule_count=schedule_controller.schedule_count(request)
    )
    if form.is_valid():
        uploaded = form.cleaned_data["schedule_file"]
        try:
            count = schedule_controller.load_schedule_json(request, uploaded)
        except ControllerError as error:
            _attach_errors(form, error)
        else:
            noun = "schedule" if count == 1 else "schedules"
            messages.success(request, f"Loaded {count} {noun} from {uploaded.name}.")
            return redirect("gui:schedule_viewer")
    return schedule_viewer(request, import_form=form)


# ---------------------------------------------------------------------- #
#  Time Slots (Configuration Editor, Section 7). This is the first finished
#  editing area, so its shape is the pattern for the others:
#    GET  list page  -> render controller data + blank forms
#    POST form       -> validate the form, call the controller, then either
#                       redirect with a flash message (success) or re-render
#                       the same page with errors on the form (failure) so
#                       the user's input is kept (Sections 10, 11).
# ---------------------------------------------------------------------- #
def _attach_errors(form, error):
    """Show a controller's errors on the matching form fields (or on the form)."""
    for item in error.errors:
        target = item.field if item.field in form.fields else None
        form.add_error(target, item.message)


def download_response(filename: str, content: str | bytes, content_type: str) -> HttpResponse:
    """Send `content` as a file download (config save, schedule export).

    Downloads let the browser choose where the file goes and ask before
    replacing an existing file, so the app never overwrites anything on
    disk -- the documented overwrite protection for Sections 9 and 18.
    Text is sent as UTF-8; include "; charset=utf-8" in `content_type`.
    """
    body = content.encode("utf-8") if isinstance(content, str) else content
    response = HttpResponse(body, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _flash_warnings(request, warnings):
    for warning in warnings:
        messages.warning(request, warning)


def _require_valid_day(day):
    if day not in DAY_NAMES:
        raise Http404("Unknown weekday")


def _render_timeslots(request, add_form=None, options_form=None):
    data = timeslot_controller.describe_timeslots(request)
    context = {"active": "config", "data": data}
    if data["has_config"]:
        if add_form is None:
            add_form = AddTimeBlockForm(initial={"spacing": 60})
        if options_form is None:
            options_form = TimingOptionsForm(
                initial={
                    "max_time_gap": data["max_time_gap"],
                    "min_time_overlap": data["min_time_overlap"],
                }
            )
        context["add_form"] = add_form
        context["options_form"] = options_form
    return render(request, "gui/timeslots.html", context)


def timeslots(request):
    """Time Slots page: weekly overview, blocks by day, add form, timing options."""
    return _render_timeslots(request)


def timeslot_add(request):
    if request.method != "POST":
        return redirect("gui:timeslots")
    form = AddTimeBlockForm(request.POST)
    if form.is_valid():
        try:
            warnings = timeslot_controller.add_timeslot(request, form.cleaned_data["day"], form.cleaned_data)
        except ControllerError as error:
            _attach_errors(form, error)
        else:
            messages.success(request, "Time Slot Added Successfully")
            _flash_warnings(request, warnings)
            return redirect("gui:timeslots")
    return _render_timeslots(request, add_form=form)


def timeslot_edit(request, day, index):
    _require_valid_day(day)
    try:
        block = timeslot_controller.get_timeslot(request, day, index)
    except ControllerError as error:
        messages.error(request, error.message)
        return redirect("gui:timeslots")

    if request.method == "POST":
        form = TimeBlockFieldsForm(request.POST)
        if form.is_valid():
            try:
                warnings = timeslot_controller.update_timeslot(request, day, index, form.cleaned_data)
            except ControllerError as error:
                _attach_errors(form, error)
            else:
                messages.success(request, "Time Changed Successfully")
                _flash_warnings(request, warnings)
                return redirect("gui:timeslots")
    else:
        form = TimeBlockFieldsForm(
            initial={"start": block["start"], "end": block["end"], "spacing": block["spacing"]}
        )
    return render(
        request,
        "gui/timeslot_edit.html",
        {"active": "config", "form": form, "slot": block, "day_name": DAY_NAMES[day]},
    )


def timeslot_delete(request, day, index):
    """Confirmation page (GET) and the confirm/cancel actions (POST)."""
    _require_valid_day(day)
    try:
        block = timeslot_controller.get_timeslot(request, day, index)
    except ControllerError as error:
        messages.error(request, error.message)
        return redirect("gui:timeslots")

    if request.method == "POST":
        if request.POST.get("action") != "confirm":
            messages.info(request, "Cancelled.")
            return redirect("gui:timeslots")
        try:
            warnings = timeslot_controller.delete_timeslot(request, day, index)
        except ControllerError as error:
            messages.error(request, error.message)
        else:
            messages.success(request, "Time slot deleted.")
            _flash_warnings(request, warnings)
        return redirect("gui:timeslots")

    return render(
        request,
        "gui/timeslot_delete.html",
        {"active": "config", "slot": block, "day_name": DAY_NAMES[day]},
    )


def timing_options(request):
    if request.method != "POST":
        return redirect("gui:timeslots")
    form = TimingOptionsForm(request.POST)
    if form.is_valid():
        try:
            timeslot_controller.update_timing_options(request, form.cleaned_data)
        except ControllerError as error:
            _attach_errors(form, error)
        else:
            messages.success(request, "Timing options updated.")
            return redirect("gui:timeslots")
    return _render_timeslots(request, options_form=form)
