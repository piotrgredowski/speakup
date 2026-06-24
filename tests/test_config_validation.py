from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from speakup.config import Config, ConfigValidationError, default_config, get_default_log_file_path
from speakup.service import build_registry_from_config


def test_config_load_given_valid_default_then_succeeds(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = Config.load(None)
    assert cfg.get("enabled") is True
    assert cfg.get("privacy", "mode") == "local_only"


def test_default_config_runtime_paths_use_system_temp_dir() -> None:
    cfg = default_config()
    temp_root = tempfile.gettempdir()
    assert cfg["tts"]["save_audio_dir"].startswith(temp_root)
    assert cfg["dedup"]["cache_file"].startswith(temp_root)
    assert Path(cfg["logging"]["file_path"]) == get_default_log_file_path()


def test_default_config_uses_local_omlx_tts_with_piper_and_macos_fallback() -> None:
    cfg = default_config()
    assert cfg["tts"]["provider_order"] == ["omlx", "piper", "macos"]
    assert cfg["providers"]["piper"]["model"] == "pl_PL-bass-high"


def test_config_load_given_edge_tts_provider_then_accepts_provider_order_and_override(tmp_path: Path) -> None:
    config = default_config()
    config["tts"]["provider_order"] = ["edge", "macos"]
    config["tts"]["project_overrides"] = {
        str(tmp_path): {"provider": "edge", "speed": 1.1}
    }
    config["providers"]["edge"] = {
        "voice": "en-US-AriaNeural",
        "title_voice": "en-US-GuyNeural",
        "message_voice": "en-US-JennyNeural",
        "available_voices": ["en-US-AriaNeural"],
    }
    config_path = tmp_path / "config_edge.json"
    config_path.write_text(json.dumps(config))

    loaded = Config.load(config_path)

    assert loaded.get("tts", "provider_order") == ["edge", "macos"]
    assert loaded.get("providers", "edge", "voice") == "en-US-AriaNeural"


def test_config_load_given_repository_config_then_accepts_absolute_path(tmp_path: Path) -> None:
    config = default_config()
    config["repositories"] = {
        str(tmp_path.resolve()): {
            "enabled": False,
            "summarization": {"provider_order": ["gemini"]},
            "tts": {"provider_order": ["edge"], "speed": 1.1},
            "providers": {"edge": {"voice": "en-US-AriaNeural"}},
        }
    }
    config_path = tmp_path / "config_repositories.json"
    config_path.write_text(json.dumps(config))

    loaded = Config.load(config_path)

    assert loaded.get("repositories", str(tmp_path.resolve()), "enabled") is False
    assert loaded.get("repositories", str(tmp_path.resolve()), "tts", "provider_order") == ["edge"]


def test_default_config_uses_local_omlx_summarization_with_rule_based_fallback() -> None:
    cfg = default_config()
    assert cfg["summarization"]["provider_order"] == ["omlx", "rule_based"]
    assert cfg["providers"]["omlx"]["summary_model"] == "unsloth/gemma-4-E4B-it-UD-MLX-4bit"
    assert cfg["privacy"]["allow_remote_fallback"] is False


def test_default_config_preserves_existing_dedup_behavior() -> None:
    cfg = default_config()
    assert cfg["dedup"]["mode"] == "duplicate"
    assert cfg["dedup"]["on_skip"] == "skip"


def test_default_config_includes_codex_integration_defaults() -> None:
    cfg = default_config()

    assert cfg["codex"] == {
        "enabled": True,
        "events": {
            "notification": True,
            "stop": True,
            "plan_approval": True,
        },
    }


def test_config_load_given_codex_overrides_then_accepts_shape(tmp_path: Path) -> None:
    config = default_config()
    config["codex"]["enabled"] = False
    config["codex"]["events"]["plan_approval"] = False
    config_path = tmp_path / "config_codex.json"
    config_path.write_text(json.dumps(config))

    loaded = Config.load(config_path)

    assert loaded.get("codex", "enabled") is False
    assert loaded.get("codex", "events", "plan_approval") is False


@pytest.mark.parametrize(
    "mutator,expected",
    [
        (lambda c: c.setdefault("playback", {}).update({"queue_enabled": "yes"}), "playback.queue_enabled"),
        (lambda c: c.update({"enabled": "yes"}), "enabled must be a boolean"),
        (lambda c: c["privacy"].update({"mode": "remote_only"}), "privacy.mode"),
        (lambda c: c["tts"].update({"audio_format": "flac"}), "tts.audio_format"),
        (lambda c: c["tts"].update({"play_audio": "yes"}), "tts.play_audio"),
        (lambda c: c["summarization"].update({"provider_order": ["rule_based", "x"]}), "summarization.provider_order"),
        (lambda c: c["event_sounds"]["files"].update({"unknown": "x"}), "event_sounds.files key 'unknown' must be one of"),
        (lambda c: c["dedup"].update({"window_seconds": 0}), "dedup.window_seconds"),
        (lambda c: c["dedup"].update({"mode": "always"}), "dedup.mode"),
        (lambda c: c["dedup"].update({"on_skip": "tts"}), "dedup.on_skip"),
        (lambda c: c["context_naming"].update({"source": "branch"}), "context_naming.source"),
        (lambda c: c.setdefault("logging", {}).update({"level": "TRACE"}), "logging.level"),
        (lambda c: c.setdefault("logging", {}).update({"destination": ["console"]}), "logging.destination[0]"),
        (lambda c: c.setdefault("fallback", {}).update({"fail_fast": "yes"}), "fallback.fail_fast"),
        (lambda c: c.setdefault("providers", {}).setdefault("command_summary", {}).update({"args": "-p {message}"}), "providers.command_summary.args"),
        (lambda c: c.setdefault("codex", {}).update({"enabled": "yes"}), "codex.enabled"),
        (lambda c: c.setdefault("codex", {}).setdefault("events", {}).update({"plan_approval": "yes"}), "codex.events.plan_approval"),
        (lambda c: c.setdefault("repositories", {}).update({"relative/path": {}}), "repositories key 'relative/path' must be an absolute path"),
        (lambda c: c.setdefault("repositories", {}).update({"/tmp/repo": {"enabled": "yes"}}), "repositories./tmp/repo.enabled must be a boolean"),
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


def test_config_load_given_partial_config_then_materializes_safe_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "partial.jsonc"
    config_path.write_text('{"tts": {"provider_order": ["openai"]}}')

    loaded = Config.load(config_path)

    assert loaded.get("privacy", "mode") == "local_only"
    assert loaded.get("privacy", "allow_remote_fallback") is False
    assert loaded.get("tts", "provider_order") == ["openai"]
    assert loaded.get("context_naming", "source") == "repository"


def test_config_load_given_legacy_omlx_summarizer_then_remains_loadable(tmp_path: Path) -> None:
    config = default_config()
    config["summarization"]["provider_order"] = ["omlx", "rule_based"]
    config_path = tmp_path / "legacy.jsonc"
    config_path.write_text(json.dumps(config))

    loaded = Config.load(config_path)

    assert loaded.get("summarization", "provider_order") == ["omlx", "rule_based"]


def test_config_load_given_omlx_for_summarization_and_tts_then_accepts_provider_config(tmp_path: Path) -> None:
    config = default_config()
    config["summarization"]["provider_order"] = ["omlx", "rule_based"]
    config["tts"]["provider_order"] = ["omlx"]
    config["providers"]["omlx"]["summary_model"] = "unsloth/gemma-4-E4B-it-UD-MLX-4bit"
    config["providers"]["omlx"]["model"] = "Kokoro-82M-bf16"
    config_path = tmp_path / "omlx.jsonc"
    config_path.write_text(json.dumps(config))

    loaded = Config.load(config_path)

    assert loaded.get("summarization", "provider_order") == ["omlx", "rule_based"]
    assert loaded.get("tts", "provider_order") == ["omlx"]
    assert loaded.get("providers", "omlx", "summary_model") == "unsloth/gemma-4-E4B-it-UD-MLX-4bit"
    assert loaded.get("providers", "omlx", "model") == "Kokoro-82M-bf16"


def test_build_registry_from_config_registers_omlx_summarizer(tmp_path: Path) -> None:
    config = default_config()
    config["summarization"]["provider_order"] = ["omlx", "rule_based"]
    config_path = tmp_path / "omlx.jsonc"
    config_path.write_text(json.dumps(config))

    registry = build_registry_from_config(Config.load(config_path))

    assert registry.has_summarizer("omlx") is True


def test_build_registry_from_config_registers_piper_tts(tmp_path: Path) -> None:
    config = default_config()
    config_path = tmp_path / "piper.jsonc"
    config_path.write_text(json.dumps(config))

    registry = build_registry_from_config(Config.load(config_path))

    assert registry.has_tts("piper") is True
