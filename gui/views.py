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

import re

from django.contrib import messages
from django.http import Http404, HttpResponse

from app import schedule_ops
from django.shortcuts import redirect, render
from django.urls import reverse

from gui.constants import (
    DAY_NAMES,
    NO_FACULTY_LABEL,
    NO_LOCATION_LABEL,
    VIEW_COURSES,
    VIEW_FACULTY,
    VIEW_OPTIONS,
    VIEW_ROOMS,
)
from gui.controllers import config_controller, schedule_controller, settings as settings_controller
from gui.controllers import timeslots as timeslot_controller
from gui.controllers.errors import ControllerError
from gui.forms import (
    AddTimeBlockForm,
    ScheduleExportForm,
    GenerationOverrideForm,
    ConfigLoadForm,
    ConfigNewForm,
    SavedConfigSelectionForm,
    ScheduleImportForm,
    TimeBlockFieldsForm,
    TimingOptionsForm,
)


MINUTES_PER_HOUR = 60


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
    ("courses", "Courses", "gui:courses"),
    ("faculty", "Faculty", "gui:faculty"),
    ("patterns", "Class Patterns", "gui:patterns"),
    ("meetings", "Meetings", "gui:meetings"),
    ("settings", "Global Settings", "gui:settings"),
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
    return download_response(filename, content, "application/json; charset=utf-8", download_token(request))


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


def _render_schedule_generator(request, form=None, result=None, config_form=None):
    data = settings_controller.describe_settings(request)
    config_choices = config_controller.saved_config_choices(request)
    context = {
        "active": "generator",
        "data": data,
        "generating": schedule_controller.is_generating(request),
        "result": result,
        "config_choices": config_choices,
    }
    if config_form is None:
        config_form = SavedConfigSelectionForm(
            config_choices=config_choices,
            initial={"config_name": getattr(config_controller.get_session(request), "config_name", "")},
        ) if config_choices else None
    context["config_form"] = config_form
    if data["has_config"]:
        if form is None:
            form = GenerationOverrideForm(
                flag_choices=data["flag_choices"],
                initial={"optimizer_flags": data["enabled_flags"]},
            )
        context["form"] = form
    return render(request, "gui/schedule_generator.html", context)


def schedule_select_config(request):
    if request.method != "POST":
        return redirect("gui:schedule_generator")
    form = SavedConfigSelectionForm(
        request.POST,
        config_choices=config_controller.saved_config_choices(request),
    )
    if form.is_valid():
        try:
            name = config_controller.select_saved_configuration(request, form.cleaned_data["config_name"])
        except ControllerError as error:
            _attach_errors(form, error)
        else:
            messages.success(request, f"Selected {name} for schedule generation.")
            return redirect("gui:schedule_generator")
    return _render_schedule_generator(request, config_form=form)


def schedule_generator(request):
    """Generate schedules using saved settings or one-run overrides."""
    if request.method != "POST":
        return _render_schedule_generator(request)

    data = settings_controller.describe_settings(request)
    form = GenerationOverrideForm(request.POST, flag_choices=data.get("flag_choices", ()))
    if not form.is_valid():
        return _render_schedule_generator(request, form=form)

    try:
        result = schedule_controller.generate(
            request,
            limit_override=form.cleaned_data["limit"],
            optimizer_overrides=form.cleaned_data["optimizer_flags"],
        )
    except ControllerError as error:
        _attach_errors(form, error)
        return _render_schedule_generator(request, form=form)

    if result.outcome == schedule_ops.GenerationOutcome.SUCCESS:
        messages.success(request, result.message)
        return redirect("gui:schedule_viewer")
    if result.outcome == schedule_ops.GenerationOutcome.NO_FEASIBLE_SCHEDULE:
        messages.warning(request, "No feasible schedule was found. Check the configuration and try again.")
    elif result.outcome == schedule_ops.GenerationOutcome.INVALID_CONFIG:
        messages.error(request, f"The configuration is invalid: {result.message}")
    else:
        messages.error(request, f"Schedule generation failed unexpectedly: {result.message}")
    return _render_schedule_generator(request, form=form, result=result)


