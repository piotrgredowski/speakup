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
    assert "PreToolUse" in hooks["hooks"]
    assert "Stop" in hooks["hooks"]
    expected_commands = {
        'uv run --script "${DROID_PLUGIN_ROOT}/hooks/speakup-hook.py"',
        'uv run "${DROID_PLUGIN_ROOT}/hooks/speakup-hook.py"',
    }
    for event_name in ("Notification", "Stop"):
        command = hooks["hooks"][event_name][0]["hooks"][0]["command"]
        assert command in expected_commands
    pre_tool_use = hooks["hooks"]["PreToolUse"][0]
    assert pre_tool_use["matcher"] == "AskUser"
    assert pre_tool_use["hooks"][0]["command"] in expected_commands


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
        assert 'git = "https://github.com/piotrgredowski/speakup"' in content
        assert '"structlog>=25.5.0"' in content
        assert "import json" in content
        assert "from speakup.integrations.droid import" in content
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
        assert "replay" in content
        assert "--session-key" in content
        assert "droid-session-pointers" in content


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
    config = module.load_droid_config()
    assert config["enabled"] is False
    assert config["events"]["subagent_stop"] is False
    assert config["events"]["session_start"] is False


def test_hook_falls_back_to_legacy_json_config(tmp_path, monkeypatch):
    module = load_hook_module()
    monkeypatch.setattr(module.Path, "home", lambda: tmp_path)

    cfg_dir = tmp_path / ".config" / "speakup"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(json.dumps({"droid": {"enabled": False}}))

    assert module.get_config_path() == cfg_dir / "config.json"
    config = module.load_droid_config()
    assert config["enabled"] is False
    assert config["events"]["subagent_stop"] is False
    assert config["events"]["session_start"] is False


def test_hook_merges_partial_droid_event_overrides_with_defaults(tmp_path, monkeypatch):
    module = load_hook_module()
    monkeypatch.setattr(module.Path, "home", lambda: tmp_path)

    cfg_dir = tmp_path / ".config" / "speakup"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.jsonc").write_text(
        '{\n  "droid": {"events": {"notification": false}}\n}\n'
    )

    config = module.load_droid_config()

    assert config["enabled"] is True
    assert config["events"] == {
        "notification": False,
        "stop": True,
        "subagent_stop": False,
        "session_start": False,
    }


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


def test_extract_message_from_transcript_allows_worker_stop_after_assistant(tmp_path):
    module = load_hook_module()
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        textwrap.dedent(
            """
            {"type":"message","id":"1","message":{"role":"assistant","content":[{"type":"text","text":"done"}]}}
            {"type":"workers_stopped"}
            """
        ).strip()
        + "\n"
    )

    assert module.extract_message_from_transcript(str(transcript)) == "done"


def test_extract_message_from_transcript_allows_session_end_after_assistant(tmp_path):
    module = load_hook_module()
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        textwrap.dedent(
            """
            {"type":"message","id":"1","message":{"role":"assistant","content":[{"type":"text","text":"done"}]}}
            {"type":"session_end"}
            """
        ).strip()
        + "\n"
    )

    assert module.extract_message_from_transcript(str(transcript)) == "done"


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


def test_extract_session_name_given_session_id_only_then_returns_none():
    module = load_hook_module()

    payload = {
        "session_id": "6b598d4b-8103-41b5-befb-2caad634760b",
    }

    assert module.extract_session_name(payload) is None


def test_extract_session_name_ignores_hex_like_title_without_fallback():
    module = load_hook_module()

    payload = {
        "sessionTitle": "6b598d4b810341b5befb2caad634760b",
        "session_id": "12345678-8103-41b5-befb-2caad634760b",
    }

    assert module.extract_session_name(payload) is None


def test_extract_session_name_ignores_hex_like_transcript_title_without_fallback(tmp_path):
    module = load_hook_module()
    transcript = tmp_path / "session.jsonl"
    transcript.write_text('{"type":"session_start","sessionTitle":"deadbeefcafebabe"}\n')

    payload = {
        "transcript_path": str(transcript),
        "session_id": "abcdef12-8103-41b5-befb-2caad634760b",
    }

    assert module.extract_session_name(payload) is None


