from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from speakup.config import Config, default_config
from speakup.errors import AdapterError
from speakup.models import AudioResult, MessageEvent, NotifyRequest
from speakup.playback.base import PlaybackAdapter
from speakup.playback.queued import SQLiteQueuedPlayback
from speakup.registry import AdapterRegistry
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

    def __init__(self, audio_path: Path) -> None:
        self.audio_path = audio_path

    def synthesize(self, text: str, output_dir: Path, *, voice: str = "default", speed: float = 1.0, audio_format: str = "mp3") -> AudioResult:
        self.audio_path.parent.mkdir(parents=True, exist_ok=True)
        self.audio_path.write_text(text)
        return AudioResult(kind="file", value=str(self.audio_path), provider=self.name)


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
    registry.register_tts("fake", lambda: _FakeTTS(speech))

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
