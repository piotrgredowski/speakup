from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from speakup.cli import app
from speakup.cli import _apply_cli_overrides, _build_cli_override_payload
from speakup.config import Config, default_config, load_config_without_repository_registration, register_repository_config


runner = CliRunner()


class _DummyNotifyResult:
    status = "ok"
    backend = "dummy"
    played = False

    def to_dict(self) -> dict[str, object]:
        return {"status": self.status, "backend": self.backend, "played": self.played}


class _DummyNotifyService:
    last_request: object | None = None

    def __init__(self, config: Config, **_: object) -> None:
        self.config = config

    def notify(self, request: object) -> _DummyNotifyResult:
        type(self).last_request = request
        return _DummyNotifyResult()


def test_apply_cli_overrides_given_gemini_summary_provider_then_updates_gemini_summary_model() -> None:
    cfg = Config(default_config())

    _apply_cli_overrides(
        cfg,
        summary_provider="gemini",
        summary_model="gemini-2.5-flash-lite",
    )

    assert cfg.get("summarization", "provider_order") == ["gemini"]
    assert cfg.get("providers", "gemini", "summary_model") == "gemini-2.5-flash-lite"


def test_apply_cli_overrides_given_omlx_summary_provider_then_updates_omlx_summary_model() -> None:
    cfg = Config(default_config())

    _apply_cli_overrides(
        cfg,
        summary_provider="omlx",
        summary_model="unsloth/gemma-4-E4B-it-UD-MLX-4bit",
    )

    assert cfg.get("summarization", "provider_order") == ["omlx"]
    assert cfg.get("providers", "omlx", "summary_model") == "unsloth/gemma-4-E4B-it-UD-MLX-4bit"


def test_apply_cli_overrides_given_omlx_tts_provider_then_updates_omlx_model() -> None:
    cfg = Config(default_config())

    _apply_cli_overrides(
        cfg,
        tts_provider="omlx",
        tts_model="Kokoro-82M-bf16",
    )

    assert cfg.get("tts", "provider_order") == ["omlx"]
    assert cfg.get("providers", "omlx", "model") == "Kokoro-82M-bf16"


def test_apply_cli_overrides_given_lmstudio_tts_provider_then_updates_lmstudio_tts_model() -> None:
    cfg = Config(default_config())

    _apply_cli_overrides(
        cfg,
        tts_provider="lmstudio",
        tts_model="local-speech-model",
    )

    assert cfg.get("tts", "provider_order") == ["lmstudio"]
    assert cfg.get("providers", "lmstudio", "tts_model") == "local-speech-model"


def test_apply_cli_overrides_given_openai_tts_provider_then_updates_openai_model() -> None:
    cfg = Config(default_config())

    _apply_cli_overrides(
        cfg,
        tts_provider="openai",
        tts_model="gpt-4o-mini-tts",
    )

    assert cfg.get("tts", "provider_order") == ["openai"]
    assert cfg.get("providers", "openai", "model") == "gpt-4o-mini-tts"


def test_build_cli_override_payload_given_omlx_models_then_targets_omlx_provider() -> None:
    cfg = Config(default_config())

    payload = _build_cli_override_payload(
        cfg,
        summary_provider="omlx",
        summary_model="unsloth/gemma-4-E4B-it-UD-MLX-4bit",
        tts_provider="omlx",
        tts_model="Kokoro-82M-bf16",
    )

    assert payload == {
        "summarization": {"provider_order": ["omlx"]},
        "tts": {"provider_order": ["omlx"]},
        "providers": {
            "omlx": {
                "summary_model": "unsloth/gemma-4-E4B-it-UD-MLX-4bit",
                "model": "Kokoro-82M-bf16",
            }
        },
    }


