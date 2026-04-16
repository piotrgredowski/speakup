"""Tests for Droid plugin."""
import importlib.util
import json
from pathlib import Path
import textwrap


def load_hook_module():
    plugin_dir = Path(__file__).parent.parent / "plugins" / "speakup-factory-plugin"
    hook_path = plugin_dir / "hooks" / "speakup-hook.py"
    spec = importlib.util.spec_from_file_location("speakup_droid_hook", hook_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plugin_structure():
    """Test that all plugin files exist."""
    plugin_dir = Path(__file__).parent.parent / "plugins" / "speakup-factory-plugin"
    
    # Check manifest exists
    manifest_path = plugin_dir / ".factory-plugin" / "plugin.json"
    assert manifest_path.exists()
    
    with open(manifest_path) as f:
        manifest = json.load(f)
    
    assert manifest["name"] == "speakup"
    assert "description" in manifest
    assert "version" in manifest


def test_hooks_configuration():
    """Test that hooks configuration exists."""
    plugin_dir = Path(__file__).parent.parent / "plugins" / "speakup-factory-plugin"
    hooks_path = plugin_dir / "hooks" / "hooks.json"
    
    assert hooks_path.exists()
    
    with open(hooks_path) as f:
        hooks = json.load(f)
    
    # Check that all expected events are configured
    assert "Notification" in hooks["hooks"]
    assert "Stop" in hooks["hooks"]


def test_hook_script_exists():
    """Test that hook script exists and is executable."""
    plugin_dir = Path(__file__).parent.parent / "plugins" / "speakup-factory-plugin"
    hook_script = plugin_dir / "hooks" / "speakup-hook.py"
    
    assert hook_script.exists()
    # Check it's a Python file (not executable via shebang on Windows)
    with open(hook_script) as f:
        content = f.read()
        assert "import json" in content
        assert "import subprocess" in content
        assert "def main():" in content


def test_slash_command_exists():
    """Test that slash command exists."""
    plugin_dir = Path(__file__).parent.parent / "plugins" / "speakup-factory-plugin"
    command_path = plugin_dir / "commands" / "speakup.md"
    
    assert command_path.exists()
    
    with open(command_path) as f:
        content = f.read()
        assert "description:" in content
        assert "Control speakup notifications" in content


def test_readme_exists():
    """Test that README exists."""
    plugin_dir = Path(__file__).parent.parent / "plugins" / "speakup-factory-plugin"
    readme_path = plugin_dir / "README.md"
    
    assert readme_path.exists()
    
    with open(readme_path) as f:
        content = f.read()
        assert "Speakup Droid Plugin" in content


def test_hook_prefers_jsonc_config(tmp_path, monkeypatch):
    module = load_hook_module()
    monkeypatch.setattr(module.Path, "home", lambda: tmp_path)

    cfg_dir = tmp_path / ".config" / "speakup"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.jsonc").write_text('{\n  // comment\n  "droid": {"enabled": false}\n}\n')

    assert module.get_config_path() == cfg_dir / "config.jsonc"
    assert module.load_droid_config()["enabled"] is False


def test_hook_falls_back_to_legacy_json_config(tmp_path, monkeypatch):
    module = load_hook_module()
    monkeypatch.setattr(module.Path, "home", lambda: tmp_path)

    cfg_dir = tmp_path / ".config" / "speakup"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(json.dumps({"droid": {"enabled": False}}))

    assert module.get_config_path() == cfg_dir / "config.json"
    assert module.load_droid_config()["enabled"] is False


def test_redact_payload_masks_sensitive_fields():
    module = load_hook_module()

    payload = {
        "message": "hello",
        "token": "secret-token",
        "nested": {
            "api_key": "secret-key",
            "session_id": "abc123",
        },
        "items": [{"authorization": "Bearer abc"}, "ok"],
    }

    redacted = module.redact_payload(payload)

    assert redacted["message"] == "hello"
    assert redacted["token"] == "***"
    assert redacted["nested"]["api_key"] == "***"
    assert redacted["nested"]["session_id"] == "abc123"
    assert redacted["items"][0]["authorization"] == "***"


def test_hook_does_not_log_full_config(monkeypatch):
    module = load_hook_module()
    logged = []

    monkeypatch.setattr(module, "load_full_config", lambda: {"providers": {"openai": {"api_key": "secret"}}})
    monkeypatch.setattr(module, "load_droid_config", lambda: {"enabled": False})
    monkeypatch.setattr(module, "setup_logging", lambda config: None)
    monkeypatch.setattr(module.logger, "info", lambda message: logged.append(message))
    monkeypatch.setattr(module.logger, "debug", lambda message: logged.append(message))
    monkeypatch.setattr(module.json, "load", lambda _: {"hook_event_name": "Notification", "message": "hello"})

    try:
        module.main()
    except SystemExit:
        pass

    assert all("Full config:" not in message for message in logged)
    assert all("secret" not in message for message in logged)


def test_extract_message_from_transcript_supports_message_envelope(tmp_path):
    module = load_hook_module()
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        textwrap.dedent(
            """
            {"type":"message","id":"1","message":{"role":"assistant","content":[{"type":"text","text":"# Hi\\n\\nDoing well."}]}}
            """
        ).strip()
        + "\n"
    )

    result = module.extract_message_from_transcript(str(transcript))

    assert result == "# Hi\n\nDoing well."


