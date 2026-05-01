from __future__ import annotations

import json

from .conftest import run_cli


def test_cli_self_test_given_fake_audio_then_returns_ok(base_config, env_with_fake_audio: dict[str, str]) -> None:
    sound_path = base_config.parent / "ping.aiff"
    sound_path.write_text("ping")
    config = json.loads(base_config.read_text())
    config["event_sounds"]["files"] = {"info": str(sound_path)}
    base_config.write_text(json.dumps(config))

    result = run_cli(["self-test", "--config", str(base_config)], env=env_with_fake_audio)
    assert result.returncode == 0

    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["checks"]["event_sound"]["ok"] is True
    assert payload["checks"]["event_sound"]["path"] == str(sound_path)
