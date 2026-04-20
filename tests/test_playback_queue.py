from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from speakup.config import Config, default_config
from speakup.errors import AdapterError
from speakup.models import AudioResult, MessageEvent, NotifyRequest
from speakup.playback.base import PlaybackAdapter
from speakup.playback.queued import SQLiteQueuedPlayback
from speakup.registry import AdapterRegistry
from speakup.session_naming import generate_session_name
from speakup.service import NotifyService
from speakup.tts.base import TTSAdapter


class _RecordingPlayback(PlaybackAdapter):
    name = "recording"

    def __init__(self) -> None:
        self.calls: list[Path] = []
        self.groups: list[list[Path]] = []

    def play_file(self, path: Path) -> None:
        self.calls.append(path)

    def play_files(self, paths):
        group = [Path(path) for path in paths]
        self.groups.append(group)
        self.calls.extend(group)


class _BlockingPlayback(PlaybackAdapter):
    name = "blocking"

    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self.started = started
        self.release = release
        self.calls: list[Path] = []

    def play_file(self, path: Path) -> None:
        self.calls.append(path)
        if len(self.calls) == 1:
            self.started.set()
            assert self.release.wait(timeout=2)


class _FailOnPathPlayback(PlaybackAdapter):
    name = "fail_on_path"

    def __init__(self, bad_path: Path) -> None:
        self.bad_path = bad_path
        self.calls: list[Path] = []

    def play_file(self, path: Path) -> None:
        self.calls.append(path)
        if path == self.bad_path:
            raise AdapterError("boom")


class _FakeTTS(TTSAdapter):
    name = "fake"

    def __init__(self, audio_paths: list[Path]) -> None:
        self.audio_paths = audio_paths
        self.calls: list[tuple[str, str, float]] = []

    def synthesize(self, text: str, output_dir: Path, *, voice: str = "default", speed: float = 1.0, audio_format: str = "mp3") -> AudioResult:
        audio_path = self.audio_paths[len(self.calls)]
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_text(text)
        self.calls.append((text, voice, speed))
        return AudioResult(kind="file", value=str(audio_path), provider=self.name)


class _FailingTTS(TTSAdapter):
    name = "broken"

    def synthesize(self, text: str, output_dir: Path, *, voice: str = "default", speed: float = 1.0, audio_format: str = "mp3") -> AudioResult:
        raise AdapterError("broken")


class _TitleOnlyTTS(TTSAdapter):
    name = "title_only"

    def __init__(self, title_audio: Path) -> None:
        self.title_audio = title_audio
        self.calls: list[tuple[str, str]] = []

    def synthesize(self, text: str, output_dir: Path, *, voice: str = "default", speed: float = 1.0, audio_format: str = "mp3") -> AudioResult:
        self.calls.append((text, voice))
        if len(self.calls) > 1:
            raise AdapterError("message failed")
        self.title_audio.parent.mkdir(parents=True, exist_ok=True)
        self.title_audio.write_text(text)
        return AudioResult(kind="file", value=str(self.title_audio), provider=self.name)


def test_sqlite_queue_given_busy_worker_then_enqueue_returns_and_owner_drains(tmp_path: Path) -> None:
    db_path = tmp_path / "queue.db"
    first_audio = tmp_path / "first.wav"
    second_audio = tmp_path / "second.wav"
    first_audio.write_text("one")
    second_audio.write_text("two")

    started = threading.Event()
    release = threading.Event()
    blocking_inner = _BlockingPlayback(started, release)
    worker_queue = SQLiteQueuedPlayback(blocking_inner, db_path)
    other_queue = SQLiteQueuedPlayback(_RecordingPlayback(), db_path)

    thread = threading.Thread(target=worker_queue.play_file, args=(first_audio,))
    thread.start()
    assert started.wait(timeout=1)

    started_at = time.monotonic()
    other_queue.play_file(second_audio)
    elapsed = time.monotonic() - started_at

    release.set()
    thread.join(timeout=2)

    assert elapsed < 1.0
    assert blocking_inner.calls == [first_audio, second_audio]


