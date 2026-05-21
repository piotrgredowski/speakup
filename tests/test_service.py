from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from speakup.config import Config, default_config
from speakup.models import AudioResult, MessageEvent, NotifyRequest, SummaryResult
from speakup.playback.base import PlaybackAdapter
from speakup.registry import AdapterRegistry
from speakup.service import NotifyService
from speakup.summarizers.base import Summarizer
from speakup.tts.base import TTSAdapter


class _RecordingSummarizer(Summarizer):
    name: ClassVar[str] = "command"

    def __init__(self, summary: str = "Task is ready for review.") -> None:
        self.summary = summary
        self.messages: list[str] = []

    def summarize(self, message: str, event: MessageEvent, max_chars: int) -> SummaryResult:
        self.messages.append(message)
        return SummaryResult(summary=self.summary, state=event)


class _FileTTS(TTSAdapter):
    name: ClassVar[str] = "macos"
    texts: ClassVar[list[str]] = []

    def synthesize(
        self,
        text: str,
        output_dir: Path,
        *,
        voice: str = "default",
        speed: float = 1.0,
        audio_format: str = "mp3",
    ) -> AudioResult:
        self.texts.append(text)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{len(list(output_dir.iterdir()))}.{audio_format}"
        path.write_text(text)
        return AudioResult(kind="file", value=str(path), provider=self.name)


class _NoopPlayback(PlaybackAdapter):
    name: ClassVar[str] = "noop"

    def play_file(self, path: Path) -> None:
        return None


def _service_with_summarizer(summarizer: _RecordingSummarizer) -> NotifyService:
    _FileTTS.texts = []
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


def test_notify_given_root_disabled_then_skips_without_summarizing() -> None:
    summarizer = _RecordingSummarizer()
    service = _service_with_summarizer(summarizer)
    service.config.raw["enabled"] = False

    result = service.notify(NotifyRequest(message="done", event=MessageEvent.FINAL))

    assert result.status == "skipped"
    assert result.backend == "none"
    assert result.played is False
    assert summarizer.messages == []
    assert _FileTTS.texts == []


def test_notify_given_central_repository_disabled_then_skips(tmp_path: Path) -> None:
    summarizer = _RecordingSummarizer()
    service = _service_with_summarizer(summarizer)
    service.config.raw["repositories"] = {str(tmp_path.resolve()): {"enabled": False}}

    result = service.notify(
        NotifyRequest(message="done", event=MessageEvent.FINAL, metadata={"cwd": str(tmp_path)})
    )

    assert result.status == "skipped"
    assert summarizer.messages == []
    assert _FileTTS.texts == []


def test_notify_given_local_repository_disabled_then_skips(tmp_path: Path) -> None:
    repo = tmp_path / "project"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".speakup.jsonc").write_text('{"enabled": false}')
    summarizer = _RecordingSummarizer()
    service = _service_with_summarizer(summarizer)

    result = service.notify(
        NotifyRequest(message="done", event=MessageEvent.FINAL, metadata={"cwd": str(repo)})
    )

    assert result.status == "skipped"
    assert summarizer.messages == []
    assert _FileTTS.texts == []


def test_project_config_overlay_given_cli_overrides_then_cli_overrides_win(tmp_path: Path) -> None:
    raw = default_config()
    raw["repositories"] = {
        str(tmp_path): {
            "summarization": {"provider_order": ["cerebras"]},
            "tts": {"provider_order": ["lmstudio"]},
            "providers": {
                "omlx": {
                    "summary_model": "old-summary-model",
                    "model": "old-tts-model",
                }
            },
        }
    }
    service = NotifyService(Config(raw), registry=AdapterRegistry())

    with service._project_config_overlay(
        str(tmp_path),
        {
            "summarization": {"provider_order": ["omlx"]},
            "tts": {"provider_order": ["omlx"]},
            "providers": {
                "omlx": {
                    "summary_model": "unsloth/gemma-4-E4B-it-UD-MLX-4bit",
                    "model": "Kokoro-82M-bf16",
                }
            },
        },
    ):
        assert service.config.get("summarization", "provider_order") == ["omlx"]
        assert service.config.get("tts", "provider_order") == ["omlx"]
        assert service.config.get("providers", "omlx", "summary_model") == "unsloth/gemma-4-E4B-it-UD-MLX-4bit"
        assert service.config.get("providers", "omlx", "model") == "Kokoro-82M-bf16"


def test_effective_project_config_given_local_config_then_overrides_central_repository_config(tmp_path: Path) -> None:
    raw = default_config()
    raw["repositories"] = {
        str(tmp_path): {
            "tts": {"provider_order": ["omlx", "gemini"]},
            "providers": {
                "gemini": {
                    "title_voice": "Vega",
                    "message_voice": "Eclipse",
                }
            },
        }
    }
    (tmp_path / ".speakup.jsonc").write_text(
        '{"tts": {"provider_order": ["macos"]}, "providers": {"gemini": {"title_voice": "Erinome"}}}'
    )
    service = NotifyService(Config(raw), registry=AdapterRegistry())

    effective = service._effective_project_config(str(tmp_path))

    assert effective["tts"]["provider_order"] == ["macos"]
    assert effective["providers"]["gemini"]["title_voice"] == "Erinome"
    assert effective["providers"]["gemini"]["message_voice"] == "Eclipse"


