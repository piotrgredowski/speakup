from __future__ import annotations

import json

from .conftest import run_cli


def test_cli_given_debug_logging_then_emits_service_lifecycle_logs(base_config, env_with_fake_audio) -> None:
    result = run_cli(
        [
            "--config",
            str(base_config),
            "--message",
            "Build completed successfully",
            "--event",
            "final",
            "--log-level",
            "DEBUG",
        ],
        env=env_with_fake_audio,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"

    stderr = result.stderr
    assert "notify_received" in stderr
    assert "summarizer_selected" in stderr
    assert "tts_selected" in stderr
    assert "notify_completed" in stderr


def test_cli_given_json_logging_then_does_not_raise_serializer_default_conflict(base_config, env_with_fake_audio) -> None:
    result = run_cli(
        [
            "--config",
            str(base_config),
            "--message",
            "Build completed successfully",
            "--event",
            "final",
            "--log-level",
            "DEBUG",
            "--log-format",
            "json",
        ],
        env=env_with_fake_audio,
    )

    assert result.returncode == 0
    assert "TypeError: json.dumps() got multiple values for keyword argument 'default'" not in result.stderr