def test_sqlite_queue_given_failed_job_then_marks_failed_and_does_not_replay(tmp_path: Path) -> None:
    db_path = tmp_path / "queue.db"
    bad_audio = tmp_path / "bad.wav"
    good_audio = tmp_path / "good.wav"
    bad_audio.write_text("bad")
    good_audio.write_text("good")

    inner = _FailOnPathPlayback(bad_audio)
    queue = SQLiteQueuedPlayback(inner, db_path)

    try:
        queue.play_file(bad_audio)
    except AdapterError:
        pass
    queue.play_file(good_audio)

    assert inner.calls == [bad_audio, good_audio]

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT payload, state, last_error FROM jobs ORDER BY id").fetchall()

    payloads = [json.loads(payload) for payload, _, _ in rows]
    states = [state for _, state, _ in rows]
    errors = [error for _, _, error in rows]

    assert payloads == [[str(bad_audio)], [str(good_audio)]]
    assert states == ["failed", "done"]
    assert errors[0] == "boom"
    assert errors[1] is None


def test_sqlite_queue_given_stale_processing_job_then_recovers_it(tmp_path: Path) -> None:
    db_path = tmp_path / "queue.db"
    stale_audio = tmp_path / "stale.wav"
    fresh_audio = tmp_path / "fresh.wav"
    stale_audio.write_text("stale")
    fresh_audio.write_text("fresh")

    inner = _RecordingPlayback()
    queue = SQLiteQueuedPlayback(inner, db_path, stale_processing_timeout_seconds=0.01)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE worker_lock SET owner_id = ?, owner_pid = ?, claimed_at = ? WHERE name = ?",
            ("dead-owner", 999999, time.time() - 10, "playback"),
        )
        conn.execute(
            """
            INSERT INTO jobs (payload, state, created_at, claimed_at)
            VALUES (?, 'processing', ?, ?)
            """,
            (json.dumps([str(stale_audio)]), time.time() - 10, time.time() - 10),
        )

    queue.play_file(fresh_audio)

    assert inner.calls == [stale_audio, fresh_audio]


def test_notify_service_given_event_sound_then_plays_cue_and_speech_together(tmp_path: Path) -> None:
    beep = tmp_path / "beep.aiff"
    speech = tmp_path / "speech.wav"
    beep.write_text("beep")

    config_data = default_config()
    config_data["tts"]["provider_order"] = ["fake"]
    config_data["tts"]["save_audio_dir"] = str(tmp_path / "audio")
    config_data["event_sounds"]["files"] = {"error": str(beep)}
    config_data["playback"]["queue_enabled"] = True
    config = Config(config_data)

    registry = AdapterRegistry()
    playback = _RecordingPlayback()
    registry.set_playback(playback)
    registry.register_tts("fake", lambda: _FakeTTS([speech]))

    service = NotifyService(config, registry=registry)
    result = service.notify(
        NotifyRequest(
            message="Build failed",
            event=MessageEvent.ERROR,
            skip_summarization=True,
        )
    )

    assert result.status == "ok"
    assert result.played is True
    assert playback.groups == [[beep, speech]]


def test_notify_service_given_short_message_then_sanitizes_text_before_tts(tmp_path: Path) -> None:
    message_audio = tmp_path / "message.wav"

    config_data = default_config()
    config_data["tts"]["provider_order"] = ["fake"]
    config_data["event_sounds"]["enabled"] = False
    config_data["summarization"]["max_chars"] = 400
    config = Config(config_data)

    registry = AdapterRegistry()
    playback = _RecordingPlayback()
    fake_tts = _FakeTTS([message_audio])
    registry.set_playback(playback)
    registry.register_tts("fake", lambda: fake_tts)

    service = NotifyService(config, registry=registry)
    result = service.notify(
        NotifyRequest(
            message="# Release Update\n- shipped commit deadbeef\n- []",
            event=MessageEvent.FINAL,
        )
    )

    assert result.status == "ok"
    assert result.summary == "Release Update. shipped commit d e a d"
    assert fake_tts.calls == [("Release Update. shipped commit d e a d", "default", 1.0)]