def test_extract_session_id_reads_top_level_value():
    module = load_hook_module()

    assert module.extract_session_id({"session_id": "6b598d4b-8103-41b5-befb-2caad634760b"}) == "6b598d4b-8103-41b5-befb-2caad634760b"


def test_build_droid_notify_request_sets_droid_fields():
    from speakup.integrations.droid import build_droid_notify_request

    request = build_droid_notify_request(
        message="hello",
        event="info",
        session_name="Session Name",
        session_key="sess-123",
        session_id="sess-123",
        cwd="/tmp/project",
    )

    assert request.message == "hello"
    assert request.event.value == "info"
    assert request.session_name == "Session Name"
    assert request.session_key == "sess-123"
    assert request.session_id == "sess-123"
    assert request.agent == "droid"
    assert request.metadata == {"cwd": "/tmp/project"}


def test_notify_in_background_uses_detached_python_process(monkeypatch, tmp_path):
    from speakup.integrations import droid as integration

    captured = {}

    class FakeProcess:
        pid = 321

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(integration, "_write_payload_file", lambda request, config_path: tmp_path / "payload.json")
    monkeypatch.setattr(integration.subprocess, "Popen", fake_popen)

    request = integration.build_droid_notify_request(message="hello", event="info")
    pid = integration.notify_in_background(request, config_path=Path("/tmp/config.jsonc"))

    assert captured["cmd"] == [
        integration.sys.executable,
        "-m",
        "speakup.integrations.droid",
        integration._PAYLOAD_FILE_ARG,
        str(tmp_path / "payload.json"),
    ]
    assert captured["kwargs"]["stdin"] is integration.subprocess.DEVNULL
    assert captured["kwargs"]["stdout"] is integration.subprocess.DEVNULL
    assert captured["kwargs"]["stderr"] is integration.subprocess.DEVNULL
    assert captured["kwargs"]["start_new_session"] is True
    pythonpath = captured["kwargs"]["env"]["PYTHONPATH"]
    assert pythonpath.split(integration.os.pathsep)[0] == str(integration._PACKAGE_ROOT)
    assert pid == 321


def test_run_payload_file_invokes_worker_and_cleans_up(tmp_path, monkeypatch):
    from speakup.integrations import droid as integration

    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps({
        "request": {
            "message": "hello",
            "event": "info",
            "session_name": "Session Name",
            "conversation_id": None,
            "session_id": "sess-123",
            "session_key": "sess-123",
            "task_id": None,
            "agent": "droid",
            "precomputed_summary": None,
            "skip_summarization": False,
            "force_summarization": False,
            "metadata": {},
        },
        "config_path": "/tmp/config.jsonc",
    }))
    captured = {}

    def fake_notify_worker(request, config_path):
        captured["request"] = request
        captured["config_path"] = config_path

    monkeypatch.setattr(integration, "_notify_worker", fake_notify_worker)

    integration._run_payload_file(payload_path)

    assert captured["request"].message == "hello"
    assert captured["request"].event.value == "info"
    assert captured["request"].session_key == "sess-123"
    assert captured["config_path"] == "/tmp/config.jsonc"
    assert not payload_path.exists()


def test_extract_request_id_prefers_top_level_request_id():
    module = load_hook_module()

    payload = {
        "request_id": "req-top",
        "metadata": {"requestId": "req-metadata"},
    }

    assert module.extract_request_id(payload) == "req-top"


def test_extract_session_key_reads_droid_session_id():
    module = load_hook_module()

    assert module.extract_session_key({"session_id": "sess-123"}) == "sess-123"


def test_save_current_session_pointer_writes_cwd_scoped_pointer(tmp_path, monkeypatch):
    module = load_hook_module()
    monkeypatch.setattr(module.Path, "home", lambda: tmp_path)

    module.save_current_session_pointer("/Users/pg/Coding/_bucket/speakup", "sess-123", "Session Name")

    pointer_path = module.get_session_pointer_path("/Users/pg/Coding/_bucket/speakup")
    payload = json.loads(pointer_path.read_text())
    assert payload["session_key"] == "sess-123"
    assert payload["session_name"] == "Session Name"


