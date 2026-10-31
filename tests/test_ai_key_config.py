import pytest

from gui.ai import runner


def test_api_key_can_be_loaded_from_config_file(monkeypatch, tmp_path):
    key_file = tmp_path / "openai_api_key.txt"
    key_file.write_text("test-key-from-file\n", encoding="utf-8")
    monkeypatch.setattr(runner, "API_KEY_FILE", key_file)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    configured_runner = runner.LangChainRunner.from_environment()

    assert configured_runner.api_key == "test-key-from-file"


def test_environment_api_key_takes_precedence(monkeypatch, tmp_path):
    key_file = tmp_path / "openai_api_key.txt"
    key_file.write_text("test-key-from-file", encoding="utf-8")
    monkeypatch.setattr(runner, "API_KEY_FILE", key_file)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-from-environment")

    configured_runner = runner.LangChainRunner.from_environment()

    assert configured_runner.api_key == "test-key-from-environment"


def test_missing_api_key_names_both_setup_options(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "API_KEY_FILE", tmp_path / "missing.txt")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(runner.NotConfigured) as error:
        runner.LangChainRunner.from_environment()

    assert "OPENAI_API_KEY" in str(error.value)
    assert "config/openai_api_key.txt" in str(error.value)