def test_notify_service_given_precomputed_summary_then_sanitizes_before_tts(tmp_path: Path) -> None:
    message_audio = tmp_path / "message.wav"

    config_data = default_config()
    config_data["tts"]["provider_order"] = ["fake"]
    config_data["event_sounds"]["enabled"] = False
    config = Config(config_data)

    registry = AdapterRegistry()
    playback = _RecordingPlayback()
    fake_tts = _FakeTTS([message_audio])
    registry.set_playback(playback)
    registry.register_tts("fake", lambda: fake_tts)

    service = NotifyService(config, registry=registry)
    result = service.notify(
        NotifyRequest(
            message="Original message",
            precomputed_summary="[] sha deadbeef",
            event=MessageEvent.FINAL,
        )
    )

    assert result.status == "ok"
    assert result.summary == "sha d e a d"
    assert fake_tts.calls == [("sha d e a d", "default", 1.0)]


def test_notify_service_given_empty_spoken_text_then_uses_event_fallback(tmp_path: Path) -> None:
    message_audio = tmp_path / "message.wav"

    config_data = default_config()
    config_data["tts"]["provider_order"] = ["fake"]
    config_data["event_sounds"]["enabled"] = False
    config = Config(config_data)

    registry = AdapterRegistry()
    playback = _RecordingPlayback()
    fake_tts = _FakeTTS([message_audio])
    registry.set_playback(playback)
    registry.register_tts("fake", lambda: fake_tts)

    service = NotifyService(config, registry=registry)
    result = service.notify(
        NotifyRequest(
            message="[]",
            session_name="[]",
            event=MessageEvent.NEEDS_INPUT,
            skip_summarization=True,
        )
    )

    assert result.status == "ok"
    assert result.summary == "Input needed"
    assert fake_tts.calls == [("Input needed", "default", 1.0)]


def test_notify_service_given_session_name_then_plays_title_and_message_with_split_voices(tmp_path: Path) -> None:
    title_audio = tmp_path / "title.wav"
    message_audio = tmp_path / "message.wav"

    config_data = default_config()
    config_data["tts"]["provider_order"] = ["fake"]
    config_data["event_sounds"]["enabled"] = False
    config_data["providers"]["fake"] = {"title_voice": "provider-title", "message_voice": "provider-message"}
    config = Config(config_data)

    registry = AdapterRegistry()
    playback = _RecordingPlayback()
    fake_tts = _FakeTTS([title_audio, message_audio])
    registry.set_playback(playback)
    registry.register_tts("fake", lambda: fake_tts)

    service = NotifyService(config, registry=registry)
    result = service.notify(
        NotifyRequest(
            message="Build failed",
            event=MessageEvent.ERROR,
            session_name="Nightly Run",
            skip_summarization=True,
        )
    )

    assert result.status == "ok"
    assert result.summary == "Nightly Run: Build failed"
    assert playback.groups == [[title_audio, message_audio]]
    assert fake_tts.calls == [("Nightly Run", "provider-title", 1.0), ("Build failed", "provider-message", 1.0)]


def test_notify_service_given_empty_session_name_and_conversation_id_then_generates_title(tmp_path: Path) -> None:
    title_audio = tmp_path / "title.wav"
    message_audio = tmp_path / "message.wav"

    config_data = default_config()
    config_data["tts"]["provider_order"] = ["fake"]
    config_data["event_sounds"]["enabled"] = False
    config_data["providers"]["fake"] = {"title_voice": "provider-title", "message_voice": "provider-message"}
    config = Config(config_data)

    registry = AdapterRegistry()
    playback = _RecordingPlayback()
    fake_tts = _FakeTTS([title_audio, message_audio])
    registry.set_playback(playback)
    registry.register_tts("fake", lambda: fake_tts)

    service = NotifyService(config, registry=registry)
    result = service.notify(
        NotifyRequest(
            message="Build failed",
            event=MessageEvent.ERROR,
            session_name="",
            conversation_id="conv-123",
            skip_summarization=True,
        )
    )

    generated = generate_session_name("conv-123")
    assert generated is not None
    assert result.status == "ok"
    assert result.summary == f"{generated}: Build failed"
    assert playback.groups == [[title_audio, message_audio]]
    assert fake_tts.calls == [(generated, "provider-title", 1.0), ("Build failed", "provider-message", 1.0)]


