from __future__ import annotations

import json
from pathlib import Path

from .conftest import run_pi_cli


def test_pi_wrapper_given_payload_on_stdin_then_returns_notify_result(base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    payload = {"message": "Could you provide API token?", "event": "needs_input", "agent": "pi"}
    result = run_pi_cli(["--config", str(base_config)], env=env_with_fake_audio, stdin=json.dumps(payload))

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["status"] == "ok"
    assert output["state"] == "needs_input"
    assert output["summary"] == "Could you provide API token?"


def test_pi_wrapper_given_invalid_config_then_exits_with_error(tmp_path: Path, env_with_fake_audio: dict[str, str]) -> None:
    invalid = {"privacy": {"mode": "remote_only"}}
    config_path = tmp_path / "bad.json"
    config_path.write_text(json.dumps(invalid))

    payload = {"message": "hello", "event": "info"}
    result = run_pi_cli(["--config", str(config_path)], env=env_with_fake_audio, stdin=json.dumps(payload))

    assert result.returncode == 2
    output = json.loads(result.stdout)
    assert output["status"] == "error"
    assert "privacy.mode" in output["error"]


def test_pi_wrapper_given_input_file_then_processes_payload(base_config: Path, tmp_path: Path, env_with_fake_audio: dict[str, str]) -> None:
    payload = {"message": "Build completed successfully", "event": "final", "agent": "pi"}
    payload_file = tmp_path / "payload.json"
    payload_file.write_text(json.dumps(payload))

    result = run_pi_cli(["--config", str(base_config), "--input-file", str(payload_file)], env=env_with_fake_audio)
    assert result.returncode == 0

    output = json.loads(result.stdout)
    assert output["status"] == "ok"
    assert output["state"] == "final"


def test_pi_wrapper_given_session_name_then_prefixes_summary(base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    payload = {
        "message": "Need your sign-off",
        "session-name": "release-42",
        "event": "needs_input",
        "agent": "pi",
    }
    result = run_pi_cli(["--config", str(base_config)], env=env_with_fake_audio, stdin=json.dumps(payload))

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["summary"] == "release-42: Need your sign-off"


def test_pi_wrapper_given_no_session_name_then_falls_back_to_conversation_id(base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    payload = {
        "message": "Need your sign-off",
        "conversationId": "conv-123",
        "event": "needs_input",
        "agent": "pi",
    }
    result = run_pi_cli(["--config", str(base_config)], env=env_with_fake_audio, stdin=json.dumps(payload))

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["summary"] == "conv-123: Need your sign-off"


def test_pi_wrapper_given_precomputed_summary_then_uses_it(base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    payload = {
        "message": "Very long content that normally would be summarized differently",
        "summary": "Custom summary from headless agent",
        "event": "final",
        "agent": "pi",
    }
    result = run_pi_cli(["--config", str(base_config)], env=env_with_fake_audio, stdin=json.dumps(payload))

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["status"] == "ok"
    assert output["summary"] == "Custom summary from headless agent"
