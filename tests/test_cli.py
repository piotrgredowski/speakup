from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from speakup.cli import app
from speakup.cli import _apply_cli_overrides
from speakup.config import Config, default_config


runner = CliRunner()


def test_apply_cli_overrides_given_gemini_summary_provider_then_updates_gemini_summary_model() -> None:
    cfg = Config(default_config())

    _apply_cli_overrides(
        cfg,
        summary_provider="gemini",
        summary_model="gemini-2.5-flash-lite",
    )

    assert cfg.get("summarization", "provider_order") == ["gemini"]
    assert cfg.get("providers", "gemini", "summary_model") == "gemini-2.5-flash-lite"


def test_save_repo_config_given_disabled_setting_then_refuses(tmp_path: Path) -> None:
    project_path = tmp_path / "project"
    project_path.mkdir()
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(default_config()))

    result = runner.invoke(app, ["save-repo-config", "--config", str(config_path), "--cwd", str(project_path)])

    assert result.exit_code == 2
    assert json.loads(result.stdout)["status"] == "error"
    assert not (project_path / ".speakup.jsonc").exists()
    assert json.loads(config_path.read_text())["repositories"] == {}


def test_save_repo_config_given_enabled_setting_then_writes_active_provider_settings(tmp_path: Path) -> None:
    project_path = tmp_path / "project"
    project_path.mkdir()
    (project_path / ".speakup.jsonc").write_text(json.dumps({"tts": {"provider_order": ["stale"]}}))
    config = default_config()
    config["repo_config"]["save_active_provider_config"] = True
    config["summarization"]["provider_order"] = ["gemini"]
    config["tts"]["provider_order"] = ["macos"]
    config["tts"]["project_overrides"] = {str(project_path.resolve()): {"provider": "lmstudio", "speed": 1.2}}
    config["providers"]["lmstudio"] = {
        "base_url": "http://127.0.0.1:1234/v1",
        "model": "summary-model",
        "tts_model": "tts-model",
        "title_voice": "title",
        "message_voice": "message",
        "available_voices": ["title", "message"],
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))

    result = runner.invoke(app, ["save-repo-config", "--config", str(config_path), "--cwd", str(project_path)])

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["status"] == "ok"
    assert output["config_path"] == str(config_path)
    assert output["repository_path"] == str(project_path.resolve())
    assert json.loads((project_path / ".speakup.jsonc").read_text()) == {"tts": {"provider_order": ["stale"]}}
    repo_config = json.loads(config_path.read_text())["repositories"][str(project_path.resolve())]
    assert repo_config["summarization"]["provider_order"] == ["gemini"]
    assert repo_config["tts"]["provider_order"] == ["lmstudio"]
    assert repo_config["providers"]["lmstudio"]["base_url"] == "http://127.0.0.1:1234/v1"
    assert repo_config["providers"]["lmstudio"]["tts_model"] == "tts-model"
    assert repo_config["providers"]["lmstudio"]["available_voices"] == ["title", "message"]
    assert repo_config["providers"]["gemini"]["summary_model"] == "gemini-2.5-flash"


def test_save_repo_config_given_local_sidecar_then_does_not_persist_sidecar_settings(tmp_path: Path) -> None:
    project_path = tmp_path / "project"
    project_path.mkdir()
    config = default_config()
    config["repo_config"]["save_active_provider_config"] = True
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    local_config = {"tts": {"provider_order": ["lmstudio"]}}
    (tmp_path / "config.local.jsonc").write_text(json.dumps(local_config))

    result = runner.invoke(app, ["save-repo-config", "--config", str(config_path), "--cwd", str(project_path)])

    assert result.exit_code == 0
    written = json.loads(config_path.read_text())
    assert written["tts"]["provider_order"] == ["macos"]
    assert written["repositories"][str(project_path.resolve())]["tts"]["provider_order"] == ["lmstudio"]