def test_replay_summary_given_prefixed_summary_then_does_not_duplicate_session_name(tmp_path: Path) -> None:
    message_audio = tmp_path / "message.wav"

    config_data = default_config()
    config_data["tts"]["provider_order"] = ["fake"]
    config_data["event_sounds"]["enabled"] = False
    config_data["providers"]["fake"] = {"title_voice": "provider-title", "message_voice": "provider-message"}
    config = Config(config_data)

    registry = AdapterRegistry()
    playback = _RecordingPlayback()
    fake_tts = _FakeTTS([message_audio])
    registry.set_playback(playback)
    registry.register_tts("fake", lambda: fake_tts)

    service = NotifyService(config, registry=registry)
    result = service.replay_summary(summary="Nightly Run: Build failed", event=MessageEvent.ERROR)

    assert result.status == "ok"
    assert result.summary == "Nightly Run: Build failed"
    assert playback.groups == [[message_audio]]
    assert fake_tts.calls == [("Nightly Run: Build failed", "provider-message", 1.0)]


def test_replay_summary_given_session_name_and_prefixed_summary_then_replays_title_and_message_once(tmp_path: Path) -> None:
    title_audio = tmp_path / "title.wav"
    message_audio = tmp_path / "message.wav"

    config_data = default_config()
    config_data["tts"]["provider_order"] = ["fake"]
    config_data["event_sounds"]["enabled"] = False
    config_data["providers"]["fake"] = {"title_voice": "provider-title", "message_voice": "provider-message"}
    config = Config(config_data)

    registry = AdapterRegistry()
    playback = _RecordingPlayback()
    fake_tts = _FakeTTS([title_audio, message_audio])
    registry.set_playback(playback)
    registry.register_tts("fake", lambda: fake_tts)

    service = NotifyService(config, registry=registry)
    result = service.replay_summary(
        summary="Nightly Run: Build failed",
        event=MessageEvent.ERROR,
        session_name="Nightly Run",
    )

    assert result.status == "ok"
    assert result.summary == "Nightly Run: Build failed"
    assert result.audio_path == message_audio
    assert result.audio_paths == [title_audio, message_audio]
    assert playback.groups == [[title_audio, message_audio]]
    assert fake_tts.calls == [("Nightly Run", "provider-title", 1.0), ("Build failed", "provider-message", 1.0)]


def test_notify_service_given_split_speeds_then_uses_role_specific_speeds(tmp_path: Path) -> None:
    title_audio = tmp_path / "title.wav"
    message_audio = tmp_path / "message.wav"

    config_data = default_config()
    config_data["tts"]["provider_order"] = ["fake"]
    config_data["tts"]["speed"] = 1.0
    config_data["tts"]["session_name_speed"] = 0.9
    config_data["tts"]["message_speed"] = 1.2
    config_data["event_sounds"]["enabled"] = False
    config_data["providers"]["fake"] = {"title_voice": "provider-title", "message_voice": "provider-message"}
    config = Config(config_data)

    registry = AdapterRegistry()
    playback = _RecordingPlayback()
    fake_tts = _FakeTTS([title_audio, message_audio])
    registry.set_playback(playback)
    registry.register_tts("fake", lambda: fake_tts)

    service = NotifyService(config, registry=registry)
    result = service.notify(
        NotifyRequest(
            message="Build failed",
            event=MessageEvent.ERROR,
            session_name="Nightly Run",
            skip_summarization=True,
        )
    )

    assert result.status == "ok"
    assert fake_tts.calls == [("Nightly Run", "provider-title", 0.9), ("Build failed", "provider-message", 1.2)]