def test_build_hook_output_includes_session_name_before_replay_command():
    module = load_hook_module()

    assert (
        module.build_hook_output("sess-123", "Session Name")
        == "Session: Session Name\nReplay cmd: speakup replay 1 --agent droid --session-key sess-123"
    )


def test_build_hook_output_without_session_name_returns_replay_command_only():
    module = load_hook_module()

    assert module.build_hook_output("sess-123") == "Replay cmd: speakup replay 1 --agent droid --session-key sess-123"


def test_extract_message_reads_questionnaire_question_for_notification():
    module = load_hook_module()

    payload = {
        "hook_event_name": "Notification",
        "questionnaire": "1. [question] Which region should we deploy to?\n[topic] Region\n[option] us-east-1",
    }

    assert module.extract_message(payload, "Notification") == "Which region should we deploy to?"


def test_extract_message_summarizes_askuser_pre_tool_use_questionnaire():
    module = load_hook_module()

    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "AskUser",
        "tool_input": {
            "questionnaire": (
                "1. [question] What would you like to talk about?\n"
                "[topic] Topic\n"
                "[option] Coding"
            ),
        },
    }

    assert module.extract_message(payload, "PreToolUse") == "Droid needs input about Topic."


def test_extract_message_ignores_non_askuser_pre_tool_use():
    module = load_hook_module()

    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Execute",
        "tool_input": {"command": "echo hi"},
    }

    assert module.extract_message(payload, "PreToolUse") is None


def test_extract_message_reads_plain_assistant_text_from_notification_envelope():
    module = load_hook_module()

    payload = {
        "hook_event_name": "Notification",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Need your sign-off"},
            ],
        },
    }

    assert module.extract_message(payload, "Notification") == "Need your sign-off"


def test_extract_message_summarizes_nested_tool_use_questionnaire_topics():
    module = load_hook_module()

    payload = {
        "hook_event_name": "Notification",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "AskUser",
                    "input": {
                        "questionnaire": (
                            "1. [question] How should the session name be shown?\n"
                            "[topic] Output format\n"
                            "[option] Separate line\n\n"
                            "2. [question] Which library should we use?\n"
                            "[topic] Library choice\n"
                            "[option] Existing"
                        )
                    },
                }
            ],
        },
    }

    assert module.extract_message(payload, "Notification") == "Droid needs input about Output format and Library choice."


def test_extract_message_reads_questionnaire_from_any_tool_use_block():
    module = load_hook_module()

    payload = {
        "hook_event_name": "Notification",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "SomeFutureTool",
                    "input": {
                        "questionnaire": "1. [question] Which region should we deploy to?\n[topic] Region\n[option] us-east-1"
                    },
                }
            ],
        },
    }

    assert module.extract_message(payload, "Notification") == "Droid needs input about Region."


def test_extract_message_preserves_mixed_case_questionnaire_topics():
    module = load_hook_module()

    payload = {
        "hook_event_name": "Notification",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "AskUser",
                    "input": {
                        "questionnaire": "1. [question] Which secret should we use?\n[topic] API key\n[option] Existing",
                    },
                }
            ],
        },
    }

    assert module.extract_message(payload, "Notification") == "Droid needs input about API key."


def test_extract_message_summarizes_exit_spec_mode_title():
    module = load_hook_module()

    payload = {
        "hook_event_name": "Notification",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "ExitSpecMode",
                    "input": {
                        "title": "Add AskUser questionnaire support to Droid notifications",
                        "plan": "## Goal\nMake notifications work.",
                    },
                }
            ],
        },
    }

    assert (
        module.extract_message(payload, "Notification")
        == "Droid is waiting for plan approval: Add AskUser questionnaire support to Droid notifications."
    )


def test_extract_message_summarizes_exit_spec_mode_goal_without_heading():
    module = load_hook_module()

    payload = {
        "hook_event_name": "Notification",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "ExitSpecMode",
                    "input": {
                        "plan": "## Goal\n\n## Steps\n- Make notifications work.",
                    },
                }
            ],
        },
    }

    assert (
        module.extract_message(payload, "Notification")
        == "Droid is waiting for plan approval. - Make notifications work."
    )


