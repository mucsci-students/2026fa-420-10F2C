"""
Helper for tests that compare a configuration before and after an undo.

The scheduler library keeps each faculty member's days (and similar fields) in
a set. Two configurations that are exactly equal can list such a set in a
different order in their JSON, because a set has no order. So tests compare the
JSON after putting every list of weekday names into week order.
"""

import json

_WEEK = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def canonical(text):
    """The parsed JSON with every list of weekday names in week order."""

    def fix(value):
        if isinstance(value, dict):
            return {key: fix(item) for key, item in value.items()}
        if isinstance(value, list):
            items = [fix(item) for item in value]
            if items and all(isinstance(item, str) and item in _WEEK for item in items):
                return sorted(items, key=_WEEK.index)
            return items
        return value

    return fix(json.loads(text))