def test_notify_service_given_missing_message_voice_then_falls_back_to_default_voice(tmp_path: Path) -> None:
    title_audio = tmp_path / "title.wav"
    message_audio = tmp_path / "message.wav"

    config_data = default_config()
    config_data["tts"]["provider_order"] = ["fake"]
    config_data["tts"]["voice"] = "default-voice"
    config_data["event_sounds"]["enabled"] = False
    config_data["providers"]["fake"] = {"title_voice": "title-voice"}
    config = Config(config_data)

    registry = AdapterRegistry()
    playback = _RecordingPlayback()
    fake_tts = _FakeTTS([title_audio, message_audio])
    registry.set_playback(playback)
    registry.register_tts("fake", lambda: fake_tts)

    service = NotifyService(config, registry=registry)
    result = service.notify(
        NotifyRequest(
            message="Ship it",
            event=MessageEvent.FINAL,
            session_name="Release 42",
            skip_summarization=True,
        )
    )

    assert result.status == "ok"
    assert fake_tts.calls == [("Release 42", "title-voice", 1.0), ("Ship it", "default-voice", 1.0)]


def test_notify_service_given_project_provider_then_picks_and_persists_project_voices(tmp_path: Path, monkeypatch) -> None:
    message_audio = tmp_path / "message.wav"
    title_audio = tmp_path / "title.wav"
    project_path = (tmp_path / "project").resolve()
    project_path.mkdir()
    chosen_voices = iter(["provider-title", "provider-message"])

    config_data = default_config()
    config_data["tts"]["provider_order"] = ["macos"]
    config_data["tts"]["speed"] = 1.0
    config_data["tts"]["project_overrides"] = {
        str(project_path): {"provider": "fake", "speed": 1.25}
    }
    config_data["providers"]["fake"] = {"available_voices": ["provider-title", "provider-message"]}
    config_data["event_sounds"]["enabled"] = False
    config = Config(config_data)

    registry = AdapterRegistry()
    playback = _RecordingPlayback()
    fake_tts = _FakeTTS([title_audio, message_audio])
    registry.set_playback(playback)
    registry.register_tts("fake", lambda: fake_tts)
    monkeypatch.setattr("speakup.service.random.choice", lambda voices: next(chosen_voices))

    service = NotifyService(config, registry=registry)
    result = service.notify(
        NotifyRequest(
            message="Ship it",
            event=MessageEvent.FINAL,
            session_name="Release 42",
            skip_summarization=True,
            metadata={"cwd": str(project_path)},
        )
    )

    assert result.status == "ok"
    assert fake_tts.calls == [("Release 42", "provider-title", 1.25), ("Ship it", "provider-message", 1.25)]
    project_config = json.loads((project_path / ".speakup.jsonc").read_text())
    assert project_config["providers"]["fake"]["title_voice"] == "provider-title"
    assert project_config["providers"]["fake"]["message_voice"] == "provider-message"