def test_build_cli_override_payload_given_model_only_then_targets_model_capable_providers() -> None:
    cfg = Config(default_config())

    payload = _build_cli_override_payload(
        cfg,
        summary_model="custom-summary-model",
        tts_model="custom-tts-model",
    )

    providers = payload["providers"]
    assert providers["omlx"]["summary_model"] == "custom-summary-model"
    assert providers["gemini"]["summary_model"] == "custom-summary-model"
    assert providers["openai"]["summary_model"] == "custom-summary-model"
    assert providers["cerebras"]["model"] == "custom-summary-model"
    assert providers["lmstudio"]["model"] == "custom-summary-model"
    assert providers["omlx"]["model"] == "custom-tts-model"
    assert providers["gemini"]["model"] == "custom-tts-model"
    assert providers["openai"]["model"] == "custom-tts-model"
    assert providers["elevenlabs"]["model"] == "custom-tts-model"
    assert providers["lmstudio"]["tts_model"] == "custom-tts-model"


def test_disable_given_config_path_then_writes_root_enabled_false(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(default_config()))

    result = runner.invoke(app, ["disable", "--config", str(config_path)])

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["status"] == "ok"
    assert output["enabled"] is False
    assert json.loads(config_path.read_text())["enabled"] is False


def test_enable_given_config_path_then_writes_root_enabled_true(tmp_path: Path) -> None:
    config = default_config()
    config["enabled"] = False
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))

    result = runner.invoke(app, ["enable", "--config", str(config_path)])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["enabled"] is True
    assert json.loads(config_path.read_text())["enabled"] is True


def test_disable_given_repo_then_writes_repository_enabled_false(tmp_path: Path) -> None:
    project_path = tmp_path / "project"
    project_path.mkdir()
    (project_path / ".git").mkdir()
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(default_config()))

    result = runner.invoke(app, ["disable", "--repo", "--config", str(config_path), "--cwd", str(project_path)])

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["enabled"] is False
    assert output["repository_path"] == str(project_path.resolve())
    written = json.loads(config_path.read_text())
    assert written["enabled"] is True
    assert written["repositories"][str(project_path.resolve())]["enabled"] is False


def test_enable_given_repo_then_preserves_existing_repository_config(tmp_path: Path) -> None:
    project_path = tmp_path / "project"
    project_path.mkdir()
    config = default_config()
    config["repositories"][str(project_path.resolve())] = {"tts": {"provider_order": ["edge"]}, "enabled": False}
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))

    result = runner.invoke(app, ["enable", "--repo", "--config", str(config_path), "--cwd", str(project_path)])

    assert result.exit_code == 0
    repo_config = json.loads(config_path.read_text())["repositories"][str(project_path.resolve())]
    assert repo_config["enabled"] is True
    assert repo_config["tts"]["provider_order"] == ["edge"]


def test_save_repo_config_given_disabled_setting_then_refuses(tmp_path: Path) -> None:
    project_path = tmp_path / "project"
    project_path.mkdir()
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(default_config()))

    result = runner.invoke(app, ["save-repo-config", "--config", str(config_path), "--cwd", str(project_path)])

    assert result.exit_code == 2
    assert json.loads(result.stdout)["status"] == "error"
    assert not (project_path / ".speakup.jsonc").exists()
    repo_config = json.loads(config_path.read_text())["repositories"][str(project_path.resolve())]
    assert repo_config["summarization"]["provider_order"] == ["omlx", "rule_based"]
    assert repo_config["tts"]["provider_order"] == ["omlx", "macos"]


