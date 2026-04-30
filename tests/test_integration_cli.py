from __future__ import annotations

import json
import os
import stat
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from speakup.session_naming import generate_session_name

from .conftest import run_cli
from speakup.history import NotificationHistory
from speakup.cli import _normalize_notify_payload
from speakup.models import MessageEvent, NotifyRequest, NotifyResult
from speakup.config import runtime_temp_dir


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


class _TTSVoiceSpeedEchoHandler(BaseHTTPRequestHandler):
    last_voice: str | None = None
    last_speed: float | None = None

    def do_POST(self):  # noqa: N802
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8"))
        _TTSVoiceSpeedEchoHandler.last_voice = payload.get("voice")
        _TTSVoiceSpeedEchoHandler.last_speed = payload.get("speed")
        body = b"RIFFFAKEAUDIO"
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A003
        return


def _spoken_title(session_name: str | None = None, *, agent: str = "speakup", source_tool: str | None = None) -> str:
    speaker = source_tool or agent
    if session_name:
        return f"{speaker} from session {session_name} says"
    return f"{speaker} says"


def _spoken_summary(message: str, session_name: str | None = None, *, agent: str = "speakup", source_tool: str | None = None) -> str:
    return f"{_spoken_title(session_name, agent=agent, source_tool=source_tool)} {message}"


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
    assert payload["summary"] == _spoken_summary("Could you confirm the deploy region?")
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


def test_cli_given_progress_duplicate_with_sound_only_then_plays_event_sound(
    tmp_path: Path, base_config: Path, env_with_fake_audio: dict[str, str]
) -> None:
    beep = tmp_path / "beep.aiff"
    beep.write_text("beep")
    config = json.loads(base_config.read_text())
    config["event_sounds"]["files"] = {"progress": str(beep)}
    base_config.write_text(json.dumps(config))

    args = [
        "--config",
        str(base_config),
        "--message",
        "Still indexing files",
        "--event",
        "progress",
        "--dedup-on-skip",
        "sound_only",
    ]
    first = run_cli(args, env=env_with_fake_audio)
    second = run_cli(args, env=env_with_fake_audio)

    assert first.returncode == 0
    assert second.returncode == 0

    second_payload = json.loads(second.stdout)
    assert second_payload["status"] == "ok"
    assert second_payload["summary"] == ""
    assert second_payload["played"] is True
    assert second_payload["dedup_skipped"] is True

    play_log = Path(env_with_fake_audio["PLAY_LOG"])
    lines = [ln.strip() for ln in play_log.read_text().splitlines() if ln.strip()]
    assert lines[-1] == str(beep)


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
    assert payload["played"] is True

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
    assert payload["summary"] == _spoken_summary("Done implementing the feature", "nightly-fix")