def test_choose_project_role_voice_given_invalid_gemini_available_voices_then_uses_base_voice(tmp_path: Path) -> None:
    raw = default_config()
    raw["providers"]["gemini"]["available_voices"] = ["Vega", "Eclipse"]
    raw["providers"]["gemini"]["voice"] = "Kore"
    service = NotifyService(Config(raw), registry=AdapterRegistry())

    assert service._resolve_voice("gemini", "title", str(tmp_path)) == "Kore"


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


def test_notify_given_repo_local_context_name_then_uses_repository_title(tmp_path: Path) -> None:
    repo = tmp_path / "speakup"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".speakup.jsonc").write_text('{"context_naming": {"source": "repository", "spoken_name": "Speak Up"}}')
    summarizer = _RecordingSummarizer()
    service = _service_with_summarizer(summarizer)

    result = service.notify(
        NotifyRequest(
            message="done",
            event=MessageEvent.FINAL,
            metadata={"cwd": str(repo)},
        )
    )

    assert result.summary == "speakup from repository Speak Up says Task is ready for review."


def test_notify_given_skip_title_metadata_then_speaks_only_message(tmp_path: Path) -> None:
    repo = tmp_path / "speakup"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".speakup.jsonc").write_text('{"context_naming": {"source": "repository", "spoken_name": "Speak Up"}}')
    summarizer = _RecordingSummarizer()
    service = _service_with_summarizer(summarizer)

    result = service.notify(
        NotifyRequest(
            message="done",
            event=MessageEvent.FINAL,
            metadata={"cwd": str(repo), "_speakup_skip_title": True},
        )
    )

    assert result.summary == "Task is ready for review."
    assert _FileTTS.texts == ["Task is ready for review."]


def test_notify_given_non_dict_metadata_then_normalizes_before_context_write() -> None:
    summarizer = _RecordingSummarizer()
    service = _service_with_summarizer(summarizer)

    request = NotifyRequest(
        message="done",
        event=MessageEvent.FINAL,
        session_name="Nightly Run",
        metadata="oops",
    )
    result = service.notify(request)

    assert result.summary == "speakup from session Nightly Run says Task is ready for review."
    assert request.metadata == {"context_kind": "session", "context_name": "Nightly Run"}


def test_replay_summary_given_saved_context_then_uses_original_repository_title() -> None:
    summarizer = _RecordingSummarizer()
    service = _service_with_summarizer(summarizer)

    result = service.replay_summary(
        summary="speakup from repository Speak Up says Task is ready for review.",
        event=MessageEvent.FINAL,
        context_kind="repository",
        context_name="Speak Up",
    )

    assert result.summary == "speakup from repository Speak Up says Task is ready for review."


def test_notify_given_noop_summarizer_output_then_skips_tts() -> None:
    summarizer = _RecordingSummarizer("NO_SPEAKUP_SUMMARY")
    service = _service_with_summarizer(summarizer)

    result = service.notify(NotifyRequest(message="done", event=MessageEvent.FINAL))

    assert summarizer.messages == ["done"]
    assert result.status == "skipped"
    assert result.summary == ""
    assert result.played is False
    assert _FileTTS.texts == []


def test_notify_given_meta_noop_summarizer_output_then_skips_tts() -> None:
    summarizer = _RecordingSummarizer("There is nothing to summarize.")
    service = _service_with_summarizer(summarizer)

    result = service.notify(NotifyRequest(message="done", event=MessageEvent.FINAL))

    assert summarizer.messages == ["done"]
    assert result.status == "skipped"
    assert result.summary == ""
    assert result.played is False
    assert _FileTTS.texts == []


@pytest.mark.parametrize(
    "summary",
    [
        '"no speakup summary"',
        "`NO_SPEAKUP_SUMMARY`",
        "[No summary available.]",
    ],
)
def test_notify_given_wrapped_noop_summarizer_output_then_skips_tts(summary: str) -> None:
    summarizer = _RecordingSummarizer(summary)
    service = _service_with_summarizer(summarizer)

    result = service.notify(NotifyRequest(message="done", event=MessageEvent.FINAL))

    assert summarizer.messages == ["done"]
    assert result.status == "skipped"
    assert result.summary == ""
    assert result.played is False
    assert _FileTTS.texts == []


def test_notify_given_noop_precomputed_summary_then_skips_tts() -> None:
    summarizer = _RecordingSummarizer()
    service = _service_with_summarizer(summarizer)

    result = service.notify(
        NotifyRequest(
            message="done",
            event=MessageEvent.FINAL,
            precomputed_summary="No summary available.",
        )
    )

    assert summarizer.messages == []
    assert result.status == "skipped"
    assert result.summary == ""
    assert result.played is False
    assert _FileTTS.texts == []


def test_notify_given_wrapped_noop_precomputed_summary_then_skips_tts() -> None:
    summarizer = _RecordingSummarizer()
    service = _service_with_summarizer(summarizer)

    result = service.notify(
        NotifyRequest(
            message="done",
            event=MessageEvent.FINAL,
            precomputed_summary='"no speakup summary"',
        )
    )

    assert summarizer.messages == []
    assert result.status == "skipped"
    assert result.summary == ""
    assert result.played is False
    assert _FileTTS.texts == []


def test_replay_summary_given_noop_summary_then_skips_tts() -> None:
    summarizer = _RecordingSummarizer()
    service = _service_with_summarizer(summarizer)

    result = service.replay_summary(summary='"no speakup summary"', event=MessageEvent.FINAL)

    assert result.status == "skipped"
    assert result.summary == ""
    assert result.played is False
    assert _FileTTS.texts == []
