"""
Django Forms for each configuration area (Section 7). Client-side/form
validation here is for usability only (Section 3) -- CombinedConfig via
app.crud.apply_edit remains the real source of truth, so forms only check
shape (a real time, a whole number) and leave rules like "end after start"
to the scheduler library.

Done:
    - AddTimeBlockForm / TimeBlockFieldsForm / TimingOptionsForm (time slots)
    - ScheduleImportForm (Schedule Viewer: load schedules from a JSON file)
    - ScheduleExportForm (Schedule Viewer: pick the schedule to export)
    - RoomForm / LabForm (rooms and labs: name, capacity, features, availability)
    - ClassPatternFieldsForm / AddClassPatternForm (class patterns: credits,
      enabled state, start time; the Add form also takes the first meeting)
    - MeetingFieldsForm / AddMeetingForm (meetings: day, duration, lab,
      delivery mode, optional start time)
    - GlobalSettingsForm (global settings: generation limit, optimizer flags)
        - FacultyForm (workload limits, availability, mandatory days, preferences)
        - CourseForm (course sections, resources, conflicts, faculty, and requirements)

TODO: one Form class per remaining area, matching the "Required editable data"
column in Section 7's table:
    - GenerationOverrideForm  (Section 14: limit override + optimizer overrides,
                                for the Schedule Generator page, separate from
                                GlobalSettingsForm since these must NOT touch
                                the saved configuration)
"""

import re

from django import forms

from gui.constants import DAY_NAMES

# <input type="time"> submits "HH:MM" (or "HH:MM:SS" if a step is set); a plain
# text fallback in older browsers may send "9:00", which %H:%M also accepts.
_TIME_FORMATS = ["%H:%M", "%H:%M:%S"]


def _time_field(label: str, help_text: str) -> forms.TimeField:
    return forms.TimeField(
        label=label,
        help_text=help_text,
        input_formats=_TIME_FORMATS,
        widget=forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
    )


class TimeBlockFieldsForm(forms.Form):
    """start / end / spacing -- used as-is for editing a block (the day is
    fixed by the URL) and as the base of the add form."""

    start = _time_field("Start time", "24-hour time, e.g. 09:00. Classes may begin at this time.")
    end = _time_field("End time", "Meetings must finish by this time.")
    spacing = forms.IntegerField(
        label="Spacing (minutes)",
        min_value=1,
        help_text="Minutes between possible start times inside the block, e.g. 60.",
    )

    # Hand the controller plain "HH:MM" strings, which is what TimeBlock wants.
    def clean_start(self):
        return self.cleaned_data["start"].strftime("%H:%M")

    def clean_end(self):
        return self.cleaned_data["end"].strftime("%H:%M")


class AddTimeBlockForm(TimeBlockFieldsForm):
    day = forms.ChoiceField(
        label="Day",
        choices=[(code, f"{name} ({code})") for code, name in DAY_NAMES.items()],
    )
    field_order = ["day", "start", "end", "spacing"]


class TimingOptionsForm(forms.Form):
    """Global timing options (Section 7). How the library applies them is
    documented by the scheduler library, so help text stays generic."""

    max_time_gap = forms.IntegerField(
        label="Maximum time gap (minutes)",
        min_value=0,
        help_text="Global scheduler timing option; see the scheduler library documentation.",
    )
    min_time_overlap = forms.IntegerField(
        label="Minimum time overlap (minutes)",
        min_value=0,
        help_text="Global scheduler timing option; see the scheduler library documentation.",
    )



