"""
Django Forms for each configuration area (Section 7). Client-side/form
validation here is for usability only (Section 3) -- CombinedConfig via
app.crud.apply_edit remains the real source of truth.

TODO: one Form class per area, matching the "Required editable data"
column in Section 7's table:
    - RoomForm            (name, capacity, features, availability)
    - LabForm             (name, capacity, features, availability)
    - CourseForm          (course/section id, credits, capacity, resources,
                            conflicts, faculty, modality, requirements)
    - FacultyForm         (workload limits, availability, mandatory days, preferences)
    - TimeSlotForm        (weekday time blocks, global timing options)
    - ClassPatternForm    (credits, enabled state, start times, meetings)
    - MeetingForm         (day, duration, lab designation, delivery mode, start time)
    - GlobalSettingsForm  (generation limit, optimizer flags)
    - GenerationOverrideForm  (Section 14: limit override + optimizer overrides,
                                for the Schedule Generator page, separate from
                                GlobalSettingsForm since these must NOT touch
                                the saved configuration)
"""
