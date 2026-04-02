from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import run_cli


def test_cli_init_config_writes_default_path(tmp_path: Path, env_with_fake_audio: dict[str, str]) -> None:
    env = dict(env_with_fake_audio)
    env["HOME"] = str(tmp_path)

    result = run_cli(["--init-config"], env=env)
    assert result.returncode == 0, result.stderr

    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"

    cfg_path = tmp_path / ".config" / "speakup" / "config.json"
    assert cfg_path.exists()


def test_cli_init_config_without_force_fails_if_exists(tmp_path: Path, env_with_fake_audio: dict[str, str]) -> None:
    env = dict(env_with_fake_audio)
    env["HOME"] = str(tmp_path)

    first = run_cli(["--init-config"], env=env)
    second = run_cli(["--init-config"], env=env)

    assert first.returncode == 0
    assert second.returncode == 2
    payload = json.loads(second.stdout)
    assert payload["status"] == "error"
    assert "already exists" in payload["error"]


def test_cli_init_config_with_force_overwrites(tmp_path: Path, env_with_fake_audio: dict[str, str]) -> None:
    env = dict(env_with_fake_audio)
    env["HOME"] = str(tmp_path)

    run_cli(["--init-config"], env=env)

    cfg_path = tmp_path / ".config" / "speakup" / "config.json"
    cfg_path.write_text("{}")

    forced = run_cli(["--init-config", "--force"], env=env)
    assert forced.returncode == 0

    payload = json.loads(forced.stdout)
    assert payload["status"] == "ok"

    content = json.loads(cfg_path.read_text())
    assert "privacy" in content
