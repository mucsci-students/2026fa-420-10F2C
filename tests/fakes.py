"""
Small stand-ins for the scheduler library's configuration, for tests of the
model layer (history, mementos, session) that need no library.

FakeConfig has the same shape as CombinedConfig: rooms, labs, courses and
faculty under `.config`, class patterns and time blocks under
`.time_slot_config`, and `limit` / `optimizer_flags` at the top. Like the real
one it has edit_mode(): a context manager that yields a deep copy, and copies
it back only when the block finishes without an error.
"""

import contextlib
import copy
from types import SimpleNamespace


class Record:
    """Stand-in for a Pydantic record: built from keyword fields, equal when its fields are."""

    def __init__(self, **fields):
        self.__dict__.update(fields)

    def __eq__(self, other):
        return isinstance(other, Record) and self.__dict__ == other.__dict__

    __hash__ = None

    def __repr__(self):
        return f"Record({self.__dict__!r})"


def room(name, capacity=10):
    return Record(name=name, capacity=capacity)


def course(course_id, section_id=None, **fields):
    return Record(course_id=course_id, section_id=section_id, **fields)


class FakeConfig:
    def __init__(
        self,
        rooms=(),
        labs=(),
        courses=(),
        faculty=(),
        classes=(),
        times=None,
        limit=10,
        optimizer_flags=(),
    ):
        self.config = SimpleNamespace(
            rooms=list(rooms),
            labs=list(labs),
            courses=list(courses),
            faculty=list(faculty),
        )
        self.time_slot_config = SimpleNamespace(
            classes=list(classes), times=dict(times or {}), max_time_gap=30
        )
        self.limit = limit
        self.optimizer_flags = list(optimizer_flags)
        self.refuse_edits = False  # set True to make edit_mode reject whatever was done

    @contextlib.contextmanager
    def edit_mode(self):
        draft = copy.deepcopy(self)
        yield draft
        if self.refuse_edits:
            raise ValueError("the configuration is not valid")
        self.config = draft.config
        self.time_slot_config = draft.time_slot_config
        self.limit = draft.limit
        self.optimizer_flags = draft.optimizer_flags
