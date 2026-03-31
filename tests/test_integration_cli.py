from __future__ import annotations

import json
import os
import stat
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .conftest import run_cli


class _SummaryHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = b'{"choices":[{"message":{"content":"LM summary from forced provider"}}]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A003
        return


class _EmptySummaryHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = b'{"choices":[{"message":{"content":""}}]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A003
        return


class _SummaryModelEchoHandler(BaseHTTPRequestHandler):
    last_model: str | None = None

    def do_POST(self):  # noqa: N802
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8"))
        _SummaryModelEchoHandler.last_model = payload.get("model")
        summary = f"summary-model={_SummaryModelEchoHandler.last_model}"
        body = json.dumps({"choices": [{"message": {"content": summary}}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A003
        return


class _TTSModelEchoHandler(BaseHTTPRequestHandler):
    last_model: str | None = None

    def do_POST(self):  # noqa: N802
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8"))
        _TTSModelEchoHandler.last_model = payload.get("model")
        body = b'data: {"choices":[{"text":"<custom_token_50000>"}]}\n\n' + b"data: [DONE]\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A003
        return


def _start_summary_server() -> tuple[HTTPServer, int]:
    return _start_server(_SummaryHandler)


def _start_server(handler_cls: type[BaseHTTPRequestHandler]) -> tuple[HTTPServer, int]:
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def test_cli_given_needs_input_message_then_returns_spoken_summary(base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    result = run_cli(["--config", str(base_config), "--message", "Could you confirm the deploy region?", "--event", "needs_input"], env=env_with_fake_audio)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["state"] == "needs_input"
    assert payload["summary"] == "Could you confirm the deploy region?"
    assert payload["played"] is True
    assert payload["backend"] == "macos"


def test_cli_given_progress_duplicate_then_skips_second_time(base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    args = ["--config", str(base_config), "--message", "Still indexing files", "--event", "progress"]
    first = run_cli(args, env=env_with_fake_audio)
    second = run_cli(args, env=env_with_fake_audio)

    assert first.returncode == 0
    assert second.returncode == 0

    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)

    assert first_payload["status"] == "ok"
    assert second_payload["status"] == "skipped"
    assert second_payload["dedup_skipped"] is True


def test_cli_given_event_sound_mapping_then_plays_sound_and_tts(tmp_path: Path, base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    beep = tmp_path / "beep.aiff"
    beep.write_text("beep")

    config = json.loads(base_config.read_text())
    config["event_sounds"]["files"] = {"error": str(beep)}
    base_config.write_text(json.dumps(config))

    result = run_cli(["--config", str(base_config), "--message", "Build failed due to timeout", "--event", "error"], env=env_with_fake_audio)
    assert result.returncode == 0

    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"

    play_log = Path(env_with_fake_audio["PLAY_LOG"])
    lines = [ln.strip() for ln in play_log.read_text().splitlines() if ln.strip()]
    assert str(beep) in lines
    assert any("tts-" in line for line in lines)


def test_cli_given_session_name_then_prefixes_spoken_summary(base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    result = run_cli(
        [
            "--config",
            str(base_config),
            "--message",
            "Done implementing the feature",
            "--event",
            "final",
            "--session-name",
            "nightly-fix",
        ],
        env=env_with_fake_audio,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["summary"] == "nightly-fix: Done implementing the feature"


def test_cli_given_playback_failure_then_returns_partial_success(tmp_path: Path, base_config: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    say_script = bin_dir / "say"
    say_script.write_text(
        "#!/bin/sh\n"
        "OUT=\"\"\n"
        "while [ $# -gt 0 ]; do\n"
        "  if [ \"$1\" = \"-o\" ]; then\n"
        "    shift\n"
        "    OUT=\"$1\"\n"
        "  fi\n"
        "  shift\n"
        "done\n"
        "echo 'FAKEAUDIO' > \"$OUT\"\n"
    )
    say_script.chmod(say_script.stat().st_mode | stat.S_IEXEC)

    afplay_script = bin_dir / "afplay"
    afplay_script.write_text("#!/bin/sh\nexit 1\n")
    afplay_script.chmod(afplay_script.stat().st_mode | stat.S_IEXEC)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

    result = run_cli(["--config", str(base_config), "--message", "Done", "--event", "final"], env=env)
    assert result.returncode == 0

    payload = json.loads(result.stdout)
    assert payload["status"] == "partial_success"
    assert payload["played"] is False
    assert payload["backend"] == "macos"
    assert payload["error"] is not None


def test_cli_given_forced_tts_provider_then_uses_it_over_config_order(tmp_path: Path, base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    config = json.loads(base_config.read_text())
    config["tts"]["provider_order"] = ["lmstudio"]
    cfg_path = tmp_path / "cfg_force_tts.json"
    cfg_path.write_text(json.dumps(config))

    result = run_cli(
        [
            "--config",
            str(cfg_path),
            "--tts-provider",
            "macos",
            "--message",
            "Done",
            "--event",
            "final",
        ],
        env=env_with_fake_audio,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["backend"] == "macos"


def test_cli_given_forced_summary_provider_then_uses_it_over_config_order(tmp_path: Path, base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    server, port = _start_summary_server()
    try:
        config = json.loads(base_config.read_text())
        config["summarization"]["provider_order"] = ["rule_based"]
        config.setdefault("providers", {})["lmstudio"] = {
            "base_url": f"http://127.0.0.1:{port}",
            "model": "fake",
            "tts_model": "fake-tts",
        }
        cfg_path = tmp_path / "cfg_force_summary.json"
        cfg_path.write_text(json.dumps(config))

        result = run_cli(
            [
                "--config",
                str(cfg_path),
                "--summary-provider",
                "lmstudio",
                "--message",
                "Original message should be replaced by LM summary",
                "--event",
                "final",
            ],
            env=env_with_fake_audio,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["summary"] == "LM summary from forced provider"
    finally:
        server.shutdown()
        server.server_close()


def test_cli_given_command_summary_provider_then_uses_pi_command_output(tmp_path: Path, base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    pi_script = bin_dir / "pi"
    pi_script.write_text("#!/bin/sh\necho 'Pi summary from command'\n")
    pi_script.chmod(pi_script.stat().st_mode | stat.S_IEXEC)

    env = dict(env_with_fake_audio)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

    config = json.loads(base_config.read_text())
    config["summarization"]["provider_order"] = ["command", "rule_based"]
    config.setdefault("providers", {})["command_summary"] = {
        "command": "pi",
        "args": ["-p", "{message}"],
        "timeout_seconds": 5,
        "trim_output": True,
    }
    cfg_path = tmp_path / "cfg_command_summary.json"
    cfg_path.write_text(json.dumps(config))

    result = run_cli(
        [
            "--config",
            str(cfg_path),
            "--message",
            "Original message",
            "--event",
            "final",
        ],
        env=env,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["summary"] == "Pi summary from command"


def test_cli_given_failing_command_summary_then_falls_back_to_rule_based(tmp_path: Path, base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    pi_script = bin_dir / "pi"
    pi_script.write_text("#!/bin/sh\necho 'broken' >&2\nexit 7\n")
    pi_script.chmod(pi_script.stat().st_mode | stat.S_IEXEC)

    env = dict(env_with_fake_audio)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

    config = json.loads(base_config.read_text())
    config["summarization"]["provider_order"] = ["command", "rule_based"]
    config.setdefault("providers", {})["command_summary"] = {
        "command": "pi",
        "args": ["-p", "{message}"],
        "timeout_seconds": 5,
        "trim_output": True,
    }
    cfg_path = tmp_path / "cfg_command_summary_fallback.json"
    cfg_path.write_text(json.dumps(config))

    result = run_cli(
        [
            "--config",
            str(cfg_path),
            "--message",
            "Original message",
            "--event",
            "final",
        ],
        env=env,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["summary"] == "Original message"


def test_cli_given_summary_model_override_then_lmstudio_uses_it(tmp_path: Path, base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    _SummaryModelEchoHandler.last_model = None
    server, port = _start_server(_SummaryModelEchoHandler)
    try:
        config = json.loads(base_config.read_text())
        config["summarization"]["provider_order"] = ["lmstudio"]
        config.setdefault("providers", {})["lmstudio"] = {
            "base_url": f"http://127.0.0.1:{port}",
            "model": "base-summary-model",
            "tts_model": "base-tts-model",
        }
        cfg_path = tmp_path / "cfg_summary_model.json"
        cfg_path.write_text(json.dumps(config))

        result = run_cli(
            [
                "--config",
                str(cfg_path),
                "--summary-model",
                "override-summary-model",
                "--message",
                "Original message",
                "--event",
                "final",
            ],
            env=env_with_fake_audio,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["summary"] == "summary-model=override-summary-model"
        assert _SummaryModelEchoHandler.last_model == "override-summary-model"
    finally:
        server.shutdown()
        server.server_close()


def test_cli_given_empty_lmstudio_summary_then_falls_back_to_rule_based_and_keeps_session_prefix(tmp_path: Path, base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    server, port = _start_server(_EmptySummaryHandler)
    try:
        config = json.loads(base_config.read_text())
        config["summarization"]["provider_order"] = ["lmstudio", "rule_based"]
        config.setdefault("providers", {})["lmstudio"] = {
            "base_url": f"http://127.0.0.1:{port}",
            "model": "fake",
        }
        cfg_path = tmp_path / "cfg_empty_summary.json"
        cfg_path.write_text(json.dumps(config))

        result = run_cli(
            [
                "--config",
                str(cfg_path),
                "--message",
                "Build is complete",
                "--session-name",
                "Pi, from session named let-me-know-agent",
                "--event",
                "final",
            ],
            env=env_with_fake_audio,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["summary"] == "Pi, from session named let-me-know-agent: Build is complete"
    finally:
        server.shutdown()
        server.server_close()


def test_cli_given_tts_model_override_then_lmstudio_uses_it(tmp_path: Path, base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    _TTSModelEchoHandler.last_model = None
    server, port = _start_server(_TTSModelEchoHandler)
    try:
        config = json.loads(base_config.read_text())
        config["tts"]["provider_order"] = ["lmstudio", "macos"]
        config["summarization"]["provider_order"] = ["rule_based"]
        config.setdefault("providers", {})["lmstudio"] = {
            "base_url": f"http://127.0.0.1:{port}",
            "model": "base-summary-model",
            "tts_model": "base-tts-model",
            "tts_mode": "orpheus_completions",
        }
        cfg_path = tmp_path / "cfg_tts_model.json"
        cfg_path.write_text(json.dumps(config))

        result = run_cli(
            [
                "--config",
                str(cfg_path),
                "--tts-model",
                "override-tts-model",
                "--no-play",
                "--message",
                "Done",
                "--event",
                "final",
            ],
            env=env_with_fake_audio,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["backend"] == "macos"
        assert _TTSModelEchoHandler.last_model == "override-tts-model"
    finally:
        server.shutdown()
        server.server_close()
