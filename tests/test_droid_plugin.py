"""Tests for Droid plugin."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import textwrap
import types


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
    expected_commands = {
        'uv run --script "${DROID_PLUGIN_ROOT}/hooks/speakup-hook.py"',
        'uv run "${DROID_PLUGIN_ROOT}/hooks/speakup-hook.py"',
    }
    for event_name in ("Notification", "Stop"):
        command = hooks["hooks"][event_name][0]["hooks"][0]["command"]
        assert command in expected_commands


def test_hook_script_exists():
    """Test that hook script exists and is executable."""
    plugin_dir = Path(__file__).parent.parent / "plugins" / "speakup-factory-plugin"
    hook_script = plugin_dir / "hooks" / "speakup-hook.py"
    
    assert hook_script.exists()
    # Check it's a Python file (not executable via shebang on Windows)
    with open(hook_script) as f:
        content = f.read()
        assert content.startswith("#!/usr/bin/env -S uv run --script\n")
        assert '# /// script' in content
        assert '"structlog>=25.5.0"' in content
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


def test_hook_uses_default_request_id_fallback_when_shared_module_lacks_it(monkeypatch):
    fake_package = types.ModuleType("speakup")
    fake_package.__path__ = []
    fake_app_logging = types.ModuleType("speakup.app_logging")
    fake_app_logging.make_formatter = lambda *args, **kwargs: object()
    fake_package.app_logging = fake_app_logging

    monkeypatch.setitem(sys.modules, "speakup", fake_package)
    monkeypatch.setitem(sys.modules, "speakup.app_logging", fake_app_logging)

    module = load_hook_module()

    assert module.DEFAULT_REQUEST_ID == "-"


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


def test_extract_session_name_ignores_hex_like_title_and_falls_back_to_session_id():
    module = load_hook_module()

    payload = {
        "sessionTitle": "6b598d4b810341b5befb2caad634760b",
        "session_id": "12345678-8103-41b5-befb-2caad634760b",
    }

    assert module.extract_session_name(payload) == "session 12345678"


def test_extract_session_name_ignores_hex_like_transcript_title_and_falls_back_to_session_id(tmp_path):
    module = load_hook_module()
    transcript = tmp_path / "session.jsonl"
    transcript.write_text('{"type":"session_start","sessionTitle":"deadbeefcafebabe"}\n')

    payload = {
        "transcript_path": str(transcript),
        "session_id": "abcdef12-8103-41b5-befb-2caad634760b",
    }

    assert module.extract_session_name(payload) == "session abcdef12"


def test_get_speakup_version_reads_cli_version(monkeypatch):
    module = load_hook_module()
    module._SPEAKUP_VERSION = None

    class CompletedProcess:
        returncode = 0
        stdout = "v1.2.3\n"

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: CompletedProcess())

    assert module.get_speakup_version() == "v1.2.3"


def test_extract_request_id_prefers_top_level_request_id():
    module = load_hook_module()

    payload = {
        "request_id": "req-top",
        "metadata": {"requestId": "req-metadata"},
    }

    assert module.extract_request_id(payload) == "req-top"


def test_build_hook_summary_includes_session_name():
    module = load_hook_module()

    assert module.build_hook_summary("Done.", "Stop", "Session Name") == "speakup final (Session Name): Done."


def test_build_hook_summary_sanitizes_markdown_and_falls_back_when_empty():
    module = load_hook_module()

    assert module.build_hook_summary("# Release Update", "Stop", "Session Name") == "speakup final (Session Name): Release Update"
    assert module.build_hook_summary("#", "Stop", "Session Name") == "speakup final (Session Name): Task finished"


def test_main_prints_notification_summary_to_stdout(monkeypatch):
    module = load_hook_module()
    stdout = io.StringIO()
    captured = {}

    monkeypatch.setattr(module.sys, "stdout", stdout)
    monkeypatch.setattr(module, "load_full_config", lambda: {})
    monkeypatch.setattr(module, "load_droid_config", lambda: {"enabled": True, "events": {"notification": True}})
    monkeypatch.setattr(module, "setup_logging", lambda config: None)
    monkeypatch.setattr(module, "extract_request_id", lambda _: "req-123")
    monkeypatch.setattr(module, "extract_session_name", lambda _: "Session Name")
    monkeypatch.setattr(module.logger, "info", lambda message: None)
    monkeypatch.setattr(module.logger, "debug", lambda message: None)
    monkeypatch.setattr(module.json, "load", lambda _: {"hook_event_name": "Notification", "message": "hello"})

    def fake_run_speakup(message, event, session_name=None):
        captured["message"] = message
        captured["event"] = event
        captured["session_name"] = session_name
        return True

    monkeypatch.setattr(module, "run_speakup", fake_run_speakup)

    try:
        module.main()
    except SystemExit:
        pass

    assert captured == {"message": "hello", "event": "needs_input", "session_name": "Session Name"}
    assert stdout.getvalue().strip() == "speakup notification (Session Name): hello"


def test_main_prints_stop_summary_to_stdout(monkeypatch, tmp_path):
    module = load_hook_module()
    stdout = io.StringIO()
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        '{"type":"message","message":{"role":"assistant","content":[{"type":"text","text":"# Final summary text"}]}}\n'
    )

    monkeypatch.setattr(module.sys, "stdout", stdout)
    monkeypatch.setattr(module, "load_full_config", lambda: {})
    monkeypatch.setattr(module, "load_droid_config", lambda: {"enabled": True, "events": {"stop": True}})
    monkeypatch.setattr(module, "setup_logging", lambda config: None)
    monkeypatch.setattr(module, "extract_request_id", lambda _: "req-123")
    monkeypatch.setattr(module, "extract_session_name", lambda _: "Session Name")
    monkeypatch.setattr(module.logger, "info", lambda message: None)
    monkeypatch.setattr(module.logger, "debug", lambda message: None)
    monkeypatch.setattr(
        module.json,
        "load",
        lambda _: {"hook_event_name": "Stop", "transcript_path": str(transcript)},
    )

    def fake_run_speakup(message, event, session_name=None):
        assert message == "# Final summary text"
        assert event == "final"
        assert session_name == "Session Name"
        return True

    monkeypatch.setattr(module, "run_speakup", fake_run_speakup)

    try:
        module.main()
    except SystemExit:
        pass

    assert stdout.getvalue().strip() == "speakup final (Session Name): Final summary text"


def test_hook_logging_writes_request_id_first(tmp_path):
    module = load_hook_module()

    module.setup_logging(
        {
            "logging": {
                "enabled": True,
                "level": "INFO",
                "format": "text",
                "file_path": str(tmp_path / "speakup.log"),
            }
        }
    )

    try:
        module.logger.info("hook_invoked", extra={"request_id": "req-123"})
        for handler in module.logger.handlers:
            handler.flush()

        log_text = (tmp_path / "droid-hook.log").read_text().strip()
        assert log_text.startswith("request_id=req-123")
        assert "logger=speakup-droid" in log_text
        assert "event=hook_invoked" in log_text
    finally:
        for handler in list(module.logger.handlers):
            handler.close()
        module.logger.handlers.clear()


def test_hook_logging_writes_colored_companion_log(tmp_path):
    module = load_hook_module()

    module.setup_logging(
        {
            "logging": {
                "enabled": True,
                "level": "INFO",
                "format": "json",
                "file_path": str(tmp_path / "speakup.log"),
            }
        }
    )

    try:
        module.logger.info("hook_invoked", extra={"request_id": "req-123"})
        for handler in module.logger.handlers:
            handler.flush()

        color_log_text = (tmp_path / "droid-hook.log.color").read_text().strip()
        assert "\x1b[" in color_log_text
        assert "hook_invoked" in color_log_text
        assert "req-123" in color_log_text
        assert not color_log_text.startswith("{")
    finally:
        for handler in list(module.logger.handlers):
            handler.close()
        module.logger.handlers.clear()


def test_run_speakup_uses_non_blocking_popen(monkeypatch):
    module = load_hook_module()
    captured = {}
    logged = []

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(module, "get_speakup_version", lambda: "v1.2.3")
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module.logger, "info", lambda message: logged.append(message))

    result = module.run_speakup("hello", "info", "session name")

    assert result is True
    assert captured["cmd"] == ["speakup", "--message", "hello", "--event", "info", "--session-name", "session name"]
    assert captured["kwargs"]["stdin"] is module.subprocess.DEVNULL
    assert captured["kwargs"]["stdout"] is module.subprocess.DEVNULL
    assert captured["kwargs"]["stderr"] is module.subprocess.DEVNULL
    assert captured["kwargs"]["start_new_session"] is True
    assert logged[0] == "Launching speakup v1.2.3: event=info, session=session name, message_len=5"


def test_run_speakup_returns_false_when_command_missing(monkeypatch):
    module = load_hook_module()

    def fake_popen(cmd, **kwargs):  # noqa: ARG001
        raise FileNotFoundError

    monkeypatch.setattr(module, "get_speakup_version", lambda: "v1.2.3")
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)

    assert module.run_speakup("hello", "info") is False


def test_run_speakup_returns_false_on_oserror(monkeypatch):
    module = load_hook_module()

    def fake_popen(cmd, **kwargs):  # noqa: ARG001
        raise OSError("boom")

    monkeypatch.setattr(module, "get_speakup_version", lambda: "v1.2.3")
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)

    assert module.run_speakup("hello", "info") is False