def test_config_loading_given_missing_default_config_then_auto_registers_git_root(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    project_path = tmp_path / "project"
    nested_path = project_path / "src"
    nested_path.mkdir(parents=True)
    (project_path / ".git").mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(nested_path)

    result = runner.invoke(app, ["show-logs-path"])

    assert result.exit_code == 0
    config_path = home / ".config" / "speakup" / "config.jsonc"
    assert result.stdout.strip() == str(home / "Library" / "Logs" / "speakup" / "speakup.log")
    repo_config = json.loads(config_path.read_text())["repositories"][str(project_path.resolve())]
    assert repo_config["summarization"]["provider_order"] == ["omlx", "rule_based"]
    assert repo_config["tts"]["provider_order"] == ["omlx", "macos"]
    assert repo_config["providers"]["omlx"]["summary_model"] == "unsloth/gemma-4-E4B-it-UD-MLX-4bit"
    assert repo_config["providers"]["macos"]["voice"] == "default"


def test_config_loading_given_non_git_directory_then_auto_registers_cwd(tmp_path: Path, monkeypatch) -> None:
    cwd = tmp_path / "workspace"
    cwd.mkdir()
    config_path = tmp_path / "config.json"
    monkeypatch.chdir(cwd)

    result = runner.invoke(app, ["show-logs-path", "--config", str(config_path)])

    assert result.exit_code == 0
    repo_config = json.loads(config_path.read_text())["repositories"]
    assert list(repo_config) == [str(cwd.resolve())]


def test_config_loading_given_existing_repository_entry_then_does_not_overwrite(
    tmp_path: Path, monkeypatch
) -> None:
    project_path = tmp_path / "project"
    project_path.mkdir()
    config = default_config()
    config["repositories"][str(project_path.resolve())] = {"tts": {"provider_order": ["edge"]}}
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.chdir(project_path)

    result = runner.invoke(app, ["show-logs-path", "--config", str(config_path)])

    assert result.exit_code == 0
    repo_config = json.loads(config_path.read_text())["repositories"][str(project_path.resolve())]
    assert repo_config == {"tts": {"provider_order": ["edge"]}}


def test_config_loading_given_provider_settings_then_auto_registers_active_payload(
    tmp_path: Path, monkeypatch
) -> None:
    project_path = tmp_path / "project"
    project_path.mkdir()
    config = default_config()
    config["summarization"]["provider_order"] = ["gemini"]
    config["tts"]["project_overrides"] = {str(project_path.resolve()): {"provider": "lmstudio", "speed": 1.2}}
    config["providers"]["lmstudio"]["tts_model"] = "tts-model"
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.chdir(project_path)

    result = runner.invoke(app, ["show-logs-path", "--config", str(config_path)])

    assert result.exit_code == 0
    repo_config = json.loads(config_path.read_text())["repositories"][str(project_path.resolve())]
    assert repo_config["summarization"]["provider_order"] == ["gemini"]
    assert repo_config["tts"] == {"provider_order": ["lmstudio"], "speed": 1.2}
    assert repo_config["providers"]["gemini"]["summary_model"] == "gemini-2.5-flash"
    assert repo_config["providers"]["lmstudio"]["tts_model"] == "tts-model"


def test_notify_given_cli_provider_overrides_then_auto_registers_overridden_payload(
    tmp_path: Path, monkeypatch
) -> None:
    project_path = tmp_path / "project"
    project_path.mkdir()
    config = default_config()
    config["tts"]["provider_order"] = ["edge"]
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.chdir(project_path)
    monkeypatch.setattr("speakup.cli.NotifyService", _DummyNotifyService)

    result = runner.invoke(
        app,
        [
            "--config",
            str(config_path),
            "--message",
            "done",
            "--tts-provider",
            "macos",
            "--summary-provider",
            "gemini",
        ],
    )

    assert result.exit_code == 0
    repo_config = json.loads(config_path.read_text())["repositories"][str(project_path.resolve())]
    assert repo_config["summarization"]["provider_order"] == ["gemini"]
    assert repo_config["tts"]["provider_order"] == ["macos"]


def test_notify_given_no_title_flag_then_sets_skip_title_metadata(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(default_config()))
    _DummyNotifyService.last_request = None
    monkeypatch.setattr("speakup.cli.NotifyService", _DummyNotifyService)

    result = runner.invoke(app, ["--config", str(config_path), "--message", "done", "--no-title"])

    assert result.exit_code == 0
    assert getattr(_DummyNotifyService.last_request, "metadata")["_speakup_skip_title"] is True


def test_register_repository_config_given_stale_loaded_configs_then_preserves_both_entries(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(default_config()))
    project_one = tmp_path / "one"
    project_two = tmp_path / "two"
    project_one.mkdir()
    project_two.mkdir()
    cfg_one = load_config_without_repository_registration(config_path)
    cfg_two = load_config_without_repository_registration(config_path)

    register_repository_config(cfg_one, config_path, project_one)
    register_repository_config(cfg_two, config_path, project_two)

    repositories = json.loads(config_path.read_text())["repositories"]
    assert str(project_one.resolve()) in repositories
    assert str(project_two.resolve()) in repositories


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
    assert written["tts"]["provider_order"] == ["omlx", "macos"]
    assert written["repositories"][str(project_path.resolve())]["tts"]["provider_order"] == ["lmstudio"]
