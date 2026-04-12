from __future__ import annotations

import json
import stat
from pathlib import Path

from tests.conftest import run_cli


def _make_fake_command(tmp_path: Path, name: str, log_path: Path) -> Path:
    script = tmp_path / name
    script.write_text("#!/bin/sh\n" f"echo \"$@\" >> \"{log_path}\"\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_show_config_given_existing_file_then_uses_default_opener_on_macos(tmp_path: Path, env_with_fake_audio: dict[str, str]) -> None:
    env = dict(env_with_fake_audio)
    env["HOME"] = str(tmp_path)

    log_path = tmp_path / "open.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _make_fake_command(bin_dir, "open", log_path)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    cfg_path = tmp_path / ".config" / "speakup" / "config.jsonc"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({"config_viewer": {"command": None}}))

    result = run_cli(["show-config"], env=env)
    assert result.returncode == 0, result.stderr
    assert str(cfg_path) in log_path.read_text()


def test_show_config_given_override_then_uses_configured_command(tmp_path: Path, env_with_fake_audio: dict[str, str]) -> None:
    env = dict(env_with_fake_audio)
    env["HOME"] = str(tmp_path)

    log_path = tmp_path / "viewer.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _make_fake_command(bin_dir, "fake-editor", log_path)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    cfg_path = tmp_path / ".config" / "speakup" / "config.jsonc"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({"config_viewer": {"command": "fake-editor --wait"}}))

    result = run_cli(["show-config"], env=env)
    assert result.returncode == 0, result.stderr
    logged = log_path.read_text()
    assert "--wait" in logged
    assert str(cfg_path) in logged


def test_show_config_given_missing_file_and_accept_then_creates_and_opens(tmp_path: Path, env_with_fake_audio: dict[str, str]) -> None:
    env = dict(env_with_fake_audio)
    env["HOME"] = str(tmp_path)

    log_path = tmp_path / "open.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _make_fake_command(bin_dir, "open", log_path)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    result = run_cli(["show-config"], env=env, stdin="y\n")
    assert result.returncode == 0, result.stderr

    cfg_path = tmp_path / ".config" / "speakup" / "config.jsonc"
    assert cfg_path.exists()
    assert str(cfg_path) in log_path.read_text()


def test_show_config_given_missing_file_and_decline_then_fails(tmp_path: Path, env_with_fake_audio: dict[str, str]) -> None:
    env = dict(env_with_fake_audio)
    env["HOME"] = str(tmp_path)

    result = run_cli(["show-config"], env=env, stdin="n\n")
    assert result.returncode == 1
    assert "Config file not found" in result.stderr


def test_show_config_given_missing_viewer_binary_then_exits_127(tmp_path: Path, env_with_fake_audio: dict[str, str]) -> None:
    env = dict(env_with_fake_audio)
    env["HOME"] = str(tmp_path)

    cfg_path = tmp_path / ".config" / "speakup" / "config.jsonc"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({"config_viewer": {"command": "missing-editor"}}))

    result = run_cli(["show-config"], env=env)
    assert result.returncode == 127
    assert "Config viewer command not found" in result.stderr