def schedule_viewer(request, import_form=None):
    """Schedule Viewer mode (Sections 15-18). Loading schedules from JSON,
    exporting one as JSON, and the grid filter views work; see
    gui/controllers/schedule_controller.py for the schedule data.

    ?schedule=N (1-based) selects the current schedule; anything missing or
    out of range falls back to schedule 1. ?view=rooms labels the grid by
    room and ?view=faculty by faculty member (see _current_view_mode).
    """
    count = schedule_controller.schedule_count(request)
    current = _current_schedule_number(request, count)
    view_mode = _current_view_mode(request)
    schedule_grid = (
        _schedule_grid(schedule_controller.get_schedule(request, current - 1), view_mode) if count else None
    )
    if import_form is None:
        import_form = ScheduleImportForm(schedule_count=count)
    export_form = ScheduleExportForm(schedule_count=count, initial={"schedule": current})
    pager = _schedule_pager_context(current, count, view_mode)
    return render(
        request,
        "gui/schedule_viewer.html",
        {
            "active": "viewer",
            "schedule_count": count,
            "current_schedule": current,
            "schedule_grid": schedule_grid,
            "view_mode": view_mode,
            "view_options": VIEW_OPTIONS,
            **pager,
            "import_form": import_form,
            "export_form": export_form,
        },
    )


def schedule_clear(request):
    """Clear all schedules, after a confirmation page (Section 15, user
    stories 32, 54, 57).

    GET shows "Remove all N schedules?" with Clear and Cancel. POST with
    action=confirm clears them; anything else (Cancel) keeps them. With no
    schedules there is nothing to confirm, so it goes back to the viewer.
    """
    count = schedule_controller.schedule_count(request)
    if count == 0:
        messages.info(request, "There are no schedules to clear.")
        return redirect("gui:schedule_viewer")

    if request.method == "POST":
        noun = "schedule" if count == 1 else "schedules"
        if request.POST.get("action") != "confirm":
            messages.info(request, f"Cancelled. Your {count} {noun} were kept.")
            return redirect("gui:schedule_viewer")
        try:
            cleared = schedule_controller.clear_schedules(request)
        except ControllerError as error:
            messages.error(request, error.message)
        else:
            noun = "schedule" if cleared == 1 else "schedules"
            messages.success(request, f"Cleared {cleared} {noun}.")
        return redirect("gui:schedule_viewer")

    return render(request, "gui/schedules_clear.html", {"active": "viewer", "schedule_count": count})


def _current_schedule_number(request, count):
    raw = request.GET.get("schedule", "")
    number = int(raw) if raw.isdigit() else 1
    return number if 1 <= number <= count else 1


def _current_view_mode(request):
    """The ?view= value when it is a known option; anything else means Courses."""
    requested = request.GET.get("view")
    return requested if requested in VIEW_OPTIONS else VIEW_COURSES


def _schedule_pager_context(
    current: int, count: int, view_mode: str = VIEW_COURSES
) -> dict[str, int | bool | str | None]:
    """Build valid one-based pager values from the selected schedule.

    Selection remains request-derived, so navigating never mutates session
    state or creates a second source of truth for the export form. view_query
    carries the chosen view across Previous/Next (empty for the default view).
    """
    has_previous = current > 1
    has_next = current < count
    return {
        "has_previous": has_previous,
        "has_next": has_next,
        "previous_schedule": current - 1 if has_previous else None,
        "next_schedule": current + 1 if has_next else None,
        "view_query": "" if view_mode == VIEW_COURSES else f"&view={view_mode}",
    }


def _block_label(view_mode, course, location, faculty):
    """Text on a grid block: the course, its room/lab, or its faculty member."""
    if view_mode == VIEW_ROOMS:
        return location or NO_LOCATION_LABEL
    if view_mode == VIEW_FACULTY:
        return faculty or NO_FACULTY_LABEL
    return course


def _schedule_rows(assignments, view_mode=VIEW_COURSES):
    """Expand a selected schedule into chronological, human-readable meeting rows."""
    day_order = {day: index for index, day in enumerate(DAY_NAMES)}
    rows = []
    for assignment in assignments:
        for meeting in assignment.meetings:
            is_lab = meeting.lab
            location = assignment.lab if is_lab else assignment.room
            rows.append(
                {
                    "day": meeting.day,
                    "day_name": DAY_NAMES.get(meeting.day, meeting.day),
                    "start": meeting.start,
                    "end": meeting.end,
                    "course": assignment.course,
                    "faculty": assignment.faculty,
                    "meeting_type": "Lab" if is_lab else "Class",
                    "location": location,
                    "label": _block_label(view_mode, assignment.course, location, assignment.faculty),
                    "sort_key": (day_order.get(meeting.day, len(day_order)), meeting.start, assignment.course),
                }
            )
    return sorted(rows, key=lambda row: row["sort_key"])


