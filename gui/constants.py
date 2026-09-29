"""
Small constants shared by GUI forms, controllers, and views.

Kept free of Django and scheduler imports so any layer can use them.
"""

# Weekday codes are the scheduler library's own ("MON".."FRI"); the dict keeps
# them in display order (Python dicts preserve insertion order).
DAY_NAMES = {
    "MON": "Monday",
    "TUE": "Tuesday",
    "WED": "Wednesday",
    "THU": "Thursday",
    "FRI": "Friday",
}
