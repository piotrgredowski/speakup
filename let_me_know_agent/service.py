from __future__ import annotations

from pathlib import Path

from .classifier import infer_event
from .config import Config, runtime_temp_dir
from .dedup import should_skip_progress
from .errors import AdapterError
from .models import MessageEvent, NotifyRequest, NotifyResult
from .playback.macos import MacOSPlaybackAdapter
from .summarizers.lmstudio import LMStudioSummarizer
from .summarizers.openai import OpenAISummarizer
from .summarizers.rule_based import RuleBasedSummarizer
from .tts.elevenlabs import ElevenLabsTTSAdapter
from .tts.kokoro import KokoroTTSAdapter
from .tts.lmstudio import LMStudioTTSAdapter
from .tts.macos import MacOSTTSAdapter
from .tts.openai import OpenAITTSAdapter


class NotifyService:
    def __init__(self, config: Config):
        self.config = config
        self.playback = MacOSPlaybackAdapter()

    def notify(self, request: NotifyRequest) -> NotifyResult:
        event = infer_event(request.message, request.event)
        if not self._should_speak(event):
            return NotifyResult(
                status="skipped",
                summary="",
                state=event,
                backend="none",
                played=False,
            )

        if self._dedup_progress(event, request.message):
            return NotifyResult(
                status="skipped",
                summary="",
                state=event,
                backend="none",
                played=False,
                dedup_skipped=True,
            )

        summary = self._summarize(request.message, event)
        summary_text = summary.summary

        self._play_event_sound(event)

        tts_result, backend = self._synthesize(summary_text)
        if tts_result is None:
            return NotifyResult(
                status="degraded_text_only",
                summary=summary_text,
                state=event,
                backend="none",
                played=False,
                error="No TTS backend succeeded",
            )

        audio_path = Path(str(tts_result.value)) if tts_result.kind == "file" and tts_result.value else None
        played = False
        playback_error: str | None = None
        play_audio = bool(self.config.get("tts", "play_audio", default=True))
        if audio_path and play_audio:
            try:
                self.playback.play_file(audio_path)
                played = True
            except AdapterError as exc:
                played = False
                playback_error = str(exc)

        status = "ok" if played or not play_audio else "partial_success"
        if audio_path is None:
            status = "ok"

        return NotifyResult(
            status=status,
            summary=summary_text,
            state=event,
            backend=backend,
            played=played,
            audio_path=audio_path,
            error=playback_error,
        )

    def _should_speak(self, event: MessageEvent) -> bool:
        mapping = {
            MessageEvent.FINAL: self.config.get("events", "speak_on_final", default=True),
            MessageEvent.ERROR: self.config.get("events", "speak_on_error", default=True),
            MessageEvent.NEEDS_INPUT: self.config.get("events", "speak_on_needs_input", default=True),
            MessageEvent.PROGRESS: self.config.get("events", "speak_on_progress", default=True),
            MessageEvent.INFO: True,
        }
        return bool(mapping.get(event, True))

    def _dedup_progress(self, event: MessageEvent, message: str) -> bool:
        enabled = self.config.get("dedup", "enabled", default=True)
        if not enabled or event != MessageEvent.PROGRESS:
            return False
        cache_file = Path(self.config.get("dedup", "cache_file", default=str(runtime_temp_dir() / "last_progress.json")))
        window = int(self.config.get("dedup", "window_seconds", default=30))
        return should_skip_progress(message, cache_file, window)

    def _summarize(self, message: str, event: MessageEvent):
        provider_order = self.config.get("summarization", "provider_order", default=["rule_based"])
        max_chars = int(self.config.get("summarization", "max_chars", default=220))
        privacy_mode = self.config.get("privacy", "mode", default="prefer_local")
        allow_remote = bool(self.config.get("privacy", "allow_remote_fallback", default=True))

        for provider in provider_order:
            if provider == "rule_based":
                return RuleBasedSummarizer().summarize(message, event, max_chars)
            if provider == "lmstudio":
                try:
                    lm = self.config.get("providers", "lmstudio", default={})
                    return LMStudioSummarizer(lm.get("base_url", "http://localhost:1234/v1"), lm.get("model", "local-model")).summarize(message, event, max_chars)
                except AdapterError:
                    continue
            if provider == "openai":
                if privacy_mode == "local_only" or (privacy_mode == "prefer_local" and not allow_remote):
                    continue
                try:
                    op = self.config.get("providers", "openai", default={})
                    return OpenAISummarizer(op.get("api_key_env", "OPENAI_API_KEY"), model=op.get("summary_model", "gpt-4o-mini")).summarize(message, event, max_chars)
                except AdapterError:
                    continue

        return RuleBasedSummarizer().summarize(message, event, max_chars)

    def _synthesize(self, text: str):
        provider_order = self.config.get("tts", "provider_order", default=["macos"])
        output_dir = Path(self.config.get("tts", "save_audio_dir", default=str(runtime_temp_dir() / "audio")))
        voice = self.config.get("tts", "voice", default="default")
        speed = float(self.config.get("tts", "speed", default=1.0))
        audio_format = self.config.get("tts", "audio_format", default="mp3")
        privacy_mode = self.config.get("privacy", "mode", default="prefer_local")
        allow_remote = bool(self.config.get("privacy", "allow_remote_fallback", default=True))

        for provider in provider_order:
            if provider in {"elevenlabs", "openai"} and (privacy_mode == "local_only" or (privacy_mode == "prefer_local" and not allow_remote)):
                continue

            adapter = self._make_tts(provider)
            if not adapter:
                continue
            try:
                audio = adapter.synthesize(text, output_dir, voice=voice, speed=speed, audio_format=audio_format)
                return audio, provider
            except AdapterError:
                continue

        return None, "none"

    def _make_tts(self, provider: str):
        if provider == "macos":
            return MacOSTTSAdapter()
        if provider == "kokoro":
            return KokoroTTSAdapter()
        if provider == "lmstudio":
            lm = self.config.get("providers", "lmstudio", default={})
            return LMStudioTTSAdapter(lm.get("base_url", "http://localhost:1234/v1"), lm.get("tts_model", lm.get("model", "local-model")))
        if provider == "elevenlabs":
            el = self.config.get("providers", "elevenlabs", default={})
            return ElevenLabsTTSAdapter(el.get("api_key_env", "ELEVENLABS_API_KEY"), el.get("voice_id", ""), model=el.get("model", "eleven_multilingual_v2"))
        if provider == "openai":
            op = self.config.get("providers", "openai", default={})
            return OpenAITTSAdapter(op.get("api_key_env", "OPENAI_API_KEY"), model=op.get("model", "gpt-4o-mini-tts"), voice=op.get("voice", "alloy"))
        return None

    def _play_event_sound(self, event: MessageEvent) -> None:
        event_key = event.value
        enabled = bool(self.config.get("event_sounds", "enabled", default=True))
        if not enabled:
            return

        mapping = self.config.get("event_sounds", "files", default={})
        path_value = mapping.get(event_key)
        if not path_value:
            return

        try:
            self.playback.play_file(Path(path_value))
        except AdapterError:
            return
