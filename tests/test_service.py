from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar

import pytest

from speakup.config import Config, default_config
from speakup.errors import AdapterError
from speakup.history import NotificationHistory
from speakup.models import AudioResult, MessageEvent, NotifyRequest, SummaryResult
from speakup.playback.base import PlaybackAdapter
from speakup.pronunciation import PronunciationAdapter, PronunciationResult
from speakup.registry import AdapterRegistry
from speakup.service import NotifyService
from speakup.session_state import SessionStateStore
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


class _RecordingPronunciationAdapter(PronunciationAdapter):
    name: ClassVar[str] = "command"

    def __init__(
        self,
        *,
        title: str | None = "spikap mówi",
        message: str = "GitHab ekszyn fejld",
        spoken_language: str = "pl",
        model: str | None = "fake-pronunciation-model",
    ) -> None:
        self.title = title
        self.message = message
        self.spoken_language = spoken_language
        self.model = model
        self.calls: list[tuple[str | None, str, str | None]] = []

    def adapt(self, *, title: str | None, message: str, spoken_language: str | None) -> PronunciationResult:
        self.calls.append((title, message, spoken_language))
        return PronunciationResult(
            title=self.title,
            message=self.message,
            spoken_language=self.spoken_language,
        )


class _FailingPronunciationAdapter(PronunciationAdapter):
    name: ClassVar[str] = "command"

    def adapt(self, *, title: str | None, message: str, spoken_language: str | None) -> PronunciationResult:
        raise AdapterError("pronunciation exploded")


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


def _service_with_pronunciation_adapter(
    summarizer: _RecordingSummarizer,
    adapter: _RecordingPronunciationAdapter,
    *,
    session_state: SessionStateStore | None = None,
) -> NotifyService:
    service = _service_with_summarizer(summarizer)
    service.config.raw["pronunciation"]["provider_order"] = ["command"]
    service.registry.register_pronunciation("command", lambda: adapter)
    service.session_state = session_state
    return service


def test_notify_given_short_message_then_still_uses_configured_summarizer() -> None:
    summarizer = _RecordingSummarizer()
    service = _service_with_summarizer(summarizer)

    result = service.notify(NotifyRequest(message="done", event=MessageEvent.FINAL))

    assert summarizer.messages == ["done"]
    assert "Task is ready for review." in result.summary


def test_notify_given_pronunciation_adapter_then_returns_and_speaks_adapted_summary() -> None:
    summarizer = _RecordingSummarizer("GitHub action failed")
    adapter = _RecordingPronunciationAdapter()
    service = _service_with_pronunciation_adapter(summarizer, adapter)

    result = service.notify(NotifyRequest(message="done", event=MessageEvent.FINAL))

    assert adapter.calls == [("speakup says", "GitHub action failed", None)]
    assert result.summary == "spikap mówi GitHab ekszyn fejld"
    assert _FileTTS.texts == ["spikap mówi", "GitHab ekszyn fejld"]


def test_notify_given_pronunciation_adapter_then_logs_pronunciation_without_raw_text(caplog: pytest.LogCaptureFixture) -> None:
    summarizer = _RecordingSummarizer("GitHub action failed")
    adapter = _RecordingPronunciationAdapter()
    service = _service_with_pronunciation_adapter(summarizer, adapter)

    with caplog.at_level(logging.INFO, logger="speakup.service"):
        service.notify(NotifyRequest(message="done", event=MessageEvent.FINAL))

    messages = [record.message for record in caplog.records]
    assert "pronunciation_started" in messages
    assert "pronunciation_completed" in messages
    started = next(record for record in caplog.records if record.message == "pronunciation_started")
    assert started.pronunciation_model == "fake-pronunciation-model"
    completed = next(record for record in caplog.records if record.message == "pronunciation_completed")
    assert completed.pronunciation_model == "fake-pronunciation-model"
    assert "GitHub action failed" not in caplog.text
    assert "GitHab ekszyn fejld" not in caplog.text


def test_notify_given_skip_title_and_pronunciation_title_then_speaks_only_adapted_message() -> None:
    summarizer = _RecordingSummarizer("GitHub action failed")
    adapter = _RecordingPronunciationAdapter()
    service = _service_with_pronunciation_adapter(summarizer, adapter)

    result = service.notify(
        NotifyRequest(
            message="done",
            event=MessageEvent.FINAL,
            metadata={"_speakup_skip_title": True},
        )
    )

    assert adapter.calls == [(None, "GitHub action failed", None)]
    assert result.summary == "GitHab ekszyn fejld"
    assert _FileTTS.texts == ["GitHab ekszyn fejld"]


def test_notify_given_session_state_language_then_passes_language_and_updates_metadata(tmp_path: Path) -> None:
    summarizer = _RecordingSummarizer("GitHub action failed")
    adapter = _RecordingPronunciationAdapter()
    session_state = SessionStateStore(tmp_path / "session_state.db")
    session_state.upsert(agent="codex", session_key="abc", session_name="Morning", spoken_language="pl")
    service = _service_with_pronunciation_adapter(summarizer, adapter, session_state=session_state)
    request = NotifyRequest(
        message="done",
        event=MessageEvent.FINAL,
        agent="codex",
        session_key="abc",
    )

    result = service.notify(request)
    stored = session_state.get(agent="codex", session_key="abc")

    assert adapter.calls == [("codex says", "GitHub action failed", "pl")]
    assert result.summary == "spikap mówi GitHab ekszyn fejld"
    assert stored is not None
    assert stored.spoken_language == "pl"
    assert request.metadata["spoken_language"] == "pl"
    assert request.metadata["pre_pronunciation_summary"] == "codex says GitHub action failed"