def test_notify_service_given_persisted_project_voices_then_reuses_them(tmp_path: Path, monkeypatch) -> None:
    message_audio = tmp_path / "message.wav"
    title_audio = tmp_path / "title.wav"
    project_path = (tmp_path / "project").resolve()
    project_path.mkdir()
    (project_path / ".speakup.jsonc").write_text(json.dumps({
        "providers": {
            "fake": {
                "title_voice": "saved-title",
                "message_voice": "saved-message",
            }
        }
    }))

    config_data = default_config()
    config_data["tts"]["provider_order"] = ["macos"]
    config_data["tts"]["speed"] = 0.9
    config_data["tts"]["project_overrides"] = {
        str(project_path): {"provider": "fake", "speed": 1.25}
    }
    config_data["providers"]["fake"] = {"available_voices": ["provider-title", "provider-message"]}
    config_data["event_sounds"]["enabled"] = False
    config = Config(config_data)

    registry = AdapterRegistry()
    playback = _RecordingPlayback()
    fake_tts = _FakeTTS([title_audio, message_audio])
    registry.set_playback(playback)
    registry.register_tts("fake", lambda: fake_tts)
    monkeypatch.setattr("speakup.service.random.choice", lambda voices: (_ for _ in ()).throw(AssertionError("random.choice should not be called")))

    service = NotifyService(config, registry=registry)
    result = service.notify(
        NotifyRequest(
            message="Ship it",
            event=MessageEvent.FINAL,
            session_name="Release 42",
            skip_summarization=True,
            metadata={"cwd": str(project_path)},
        )
    )

    assert result.status == "ok"
    assert fake_tts.calls == [("Release 42", "saved-title", 1.25), ("Ship it", "saved-message", 1.25)]


def test_notify_service_given_non_object_project_config_then_recovers_and_persists_voices(tmp_path: Path, monkeypatch) -> None:
    message_audio = tmp_path / "message.wav"
    title_audio = tmp_path / "title.wav"
    project_path = (tmp_path / "project").resolve()
    project_path.mkdir()
    (project_path / ".speakup.jsonc").write_text("[]")
    chosen_voices = iter(["provider-title", "provider-message"])

    config_data = default_config()
    config_data["tts"]["provider_order"] = ["macos"]
    config_data["tts"]["project_overrides"] = {
        str(project_path): {"provider": "fake", "speed": 1.1}
    }
    config_data["providers"]["fake"] = {"available_voices": ["provider-title", "provider-message"]}
    config_data["event_sounds"]["enabled"] = False
    config = Config(config_data)

    registry = AdapterRegistry()
    playback = _RecordingPlayback()
    fake_tts = _FakeTTS([title_audio, message_audio])
    registry.set_playback(playback)
    registry.register_tts("fake", lambda: fake_tts)
    monkeypatch.setattr("speakup.service.random.choice", lambda voices: next(chosen_voices))

    service = NotifyService(config, registry=registry)
    result = service.notify(
        NotifyRequest(
            message="Ship it",
            event=MessageEvent.FINAL,
            session_name="Release 42",
            skip_summarization=True,
            metadata={"cwd": str(project_path)},
        )
    )

    assert result.status == "ok"
    assert fake_tts.calls == [("Release 42", "provider-title", 1.1), ("Ship it", "provider-message", 1.1)]
    project_config = json.loads((project_path / ".speakup.jsonc").read_text())
    assert project_config["providers"]["fake"]["title_voice"] == "provider-title"
    assert project_config["providers"]["fake"]["message_voice"] == "provider-message"


def test_notify_service_given_empty_available_voices_then_falls_back_to_provider_default(tmp_path: Path) -> None:
    message_audio = tmp_path / "message.wav"
    project_path = (tmp_path / "project").resolve()
    project_path.mkdir()

    config_data = default_config()
    config_data["tts"]["provider_order"] = ["macos"]
    config_data["tts"]["project_overrides"] = {
        str(project_path): {"provider": "fake", "speed": 0.9}
    }
    config_data["providers"]["fake"] = {"voice": "provider-default", "available_voices": []}
    config_data["event_sounds"]["enabled"] = False
    config = Config(config_data)

    registry = AdapterRegistry()
    playback = _RecordingPlayback()
    fake_tts = _FakeTTS([message_audio])
    registry.set_playback(playback)
    registry.register_tts("fake", lambda: fake_tts)

    service = NotifyService(config, registry=registry)
    result = service.notify(
        NotifyRequest(
            message="Ship it",
            event=MessageEvent.FINAL,
            skip_summarization=True,
            metadata={"cwd": str(project_path)},
        )
    )

    assert result.status == "ok"
    assert fake_tts.calls == [("Ship it", "provider-default", 0.9)]


