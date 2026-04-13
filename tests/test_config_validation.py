from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from speakup.config import Config, ConfigValidationError, default_config, get_default_log_file_path


def test_config_load_given_valid_default_then_succeeds(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = Config.load(None)
    assert cfg.get("privacy", "mode") == "prefer_local"


def test_default_config_runtime_paths_use_system_temp_dir() -> None:
    cfg = default_config()
    temp_root = tempfile.gettempdir()
    assert cfg["tts"]["save_audio_dir"].startswith(temp_root)
    assert cfg["dedup"]["cache_file"].startswith(temp_root)
    assert Path(cfg["logging"]["file_path"]) == get_default_log_file_path()


def test_default_config_prefers_omlx_then_elevenlabs_then_openai_for_tts() -> None:
    cfg = default_config()
    assert cfg["tts"]["provider_order"] == ["omlx", "elevenlabs", "openai", "gemini", "lmstudio", "macos"]


def test_default_config_prefers_cerebras_then_omlx_then_openai_for_summarization() -> None:
    cfg = default_config()
    assert cfg["summarization"]["provider_order"][:3] == ["cerebras", "omlx", "openai"]


@pytest.mark.parametrize(
    "mutator,expected",
    [
        (lambda c: c.setdefault("playback", {}).update({"queue_enabled": "yes"}), "playback.queue_enabled"),
        (lambda c: c["privacy"].update({"mode": "remote_only"}), "privacy.mode"),
        (lambda c: c["tts"].update({"audio_format": "flac"}), "tts.audio_format"),
        (lambda c: c["tts"].update({"play_audio": "yes"}), "tts.play_audio"),
        (lambda c: c["summarization"].update({"provider_order": ["rule_based", "x"]}), "summarization.provider_order"),
        (lambda c: c["event_sounds"]["files"].update({"unknown": "x"}), "event_sounds.files key 'unknown' must be one of"),
        (lambda c: c["dedup"].update({"window_seconds": 0}), "dedup.window_seconds"),
        (lambda c: c.setdefault("logging", {}).update({"level": "TRACE"}), "logging.level"),
        (lambda c: c.setdefault("logging", {}).update({"destination": "console"}), "logging.destination"),
        (lambda c: c.setdefault("fallback", {}).update({"fail_fast": "yes"}), "fallback.fail_fast"),
        (lambda c: c.setdefault("providers", {}).setdefault("command_summary", {}).update({"args": "-p {message}"}), "providers.command_summary.args"),
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


def test_config_load_given_jsonc_comments_then_parses_successfully(tmp_path: Path) -> None:
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(
        """{
  // comment
  "privacy": {"mode": "local_only", "allow_remote_fallback": false},
  /* block comment */
  "events": {"speak_on_final": true, "speak_on_error": true, "speak_on_needs_input": true, "speak_on_progress": true},
  "summarization": {"max_chars": 123, "provider_order": ["rule_based"]},
  "event_sounds": {"enabled": true, "files": {}},
  "tts": {"provider_order": ["macos"], "voice": "default", "speed": 1.0, "audio_format": "mp3", "save_audio_dir": ".cache/audio"},
  "dedup": {"enabled": true, "window_seconds": 30, "cache_file": ".cache/last_progress.json"},
  "providers": {"lmstudio": {}, "elevenlabs": {}, "openai": {}}
}
"""
    )

    loaded = Config.load(config_path)

    assert loaded.get("privacy", "mode") == "local_only"