def test_extract_message_ignores_fenced_code_in_exit_spec_mode_goal():
    module = load_hook_module()

    payload = {
        "hook_event_name": "Notification",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "ExitSpecMode",
                    "input": {
                        "plan": "## Goal\n\n```py\nprint(1)\n```\n\nConfirm the implementation plan.",
                    },
                }
            ],
        },
    }

    assert (
        module.extract_message(payload, "Notification")
        == "Droid is waiting for plan approval. Confirm the implementation plan."
    )


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
    monkeypatch.setattr(module, "extract_session_id", lambda _: "sess-123")
    monkeypatch.setattr(module, "extract_session_key", lambda _: "sess-123")
    saved = {}
    monkeypatch.setattr(module, "save_current_session_pointer", lambda cwd, session_key, session_name=None: saved.update({"cwd": cwd, "session_key": session_key, "session_name": session_name}))
    monkeypatch.setattr(module.logger, "info", lambda message: None)
    monkeypatch.setattr(module.logger, "debug", lambda message: None)
    monkeypatch.setattr(module.json, "load", lambda _: {"hook_event_name": "Notification", "message": "hello", "cwd": "/tmp/project"})

    def fake_run_speakup(message, event, session_name=None, session_key=None, session_id=None, cwd=None, source_tool=None):
        captured["message"] = message
        captured["event"] = event
        captured["session_name"] = session_name
        captured["session_key"] = session_key
        captured["session_id"] = session_id
        captured["cwd"] = cwd
        captured["source_tool"] = source_tool
        return True

    monkeypatch.setattr(module, "run_speakup", fake_run_speakup)

    try:
        module.main()
    except SystemExit:
        pass

    assert captured == {
        "message": "hello",
        "event": "needs_input",
        "session_name": "Session Name",
        "session_key": "sess-123",
        "session_id": "sess-123",
        "cwd": "/tmp/project",
        "source_tool": "Droid",
    }
    assert saved == {"cwd": "/tmp/project", "session_key": "sess-123", "session_name": "Session Name"}
    assert (
        stdout.getvalue().strip()
        == "Session: Session Name\nReplay cmd: speakup replay 1 --agent droid --session-key sess-123"
    )


def test_main_prints_notification_summary_from_exit_spec_mode(monkeypatch):
    module = load_hook_module()
    stdout = io.StringIO()
    captured = {}
    saved = {}

    monkeypatch.setattr(module.sys, "stdout", stdout)
    monkeypatch.setattr(module, "load_full_config", lambda: {})
    monkeypatch.setattr(module, "load_droid_config", lambda: {"enabled": True, "events": {"notification": True}})
    monkeypatch.setattr(module, "setup_logging", lambda config: None)
    monkeypatch.setattr(module, "extract_request_id", lambda _: "req-123")
    monkeypatch.setattr(module, "extract_session_name", lambda _: "Session Name")
    monkeypatch.setattr(module, "extract_session_id", lambda _: "sess-123")
    monkeypatch.setattr(module, "extract_session_key", lambda _: "sess-123")
    monkeypatch.setattr(module, "save_current_session_pointer", lambda cwd, session_key, session_name=None: saved.update({"cwd": cwd, "session_key": session_key, "session_name": session_name}))
    monkeypatch.setattr(module.logger, "info", lambda message: None)
    monkeypatch.setattr(module.logger, "debug", lambda message: None)
    monkeypatch.setattr(
        module.json,
        "load",
        lambda _: {
            "hook_event_name": "Notification",
            "cwd": "/tmp/project",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "ExitSpecMode",
                        "input": {
                            "title": "Add AskUser questionnaire support to Droid notifications",
                            "plan": "## Goal\nMake notifications work.",
                        },
                    }
                ],
            },
        },
    )

    def fake_run_speakup(message, event, session_name=None, session_key=None, session_id=None, cwd=None, source_tool=None):
        captured["message"] = message
        captured["event"] = event
        captured["session_name"] = session_name
        captured["session_key"] = session_key
        captured["session_id"] = session_id
        captured["cwd"] = cwd
        captured["source_tool"] = source_tool
        return True

    monkeypatch.setattr(module, "run_speakup", fake_run_speakup)

    try:
        module.main()
    except SystemExit:
        pass

    assert captured == {
        "message": "Droid is waiting for plan approval: Add AskUser questionnaire support to Droid notifications.",
        "event": "needs_input",
        "session_name": "Session Name",
        "session_key": "sess-123",
        "session_id": "sess-123",
        "cwd": "/tmp/project",
        "source_tool": "Droid",
    }
    assert saved == {"cwd": "/tmp/project", "session_key": "sess-123", "session_name": "Session Name"}
    assert (
        stdout.getvalue().strip()
        == "Session: Session Name\nReplay cmd: speakup replay 1 --agent droid --session-key sess-123"
    )