def test_notify_service_given_cli_speed_then_overrides_split_speeds(tmp_path: Path) -> None:
    title_audio = tmp_path / "title.wav"
    message_audio = tmp_path / "message.wav"

    config_data = default_config()
    config_data["tts"]["provider_order"] = ["fake"]
    config_data["tts"]["speed"] = 1.0
    config_data["tts"]["session_name_speed"] = 0.9
    config_data["tts"]["message_speed"] = 1.2
    config_data["event_sounds"]["enabled"] = False
    config_data["providers"]["fake"] = {"title_voice": "provider-title", "message_voice": "provider-message"}
    config = Config(config_data)

    registry = AdapterRegistry()
    playback = _RecordingPlayback()
    fake_tts = _FakeTTS([title_audio, message_audio])
    registry.set_playback(playback)
    registry.register_tts("fake", lambda: fake_tts)

    service = NotifyService(config, registry=registry)
    result = service.notify(
        NotifyRequest(
            message="Build failed",
            event=MessageEvent.ERROR,
            session_name="Nightly Run",
            skip_summarization=True,
            metadata={"cli_speed": 2.0},
        )
    )

    assert result.status == "ok"
    assert fake_tts.calls == [("Nightly Run", "provider-title", 2.0), ("Build failed", "provider-message", 2.0)]


def test_notify_service_given_first_provider_failure_then_uses_next_provider_specific_voices(tmp_path: Path) -> None:
    title_audio = tmp_path / "title.wav"
    message_audio = tmp_path / "message.wav"

    config_data = default_config()
    config_data["tts"]["provider_order"] = ["broken", "fake"]
    config_data["tts"]["voice"] = "global-default"
    config_data["event_sounds"]["enabled"] = False
    config_data["providers"]["fake"] = {"title_voice": "provider-title", "message_voice": "provider-message"}
    config = Config(config_data)

    registry = AdapterRegistry()
    playback = _RecordingPlayback()
    fake_tts = _FakeTTS([title_audio, message_audio])
    registry.set_playback(playback)
    registry.register_tts("broken", lambda: _FailingTTS())
    registry.register_tts("fake", lambda: fake_tts)

    service = NotifyService(config, registry=registry)
    result = service.notify(
        NotifyRequest(
            message="Build failed",
            event=MessageEvent.ERROR,
            session_name="Nightly Run",
            skip_summarization=True,
        )
    )

    assert result.status == "ok"
    assert result.backend == "fake"
    assert fake_tts.calls == [("Nightly Run", "provider-title", 1.0), ("Build failed", "provider-message", 1.0)]


def test_notify_service_given_elevenlabs_split_voices_then_uses_role_specific_voices(tmp_path: Path) -> None:
    title_audio = tmp_path / "title.wav"
    message_audio = tmp_path / "message.wav"

    config_data = default_config()
    config_data["tts"]["provider_order"] = ["elevenlabs"]
    config_data["event_sounds"]["enabled"] = False
    config_data["providers"]["elevenlabs"] = {
        "voice_id": "fallback-voice",
        "title_voice": "title-voice-id",
        "message_voice": "message-voice-id",
    }
    config = Config(config_data)

    registry = AdapterRegistry()
    playback = _RecordingPlayback()
    fake_tts = _FakeTTS([title_audio, message_audio])
    registry.set_playback(playback)
    registry.register_tts("elevenlabs", lambda: fake_tts)

    service = NotifyService(config, registry=registry)
    result = service.notify(
        NotifyRequest(
            message="Build failed",
            event=MessageEvent.ERROR,
            session_name="Nightly Run",
            skip_summarization=True,
        )
    )

    assert result.status == "ok"
    assert fake_tts.calls == [("Nightly Run", "title-voice-id", 1.0), ("Build failed", "message-voice-id", 1.0)]