def test_notify_given_adapter_omits_existing_session_language_then_metadata_keeps_used_language(tmp_path: Path) -> None:
    summarizer = _RecordingSummarizer("GitHub action failed")
    adapter = _RecordingPronunciationAdapter(spoken_language=None)
    session_state = SessionStateStore(tmp_path / "session_state.db")
    session_state.upsert(agent="codex", session_key="abc", session_name="Morning", spoken_language="pl")
    service = _service_with_pronunciation_adapter(summarizer, adapter, session_state=session_state)
    request = NotifyRequest(
        message="done",
        event=MessageEvent.FINAL,
        agent="codex",
        session_key="abc",
    )

    service.notify(request)

    assert adapter.calls == [("codex says", "GitHub action failed", "pl")]
    assert request.metadata["spoken_language"] == "pl"


def test_notify_given_session_key_without_language_then_stores_inferred_spoken_language(tmp_path: Path) -> None:
    summarizer = _RecordingSummarizer("GitHub action failed")
    adapter = _RecordingPronunciationAdapter()
    session_state = SessionStateStore(tmp_path / "session_state.db")
    service = _service_with_pronunciation_adapter(summarizer, adapter, session_state=session_state)

    service.notify(
        NotifyRequest(
            message="done",
            event=MessageEvent.FINAL,
            agent="codex",
            session_key="abc",
        )
    )

    stored = session_state.get(agent="codex", session_key="abc")
    assert adapter.calls == [("codex says", "GitHub action failed", None)]
    assert stored is not None
    assert stored.spoken_language == "pl"


def test_notify_without_session_key_does_not_write_session_state(tmp_path: Path) -> None:
    summarizer = _RecordingSummarizer("GitHub action failed")
    adapter = _RecordingPronunciationAdapter()
    session_state = SessionStateStore(tmp_path / "session_state.db")
    service = _service_with_pronunciation_adapter(summarizer, adapter, session_state=session_state)

    service.notify(NotifyRequest(message="done", event=MessageEvent.FINAL, agent="codex"))

    assert session_state.get(agent="codex", session_key="") is None


def test_notify_given_pronunciation_changes_text_then_history_stores_adapted_summary(tmp_path: Path) -> None:
    summarizer = _RecordingSummarizer("GitHub action failed")
    adapter = _RecordingPronunciationAdapter()
    history = NotificationHistory(tmp_path / "history.db")
    service = _service_with_pronunciation_adapter(summarizer, adapter)
    service.history = history

    service.notify(NotifyRequest(message="done", event=MessageEvent.FINAL))

    entry = history.get_recent(limit=1)[0]
    assert entry.summary == "spikap mówi GitHab ekszyn fejld"
    assert entry.metadata["pre_pronunciation_summary"] == "speakup says GitHub action failed"
    assert entry.metadata["spoken_language"] == "pl"


def test_replay_summary_given_pronunciation_adapter_then_uses_saved_summary_without_readapting() -> None:
    summarizer = _RecordingSummarizer()
    adapter = _RecordingPronunciationAdapter()
    service = _service_with_pronunciation_adapter(summarizer, adapter)

    result = service.replay_summary(summary="spikap mówi GitHab ekszyn fejld", event=MessageEvent.FINAL)

    assert adapter.calls == []
    assert result.summary == "speakup says spikap mówi GitHab ekszyn fejld"


def test_notify_given_pronunciation_failure_then_falls_back_to_original_spoken_text() -> None:
    summarizer = _RecordingSummarizer("GitHub action failed")
    service = _service_with_pronunciation_adapter(summarizer, _FailingPronunciationAdapter())

    result = service.notify(NotifyRequest(message="done", event=MessageEvent.FINAL))

    assert result.summary == "speakup says GitHub action failed"
    assert _FileTTS.texts == ["speakup says", "GitHub action failed"]


def test_notify_given_pronunciation_failure_and_fail_fast_then_raises() -> None:
    summarizer = _RecordingSummarizer("GitHub action failed")
    service = _service_with_pronunciation_adapter(summarizer, _FailingPronunciationAdapter())
    service.config.raw["fallback"]["fail_fast"] = True

    with pytest.raises(AdapterError, match="pronunciation exploded"):
        service.notify(NotifyRequest(message="done", event=MessageEvent.FINAL))


def test_notify_given_skip_summarization_then_still_runs_pronunciation_adapter() -> None:
    summarizer = _RecordingSummarizer("unused")
    adapter = _RecordingPronunciationAdapter(message="Bild fejld w module płatności")
    service = _service_with_pronunciation_adapter(summarizer, adapter)

    result = service.notify(
        NotifyRequest(
            message="Build failed w module płatności",
            event=MessageEvent.ERROR,
            skip_summarization=True,
        )
    )

    assert summarizer.messages == []
    assert adapter.calls == [("speakup says", "Build failed w module płatności", None)]
    assert result.summary == "spikap mówi Bild fejld w module płatności"


def test_notify_given_precomputed_plan_approval_then_still_runs_pronunciation_adapter() -> None:
    summarizer = _RecordingSummarizer("unused")
    adapter = _RecordingPronunciationAdapter(message="Codex is waiting for plan approval")
    service = _service_with_pronunciation_adapter(summarizer, adapter)

    result = service.notify(
        NotifyRequest(
            message="Codex is waiting for plan approval: Add tests.",
            event=MessageEvent.NEEDS_INPUT,
            agent="codex",
            precomputed_summary="Codex is waiting for plan approval: Add tests.",
            skip_summarization=True,
        )
    )

    assert summarizer.messages == []
    assert adapter.calls == [("codex says", "Codex is waiting for plan approval: Add tests.", None)]
    assert result.summary == "spikap mówi Codex is waiting for plan approval"


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
