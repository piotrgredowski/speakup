from __future__ import annotations

import json
import tempfile

import pytest

from let_me_know_agent.config import Config, ConfigValidationError, default_config


def test_config_load_given_valid_default_then_succeeds() -> None:
    cfg = Config.load(None)
    assert cfg.get("privacy", "mode") == "prefer_local"


def test_default_config_runtime_paths_use_system_temp_dir() -> None:
    cfg = default_config()
    temp_root = tempfile.gettempdir()
    assert cfg["tts"]["save_audio_dir"].startswith(temp_root)
    assert cfg["dedup"]["cache_file"].startswith(temp_root)


def test_default_config_prefers_kokoro_cli_before_macos() -> None:
    cfg = default_config()
    assert cfg["tts"]["provider_order"][:2] == ["kokoro_cli", "macos"]


@pytest.mark.parametrize(
    "mutator,expected",
    [
        (lambda c: c["privacy"].update({"mode": "remote_only"}), "privacy.mode"),
        (lambda c: c["tts"].update({"audio_format": "flac"}), "tts.audio_format"),
        (lambda c: c["tts"].update({"play_audio": "yes"}), "tts.play_audio"),
        (lambda c: c["summarization"].update({"provider_order": ["rule_based", "x"]}), "summarization.provider_order"),
        (lambda c: c["event_sounds"]["files"].update({"unknown": "x"}), "event_sounds.files has unknown event key"),
        (lambda c: c["dedup"].update({"window_seconds": 0}), "dedup.window_seconds"),
        (lambda c: c.setdefault("logging", {}).update({"level": "TRACE"}), "logging.level"),
        (lambda c: c.setdefault("logging", {}).update({"destination": "stdout"}), "logging.destination"),
    ],
)
def test_config_load_given_invalid_shape_then_raises(mutator, expected, tmp_path) -> None:
    config = default_config()
    mutator(config)
    config_path = tmp_path / "bad.json"
    config_path.write_text(json.dumps(config))

    with pytest.raises(ConfigValidationError) as exc:
        Config.load(config_path)

    assert expected in str(exc.value)
