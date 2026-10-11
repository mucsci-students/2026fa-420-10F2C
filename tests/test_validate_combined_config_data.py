"""Tests for validate_combined_config_data (Sprint 2 Sections 3, 10, 23.1)."""

import json
from pathlib import Path

import pytest
from scheduler.config import CombinedConfig, ValidationError

from app.commands.configuration import revalidate, validate_combined_config_data
from app.session import Session

EXAMPLE = "app/examples/config_example.json"


def example_data() -> dict:
    return json.loads(Path(EXAMPLE).read_text(encoding="utf-8"))


def test_valid_data_returns_a_combined_config():
    result = validate_combined_config_data(example_data())
    assert isinstance(result, CombinedConfig)
    assert len(result.config.rooms) == 3


def test_schema_invalid_data_is_rejected():
    data = example_data()
    data["config"]["rooms"] = []
    with pytest.raises(ValidationError):
        validate_combined_config_data(data)


def test_missing_sections_are_rejected():
    with pytest.raises(ValidationError):
        validate_combined_config_data({})


def test_validation_does_not_modify_the_input():
    data = example_data()
    before = json.dumps(data, sort_keys=True)
    validate_combined_config_data(data)
    assert json.dumps(data, sort_keys=True) == before


def test_revalidate_passes_for_a_valid_session():
    session = Session()
    session.load(EXAMPLE)
    assert revalidate(session) is None


def test_revalidate_reports_an_invalid_config_without_changing_it():
    session = Session()
    session.load(EXAMPLE)
    session.config.config.rooms.clear()  # bypasses edit mode on purpose
    assert revalidate(session) is not None
    assert session.config.config.rooms == []  # reported, not repaired