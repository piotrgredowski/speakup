from __future__ import annotations

import json

from .conftest import run_cli


def test_cli_self_test_given_fake_audio_then_returns_ok(base_config, env_with_fake_audio: dict[str, str]) -> None:
    result = run_cli(["self-test", "--config", str(base_config)], env=env_with_fake_audio)
    assert result.returncode == 0

    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["checks"]["event_sound"]["ok"] is True
    assert payload["checks"]["event_sound"]["path"] == "/System/Library/Sounds/Ping.aiff"
