from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

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
from .tts.kokoro_cli import KokoroCliTTSAdapter
from .tts.kokoro import KokoroTTSAdapter
from .tts.lmstudio import LMStudioTTSAdapter
from .tts.macos import MacOSTTSAdapter
from .tts.openai import OpenAITTSAdapter


class NotifyService:
    def __init__(self, config: Config):
        self.config = config
        self.playback = MacOSPlaybackAdapter()
        self.logger = logging.getLogger(__name__)

    @contextmanager
    def _timed(self, operation: str, request_id: str, **extra):
        start = time.perf_counter()
        self.logger.debug("operation_start", extra={"request_id": request_id, "operation": operation, **extra})
        try:
            yield
        finally:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            self.logger.debug("operation_end", extra={"request_id": request_id, "operation": operation, "elapsed_ms": elapsed_ms, **extra})

    def notify(self, request: NotifyRequest) -> NotifyResult:
        request_id = uuid4().hex[:12]
        include_message = bool(self.config.get("logging", "log_message_text", default=False))
        self.logger.info(
            "notify_received",
            extra={
                "request_id": request_id,
                "event": request.event.value,
                "message_length": len(request.message),
                "message_text": request.message if include_message else None,
            },
        )

        with self._timed("infer_event", request_id):
            event = infer_event(request.message, request.event)
        self.logger.info("event_inferred", extra={"request_id": request_id, "event": event.value})

        if not self._should_speak(event):
            self.logger.info("notify_skipped_speak_disabled", extra={"request_id": request_id, "event": event.value})
            return NotifyResult(
                status="skipped",
                summary="",
                state=event,
                backend="none",
                played=False,
            )

        if self._dedup_progress(event, request.message):
            self.logger.info("notify_skipped_dedup", extra={"request_id": request_id, "event": event.value})
            return NotifyResult(
                status="skipped",
                summary="",
                state=event,
                backend="none",
                played=False,
                dedup_skipped=True,
            )

        if request.precomputed_summary:
            summary_text = str(request.precomputed_summary).strip()
            self.logger.info("summary_precomputed_used", extra={"request_id": request_id, "summary_length": len(summary_text)})
        else:
            with self._timed("summarize", request_id, event=event.value):
                summary = self._summarize(request.message, event, request_id=request_id)
            summary_text = summary.summary
            self.logger.info("summary_ready", extra={"request_id": request_id, "summary_length": len(summary_text)})

        with self._timed("tts", request_id):
            tts_result, backend = self._synthesize(summary_text, request_id=request_id)
        if tts_result is None:
            self.logger.warning("tts_failed_all_backends", extra={"request_id": request_id})
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
                # Play the event cue immediately before spoken TTS to avoid a gap.
                with self._timed("event_sound", request_id, event=event.value):
                    self._play_event_sound(event, request_id=request_id)

                self.logger.info("playback_start", extra={"request_id": request_id, "audio_path": str(audio_path)})
                self.playback.play_file(audio_path)
                played = True
                self.logger.info("playback_success", extra={"request_id": request_id, "audio_path": str(audio_path)})
            except AdapterError as exc:
                played = False
                playback_error = str(exc)
                self.logger.warning("playback_failed", extra={"request_id": request_id, "error": playback_error})

        status = "ok" if played or not play_audio else "partial_success"
        if audio_path is None:
            status = "ok"

        self.logger.info(
            "notify_completed",
            extra={"request_id": request_id, "status": status, "backend": backend, "played": played, "audio_path": str(audio_path) if audio_path else None},
        )

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

    def _summarize(self, message: str, event: MessageEvent, *, request_id: str):
        provider_order = self.config.get("summarization", "provider_order", default=["rule_based"])
        max_chars = int(self.config.get("summarization", "max_chars", default=220))
        privacy_mode = self.config.get("privacy", "mode", default="prefer_local")
        allow_remote = bool(self.config.get("privacy", "allow_remote_fallback", default=True))

        for provider in provider_order:
            self.logger.debug("summarizer_try", extra={"request_id": request_id, "provider": provider})
            if provider == "rule_based":
                result = RuleBasedSummarizer().summarize(message, event, max_chars)
                self.logger.info("summarizer_selected", extra={"request_id": request_id, "provider": provider})
                return result
            if provider == "lmstudio":
                try:
                    lm = self.config.get("providers", "lmstudio", default={})
                    result = LMStudioSummarizer(lm.get("base_url", "http://localhost:1234/v1"), lm.get("model", "local-model")).summarize(message, event, max_chars)
                    self.logger.info("summarizer_selected", extra={"request_id": request_id, "provider": provider})
                    return result
                except AdapterError as exc:
                    self.logger.warning("summarizer_failed", extra={"request_id": request_id, "provider": provider, "error": str(exc)})
                    continue
            if provider == "openai":
                if privacy_mode == "local_only" or (privacy_mode == "prefer_local" and not allow_remote):
                    self.logger.info("summarizer_skipped_privacy", extra={"request_id": request_id, "provider": provider, "privacy_mode": privacy_mode})
                    continue
                try:
                    op = self.config.get("providers", "openai", default={})
                    result = OpenAISummarizer(op.get("api_key_env", "OPENAI_API_KEY"), model=op.get("summary_model", "gpt-4o-mini")).summarize(message, event, max_chars)
                    self.logger.info("summarizer_selected", extra={"request_id": request_id, "provider": provider})
                    return result
                except AdapterError as exc:
                    self.logger.warning("summarizer_failed", extra={"request_id": request_id, "provider": provider, "error": str(exc)})
                    continue

        self.logger.info("summarizer_fallback_rule_based", extra={"request_id": request_id})
        return RuleBasedSummarizer().summarize(message, event, max_chars)

    def _synthesize(self, text: str, *, request_id: str):
        provider_order = self.config.get("tts", "provider_order", default=["kokoro_cli", "macos"])
        output_dir = Path(self.config.get("tts", "save_audio_dir", default=str(runtime_temp_dir() / "audio")))
        voice = self.config.get("tts", "voice", default="default")
        speed = float(self.config.get("tts", "speed", default=1.0))
        audio_format = self.config.get("tts", "audio_format", default="mp3")
        privacy_mode = self.config.get("privacy", "mode", default="prefer_local")
        allow_remote = bool(self.config.get("privacy", "allow_remote_fallback", default=True))

        for provider in provider_order:
            if provider in {"elevenlabs", "openai"} and (privacy_mode == "local_only" or (privacy_mode == "prefer_local" and not allow_remote)):
                self.logger.info("tts_skipped_privacy", extra={"request_id": request_id, "provider": provider, "privacy_mode": privacy_mode})
                continue

            adapter = self._make_tts(provider)
            if not adapter:
                self.logger.warning("tts_unknown_provider", extra={"request_id": request_id, "provider": provider})
                continue
            try:
                self.logger.debug("tts_try", extra={"request_id": request_id, "provider": provider})
                audio = adapter.synthesize(text, output_dir, voice=voice, speed=speed, audio_format=audio_format)
                self.logger.info("tts_selected", extra={"request_id": request_id, "provider": provider, "audio_kind": audio.kind})
                return audio, provider
            except AdapterError as exc:
                self.logger.warning("tts_failed", extra={"request_id": request_id, "provider": provider, "error": str(exc)})
                continue

        return None, "none"

    def _make_tts(self, provider: str):
        if provider == "kokoro_cli":
            kk_cli = self.config.get("providers", "kokoro_cli", default={})
            return KokoroCliTTSAdapter(
                command=kk_cli.get("command", "kokoro"),
                args=kk_cli.get("args", ["-o", "{output}", "-m", "{voice}", "-s", "{speed}", "-t", "{text}"]),
                timeout_seconds=int(kk_cli.get("timeout_seconds", 60)),
                default_voice=kk_cli.get("voice", self.config.get("providers", "kokoro", "voice", default="af_heart")),
            )
        if provider == "macos":
            return MacOSTTSAdapter()
        if provider == "kokoro":
            kk = self.config.get("providers", "kokoro", default={})
            return KokoroTTSAdapter(
                lang_code=kk.get("lang_code", "a"),
                default_voice=kk.get("voice", "af_heart"),
                repo_id=kk.get("repo_id", "hexgrad/Kokoro-82M"),
                offline=bool(kk.get("offline", True)),
            )
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

    def _play_event_sound(self, event: MessageEvent, *, request_id: str) -> None:
        event_key = event.value
        enabled = bool(self.config.get("event_sounds", "enabled", default=True))
        if not enabled:
            self.logger.debug("event_sound_disabled", extra={"request_id": request_id, "event": event_key})
            return

        mapping = self.config.get("event_sounds", "files", default={})
        path_value = mapping.get(event_key)
        if not path_value:
            self.logger.debug("event_sound_not_configured", extra={"request_id": request_id, "event": event_key})
            return

        try:
            self.logger.debug("event_sound_play_start", extra={"request_id": request_id, "event": event_key, "path": path_value})
            self.playback.play_file(Path(path_value))
            self.logger.debug("event_sound_play_success", extra={"request_id": request_id, "event": event_key, "path": path_value})
        except AdapterError as exc:
            self.logger.warning("event_sound_play_failed", extra={"request_id": request_id, "event": event_key, "path": path_value, "error": str(exc)})
            return