def test_main_prints_notification_summary_from_questionnaire(monkeypatch):
    module = load_hook_module()
    stdout = io.StringIO()
    captured = {}

    monkeypatch.setattr(module.sys, "stdout", stdout)
    monkeypatch.setattr(module, "load_full_config", lambda: {})
    monkeypatch.setattr(module, "load_droid_config", lambda: {"enabled": True, "events": {"notification": True}})
    monkeypatch.setattr(module, "setup_logging", lambda config: None)
    monkeypatch.setattr(module, "extract_request_id", lambda _: "req-123")
    monkeypatch.setattr(module, "extract_session_name", lambda _: None)
    monkeypatch.setattr(module.logger, "info", lambda message: None)
    monkeypatch.setattr(module.logger, "debug", lambda message: None)
    monkeypatch.setattr(
        module.json,
        "load",
        lambda _: {
            "hook_event_name": "Notification",
            "questionnaire": "1. [question] Which region should we deploy to?\n[topic] Region\n[option] us-east-1",
        },
    )

    def fake_run_speakup(message, event, session_name=None, session_key=None, session_id=None, cwd=None, source_tool=None):
        captured["message"] = message
        captured["event"] = event
        captured["session_name"] = session_name
        captured["session_key"] = session_key
        captured["session_id"] = session_id
        captured["cwd"] = cwd
        captured["source_tool"] = source_tool
        return True

    monkeypatch.setattr(module, "run_speakup", fake_run_speakup)

    try:
        module.main()
    except SystemExit:
        pass

    assert captured == {
        "message": "Which region should we deploy to?",
        "event": "needs_input",
        "session_name": None,
        "session_key": None,
        "session_id": None,
        "cwd": None,
        "source_tool": "Droid",
    }
    assert stdout.getvalue() == ""


def test_main_prints_notification_summary_from_assistant_text_envelope(monkeypatch):
    module = load_hook_module()
    stdout = io.StringIO()
    captured = {}
    saved = {}

    monkeypatch.setattr(module.sys, "stdout", stdout)
    monkeypatch.setattr(module, "load_full_config", lambda: {})
    monkeypatch.setattr(module, "load_droid_config", lambda: {"enabled": True, "events": {"notification": True}})
    monkeypatch.setattr(module, "setup_logging", lambda config: None)
    monkeypatch.setattr(module, "extract_request_id", lambda _: "req-123")
    monkeypatch.setattr(module, "extract_session_name", lambda _: "Session Name")
    monkeypatch.setattr(module, "extract_session_id", lambda _: "sess-123")
    monkeypatch.setattr(module, "extract_session_key", lambda _: "sess-123")
    monkeypatch.setattr(module, "save_current_session_pointer", lambda cwd, session_key, session_name=None: saved.update({"cwd": cwd, "session_key": session_key, "session_name": session_name}))
    monkeypatch.setattr(module.logger, "info", lambda message: None)
    monkeypatch.setattr(module.logger, "debug", lambda message: None)
    monkeypatch.setattr(
        module.json,
        "load",
        lambda _: {
            "hook_event_name": "Notification",
            "cwd": "/tmp/project",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Need your sign-off"},
                ],
            },
        },
    )

    def fake_run_speakup(message, event, session_name=None, session_key=None, session_id=None, cwd=None, source_tool=None):
        captured["message"] = message
        captured["event"] = event
        captured["session_name"] = session_name
        captured["session_key"] = session_key
        captured["session_id"] = session_id
        captured["cwd"] = cwd
        captured["source_tool"] = source_tool
        return True

    monkeypatch.setattr(module, "run_speakup", fake_run_speakup)

    try:
        module.main()
    except SystemExit:
        pass

    assert captured == {
        "message": "Need your sign-off",
        "event": "needs_input",
        "session_name": "Session Name",
        "session_key": "sess-123",
        "session_id": "sess-123",
        "cwd": "/tmp/project",
        "source_tool": "Droid",
    }
    assert saved == {"cwd": "/tmp/project", "session_key": "sess-123", "session_name": "Session Name"}
    assert (
        stdout.getvalue().strip()
        == "Session: Session Name\nReplay cmd: speakup replay 1 --agent droid --session-key sess-123"
    )