def test_notify_service_given_elevenlabs_voice_id_without_split_voices_then_uses_provider_default(tmp_path: Path) -> None:
    message_audio = tmp_path / "message.wav"

    config_data = default_config()
    config_data["tts"]["provider_order"] = ["elevenlabs"]
    config_data["event_sounds"]["enabled"] = False
    config_data["providers"]["elevenlabs"] = {"voice_id": "fallback-voice"}
    config = Config(config_data)

    registry = AdapterRegistry()
    playback = _RecordingPlayback()
    fake_tts = _FakeTTS([message_audio])
    registry.set_playback(playback)
    registry.register_tts("elevenlabs", lambda: fake_tts)

    service = NotifyService(config, registry=registry)
    result = service.notify(
        NotifyRequest(
            message="Build failed",
            event=MessageEvent.ERROR,
            skip_summarization=True,
        )
    )

    assert result.status == "ok"
    assert fake_tts.calls == [("Build failed", "fallback-voice", 1.0)]


def test_notify_service_given_unconfigured_elevenlabs_then_skips_without_warning(tmp_path: Path, caplog) -> None:
    message_audio = tmp_path / "message.wav"

    config_data = default_config()
    config_data["tts"]["provider_order"] = ["elevenlabs", "fake"]
    config_data["tts"]["voice"] = "default"
    config_data["event_sounds"]["enabled"] = False
    config_data["providers"]["elevenlabs"] = {}
    config = Config(config_data)

    registry = AdapterRegistry()
    playback = _RecordingPlayback()
    fake_tts = _FakeTTS([message_audio])
    registry.set_playback(playback)
    registry.register_tts("elevenlabs", lambda: _FailingTTS())
    registry.register_tts("fake", lambda: fake_tts)

    service = NotifyService(config, registry=registry)
    with caplog.at_level(logging.WARNING):
        result = service.notify(
            NotifyRequest(
                message="Build failed",
                event=MessageEvent.ERROR,
                skip_summarization=True,
            )
        )

    assert result.status == "ok"
    assert result.backend == "fake"
    assert fake_tts.calls == [("Build failed", "default", 1.0)]
    assert not any(record.message == "tts_failed" and getattr(record, "provider", None) == "elevenlabs" for record in caplog.records)


def test_notify_service_given_unconfigured_elevenlabs_and_fail_fast_then_raises(tmp_path: Path) -> None:
    config_data = default_config()
    config_data["tts"]["provider_order"] = ["elevenlabs", "fake"]
    config_data["tts"]["voice"] = "default"
    config_data["event_sounds"]["enabled"] = False
    config_data["fallback"]["fail_fast"] = True
    config_data["providers"]["elevenlabs"] = {}
    config = Config(config_data)

    registry = AdapterRegistry()
    registry.set_playback(_RecordingPlayback())
    registry.register_tts("elevenlabs", lambda: _FailingTTS())
    registry.register_tts("fake", lambda: _FailingTTS())

    service = NotifyService(config, registry=registry)

    with pytest.raises(AdapterError, match="ElevenLabs voice_id is not configured"):
        service.notify(
            NotifyRequest(
                message="Build failed",
                event=MessageEvent.ERROR,
                skip_summarization=True,
            )
        )


def test_notify_service_given_message_synthesis_failure_then_preserves_title_audio(tmp_path: Path) -> None:
    title_audio = tmp_path / "title.wav"

    config_data = default_config()
    config_data["tts"]["provider_order"] = ["title_only"]
    config_data["event_sounds"]["enabled"] = False
    config = Config(config_data)

    registry = AdapterRegistry()
    playback = _RecordingPlayback()
    title_only_tts = _TitleOnlyTTS(title_audio)
    registry.set_playback(playback)
    registry.register_tts("title_only", lambda: title_only_tts)

    service = NotifyService(config, registry=registry)
    result = service.notify(
        NotifyRequest(
            message="Build failed",
            event=MessageEvent.ERROR,
            session_name="Nightly Run",
            skip_summarization=True,
        )
    )

    assert result.status == "ok"
    assert result.backend == "title_only"
    assert result.played is True
    assert playback.groups == [[title_audio]]
