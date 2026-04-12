from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import run_cli


def test_show_config_path_given_default_then_prints_default_path(
    tmp_path: Path, env_with_fake_audio: dict[str, str]
) -> None:
    env = dict(env_with_fake_audio)
    env["HOME"] = str(tmp_path)

    result = run_cli(["show-config-path"], env=env)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(tmp_path / ".config" / "speakup" / "config.jsonc")


def test_show_config_path_given_override_then_prints_override(
    tmp_path: Path, env_with_fake_audio: dict[str, str]
) -> None:
    env = dict(env_with_fake_audio)
    env["HOME"] = str(tmp_path)
    config_path = tmp_path / "custom.json"

    result = run_cli(["show-config-path", "--config", str(config_path)], env=env)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(config_path)


def test_show_logs_path_given_default_then_prints_default_log_path(
    tmp_path: Path, env_with_fake_audio: dict[str, str]
) -> None:
    env = dict(env_with_fake_audio)
    env["HOME"] = str(tmp_path)

    result = run_cli(["show-logs-path"], env=env)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(tmp_path / "Library" / "Logs" / "speakup" / "speakup.log")


def test_show_logs_path_given_override_then_prints_configured_path(
    tmp_path: Path, env_with_fake_audio: dict[str, str]
) -> None:
    env = dict(env_with_fake_audio)
    env["HOME"] = str(tmp_path)
    log_path = tmp_path / "logs" / "speakup.log"
    cfg_path = tmp_path / ".config" / "speakup" / "config.jsonc"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({"logging": {"file_path": str(log_path)}}))

    result = run_cli(["show-logs-path"], env=env)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(log_path)


def test_show_logs_path_given_existing_color_log_then_prefers_color_path(
    tmp_path: Path, env_with_fake_audio: dict[str, str]
) -> None:
    env = dict(env_with_fake_audio)
    env["HOME"] = str(tmp_path)
    log_path = tmp_path / "logs" / "speakup.log"
    color_log_path = tmp_path / "logs" / "speakup.log.color"
    color_log_path.parent.mkdir(parents=True, exist_ok=True)
    color_log_path.write_text("")
    cfg_path = tmp_path / ".config" / "speakup" / "config.jsonc"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({"logging": {"file_path": str(log_path)}}))

    result = run_cli(["show-logs-path"], env=env)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(color_log_path)
