from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from speakup.config import Config, default_config
from speakup.models import AudioResult, MessageEvent, NotifyRequest, SummaryResult
from speakup.playback.base import PlaybackAdapter
from speakup.registry import AdapterRegistry
from speakup.service import NotifyService
from speakup.summarizers.base import Summarizer
from speakup.tts.base import TTSAdapter


class _RecordingSummarizer(Summarizer):
    name: ClassVar[str] = "command"

    def __init__(self) -> None:
        self.messages: list[str] = []

    def summarize(self, message: str, event: MessageEvent, max_chars: int) -> SummaryResult:
        self.messages.append(message)
        return SummaryResult(summary="Task is ready for review.", state=event)


class _FileTTS(TTSAdapter):
    name: ClassVar[str] = "macos"

    def synthesize(
        self,
        text: str,
        output_dir: Path,
        *,
        voice: str = "default",
        speed: float = 1.0,
        audio_format: str = "mp3",
    ) -> AudioResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{len(list(output_dir.iterdir()))}.{audio_format}"
        path.write_text(text)
        return AudioResult(kind="file", value=str(path), provider=self.name)


class _NoopPlayback(PlaybackAdapter):
    name: ClassVar[str] = "noop"

    def play_file(self, path: Path) -> None:
        return None


def _service_with_summarizer(summarizer: _RecordingSummarizer) -> NotifyService:
    raw = default_config()
    raw["summarization"]["provider_order"] = ["command"]
    raw["summarization"]["max_chars"] = 160
    raw["tts"]["provider_order"] = ["macos"]
    raw["tts"]["play_audio"] = False
    raw["event_sounds"]["enabled"] = False
    registry = AdapterRegistry()
    registry.register_summarizer("command", lambda: summarizer)
    registry.register_tts("macos", _FileTTS)
    registry.set_playback(_NoopPlayback())
    return NotifyService(Config(raw), registry=registry)


def test_notify_given_short_message_then_still_uses_configured_summarizer() -> None:
    summarizer = _RecordingSummarizer()
    service = _service_with_summarizer(summarizer)

    result = service.notify(NotifyRequest(message="done", event=MessageEvent.FINAL))

    assert summarizer.messages == ["done"]
    assert "Task is ready for review." in result.summary


def test_notify_given_skip_summarization_then_bypasses_configured_summarizer() -> None:
    summarizer = _RecordingSummarizer()
    service = _service_with_summarizer(summarizer)

    result = service.notify(NotifyRequest(message="done", event=MessageEvent.FINAL, skip_summarization=True))

    assert summarizer.messages == []
    assert "done" in result.summary


def test_notify_given_precomputed_summary_then_bypasses_configured_summarizer() -> None:
    summarizer = _RecordingSummarizer()
    service = _service_with_summarizer(summarizer)

    result = service.notify(
        NotifyRequest(
            message="done",
            event=MessageEvent.FINAL,
            precomputed_summary="Already rewritten for speech.",
        )
    )

    assert summarizer.messages == []
    assert "Already rewritten for speech." in result.summary
