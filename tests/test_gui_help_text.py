"""
Tests for help text and tooltips (Sprint 2 Sections 4 and 24; user story 53).

Story 53:
  * Tooltip: hovering over or focusing the "pack_rooms" option shows a short
    description of what it does.
  * Field hint: fields with a specific format, like time, show an example
    such as "09:00".

Every optimizer flag checkbox, in Global Settings and in the Schedule
Generator, gets its description three ways: as the checkbox's tooltip
(title), as a short line under it, and linked with aria-describedby so a
screen reader reads it when the checkbox gets keyboard focus.
"""

import re

import pytest

from app.commands.common import VALID_OPTIMIZER_FLAGS
from gui.constants import OPTIMIZER_FLAG_HELP, OPTIMIZER_FLAGS_INTRO
from gui.forms import GenerationOverrideForm, GlobalSettingsForm, OptimizerFlagsWidget

SETTINGS_URL = "/configuration/settings/"
GENERATOR_URL = "/generate/"
TIMESLOTS_URL = "/configuration/timeslots/"


def page(response) -> str:
    return response.content.decode()


def checkbox(html: str, flag: str) -> str:
    """The <input> tag of one optimizer-flag checkbox."""
    match = re.search(rf'<input[^>]*name="optimizer_flags"[^>]*value="{flag}"[^>]*>', html)
    if match is None:  # attribute order can differ
        match = re.search(rf'<input[^>]*value="{flag}"[^>]*name="optimizer_flags"[^>]*>', html)
    assert match, f"no checkbox for {flag}"
    return match.group(0)


# ---------------------------------------------------------------------- #
#  Descriptions
# ---------------------------------------------------------------------- #
def test_every_optimizer_flag_has_a_description():
    assert set(OPTIMIZER_FLAG_HELP) == set(VALID_OPTIMIZER_FLAGS)
    for flag, text in OPTIMIZER_FLAG_HELP.items():
        assert text.endswith("."), flag
        assert 20 < len(text) < 200, flag  # short, but more than a restated name


def test_descriptions_are_plain_language():
    for text in OPTIMIZER_FLAG_HELP.values():
        assert "_" not in text  # no code names like pack_rooms inside the explanation
        assert '"' not in text and "'" not in text  # safe inside a title="..." attribute


# ---------------------------------------------------------------------- #
#  Widget
# ---------------------------------------------------------------------- #
def test_widget_adds_tooltip_and_link_to_the_description():
    widget = OptimizerFlagsWidget(choices=[("pack_rooms", "pack_rooms")])
    html = widget.render("optimizer_flags", ["pack_rooms"], attrs={"id": "id_optimizer_flags"})
    text = OPTIMIZER_FLAG_HELP["pack_rooms"]
    assert f'title="{text}"' in html
    assert 'aria-describedby="id_optimizer_flags_0_help"' in html
    assert f'<span class="option-help" id="id_optimizer_flags_0_help">{text}</span>' in html
    assert "checked" in html  # still a normal checkbox


def test_unknown_flag_renders_without_a_description():
    widget = OptimizerFlagsWidget(choices=[("future_flag", "future_flag")])
    html = widget.render("optimizer_flags", [], attrs={"id": "id_optimizer_flags"})
    assert "future_flag" in html
    assert "option-help" not in html and "aria-describedby" not in html


@pytest.mark.parametrize("form_class", [GlobalSettingsForm, GenerationOverrideForm])
def test_both_forms_use_the_described_checkboxes(form_class):
    form = form_class(flag_choices=sorted(VALID_OPTIMIZER_FLAGS))
    assert isinstance(form.fields["optimizer_flags"].widget, OptimizerFlagsWidget)
    assert OPTIMIZER_FLAGS_INTRO in form.fields["optimizer_flags"].help_text


# ---------------------------------------------------------------------- #
#  Pages (story 53 scenarios)
# ---------------------------------------------------------------------- #
def test_story_53_pack_rooms_tooltip_in_global_settings(client):
    html = page(client.get(SETTINGS_URL))
    text = OPTIMIZER_FLAG_HELP["pack_rooms"]
    box = checkbox(html, "pack_rooms")
    assert f'title="{text}"' in box  # hover
    assert "aria-describedby=" in box  # keyboard focus + screen readers
    assert f'class="option-help"' in html and text in html  # also visible


@pytest.mark.parametrize("flag", sorted(VALID_OPTIMIZER_FLAGS))
def test_every_flag_is_described_in_global_settings(client, flag):
    html = page(client.get(SETTINGS_URL))
    assert f'title="{OPTIMIZER_FLAG_HELP[flag]}"' in checkbox(html, flag)


@pytest.mark.parametrize("flag", sorted(VALID_OPTIMIZER_FLAGS))
def test_every_flag_is_described_in_the_schedule_generator(client, flag):
    html = page(client.get(GENERATOR_URL))
    assert f'title="{OPTIMIZER_FLAG_HELP[flag]}"' in checkbox(html, flag)


def test_old_see_the_documentation_text_is_gone(client):
    assert "see its documentation" not in page(client.get(SETTINGS_URL))


def test_settings_still_save_with_the_new_checkboxes(client):
    client.get(SETTINGS_URL)
    response = client.post(
        "/configuration/settings/save/",
        {"limit": "10", "optimizer_flags": ["pack_rooms", "same_room"]},
        follow=True,
    )
    assert response.status_code == 200
    assert "Error:" not in page(response)


def test_story_53_time_fields_show_an_example(client):
    assert "e.g. 09:00" in page(client.get(TIMESLOTS_URL))
