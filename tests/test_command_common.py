from app.commands import common


def test_prompt_resource_availability_without_restriction(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "n")

    assert common.prompt_resource_availability("room") is None


def test_prompt_resource_availability_parses_weekdays_and_skips_invalid_input(
    monkeypatch, capsys
):
    responses = iter(("yes", "09:00-17:00", "", "invalid", "13:00-15:00", ""))
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    assert common.prompt_resource_availability("lab") == {
        "MON": [{"start": "09:00", "end": "17:00"}],
        "THU": [{"start": "13:00", "end": "15:00"}],
    }
    assert "isn't a valid HH:MM-HH:MM range" in capsys.readouterr().out
