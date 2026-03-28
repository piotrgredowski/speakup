from __future__ import annotations

import json
from pathlib import Path

from .conftest import run_cli


def test_cli_given_local_only_mode_then_remote_tts_is_not_used(tmp_path: Path, base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    config = json.loads(base_config.read_text())
    config["privacy"] = {"mode": "local_only", "allow_remote_fallback": False}
    config["tts"]["provider_order"] = ["openai", "elevenlabs", "macos"]
    config_path = tmp_path / "config_local_only.json"
    config_path.write_text(json.dumps(config))

    result = run_cli(["--config", str(config_path), "--message", "All done", "--event", "final"], env=env_with_fake_audio)
    assert result.returncode == 0

    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["backend"] == "macos"


def test_cli_given_all_tts_failures_then_returns_degraded_text_only(tmp_path: Path, base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    config = json.loads(base_config.read_text())
    config["tts"]["provider_order"] = ["kokoro"]  # command missing by default in fake PATH
    config_path = tmp_path / "config_fail.json"
    config_path.write_text(json.dumps(config))

    result = run_cli(["--config", str(config_path), "--message", "Task complete", "--event", "final"], env=env_with_fake_audio)
    assert result.returncode == 0

    payload = json.loads(result.stdout)
    assert payload["status"] == "degraded_text_only"
    assert payload["played"] is False
    assert payload["backend"] == "none"
