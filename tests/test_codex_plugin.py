from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path


def plugin_dir() -> Path:
    return Path(__file__).parent.parent / "plugins" / "speakup-codex-plugin"


def load_hook_module():
    hook_path = plugin_dir() / "hooks" / "speakup-hook.py"
    spec = importlib.util.spec_from_file_location("speakup_codex_hook", hook_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_codex_plugin_structure() -> None:
    manifest_path = plugin_dir() / ".codex-plugin" / "plugin.json"

    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["name"] == "speakup-codex-plugin"
    assert "description" in manifest
    assert "version" in manifest


def test_codex_hooks_configuration() -> None:
    hooks_path = plugin_dir() / "hooks" / "hooks.json"

    assert hooks_path.exists()
    hooks = json.loads(hooks_path.read_text())
    assert "Notification" in hooks["hooks"]
    assert "Stop" in hooks["hooks"]
    expected_command = 'uv run --script "${PLUGIN_ROOT}/hooks/speakup-hook.py"'
    assert hooks["hooks"]["Notification"][0]["hooks"][0]["command"] == expected_command
    assert hooks["hooks"]["Stop"][0]["hooks"][0]["command"] == expected_command


def test_codex_hook_script_exists() -> None:
    hook_path = plugin_dir() / "hooks" / "speakup-hook.py"

    assert hook_path.exists()
    content = hook_path.read_text()
    assert content.startswith("#!/usr/bin/env -S uv run --script\n")
    assert '# /// script' in content
    assert 'git = "https://github.com/piotrgredowski/speakup"' in content
    assert "from speakup.integrations.codex import" in content
    assert "def main():" in content


def test_codex_readme_exists() -> None:
    readme_path = plugin_dir() / "README.md"

    assert readme_path.exists()
    content = readme_path.read_text()
    assert "SpeakUp Codex Plugin" in content
    assert "speakup replay 1 --agent codex --session-key" in content


def test_codex_hook_main_speaks_notification(monkeypatch, tmp_path: Path) -> None:
    module = load_hook_module()
    stdout = io.StringIO()
    captured = {}
    saved = {}

    monkeypatch.setattr(module.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(module.sys, "stdout", stdout)
    monkeypatch.setattr(module, "load_full_config", lambda: {})
    monkeypatch.setattr(module, "load_codex_config", lambda: {"enabled": True, "events": {"notification": True}})
    monkeypatch.setattr(module, "setup_logging", lambda _: None)
    monkeypatch.setattr(module.logger, "info", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.logger, "debug", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module.json,
        "load",
        lambda _: {
            "hook_event_name": "Notification",
            "message": "Approval needed",
            "session_id": "sess-123",
            "cwd": "/tmp/project",
            "session": {"name": "Codex Session"},
        },
    )
    monkeypatch.setattr(
        module,
        "save_current_session_pointer",
        lambda cwd, session_key, session_name=None: saved.update(
            {"cwd": cwd, "session_key": session_key, "session_name": session_name}
        ),
    )

    def fake_run_speakup(request, config_path=None):
        captured["request"] = request
        captured["config_path"] = config_path
        return True

    monkeypatch.setattr(module, "run_speakup", fake_run_speakup)

    try:
        module.main()
    except SystemExit:
        pass

    request = captured["request"]
    assert request.message == "Approval needed"
    assert request.event.value == "needs_input"
    assert request.agent == "codex"
    assert request.session_key == "sess-123"
    assert saved == {"cwd": "/tmp/project", "session_key": "sess-123", "session_name": "Codex Session"}
    assert stdout.getvalue().strip() == (
        "Session: Codex Session\nReplay cmd: speakup replay 1 --agent codex --session-key sess-123"
    )


def test_codex_hook_does_not_print_replay_output_when_launch_fails(monkeypatch, tmp_path: Path) -> None:
    module = load_hook_module()
    stdout = io.StringIO()

    monkeypatch.setattr(module.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(module.sys, "stdout", stdout)
    monkeypatch.setattr(module, "load_full_config", lambda: {})
    monkeypatch.setattr(module, "load_codex_config", lambda: {"enabled": True, "events": {"notification": True}})
    monkeypatch.setattr(module, "setup_logging", lambda _: None)
    monkeypatch.setattr(module.logger, "info", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.logger, "debug", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module.json,
        "load",
        lambda _: {
            "hook_event_name": "Notification",
            "message": "Approval needed",
            "session_id": "sess-123",
            "cwd": "/tmp/project",
            "session": {"name": "Codex Session"},
        },
    )
    monkeypatch.setattr(module, "run_speakup", lambda *args, **kwargs: False)

    try:
        module.main()
    except SystemExit:
        pass

    assert stdout.getvalue() == ""


def test_codex_hook_skips_seen_plan_approval(monkeypatch, tmp_path: Path) -> None:
    module = load_hook_module()
    stdout = io.StringIO()

    monkeypatch.setattr(module.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(module.sys, "stdout", stdout)
    monkeypatch.setattr(module, "load_full_config", lambda: {})
    monkeypatch.setattr(module, "load_codex_config", lambda: {"enabled": True, "events": {"plan_approval": True}})
    monkeypatch.setattr(module, "setup_logging", lambda _: None)
    monkeypatch.setattr(module.logger, "info", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.logger, "debug", lambda *_args, **_kwargs: None)
    payload = {
        "hook_event_name": "Stop",
        "session_id": "sess-123",
        "message": "<proposed_plan>\n# Codex plan\n</proposed_plan>",
    }
    monkeypatch.setattr(module.json, "load", lambda _: payload)

    first_calls = []
    monkeypatch.setattr(module, "run_speakup", lambda *args, **kwargs: first_calls.append((args, kwargs)) or True)

    for _ in range(2):
        try:
            module.main()
        except SystemExit:
            pass

    assert len(first_calls) == 1


def test_codex_hook_dedupes_plan_approval_without_session_key(monkeypatch, tmp_path: Path) -> None:
    module = load_hook_module()

    monkeypatch.setattr(module.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(module.sys, "stdout", io.StringIO())
    monkeypatch.setattr(module, "load_full_config", lambda: {})
    monkeypatch.setattr(module, "load_codex_config", lambda: {"enabled": True, "events": {"plan_approval": True}})
    monkeypatch.setattr(module, "setup_logging", lambda _: None)
    monkeypatch.setattr(module.logger, "info", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.logger, "debug", lambda *_args, **_kwargs: None)
    payload = {
        "hook_event_name": "Stop",
        "cwd": "/tmp/project",
        "message": "<proposed_plan>\n# Codex plan\n</proposed_plan>",
    }
    monkeypatch.setattr(module.json, "load", lambda _: payload)

    calls = []
    monkeypatch.setattr(module, "run_speakup", lambda *args, **kwargs: calls.append((args, kwargs)) or True)

    for _ in range(2):
        try:
            module.main()
        except SystemExit:
            pass

    assert len(calls) == 1
