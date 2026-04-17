from __future__ import annotations

import json
from pathlib import Path

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
    assert ("summarizer_selected" in stderr) or ("summarization_skipped_short_message" in stderr)
    assert "tts_selected" in stderr
    assert "voice=default" in stderr
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


def test_cli_given_json_file_logging_then_writes_colored_companion_log(base_config, tmp_path, env_with_fake_audio) -> None:
    config = json.loads(base_config.read_text())
    log_path = tmp_path / "logs" / "speakup.log"
    color_log_path = Path(f"{log_path}.color")
    config["logging"] = {
        "enabled": True,
        "level": "DEBUG",
        "format": "json",
        "destination": ["file"],
        "file_path": str(log_path),
        "rotate_max_bytes": 1_048_576,
        "rotate_backup_count": 3,
        "include_timestamps": False,
        "include_module": True,
    }
    base_config.write_text(json.dumps(config))

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
    plain_log = log_path.read_text()
    color_log = color_log_path.read_text()

    assert plain_log.lstrip().startswith('{"request_id":')
    assert '"event": "notify_completed"' in plain_log
    assert "\x1b[" in color_log
    assert "notify_completed" in color_log
    assert not color_log.lstrip().startswith("{")