class ConfirmReplaceMixin:
    """Adds a "confirm_replace" checkbox that must be ticked, but only when
    submitting the form would replace or discard something (Sections 8, 17).

    Use it for any action that overwrites data: loading schedules over the
    current ones, loading a configuration over unsaved changes, etc. Call
    require_confirmation() from the form's __init__; when `needed` is False
    the checkbox is not added at all, so nothing extra is shown.

        class ConfigLoadForm(ConfirmReplaceMixin, forms.Form):
            config_file = forms.FileField(label="Configuration JSON file")

            def __init__(self, *args, has_unsaved_changes=False, **kwargs):
                super().__init__(*args, **kwargs)
                self.require_confirmation(
                    has_unsaved_changes,
                    label="Discard my unsaved changes",
                    error="Tick this box to confirm discarding your unsaved changes.",
                )
    """

    confirm_field = "confirm_replace"

    def require_confirmation(self, needed: bool, *, label: str, error: str, help_text: str = ""):
        self._confirm_error = error if needed else None
        if needed:
            self.fields[self.confirm_field] = forms.BooleanField(
                required=False, label=label, help_text=help_text
            )

    def clean_confirm_replace(self):
        confirmed = self.cleaned_data.get(self.confirm_field)
        if getattr(self, "_confirm_error", None) and not confirmed:
            raise forms.ValidationError(self._confirm_error)
        return confirmed


class ScheduleImportForm(ConfirmReplaceMixin, forms.Form):
    """Schedule Viewer: load schedules from a JSON file (Section 17).

    Only checks that a file was chosen and, when schedules are already
    loaded, that the user agreed to replace them. Whether the file is a
    usable schedule file is decided by app.schedule_io via the controller.
    """

    schedule_file = forms.FileField(
        label="Schedule JSON file",
        help_text="A .json file exported from the Schedule Viewer, holding one schedule or a full set.",
        widget=forms.ClearableFileInput(attrs={"accept": ".json,application/json"}),
    )

    def __init__(self, *args, schedule_count=0, **kwargs):
        super().__init__(*args, **kwargs)
        self.require_confirmation(
            bool(schedule_count),
            label=f"Replace the {schedule_count} schedule(s) currently loaded",
            help_text="Loading a file replaces the schedules in the viewer. Export them first to keep them.",
            error="Tick this box to confirm replacing the schedules that are loaded now.",
        )