def test_cli_given_conversation_id_without_session_name_then_generates_session_name(base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    result = run_cli(
        [
            "--config",
            str(base_config),
            "--message",
            "Done implementing the feature",
            "--event",
            "final",
            "--conversation-id",
            "conv-123",
        ],
        env=env_with_fake_audio,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["summary"] == _spoken_summary("Done implementing the feature", generate_session_name("conv-123"))


def test_normalize_notify_payload_given_both_source_tool_keys_then_drops_legacy_key() -> None:
    payload = _normalize_notify_payload(
        {
            "message": "Done implementing the feature",
            "source_tool": "modern-tool",
            "sourceTool": "legacy-tool",
        }
    )

    assert payload["source_tool"] == "modern-tool"
    assert "sourceTool" not in payload


def test_cli_replay_without_filters_defaults_to_latest_replayable_message(
    tmp_path: Path,
    base_config: Path,
    env_with_fake_audio: dict[str, str],
    monkeypatch,
) -> None:
    runtime_root = tmp_path / "tmp-runtime"
    runtime_root.mkdir()
    monkeypatch.setenv("TMPDIR", str(runtime_root))
    monkeypatch.setattr(tempfile, "tempdir", None)

    history = NotificationHistory(runtime_temp_dir() / "history.db")
    older_title = tmp_path / "older-title.wav"
    older_audio = tmp_path / "older.wav"
    older_title.write_text("OLDER TITLE")
    older_audio.write_text("OLDER")
    latest_title = tmp_path / "latest-title.wav"
    latest_audio = tmp_path / "latest.wav"
    latest_title.write_text("LATEST TITLE")
    latest_audio.write_text("LATEST")
    history.add(
        NotifyRequest(
            message="Older",
            event=MessageEvent.FINAL,
            agent="pi",
            session_name="Older Session",
            session_key="sess-older",
        ),
        NotifyResult(
            status="ok",
            summary="Older summary",
            state=MessageEvent.FINAL,
            backend="macos",
            played=True,
            audio_path=older_audio,
            audio_paths=[older_title, older_audio],
        ),
        timestamp=1.0,
    )
    history.add(
        NotifyRequest(
            message="Latest",
            event=MessageEvent.ERROR,
            agent="droid",
            session_name="Latest Session",
            session_key="sess-latest",
        ),
        NotifyResult(
            status="ok",
            summary="Latest summary",
            state=MessageEvent.ERROR,
            backend="macos",
            played=True,
            audio_path=latest_audio,
            audio_paths=[latest_title, latest_audio],
        ),
        timestamp=2.0,
    )

    result = run_cli(
        ["replay", "--config", str(base_config)],
        env=env_with_fake_audio | {"TMPDIR": str(runtime_root)},
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["requested"] == 1
    assert payload["replayed"] == 1
    assert payload["from_audio"] == 1
    assert payload["agent"] == "droid"
    assert payload["session_key"] == "sess-latest"
    play_log = Path(env_with_fake_audio["PLAY_LOG"])
    assert play_log.read_text().splitlines() == [str(latest_title), str(latest_audio)]


def test_cli_replay_without_filters_returns_sessions_for_mixed_results(
    tmp_path: Path,
    base_config: Path,
    env_with_fake_audio: dict[str, str],
    monkeypatch,
) -> None:
    runtime_root = tmp_path / "tmp-runtime"
    runtime_root.mkdir()
    monkeypatch.setenv("TMPDIR", str(runtime_root))
    monkeypatch.setattr(tempfile, "tempdir", None)

    history = NotificationHistory(runtime_temp_dir() / "history.db")
    older_title = tmp_path / "older-title.wav"
    older_audio = tmp_path / "older.wav"
    older_title.write_text("OLDER TITLE")
    older_audio.write_text("OLDER")
    latest_title = tmp_path / "latest-title.wav"
    latest_audio = tmp_path / "latest.wav"
    latest_title.write_text("LATEST TITLE")
    latest_audio.write_text("LATEST")
    history.add(
        NotifyRequest(
            message="Older",
            event=MessageEvent.FINAL,
            agent="pi",
            session_name="Older Session",
            session_key="sess-older",
        ),
        NotifyResult(
            status="ok",
            summary="Older summary",
            state=MessageEvent.FINAL,
            backend="macos",
            played=True,
            audio_path=older_audio,
            audio_paths=[older_title, older_audio],
        ),
        timestamp=1.0,
    )
    history.add(
        NotifyRequest(
            message="Latest",
            event=MessageEvent.ERROR,
            agent="droid",
            session_name="Latest Session",
            session_key="sess-latest",
        ),
        NotifyResult(
            status="ok",
            summary="Latest summary",
            state=MessageEvent.ERROR,
            backend="macos",
            played=True,
            audio_path=latest_audio,
            audio_paths=[latest_title, latest_audio],
        ),
        timestamp=2.0,
    )

    result = run_cli(
        ["replay", "2", "--config", str(base_config)],
        env=env_with_fake_audio | {"TMPDIR": str(runtime_root)},
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["requested"] == 2
    assert payload["replayed"] == 2
    assert payload["from_audio"] == 2
    assert "agent" not in payload
    assert "session_key" not in payload
    assert payload["sessions"] == [
        {"agent": "droid", "session_key": "sess-latest"},
        {"agent": "pi", "session_key": "sess-older"},
    ]
    play_log = Path(env_with_fake_audio["PLAY_LOG"])
    assert play_log.read_text().splitlines() == [
        str(older_title),
        str(older_audio),
        str(latest_title),
        str(latest_audio),
    ]


def test_cli_replay_without_filters_keeps_distinct_entries_without_session_keys(
    tmp_path: Path,
    base_config: Path,
    env_with_fake_audio: dict[str, str],
    monkeypatch,
) -> None:
    runtime_root = tmp_path / "tmp-runtime"
    runtime_root.mkdir()
    monkeypatch.setenv("TMPDIR", str(runtime_root))
    monkeypatch.setattr(tempfile, "tempdir", None)

    first = run_cli(
        ["--config", str(base_config), "--message", "First", "--event", "final"],
        env=env_with_fake_audio | {"TMPDIR": str(runtime_root)},
    )
    second = run_cli(
        ["--config", str(base_config), "--message", "Second", "--event", "final"],
        env=env_with_fake_audio | {"TMPDIR": str(runtime_root)},
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr

    replay = run_cli(
        ["replay", "2", "--config", str(base_config)],
        env=env_with_fake_audio | {"TMPDIR": str(runtime_root)},
    )

    assert replay.returncode == 0, replay.stderr
    payload = json.loads(replay.stdout)
    assert payload["requested"] == 2
    assert payload["replayed"] == 2
    assert "agent" not in payload
    assert "session_key" not in payload
    assert payload["sessions"] == [
        {"agent": "speakup", "session_key": None},
        {"agent": "speakup", "session_key": None},
    ]


def test_cli_given_session_key_then_replay_finds_saved_notification(
    tmp_path: Path,
    base_config: Path,
    env_with_fake_audio: dict[str, str],
    monkeypatch,
) -> None:
    runtime_root = tmp_path / "tmp-runtime"
    runtime_root.mkdir()
    monkeypatch.setenv("TMPDIR", str(runtime_root))
    monkeypatch.setattr(tempfile, "tempdir", None)

    notify = run_cli(
        [
            "--config",
            str(base_config),
            "--message",
            "Stored for replay",
            "--event",
            "final",
            "--session-key",
            "sess-cli",
        ],
        env=env_with_fake_audio | {"TMPDIR": str(runtime_root)},
    )
    assert notify.returncode == 0, notify.stderr

    replay = run_cli(
        ["replay", "--config", str(base_config), "--agent", "speakup", "--session-key", "sess-cli"],
        env=env_with_fake_audio | {"TMPDIR": str(runtime_root)},
    )
    assert replay.returncode == 0, replay.stderr
    payload = json.loads(replay.stdout)
    assert payload["status"] == "ok"
    assert payload["replayed"] == 1
    assert payload["agent"] == "speakup"
    assert payload["session_key"] == "sess-cli"


def test_cli_replay_given_saved_audio_then_replays_exact_session_entry(
    tmp_path: Path,
    base_config: Path,
    env_with_fake_audio: dict[str, str],
    monkeypatch,
) -> None:
    runtime_root = tmp_path / "tmp-runtime"
    runtime_root.mkdir()
    monkeypatch.setenv("TMPDIR", str(runtime_root))
    monkeypatch.setattr(tempfile, "tempdir", None)

    history = NotificationHistory(runtime_temp_dir() / "history.db")
    title_audio = tmp_path / "title.wav"
    saved_audio = tmp_path / "saved.wav"
    title_audio.write_text("FAKETITLE")
    saved_audio.write_text("FAKEAUDIO")
    history.add(
        NotifyRequest(
            message="Original",
            event=MessageEvent.FINAL,
            agent="droid",
            session_name="Session Name",
            session_key="sess-123",
        ),
        NotifyResult(
            status="ok",
            summary="Stored summary",
            state=MessageEvent.FINAL,
            backend="macos",
            played=True,
            audio_path=saved_audio,
            audio_paths=[title_audio, saved_audio],
        ),
        timestamp=1.0,
    )

    result = run_cli(
        ["replay", "1", "--config", str(base_config), "--agent", "droid", "--session-key", "sess-123"],
        env=env_with_fake_audio | {"TMPDIR": str(runtime_root)},
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["replayed"] == 1
    assert payload["from_audio"] == 1
    play_log = Path(env_with_fake_audio["PLAY_LOG"])
    assert play_log.read_text().splitlines() == [str(title_audio), str(saved_audio)]


def test_cli_replay_given_saved_playback_audio_then_prefers_composed_asset(
    tmp_path: Path,
    base_config: Path,
    env_with_fake_audio: dict[str, str],
    monkeypatch,
) -> None:
    runtime_root = tmp_path / "tmp-runtime"
    runtime_root.mkdir()
    monkeypatch.setenv("TMPDIR", str(runtime_root))
    monkeypatch.setattr(tempfile, "tempdir", None)

    history = NotificationHistory(runtime_temp_dir() / "history.db")
    title_audio = tmp_path / "title.wav"
    saved_audio = tmp_path / "saved.wav"
    composed_audio = tmp_path / "composed.wav"
    title_audio.write_text("FAKETITLE")
    saved_audio.write_text("FAKEAUDIO")
    composed_audio.write_text("COMPOSED")
    history.add(
        NotifyRequest(
            message="Original",
            event=MessageEvent.FINAL,
            agent="droid",
            session_name="Session Name",
            session_key="sess-composed",
        ),
        NotifyResult(
            status="ok",
            summary="Stored summary",
            state=MessageEvent.FINAL,
            backend="macos",
            played=True,
            audio_path=saved_audio,
            audio_paths=[title_audio, saved_audio],
            playback_audio_paths=[composed_audio],
        ),
        timestamp=1.0,
    )

    result = run_cli(
        ["replay", "1", "--config", str(base_config), "--agent", "droid", "--session-key", "sess-composed"],
        env=env_with_fake_audio | {"TMPDIR": str(runtime_root)},
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["replayed"] == 1
    assert payload["from_audio"] == 1
    play_log = Path(env_with_fake_audio["PLAY_LOG"])
    assert play_log.read_text().splitlines() == [str(composed_audio)]


def test_cli_replay_given_missing_audio_then_falls_back_to_summary_without_saving_history(
    tmp_path: Path,
    base_config: Path,
    env_with_fake_audio: dict[str, str],
    monkeypatch,
) -> None:
    runtime_root = tmp_path / "tmp-runtime"
    runtime_root.mkdir()
    monkeypatch.setenv("TMPDIR", str(runtime_root))
    monkeypatch.setattr(tempfile, "tempdir", None)

    history = NotificationHistory(runtime_temp_dir() / "history.db")
    missing_title = tmp_path / "missing-title.wav"
    missing_message = tmp_path / "missing-message.wav"
    history.add(
        NotifyRequest(
            message="Original",
            event=MessageEvent.NEEDS_INPUT,
            agent="pi",
            session_name="Session Name",
            session_key="sess-456",
        ),
        NotifyResult(
            status="ok",
            summary="Stored summary",
            state=MessageEvent.NEEDS_INPUT,
            backend="macos",
            played=True,
            audio_path=missing_message,
            audio_paths=[missing_title, missing_message],
        ),
        timestamp=1.0,
    )

    result = run_cli(
        ["replay", "--config", str(base_config), "--agent", "pi", "--session-key", "sess-456"],
        env=env_with_fake_audio | {"TMPDIR": str(runtime_root)},
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["requested"] == 1
    assert payload["replayed"] == 1
    assert payload["from_summary"] == 1
    assert history.count() == 1
    play_log = Path(env_with_fake_audio["PLAY_LOG"])
    assert len(play_log.read_text().splitlines()) == 2


def test_cli_replay_given_title_only_audio_then_falls_back_to_summary(
    tmp_path: Path,
    base_config: Path,
    env_with_fake_audio: dict[str, str],
    monkeypatch,
) -> None:
    runtime_root = tmp_path / "tmp-runtime"
    runtime_root.mkdir()
    monkeypatch.setenv("TMPDIR", str(runtime_root))
    monkeypatch.setattr(tempfile, "tempdir", None)

    history = NotificationHistory(runtime_temp_dir() / "history.db")
    title_audio = tmp_path / "title.wav"
    title_audio.write_text("TITLE")
    history.add(
        NotifyRequest(
            message="Original",
            event=MessageEvent.NEEDS_INPUT,
            agent="pi",
            session_name="Session Name",
            session_key="sess-title-only",
        ),
        NotifyResult(
            status="ok",
            summary="Stored summary",
            state=MessageEvent.NEEDS_INPUT,
            backend="macos",
            played=True,
            audio_path=title_audio,
            audio_paths=[title_audio],
        ),
        timestamp=1.0,
    )

    result = run_cli(
        ["replay", "--config", str(base_config), "--agent", "pi", "--session-key", "sess-title-only"],
        env=env_with_fake_audio | {"TMPDIR": str(runtime_root)},
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["requested"] == 1
    assert payload["replayed"] == 1
    assert payload["from_audio"] == 0
    assert payload["from_summary"] == 1
    play_log = Path(env_with_fake_audio["PLAY_LOG"])
    assert len(play_log.read_text().splitlines()) == 2
    assert str(title_audio) not in play_log.read_text().splitlines()


def test_cli_replay_given_session_audio_and_empty_title_template_then_uses_saved_audio(
    tmp_path: Path,
    base_config: Path,
    env_with_fake_audio: dict[str, str],
    monkeypatch,
) -> None:
    runtime_root = tmp_path / "tmp-runtime"
    runtime_root.mkdir()
    monkeypatch.setenv("TMPDIR", str(runtime_root))
    monkeypatch.setattr(tempfile, "tempdir", None)

    config = json.loads(base_config.read_text())
    config["speech_template"] = {
        "title": {"parts": []},
        "message": {"parts": [{"field": "summary"}]},
    }
    base_config.write_text(json.dumps(config))

    history = NotificationHistory(runtime_temp_dir() / "history.db")
    message_audio = tmp_path / "message.wav"
    message_audio.write_text("MESSAGE")
    history.add(
        NotifyRequest(
            message="Original",
            event=MessageEvent.NEEDS_INPUT,
            agent="pi",
            session_name="Session Name",
            session_key="sess-no-title-template",
        ),
        NotifyResult(
            status="ok",
            summary="Stored summary",
            state=MessageEvent.NEEDS_INPUT,
            backend="macos",
            played=True,
            audio_path=message_audio,
            audio_paths=[message_audio],
        ),
        timestamp=1.0,
    )

    result = run_cli(
        ["replay", "--config", str(base_config), "--agent", "pi", "--session-key", "sess-no-title-template"],
        env=env_with_fake_audio | {"TMPDIR": str(runtime_root)},
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["requested"] == 1
    assert payload["replayed"] == 1
    assert payload["from_audio"] == 1
    assert payload["from_summary"] == 0
    play_log = Path(env_with_fake_audio["PLAY_LOG"])
    assert play_log.read_text().splitlines() == [str(message_audio)]


def test_cli_replay_given_title_only_audio_without_session_name_then_falls_back_to_summary(
    tmp_path: Path,
    base_config: Path,
    env_with_fake_audio: dict[str, str],
    monkeypatch,
) -> None:
    runtime_root = tmp_path / "tmp-runtime"
    runtime_root.mkdir()
    monkeypatch.setenv("TMPDIR", str(runtime_root))
    monkeypatch.setattr(tempfile, "tempdir", None)

    history = NotificationHistory(runtime_temp_dir() / "history.db")
    title_audio = tmp_path / "title.wav"
    title_audio.write_text("TITLE")
    history.add(
        NotifyRequest(
            message="Original",
            event=MessageEvent.NEEDS_INPUT,
            agent="pi",
            session_key="sess-title-only-no-session",
        ),
        NotifyResult(
            status="ok",
            summary=_spoken_summary("Stored summary", agent="pi"),
            state=MessageEvent.NEEDS_INPUT,
            backend="macos",
            played=True,
            audio_path=title_audio,
            audio_paths=[title_audio],
        ),
        timestamp=1.0,
    )

    result = run_cli(
        ["replay", "--config", str(base_config), "--agent", "pi", "--session-key", "sess-title-only-no-session"],
        env=env_with_fake_audio | {"TMPDIR": str(runtime_root)},
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["requested"] == 1
    assert payload["replayed"] == 1
    assert payload["from_audio"] == 0
    assert payload["from_summary"] == 1
    play_log = Path(env_with_fake_audio["PLAY_LOG"])
    assert len(play_log.read_text().splitlines()) == 2
    assert str(title_audio) not in play_log.read_text().splitlines()


def test_cli_replay_skips_history_rows_that_were_never_spoken(
    tmp_path: Path,
    base_config: Path,
    env_with_fake_audio: dict[str, str],
    monkeypatch,
) -> None:
    runtime_root = tmp_path / "tmp-runtime"
    runtime_root.mkdir()
    monkeypatch.setenv("TMPDIR", str(runtime_root))
    monkeypatch.setattr(tempfile, "tempdir", None)

    history = NotificationHistory(runtime_temp_dir() / "history.db")
    history.add(
        NotifyRequest(
            message="Still indexing files",
            event=MessageEvent.PROGRESS,
            agent="pi",
            session_name="Session Name",
            session_key="sess-789",
        ),
        NotifyResult(
            status="skipped",
            summary="",
            state=MessageEvent.PROGRESS,
            backend="none",
            played=False,
            dedup_skipped=True,
        ),
        timestamp=2.0,
    )
    history.add(
        NotifyRequest(
            message="Original",
            event=MessageEvent.NEEDS_INPUT,
            agent="pi",
            session_name="Session Name",
            session_key="sess-789",
        ),
        NotifyResult(
            status="ok",
            summary="Session Name: Stored summary",
            state=MessageEvent.NEEDS_INPUT,
            backend="macos",
            played=True,
            audio_path=tmp_path / "missing.wav",
        ),
        timestamp=1.0,
    )

    result = run_cli(
        ["replay", "--config", str(base_config), "--agent", "pi", "--session-key", "sess-789"],
        env=env_with_fake_audio | {"TMPDIR": str(runtime_root)},
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["replayed"] == 1
    assert payload["from_summary"] == 1
    assert payload["failed"] == 0


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
    env["SPEAKUP_SAY_BIN"] = str(say_script)
    env["SPEAKUP_AFPLAY_BIN"] = str(afplay_script)

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
                "Original message should be replaced by LM summary and is definitely longer than two hundred and twenty characters when repeated. Original message should be replaced by LM summary and is definitely longer than two hundred and twenty characters when repeated.",
                "--event",
                "final",
            ],
            env=env_with_fake_audio,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["summary"] == _spoken_summary("LM summary from forced provider")
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
            "Original message that is intentionally long enough to require summarization when command provider is enabled. Original message that is intentionally long enough to require summarization when command provider is enabled.",
            "--event",
            "final",
        ],
        env=env,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["summary"] == _spoken_summary("Pi summary from command")


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
    assert payload["summary"] == _spoken_summary("Original message")


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
                "Original message that is intentionally long enough to require summarization when command provider is enabled. Original message that is intentionally long enough to require summarization when command provider is enabled.",
                "--event",
                "final",
            ],
            env=env_with_fake_audio,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["summary"] == _spoken_summary("summary-model=override-summary-model")
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
                "Pi, from session named speakup",
                "--event",
                "final",
            ],
            env=env_with_fake_audio,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["summary"] == _spoken_summary("Build is complete", "Pi, from session named speakup")
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


def test_cli_given_project_provider_then_persists_project_selected_voices(tmp_path: Path, base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    _TTSVoiceSpeedEchoHandler.last_voice = None
    _TTSVoiceSpeedEchoHandler.last_speed = None
    server, port = _start_server(_TTSVoiceSpeedEchoHandler)
    try:
        project_path = tmp_path / "project"
        project_path.mkdir()
        config = json.loads(base_config.read_text())
        config["tts"]["provider_order"] = ["macos"]
        config["tts"]["project_overrides"] = {
            str(project_path.resolve()): {"provider": "lmstudio", "speed": 0.85}
        }
        config["summarization"]["provider_order"] = ["rule_based"]
        config.setdefault("providers", {})["lmstudio"] = {
            "base_url": f"http://127.0.0.1:{port}",
            "model": "base-summary-model",
            "tts_model": "base-tts-model",
            "available_voices": ["persisted-voice"],
        }
        cfg_path = tmp_path / "cfg_project_override.json"
        cfg_path.write_text(json.dumps(config))

        result = run_cli(
            [
                "--config",
                str(cfg_path),
                "--speed",
                "1.3",
                "--no-play",
                "--message",
                "Done",
                "--session-name",
                "release",
                "--event",
                "final",
            ],
            env=env_with_fake_audio,
            cwd=project_path,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["backend"] == "lmstudio"
        assert _TTSVoiceSpeedEchoHandler.last_voice == "persisted-voice"
        assert _TTSVoiceSpeedEchoHandler.last_speed == 1.3
        project_config = json.loads((project_path / ".speakup.jsonc").read_text())
        assert project_config["providers"]["lmstudio"]["title_voice"] == "persisted-voice"
        assert project_config["providers"]["lmstudio"]["message_voice"] == "persisted-voice"
    finally:
        server.shutdown()
        server.server_close()
