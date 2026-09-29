"""
Tests for gui/controllers/errors.py -- the shared translation of scheduler
library failures into messages a user can act on (Sprint 2 Section 10).

These run against the REAL scheduler library (no fakes), so they also pin down
the error types the friendly messages depend on. If a library upgrade renames
one of these types, a test here fails instead of users seeing raw Pydantic text.
"""

import pytest
from scheduler.config import TimeBlock, ValidationError

from app.crud import ValidationFailure, apply_edit
from app.session import ConfigError, Session
from gui.controllers.errors import (
    ControllerError,
    FieldError,
    to_controller_error,
    translate_validation_error,
)

EXAMPLE = "app/examples/config_example.json"
FIELDS = ("start", "end", "spacing")


def block_error(**kwargs):
    with pytest.raises(ValidationError) as info:
        TimeBlock(**kwargs)
    return info.value


def test_end_not_after_start_is_attached_to_end_field():
    result = translate_validation_error(block_error(start="15:00", spacing=60, end="09:00"), FIELDS)
    assert result[0].field == "end"
    assert "later than the start" in result[0].message


def test_bad_time_format_is_attached_to_start_field_in_plain_language():
    result = translate_validation_error(block_error(start="25:00", spacing=60, end="26:00"), FIELDS)
    assert "start" in {item.field for item in result}
    assert all("pattern" not in item.message for item in result)  # no raw regex text


def test_zero_spacing_is_attached_to_spacing_field():
    result = translate_validation_error(block_error(start="09:00", spacing=0, end="10:00"), FIELDS)
    assert result[0].field == "spacing"
    assert "greater than 0" in result[0].message


def test_unlisted_field_becomes_a_form_level_error():
    result = translate_validation_error(block_error(start="15:00", spacing=60, end="09:00"), form_fields=())
    assert result[0].field is None


def test_failed_whole_config_edit_is_translated_and_names_the_day():
    session = Session()
    session.load(EXAMPLE)

    def empty_monday(draft):
        draft.time_slot_config.times["MON"] = []

    with pytest.raises(ValidationFailure) as info:
        apply_edit(session.config, "timeslot", empty_monday)

    result = translate_validation_error(info.value, FIELDS)
    assert result == [FieldError(None, "MON needs at least one time block.")]


def test_non_pydantic_exception_falls_back_to_its_text():
    assert translate_validation_error(ValueError("boom")) == [FieldError(None, "boom")]


def test_controller_error_accepts_a_plain_string():
    error = ControllerError("Something went wrong.")
    assert error.errors == [FieldError(None, "Something went wrong.")]
    assert error.message == "Something went wrong."


def test_to_controller_error_handles_config_errors_and_passes_controller_errors_through():
    assert to_controller_error(ConfigError("No configuration loaded.")).message == "No configuration loaded."
    original = ControllerError("x")
    assert to_controller_error(original) is original
