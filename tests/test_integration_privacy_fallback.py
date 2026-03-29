from __future__ import annotations

import json
from pathlib import Path
import stat

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
    config["tts"]["provider_order"] = ["kokoro"]
    config.setdefault("providers", {}).setdefault("kokoro", {})["voice"] = "invalid_voice"
    config_path = tmp_path / "config_fail.json"
    config_path.write_text(json.dumps(config))

    result = run_cli(["--config", str(config_path), "--message", "Task complete", "--event", "final"], env=env_with_fake_audio)
    assert result.returncode == 0

    payload = json.loads(result.stdout)
    assert payload["status"] == "degraded_text_only"
    assert payload["played"] is False
    assert payload["backend"] == "none"


def test_cli_given_kokoro_cli_failure_then_falls_back_to_macos(tmp_path: Path, base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    kokoro_script = bin_dir / "kokoro"
    kokoro_script.write_text("#!/bin/sh\necho 'kokoro failed' >&2\nexit 3\n")
    kokoro_script.chmod(kokoro_script.stat().st_mode | stat.S_IEXEC)

    env = dict(env_with_fake_audio)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

    config = json.loads(base_config.read_text())
    config["tts"]["provider_order"] = ["kokoro_cli", "macos"]
    config.setdefault("providers", {})["kokoro_cli"] = {
        "command": "kokoro",
        "args": ["--output", "{output}", "--voice", "{voice}", "--speed", "{speed}", "{text}"],
        "timeout_seconds": 10,
    }
    config_path = tmp_path / "config_kokoro_cli_fallback.json"
    config_path.write_text(json.dumps(config))

    result = run_cli(["--config", str(config_path), "--message", "All done", "--event", "final"], env=env)
    assert result.returncode == 0

    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["backend"] == "macos"