class ScheduleExportForm(forms.Form):
    """Schedule Viewer: which schedule to export (Section 18).

    Submitted with GET, since exporting changes nothing. `schedule` is the
    1-based number the user sees ("Schedule 2 of 5"); cleaned_data["index"]
    is the 0-based index the controller takes. Pass initial={"schedule": n}
    to preselect the schedule currently shown in the viewer.
    """

    schedule = forms.TypedChoiceField(
        label="Schedule",
        coerce=int,
        help_text="The schedule to save as a JSON file you can load back into the viewer later.",
    )

    def __init__(self, *args, schedule_count=0, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["schedule"].choices = [
            (number, f"Schedule {number} of {schedule_count}") for number in range(1, schedule_count + 1)
        ]

    def clean(self):
        cleaned = super().clean()
        if "schedule" in cleaned:
            cleaned["index"] = cleaned["schedule"] - 1
        return cleaned
class ConfigNewForm(ConfirmReplaceMixin, forms.Form):
    """Configuration Editor: start a new configuration (Section 8).

    Has no inputs of its own. When starting over would discard unsaved
    changes (or loaded schedules), it shows a checkbox that must be ticked;
    `discard_note` says what would be lost, e.g. "your unsaved changes".
    """

    def __init__(self, *args, discard_note="", **kwargs):
        kwargs.setdefault("prefix", "new")  # keeps ids apart from the load form
        super().__init__(*args, **kwargs)
        self.require_confirmation(
            bool(discard_note),
            label=f"Discard {discard_note}",
            help_text="Starting a new configuration replaces the one you have now. Save it first to keep it.",
            error=f"Tick this box to confirm discarding {discard_note}.",
        )


class ConfigLoadForm(ConfirmReplaceMixin, forms.Form):
    """Configuration Editor: load a configuration from a JSON file (Section 8).

    Only checks that a file was chosen and, when there is something to lose,
    that the user agreed to discard it. Whether the file is a usable
    configuration is decided by the scheduler library via the controller.
    """

    config_file = forms.FileField(
        label="Configuration JSON file",
        help_text="A .json configuration file, such as one saved from this page.",
        widget=forms.ClearableFileInput(attrs={"accept": ".json,application/json"}),
    )

    def __init__(self, *args, discard_note="", **kwargs):
        kwargs.setdefault("prefix", "load")
        super().__init__(*args, **kwargs)
        self.require_confirmation(
            bool(discard_note),
            label=f"Discard {discard_note}",
            help_text="Loading a file replaces the configuration you have now. Save it first to keep it.",
            error=f"Tick this box to confirm discarding {discard_note}.",
        )


# ---------------------------------------------------------------------- #
#  Rooms and Labs (Section 7). The two have identical fields, so they share
#  one base class; the controllers (gui/controllers/rooms.py, labs.py) do the
#  real validation and the reference checks.
# ---------------------------------------------------------------------- #
_AVAILABILITY_LINE = re.compile(r"^(\w+)\s+(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$")


def parse_availability(text):
    """Turn the availability box into {"MON": [{"start": "09:00", "end": "17:00"}], ...}.

    One range per line, e.g. "MON 09:00-17:00"; a day may appear on several
    lines. Returns (times, problems). `times` is None when the box is blank,
    which means "available any time". Only the shape is checked here; whether
    a range is acceptable (end after start, etc.) is decided by the scheduler
    library through the controller.
    """
    times = {}
    problems = []
    for number, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        match = _AVAILABILITY_LINE.match(line)
        if not match:
            problems.append(f'Line {number} ("{line}") is not in the form MON 09:00-17:00.')
            continue
        day = match.group(1).upper()
        if day not in DAY_NAMES:
            problems.append(
                f"Line {number}: '{match.group(1)}' is not a weekday. Use one of: {', '.join(DAY_NAMES)}."
            )
            continue
        start_h, start_m, end_h, end_m = (int(part) for part in match.groups()[1:])
        if start_h > 23 or end_h > 23 or start_m > 59 or end_m > 59:
            problems.append(f"Line {number}: use 24-hour times such as 09:00 or 17:30.")
            continue
        times.setdefault(day, []).append(
            {"start": f"{start_h:02d}:{start_m:02d}", "end": f"{end_h:02d}:{end_m:02d}"}
        )
    return (times or None), problems


def availability_to_text(times):
    """The reverse of parse_availability, for filling the box when editing."""
    lines = []
    for day in DAY_NAMES:
        for block in (times or {}).get(day, []):
            lines.append(f"{day} {block['start']}-{block['end']}")
    return "\n".join(lines)


class _SpaceForm(forms.Form):
    name = forms.CharField(
        label="Name",
        help_text="Must be unique. It can only be changed while no course or faculty member uses it.",
    )
    capacity = forms.IntegerField(label="Capacity", min_value=1, help_text="Number of seats (a whole number).")
    features = forms.CharField(
        label="Features",
        required=False,
        help_text="Separated by commas, e.g. projector, whiteboard. Leave blank for none.",
    )
    times = forms.CharField(
        label="Availability",
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text=(
            "Leave blank if it is available at any time. Otherwise one range per line, "
            "e.g. MON 09:00-17:00 (24-hour times; a day can have several lines)."
        ),
    )

    def clean_times(self):
        times, problems = parse_availability(self.cleaned_data.get("times", ""))
        if problems:
            raise forms.ValidationError(problems)
        return times


class RoomForm(_SpaceForm):
    """Add or edit a room (Section 7, Rooms row)."""


class LabForm(_SpaceForm):
    """Add or edit a lab (Section 7, Labs row)."""


# ---------------------------------------------------------------------- #
#  Faculty (Section 7). Faculty availability uses the same plain-text
#  weekday/range input as rooms and labs, but a blank value means unavailable
#  every day rather than unrestricted. Preference fields are generated from
#  the resources that exist in the loaded configuration.
# ---------------------------------------------------------------------- #
MAX_WEEKDAYS = len(DAY_NAMES)
MAX_PREFERENCE_WEIGHT = 10


class FacultyForm(forms.Form):
    """Add or edit one FacultyConfig record.

    The static fields model one faculty member's workload and availability.
    __init__ adds optional 0-10 preference fields for each current course,
    room, and lab; clean() packs those values into the three dictionaries the
    scheduler model serializes in configuration JSON.
    """

    name = forms.CharField(
        label="Name",
        help_text="Must be unique. It can only be changed while no course lists this faculty member.",
    )
    minimum_credits = forms.IntegerField(
        label="Minimum credits",
        min_value=0,
        help_text="The least number of credit hours this faculty member must teach.",
    )
    maximum_credits = forms.IntegerField(
        label="Maximum credits",
        min_value=0,
        help_text="The most number of credit hours this faculty member may teach.",
    )
    unique_course_limit = forms.IntegerField(
        label="Unique course limit",
        min_value=1,
        help_text="Maximum number of different course IDs this faculty member may teach.",
    )
    maximum_days = forms.IntegerField(
        label="Maximum teaching days",
        min_value=0,
        max_value=MAX_WEEKDAYS,
        initial=MAX_WEEKDAYS,
        help_text="Maximum number of weekdays this faculty member may teach.",
    )
    times = forms.CharField(
        label="Availability",
        required=False,
        widget=forms.Textarea(attrs={"rows": MAX_WEEKDAYS}),
        help_text=(
            "One range per line, e.g. MON 09:00-17:00. Leave blank when this faculty member "
            "is unavailable every day."
        ),
    )
    mandatory_days = forms.MultipleChoiceField(
        label="Mandatory teaching days",
        required=False,
        choices=[(code, f"{name} ({code})") for code, name in DAY_NAMES.items()],
        widget=forms.CheckboxSelectMultiple,
        help_text="Days this faculty member must teach. Each selected day must have availability above.",
    )

    def __init__(self, *args, course_names=(), room_names=(), lab_names=(), **kwargs):
        initial = dict(kwargs.get("initial") or {})
        super().__init__(*args, **kwargs)
        self._add_preference_fields(
            "course",
            "Course preference",
            course_names,
            initial.get("course_preferences") or {},
        )
        self._add_preference_fields(
            "room",
            "Room preference",
            room_names,
            initial.get("room_preferences") or {},
        )
        self._add_preference_fields(
            "lab",
            "Lab preference",
            lab_names,
            initial.get("lab_preferences") or {},
        )

    def _add_preference_fields(self, kind, label, names, values):
        """Add stable field names so arbitrary resource labels stay data, not HTML IDs."""
        for index, name in enumerate(sorted(set(names))):
            field_name = f"{kind}_preference_{index}"
            self.fields[field_name] = forms.IntegerField(
                label=f"{label}: {name}",
                required=False,
                min_value=0,
                max_value=MAX_PREFERENCE_WEIGHT,
                initial=values.get(name),
                help_text="Leave blank for no preference.",
            )
            self.fields[field_name].resource_name = name
            self.fields[field_name].preference_kind = kind

    def clean_times(self):
        times, problems = parse_availability(self.cleaned_data.get("times", ""))
        if problems:
            raise forms.ValidationError(problems)
        # Unlike a room/lab, a faculty record requires a times mapping. Empty
        # availability means unavailable, which is represented by an empty map.
        return times or {}

    def clean(self):
        cleaned = super().clean()
        for kind in ("course", "room", "lab"):
            preferences = {}
            prefix = f"{kind}_preference_"
            for field_name, field in self.fields.items():
                if not field_name.startswith(prefix):
                    continue
                weight = cleaned.get(field_name)
                if weight is not None:
                    preferences[field.resource_name] = weight
            cleaned[f"{kind}_preferences"] = preferences
        return cleaned


# ---------------------------------------------------------------------- #
#  Courses (Section 7). Resource and reference fields are populated from the
#  active configuration by the Course controller. The controller verifies the
#  complete configuration before committing a CourseConfig.
# ---------------------------------------------------------------------- #
COURSE_MODALITY_CHOICES = [
    ("in_person", "In person"),
    ("online", "Online"),
    ("hybrid", "Hybrid"),
]


class CourseForm(forms.Form):
    """Add or edit one CourseConfig record.

    The constructor receives names from the controller instead of reading
    scheduler models in the view. That keeps the form responsible only for
    user input shape while the controller owns cross-record validation.
    """

    course_id = forms.CharField(
        label="Course ID",
        help_text="Base identifier, such as CMSC 420. Repeated IDs create separate sections.",
    )
    section_id = forms.CharField(
        label="Section ID",
        required=False,
        help_text="Optional suffix, such as 01. Leave blank to number by input order.",
    )
    credits = forms.IntegerField(label="Credits", min_value=1, help_text="Credit hours for this section.")
    capacity = forms.IntegerField(
        label="Expected enrollment",
        min_value=1,
        help_text="Students expected in this section; assigned rooms and labs must accommodate it.",
    )
    modality = forms.ChoiceField(
        label="Modality",
        choices=COURSE_MODALITY_CHOICES,
        initial="in_person",
        help_text="Required delivery composition for the selected class pattern.",
    )
    room = forms.MultipleChoiceField(
        label="Candidate rooms",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Rooms the scheduler may use for lecture meetings.",
    )
    lab = forms.MultipleChoiceField(
        label="Candidate labs",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Labs the scheduler may use. Leave blank when the section has no lab meeting.",
    )
    conflicts = forms.MultipleChoiceField(
        label="Conflicting courses",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Sections of these course IDs cannot overlap with this section.",
    )
    faculty = forms.MultipleChoiceField(
        label="Faculty candidates",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Leave blank to derive candidates from faculty course preferences.",
    )
    required_room_features = forms.CharField(
        label="Required room features",
        required=False,
        help_text="Separate feature tags with commas. Leave blank when none are required.",
    )
    required_lab_features = forms.CharField(
        label="Required lab features",
        required=False,
        help_text="Separate feature tags with commas. Leave blank when none are required.",
    )
    reserve_room_during_lab = forms.BooleanField(
        label="Reserve the lecture room during lab meetings",
        required=False,
        initial=True,
        help_text="Keep the selected lecture room occupied while this section's lab meets.",
    )

    def __init__(self, *args, course_names=(), room_names=(), lab_names=(), faculty_names=(), **kwargs):
        """Populate checkbox choices from plain controller-provided names."""
        super().__init__(*args, **kwargs)
        self.fields["room"].choices = [(name, name) for name in sorted(set(room_names))]
        self.fields["lab"].choices = [(name, name) for name in sorted(set(lab_names))]
        self.fields["conflicts"].choices = [(name, name) for name in sorted(set(course_names))]
        self.fields["faculty"].choices = [(name, name) for name in sorted(set(faculty_names))]

    def clean_section_id(self):
        """Use None for automatic section numbering, as required by CourseConfig."""
        return self.cleaned_data["section_id"].strip() or None

    def clean_faculty(self):
        """An empty candidate list means the scheduler derives faculty choices."""
        return self.cleaned_data["faculty"] or None


# ---------------------------------------------------------------------- #
#  Class Patterns and Meetings (Section 7). Forms only check shape (a whole
#  number, a real time, a listed choice); the controllers
#  (gui/controllers/patterns.py, meetings.py) and the scheduler library decide
#  whether the values are acceptable.
# ---------------------------------------------------------------------- #
# The three delivery modes the scheduler's Meeting accepts (same list the
# command-line shell offers in app/commands/meetings.py).
DELIVERY_CHOICES = [("in_person", "In person"), ("online", "Online"), ("hybrid", "Hybrid")]


def _optional_time_field(label: str, help_text: str) -> forms.TimeField:
    return forms.TimeField(
        label=label,
        required=False,
        help_text=help_text,
        input_formats=_TIME_FORMATS,
        widget=forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
    )


def _time_or_none(value):
    """Hand the controller "HH:MM" or None, which is what the library wants."""
    return value.strftime("%H:%M") if value else None


def _day_field() -> forms.ChoiceField:
    return forms.ChoiceField(
        label="Day",
        choices=[(code, f"{name} ({code})") for code, name in DAY_NAMES.items()],
    )


def _duration_field() -> forms.IntegerField:
    return forms.IntegerField(
        label="Duration (minutes)",
        min_value=1,
        help_text="Length of one meeting, in whole minutes, e.g. 50.",
    )


def _lab_field() -> forms.BooleanField:
    return forms.BooleanField(
        label="Lab meeting",
        required=False,
        help_text="Tick if this meeting takes place in a lab instead of a room.",
    )


def _delivery_field() -> forms.ChoiceField:
    return forms.ChoiceField(label="Delivery mode", choices=DELIVERY_CHOICES, initial="in_person")


_MEETING_START_HELP = "Optional. Leave blank to let the scheduler choose; otherwise a 24-hour time such as 09:00."


class MeetingFieldsForm(forms.Form):
    """day / duration / lab / delivery / start_time -- used as-is for editing a
    meeting (its pattern is fixed by the URL) and as the base of the add form."""

    day = _day_field()
    duration = _duration_field()
    lab = _lab_field()
    delivery = _delivery_field()
    start_time = _optional_time_field("Fixed start time", _MEETING_START_HELP)

    def clean_start_time(self):
        return _time_or_none(self.cleaned_data.get("start_time"))


class AddMeetingForm(MeetingFieldsForm):
    """Add a meeting: first choose which class pattern it belongs to."""

    pattern = forms.TypedChoiceField(
        label="Class pattern",
        coerce=int,
        choices=[],
        help_text="The meeting is added to this pattern.",
    )
    field_order = ["pattern", "day", "duration", "lab", "delivery", "start_time"]

    def __init__(self, *args, pattern_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pattern"].choices = list(pattern_choices)


class ClassPatternFieldsForm(forms.Form):
    """credits / start_time / enabled -- a pattern's own fields. Its meetings are
    managed on the Meetings page, so editing a pattern keeps them."""

    credits = forms.IntegerField(
        label="Credits",
        min_value=1,
        help_text="Credit hours this pattern is used for (a positive whole number).",
    )
    start_time = _optional_time_field(
        "Fixed start time",
        "Optional. Leave blank to let the scheduler choose; otherwise a 24-hour time such as 16:00.",
    )
    enabled = forms.BooleanField(
        label="Enabled",
        required=False,
        initial=True,
        help_text="Untick to keep the pattern but leave it out of scheduling.",
    )

    def clean_start_time(self):
        return _time_or_none(self.cleaned_data.get("start_time"))


class AddClassPatternForm(ClassPatternFieldsForm):
    """Add a class pattern. A pattern needs at least one meeting, so the form
    also asks for the first one (more can be added on the Meetings page)."""

    meeting_day = _day_field()
    meeting_duration = _duration_field()
    meeting_lab = _lab_field()
    meeting_delivery = _delivery_field()
    meeting_start_time = _optional_time_field("First meeting: fixed start time", _MEETING_START_HELP)

    field_order = [
        "credits",
        "start_time",
        "enabled",
        "meeting_day",
        "meeting_duration",
        "meeting_lab",
        "meeting_delivery",
        "meeting_start_time",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Say which fields describe the first meeting.
        for name in ("meeting_day", "meeting_duration", "meeting_lab", "meeting_delivery"):
            self.fields[name].label = f"First meeting: {self.fields[name].label[0].lower()}{self.fields[name].label[1:]}"

    def clean_meeting_start_time(self):
        return _time_or_none(self.cleaned_data.get("meeting_start_time"))


# ---------------------------------------------------------------------- #
#  Global Settings (Section 7): the saved generation limit and optimizer
#  flags. The Schedule Generator's one-run overrides (Section 14) will get
#  their own form so they can never touch the saved configuration.
# ---------------------------------------------------------------------- #
class GlobalSettingsForm(forms.Form):
    """Generation limit plus one checkbox per optimizer flag. The checked boxes
    become the enabled flags; unchecked ones are turned off."""

    limit = forms.IntegerField(
        label="Generation limit",
        min_value=1,
        help_text="The most schedules the scheduler will generate in one run (a positive whole number).",
    )
    optimizer_flags = forms.MultipleChoiceField(
        label="Optimizer flags",
        required=False,
        choices=[],
        widget=forms.CheckboxSelectMultiple,
        help_text=(
            "Tick the optimizations to turn on. What each one does is defined by the "
            "scheduler library; see its documentation."
        ),
    )

    def __init__(self, *args, flag_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["optimizer_flags"].choices = [(flag, flag) for flag in flag_choices]
