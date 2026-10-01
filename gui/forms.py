"""
Django Forms for each configuration area (Section 7). Client-side/form
validation here is for usability only (Section 3) -- CombinedConfig via
app.crud.apply_edit remains the real source of truth, so forms only check
shape (a real time, a whole number) and leave rules like "end after start"
to the scheduler library.

Done:
    - AddTimeBlockForm / TimeBlockFieldsForm / TimingOptionsForm (time slots)
    - ScheduleImportForm (Schedule Viewer: load schedules from a JSON file)

TODO: one Form class per remaining area, matching the "Required editable data"
column in Section 7's table:
    - RoomForm            (name, capacity, features, availability)
    - LabForm             (name, capacity, features, availability)
    - CourseForm          (course/section id, credits, capacity, resources,
                            conflicts, faculty, modality, requirements)
    - FacultyForm         (workload limits, availability, mandatory days, preferences)
    - ClassPatternForm    (credits, enabled state, start times, meetings)
    - MeetingForm         (day, duration, lab designation, delivery mode, start time)
    - GlobalSettingsForm  (generation limit, optimizer flags)
    - GenerationOverrideForm  (Section 14: limit override + optimizer overrides,
                                for the Schedule Generator page, separate from
                                GlobalSettingsForm since these must NOT touch
                                the saved configuration)
"""

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