DENSE_LANE_COUNT = 3
LANE_MIN_WIDTH_REM = 34
LANE_WIDTH_STEP_REM = 12


def _schedule_grid(assignments, view_mode=VIEW_COURSES):
    """Build the same day-by-time geometry used by the Time Slots overview.

    Assignment records are already normalized by schedule_controller, so this
    only organizes the selected schedule for display and never changes it.
    """
    rows = _schedule_rows(assignments, view_mode)
    minutes = [
        value
        for row in rows
        for value in (_clock_minutes(row["start"]), _clock_minutes(row["end"]))
    ]
    axis_start, axis_end = _schedule_axis_bounds(minutes)
    span = axis_end - axis_start
    meetings_by_day = {day: [] for day in DAY_NAMES}

    for row in rows:
        start = _clock_minutes(row["start"])
        end = _clock_minutes(row["end"])
        meetings_by_day[row["day"]].append(
            {
                **row,
                "top": f"{(start - axis_start) / span * 100:.2f}",
                "height": f"{(end - start) / span * 100:.2f}",
            }
        )

    days = []
    max_lanes = 1
    for day in DAY_NAMES:
        meetings = meetings_by_day[day]
        _assign_meeting_lanes(meetings)
        lanes = [meeting for meeting in meetings if meeting["lane_count"] < DENSE_LANE_COUNT]
        dense = [meeting for meeting in meetings if meeting["lane_count"] >= DENSE_LANE_COUNT]
        max_lanes = max([max_lanes, *(meeting["lane_count"] for meeting in lanes)])
        days.append({"day": day, "name": DAY_NAMES[day], "meetings": lanes, "clusters": _stack_clusters(dense)})

    return {
        "days": days,
        "hours": [
            {"label": f"{minute // MINUTES_PER_HOUR:02d}:00", "top": f"{(minute - axis_start) / span * 100:.2f}"}
            for minute in range(axis_start, axis_end + 1, MINUTES_PER_HOUR)
        ],
        "hour_pct": f"{MINUTES_PER_HOUR / span * 100:.3f}",
        "min_width": f"{LANE_MIN_WIDTH_REM + LANE_WIDTH_STEP_REM * (max_lanes - 1)}rem",
    }


def _stack_clusters(meetings):
    """Merge each dense overlap cluster into one block that lists its labels."""
    clusters = {}
    for meeting in meetings:
        clusters.setdefault(meeting["cluster"], []).append(meeting)

    stacked = []
    for group in clusters.values():
        top = min(float(meeting["top"]) for meeting in group)
        bottom = max(float(meeting["top"]) + float(meeting["height"]) for meeting in group)
        stacked.append(
            {
                "top": f"{top:.2f}",
                "height": f"{bottom - top:.2f}",
                "meetings": sorted(group, key=lambda meeting: (meeting["start"], meeting["course"])),
            }
        )
    return stacked


def _assign_meeting_lanes(meetings):
    """Give overlapping meetings separate horizontal lanes in a day column.

    A connected overlap group shares its widest lane count so adjacent blocks
    never jump between widths while one course remains in progress.
    """
    meetings.sort(key=lambda meeting: (meeting["start"], meeting["end"], meeting["course"]))
    group = []
    latest_end = None
    cluster_id = 0

    for meeting in meetings:
        start = _clock_minutes(meeting["start"])
        end = _clock_minutes(meeting["end"])
        if group and start >= latest_end:
            _layout_overlap_group(group, cluster_id)
            cluster_id += 1
            group = []
            latest_end = None
        group.append(meeting)
        latest_end = end if latest_end is None else max(latest_end, end)

    if group:
        _layout_overlap_group(group, cluster_id)