def test_main_prints_notification_summary_from_nested_tool_use_questionnaire(monkeypatch):
    module = load_hook_module()
    stdout = io.StringIO()
    captured = {}
    saved = {}

    monkeypatch.setattr(module.sys, "stdout", stdout)
    monkeypatch.setattr(module, "load_full_config", lambda: {})
    monkeypatch.setattr(module, "load_droid_config", lambda: {"enabled": True, "events": {"notification": True}})
    monkeypatch.setattr(module, "setup_logging", lambda config: None)
    monkeypatch.setattr(module, "extract_request_id", lambda _: "req-123")
    monkeypatch.setattr(module, "extract_session_name", lambda _: "Session Name")
    monkeypatch.setattr(module, "extract_session_id", lambda _: "sess-123")
    monkeypatch.setattr(module, "extract_session_key", lambda _: "sess-123")
    monkeypatch.setattr(module, "save_current_session_pointer", lambda cwd, session_key, session_name=None: saved.update({"cwd": cwd, "session_key": session_key, "session_name": session_name}))
    monkeypatch.setattr(module.logger, "info", lambda message: None)
    monkeypatch.setattr(module.logger, "debug", lambda message: None)
    monkeypatch.setattr(
        module.json,
        "load",
        lambda _: {
            "hook_event_name": "Notification",
            "cwd": "/tmp/project",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "AskUser",
                        "input": {
                            "questionnaire": (
                                "1. [question] How should the session name be shown?\n"
                                "[topic] Output format\n"
                                "[option] Separate line\n\n"
                                "2. [question] Which library should we use?\n"
                                "[topic] Library choice\n"
                                "[option] Existing"
                            )
                        },
                    }
                ],
            },
        },
    )

    def fake_run_speakup(message, event, session_name=None, session_key=None, session_id=None, cwd=None, source_tool=None):
        captured["message"] = message
        captured["event"] = event
        captured["session_name"] = session_name
        captured["session_key"] = session_key
        captured["session_id"] = session_id
        captured["cwd"] = cwd
        captured["source_tool"] = source_tool
        return True

    monkeypatch.setattr(module, "run_speakup", fake_run_speakup)

    try:
        module.main()
    except SystemExit:
        pass

    assert captured == {
        "message": "Droid needs input about Output format and Library choice.",
        "event": "needs_input",
        "session_name": "Session Name",
        "session_key": "sess-123",
        "session_id": "sess-123",
        "cwd": "/tmp/project",
        "source_tool": "Droid",
    }
    assert saved == {"cwd": "/tmp/project", "session_key": "sess-123", "session_name": "Session Name"}
    assert (
        stdout.getvalue().strip()
        == "Session: Session Name\nReplay cmd: speakup replay 1 --agent droid --session-key sess-123"
    )


