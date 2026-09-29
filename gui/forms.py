"""
Django Forms for each configuration area (Section 7). Client-side/form
validation here is for usability only (Section 3) -- CombinedConfig via
app.crud.apply_edit remains the real source of truth, so forms only check
shape (a real time, a whole number) and leave rules like "end after start"
to the scheduler library.

Done:
    - AddTimeBlockForm / TimeBlockFieldsForm / TimingOptionsForm (time slots)

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