def _layout_overlap_group(meetings, cluster_id):
    """Set zero-based lane position and width for one connected overlap group."""
    lane_end_times = []
    for meeting in meetings:
        start = _clock_minutes(meeting["start"])
        end = _clock_minutes(meeting["end"])
        lane = next(
            (index for index, lane_end in enumerate(lane_end_times) if lane_end <= start),
            len(lane_end_times),
        )
        if lane == len(lane_end_times):
            lane_end_times.append(end)
        else:
            lane_end_times[lane] = end
        meeting["lane"] = lane

    lane_count = len(lane_end_times)
    for meeting in meetings:
        meeting["cluster"] = cluster_id
        meeting["lane_count"] = lane_count
        meeting["left"] = f"{meeting['lane'] / lane_count * 100:.2f}"
        meeting["width"] = f"{100 / lane_count:.2f}"


def _schedule_axis_bounds(minutes):
    """Return whole-hour bounds that contain every meeting in the grid."""
    if not minutes:
        return 8 * MINUTES_PER_HOUR, 17 * MINUTES_PER_HOUR
    earliest = min(minutes) // MINUTES_PER_HOUR * MINUTES_PER_HOUR
    latest = -(-max(minutes) // MINUTES_PER_HOUR) * MINUTES_PER_HOUR
    return earliest, max(latest, earliest + MINUTES_PER_HOUR)


def _clock_minutes(value: str) -> int:
    """Convert a validated 24-hour clock string into minutes after midnight."""
    hour, minute = value.split(":", 1)
    return int(hour) * MINUTES_PER_HOUR + int(minute)


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


def schedule_export(request):
    """Download one schedule or the whole set, as JSON or CSV (Section 18).

    A GET form, since nothing changes. Success sends the file as a browser
    download (download_response), so the browser picks where it goes and
    asks before replacing an existing file. Problems (no schedules, a
    schedule number that no longer exists, an unknown format) go back to
    the viewer with an error message. Without file_format the export is
    JSON, so the older /schedules/export/json/ links keep working.
    """
    count = schedule_controller.schedule_count(request)
    form = ScheduleExportForm(request.GET, schedule_count=count)
    if not form.is_valid():
        if count == 0:
            messages.error(request, schedule_controller.NO_SCHEDULES_MESSAGE)
        elif "file_format" in form.errors:
            messages.error(request, "Choose JSON or CSV as the export format.")
        else:
            messages.error(request, f"Choose a schedule from 1 to {count} to export.")
        return redirect("gui:schedule_viewer")

    try:
        export = schedule_controller.export_schedules(
            request, form.cleaned_data["index"], form.cleaned_data["file_format"]
        )
    except ControllerError as error:
        messages.error(request, error.message)
        return redirect("gui:schedule_viewer")
    return download_response(export.filename, export.content, export.content_type, download_token(request))


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


DOWNLOAD_TOKEN_FIELD = "download_token"
DOWNLOAD_TOKEN_COOKIE = "download_token"
_DOWNLOAD_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def download_token(request) -> str | None:
    """The token gui/static/gui/js/loading.js sends with a download form, or None.

    Only short letter/digit/-/_ strings are accepted, so nothing odd is
    ever echoed back in a cookie.
    """
    raw = request.POST.get(DOWNLOAD_TOKEN_FIELD) or request.GET.get(DOWNLOAD_TOKEN_FIELD) or ""
    return raw if _DOWNLOAD_TOKEN_RE.match(raw) else None


def download_response(
    filename: str, content: str | bytes, content_type: str, token: str | None = None
) -> HttpResponse:
    """Send `content` as a file download (config save, schedule export).

    Downloads let the browser choose where the file goes and ask before
    replacing an existing file, so the app never overwrites anything on
    disk -- the documented overwrite protection for Sections 9 and 18.
    Text is sent as UTF-8; include "; charset=utf-8" in `content_type`.

    `token` (from download_token(request)) is echoed back in a short-lived
    cookie. A download doesn't load a new page, so this is how the page's
    loading state (Section 19, user story 48) knows the file has arrived.
    """
    body = content.encode("utf-8") if isinstance(content, str) else content
    response = HttpResponse(body, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    if token and _DOWNLOAD_TOKEN_RE.match(token):
        response.set_cookie(DOWNLOAD_TOKEN_COOKIE, token, max_age=120, samesite="Lax")
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