def test_main_speaks_askuser_pre_tool_use_questionnaire(monkeypatch):
    module = load_hook_module()
    stdout = io.StringIO()
    captured = {}
    saved = {}

    monkeypatch.setattr(module.sys, "stdout", stdout)
    monkeypatch.setattr(module, "load_full_config", lambda: {})
    monkeypatch.setattr(module, "load_droid_config", lambda: {"enabled": True, "events": {"notification": True}})
    monkeypatch.setattr(module, "setup_logging", lambda config: None)
    monkeypatch.setattr(module, "extract_request_id", lambda _: "req-123")
    monkeypatch.setattr(module, "extract_session_name", lambda _: "Session Name")
    monkeypatch.setattr(module, "extract_session_id", lambda _: "sess-123")
    monkeypatch.setattr(module, "extract_session_key", lambda _: "sess-123")
    monkeypatch.setattr(module, "save_current_session_pointer", lambda cwd, session_key, session_name=None: saved.update({"cwd": cwd, "session_key": session_key, "session_name": session_name}))
    monkeypatch.setattr(module.logger, "info", lambda message: None)
    monkeypatch.setattr(module.logger, "debug", lambda message: None)
    monkeypatch.setattr(
        module.json,
        "load",
        lambda _: {
            "hook_event_name": "PreToolUse",
            "tool_name": "AskUser",
            "cwd": "/tmp/project",
            "tool_input": {
                "questionnaire": (
                    "1. [question] What would you like to talk about?\n"
                    "[topic] Topic\n"
                    "[option] Coding"
                ),
            },
        },
    )

    def fake_run_speakup(message, event, session_name=None, session_key=None, session_id=None, cwd=None, source_tool=None):
        captured["message"] = message
        captured["event"] = event
        captured["session_name"] = session_name
        captured["session_key"] = session_key
        captured["session_id"] = session_id
        captured["cwd"] = cwd
        captured["source_tool"] = source_tool
        return True

    monkeypatch.setattr(module, "run_speakup", fake_run_speakup)

    try:
        module.main()
    except SystemExit:
        pass

    assert captured == {
        "message": "Droid needs input about Topic.",
        "event": "needs_input",
        "session_name": "Session Name",
        "session_key": "sess-123",
        "session_id": "sess-123",
        "cwd": "/tmp/project",
        "source_tool": "Droid",
    }
    assert saved == {"cwd": "/tmp/project", "session_key": "sess-123", "session_name": "Session Name"}
    assert (
        stdout.getvalue().strip()
        == "Session: Session Name\nReplay cmd: speakup replay 1 --agent droid --session-key sess-123"
    )


def test_main_ignores_non_askuser_pre_tool_use(monkeypatch):
    module = load_hook_module()
    stdout = io.StringIO()

    monkeypatch.setattr(module.sys, "stdout", stdout)
    monkeypatch.setattr(module, "load_full_config", lambda: {})
    monkeypatch.setattr(module, "load_droid_config", lambda: {"enabled": True, "events": {"notification": True}})
    monkeypatch.setattr(module, "setup_logging", lambda config: None)
    monkeypatch.setattr(module, "extract_request_id", lambda _: "req-123")
    monkeypatch.setattr(module.logger, "info", lambda message: None)
    monkeypatch.setattr(module.logger, "debug", lambda message: None)
    monkeypatch.setattr(
        module.json,
        "load",
        lambda _: {
            "hook_event_name": "PreToolUse",
            "tool_name": "Execute",
            "tool_input": {"command": "echo hi"},
        },
    )

    called = {"run_speakup": False}

    def fake_run_speakup(*args, **kwargs):
        called["run_speakup"] = True
        return True

    monkeypatch.setattr(module, "run_speakup", fake_run_speakup)

    try:
        module.main()
    except SystemExit:
        pass

    assert called["run_speakup"] is False
    assert stdout.getvalue() == ""


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

    def fake_run_speakup(message, event, session_name=None, session_key=None, session_id=None, cwd=None, source_tool=None):
        assert message == "# Final summary text"
        assert event == "final"
        assert session_name == "Session Name"
        assert session_key is None
        assert session_id is None
        assert cwd is None
        assert source_tool == "Droid"
        return True

    monkeypatch.setattr(module, "run_speakup", fake_run_speakup)

    try:
        module.main()
    except SystemExit:
        pass

    assert stdout.getvalue() == ""