def test_extract_session_name_prefers_session_title_over_title():
    module = load_hook_module()

    payload = {
        "title": "New Session",
        "sessionTitle": "Code Changes Review Findings",
        "session": {"name": "Fallback Name"},
        "metadata": {"sessionTitle": "Metadata Title"},
        "session_id": "abc12345",
    }

    assert module.extract_session_name(payload) == "Code Changes Review Findings"


def test_extract_session_name_reads_nested_session_title():
    module = load_hook_module()

    payload = {
        "session": {
            "title": "New Session",
            "sessionTitle": "Investigate Droid Speakup Plugin Failure",
        },
        "session_id": "abc12345",
    }

    assert module.extract_session_name(payload) == "Investigate Droid Speakup Plugin Failure"


def test_extract_session_name_reads_transcript_session_title(tmp_path):
    module = load_hook_module()
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        '{"type":"session_start","title":"New Session","sessionTitle":"Investigate Droid Speakup Plugin Failure"}' + "\n"
    )

    payload = {
        "transcript_path": str(transcript),
        "session_id": "6b598d4b-8103-41b5-befb-2caad634760b",
    }

    assert module.extract_session_name(payload) == "Investigate Droid Speakup Plugin Failure"


def test_extract_session_name_humanizes_session_id_fallback():
    module = load_hook_module()

    payload = {
        "session_id": "6b598d4b-8103-41b5-befb-2caad634760b",
    }

    assert module.extract_session_name(payload) == "session 6b598d4b"


def test_run_speakup_uses_non_blocking_popen(monkeypatch):
    module = load_hook_module()
    captured = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)

    result = module.run_speakup("hello", "info", "session name")

    assert result is True
    assert captured["cmd"] == ["speakup", "--message", "hello", "--event", "info", "--session-name", "session name"]
    assert captured["kwargs"]["stdin"] is module.subprocess.DEVNULL
    assert captured["kwargs"]["stdout"] is module.subprocess.DEVNULL
    assert captured["kwargs"]["stderr"] is module.subprocess.DEVNULL
    assert captured["kwargs"]["start_new_session"] is True


def test_run_speakup_returns_false_when_command_missing(monkeypatch):
    module = load_hook_module()

    def fake_popen(cmd, **kwargs):  # noqa: ARG001
        raise FileNotFoundError

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)

    assert module.run_speakup("hello", "info") is False


def test_run_speakup_returns_false_on_oserror(monkeypatch):
    module = load_hook_module()

    def fake_popen(cmd, **kwargs):  # noqa: ARG001
        raise OSError("boom")

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)

    assert module.run_speakup("hello", "info") is False