def test_main_ignores_subagent_stop_when_disabled(monkeypatch, tmp_path):
    module = load_hook_module()
    stdout = io.StringIO()
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        '{"type":"message","message":{"role":"assistant","content":[{"type":"text","text":"subagent done"}]}}\n'
    )

    monkeypatch.setattr(module.sys, "stdout", stdout)
    monkeypatch.setattr(module, "load_full_config", lambda: {})
    monkeypatch.setattr(module, "load_droid_config", lambda: {"enabled": True, "events": {"subagent_stop": False}})
    monkeypatch.setattr(module, "setup_logging", lambda config: None)
    monkeypatch.setattr(module, "extract_request_id", lambda _: "req-123")
    monkeypatch.setattr(module.logger, "info", lambda message: None)
    monkeypatch.setattr(module.logger, "debug", lambda message: None)
    monkeypatch.setattr(
        module.json,
        "load",
        lambda _: {"hook_event_name": "SubagentStop", "transcript_path": str(transcript)},
    )

    called = {"run_speakup": False}

    def fake_run_speakup(*args, **kwargs):
        called["run_speakup"] = True
        return True

    monkeypatch.setattr(module, "run_speakup", fake_run_speakup)

    try:
        module.main()
    except SystemExit:
        pass

    assert called["run_speakup"] is False
    assert stdout.getvalue() == ""


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


def test_run_speakup_dispatches_internal_background_notify(monkeypatch, tmp_path):
    module = load_hook_module()
    captured = {}
    logged = []
    config_path = tmp_path / "config.jsonc"
    config_path.write_text("{}")
    fake_request = object()

    def fake_build_request(**kwargs):
        captured["request_kwargs"] = kwargs
        return fake_request

    def fake_notify_in_background(request, *, config_path):
        captured["request"] = request
        captured["config_path"] = config_path
        return 321

    monkeypatch.setattr(module, "get_config_path", lambda: config_path)
    monkeypatch.setattr(module, "build_droid_notify_request", fake_build_request)
    monkeypatch.setattr(module, "notify_in_background", fake_notify_in_background)
    monkeypatch.setattr(module.logger, "info", lambda message: logged.append(message))

    result = module.run_speakup("hello", "info", "session name", "sess-123", "sess-123")

    assert result is True
    assert captured["request_kwargs"] == {
        "message": "hello",
        "event": "info",
        "session_name": "session name",
        "session_key": "sess-123",
        "session_id": "sess-123",
        "cwd": None,
    }
    assert captured["request"] is fake_request
    assert captured["config_path"] == config_path
    assert logged[0] == "Launching speakup internals: event=info, session=session name, session_key=sess-123, session_id=sess-123, message_len=5"
    assert logged[1] == "speakup launched successfully: pid=321"


def test_run_speakup_passes_session_id(monkeypatch, tmp_path):
    module = load_hook_module()
    captured = {}
    config_path = tmp_path / "config.jsonc"
    config_path.write_text("{}")

    def fake_build_request(**kwargs):
        captured["request_kwargs"] = kwargs
        return object()

    monkeypatch.setattr(module, "get_config_path", lambda: config_path)
    monkeypatch.setattr(module, "build_droid_notify_request", fake_build_request)
    monkeypatch.setattr(module, "notify_in_background", lambda request, *, config_path: 321)
    monkeypatch.setattr(module.logger, "info", lambda message: None)

    result = module.run_speakup("hello", "info", session_id="sess-123")

    assert result is True
    assert captured["request_kwargs"] == {
        "message": "hello",
        "event": "info",
        "session_name": None,
        "session_key": None,
        "session_id": "sess-123",
        "cwd": None,
    }


def test_run_speakup_returns_false_when_integration_missing(monkeypatch):
    module = load_hook_module()

    monkeypatch.setattr(module, "build_droid_notify_request", None)
    monkeypatch.setattr(module, "notify_in_background", None)

    assert module.run_speakup("hello", "info") is False


def test_run_speakup_returns_false_on_oserror(monkeypatch):
    module = load_hook_module()

    monkeypatch.setattr(module, "build_droid_notify_request", lambda **kwargs: object())
    monkeypatch.setattr(module, "notify_in_background", lambda request, *, config_path: (_ for _ in ()).throw(OSError("boom")))

    assert module.run_speakup("hello", "info") is False
