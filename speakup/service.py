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
from .history import NotificationHistory
from .models import MessageEvent, NotifyRequest, NotifyResult, SummaryResult
from .playback.macos import MacOSPlaybackAdapter
from .playback.queued import SQLiteQueuedPlayback
from .registry import AdapterRegistry
from .session_naming import resolve_session_name
from .summarizers.cerebras import CerebrasSummarizer
from .summarizers.command import CommandSummarizer
from .summarizers.lmstudio import LMStudioSummarizer
from .summarizers.openai import OpenAISummarizer
from .summarizers.rule_based import RuleBasedSummarizer
from .text_transform import sanitize_text_for_tts
from .tts.elevenlabs import ElevenLabsTTSAdapter
from .tts.gemini import GeminiTTSAdapter
from .tts.omlx import OmlxTTSAdapter
from .tts.lmstudio import LMStudioTTSAdapter
from .tts.macos import MacOSTTSAdapter
from .tts.openai import OpenAITTSAdapter


def _clean_voice(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    voice = value.strip()
    return voice or None


def _provider_default_voice(provider: str, provider_cfg: dict[object, object]) -> str | None:
    return _clean_voice(provider_cfg.get("voice")) or (
        _clean_voice(provider_cfg.get("voice_id")) if provider == "elevenlabs" else None
    )


def _fallback_spoken_summary(event: MessageEvent) -> str:
    mapping = {
        MessageEvent.FINAL: "Task finished",
        MessageEvent.ERROR: "Task failed",
        MessageEvent.NEEDS_INPUT: "Input needed",
        MessageEvent.PROGRESS: "Task updated",
        MessageEvent.INFO: "Notification",
    }
    return mapping.get(event, "Notification")


def build_registry_from_config(config: Config) -> AdapterRegistry:
    """Build an adapter registry from configuration.

    This factory function creates all adapter factories based on config,
    enabling dependency injection for the NotifyService.
    """
    registry = AdapterRegistry()

    # Playback adapter (singleton)
    playback = MacOSPlaybackAdapter()
    if config.get("playback", "queue_enabled", default=True):
        playback = SQLiteQueuedPlayback(playback)
    registry.set_playback(playback)

    # TTS adapters (factories for lazy instantiation)
    def make_macos() -> MacOSTTSAdapter:
        return MacOSTTSAdapter()

    def make_lmstudio_tts() -> LMStudioTTSAdapter:
        lm = config.get("providers", "lmstudio", default={})
        return LMStudioTTSAdapter(
            lm.get("base_url", "http://localhost:1234/v1"),
            lm.get("tts_model", lm.get("model", "local-model")),
        )

    def make_gemini_tts() -> GeminiTTSAdapter:
        gem = config.get("providers", "gemini", default={})
        return GeminiTTSAdapter(
            gem.get("api_key_env", "GOOGLE_API_KEY"),
            model=gem.get("model", "gemini-2.5-flash-preview-tts"),
            voice=gem.get("voice", "en-US-Neural2-C"),
        )

    def make_elevenlabs() -> ElevenLabsTTSAdapter:
        el = config.get("providers", "elevenlabs", default={})
        return ElevenLabsTTSAdapter(
            el.get("api_key_env", "ELEVENLABS_API_KEY"),
            el.get("voice_id", ""),
            model=el.get("model", "eleven_multilingual_v2"),
        )

    def make_openai_tts() -> OpenAITTSAdapter:
        op = config.get("providers", "openai", default={})
        return OpenAITTSAdapter(
            op.get("api_key_env", "OPENAI_API_KEY"),
            model=op.get("model", "gpt-4o-mini-tts"),
            voice=op.get("voice", "alloy"),
        )

    def make_omlx() -> OmlxTTSAdapter:
        ok = config.get("providers", "omlx", default={})
        return OmlxTTSAdapter(
            base_url=ok.get("base_url", "http://127.0.0.1:8000/v1"),
            api_key_env=ok.get("api_key_env", "OMLX_API_KEY"),
            model=ok.get("model", "Kokoro-82M-bf16"),
            voice=ok.get("voice", "af_heart"),
            timeout=float(ok.get("timeout", 60.0)),
        )

    registry.register_tts("macos", make_macos)
    registry.register_tts("lmstudio", make_lmstudio_tts)
    registry.register_tts("elevenlabs", make_elevenlabs)
    registry.register_tts("openai", make_openai_tts)
    registry.register_tts("gemini", make_gemini_tts)
    registry.register_tts("omlx", make_omlx)

    # Summarizer adapters (factories)
    def make_rule_based() -> RuleBasedSummarizer:
        return RuleBasedSummarizer()

    def make_command_summarizer() -> CommandSummarizer:
        command_cfg = config.get("providers", "command_summary", default={})
        return CommandSummarizer(
            command=command_cfg.get("command", "pi"),
            args=command_cfg.get("args", ["-p", "{message}"]),
            timeout_seconds=int(command_cfg.get("timeout_seconds", 30)),
            trim_output=bool(command_cfg.get("trim_output", True)),
        )

    def make_lmstudio_summarizer() -> LMStudioSummarizer:
        lm = config.get("providers", "lmstudio", default={})
        return LMStudioSummarizer(
            lm.get("base_url", "http://localhost:1234/v1"),
            lm.get("model", "local-model"),
        )

    def make_openai_summarizer() -> OpenAISummarizer:
        op = config.get("providers", "openai", default={})
        return OpenAISummarizer(
            op.get("api_key_env", "OPENAI_API_KEY"),
            model=op.get("summary_model", "gpt-4o-mini"),
        )

    def make_cerebras_summarizer() -> CerebrasSummarizer:
        cb = config.get("providers", "cerebras", default={})
        return CerebrasSummarizer(
            api_key_env=cb.get("api_key_env", "CEREBRAS_API_KEY"),
            model=cb.get("model", "llama-3.3-70b"),
            base_url=cb.get("base_url", "https://api.cerebras.ai/v1"),
        )

    registry.register_summarizer("rule_based", make_rule_based)
    registry.register_summarizer("command", make_command_summarizer)
    registry.register_summarizer("lmstudio", make_lmstudio_summarizer)
    registry.register_summarizer("openai", make_openai_summarizer)
    registry.register_summarizer("cerebras", make_cerebras_summarizer)

    return registry


class NotifyService:
    """Service for processing notification requests with TTS and summarization."""

    def __init__(
        self,
        config: Config,
        registry: AdapterRegistry | None = None,
        history: NotificationHistory | None = None,
    ):
        self.config = config
        self.registry = registry or build_registry_from_config(config)
        self.history = history
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

    def _save_history(self, request: NotifyRequest, result: NotifyResult, *, request_id: str) -> None:
        if not self.history:
            return

        try:
            self.history.add(request, result)
        except Exception as exc:
            self.logger.warning("history_save_failed", extra={"request_id": request_id, "error": str(exc)})

    def _prepare_spoken_summary(
        self,
        *,
        event: MessageEvent,
        session_name: str | None,
        summary_text: str,
    ) -> tuple[str | None, str, str]:
        spoken_session_name = sanitize_text_for_tts(str(session_name or "")) or None
        spoken_message = sanitize_text_for_tts(summary_text)
        if not spoken_message:
            spoken_message = _fallback_spoken_summary(event)

        spoken_summary = (
            f"{spoken_session_name}: {spoken_message}"
            if spoken_session_name
            else spoken_message
        )
        return spoken_session_name, spoken_message, spoken_summary

    def _play_synthesized_summary(
        self,
        *,
        event: MessageEvent,
        spoken_session_name: str | None,
        spoken_message: str,
        spoken_summary: str,
        request_id: str,
        include_event_sound: bool,
        force_play_audio: bool | None = None,
    ) -> NotifyResult:
        with self._timed("tts", request_id):
            tts_results, backend = self._synthesize_segments(
                session_name=spoken_session_name,
                summary_text=spoken_message,
                request_id=request_id,
            )
        if not tts_results:
            self.logger.warning("tts_failed_all_backends", extra={"request_id": request_id})
            return NotifyResult(
                status="degraded_text_only",
                summary=spoken_summary,
                state=event,
                backend="none",
                played=False,
                error="No TTS backend succeeded",
            )

        audio_paths = [Path(str(result.value)) for result in tts_results if result.kind == "file" and result.value]
        audio_path = audio_paths[-1] if audio_paths else None
        played = False
        playback_error: str | None = None
        play_audio = force_play_audio if force_play_audio is not None else bool(self.config.get("tts", "play_audio", default=True))
        if audio_paths and play_audio:
            try:
                playback_paths: list[Path] = []
                if include_event_sound:
                    event_sound_path = self._event_sound_path(event, request_id=request_id)
                    if event_sound_path is not None:
                        playback_paths.append(event_sound_path)
                playback_paths.extend(audio_paths)

                self.logger.info(
                    "playback_start",
                    extra={
                        "request_id": request_id,
                        "audio_path": str(audio_path),
                        "queue_length": len(playback_paths),
                    },
                )
                self.registry.get_playback().play_files(playback_paths)
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
            summary=spoken_summary,
            state=event,
            backend=backend,
            played=played,
            audio_path=audio_path,
            error=playback_error,
        )

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

        request.session_name = resolve_session_name(
            request,
            self.config.get("session_naming", default={}),
        )

        if not self._should_speak(event):
            self.logger.info("notify_skipped_speak_disabled", extra={"request_id": request_id, "event": event.value})
            result = NotifyResult(
                status="skipped",
                summary="",
                state=event,
                backend="none",
                played=False,
            )
            self._save_history(request, result, request_id=request_id)
            return result

        if self._dedup_progress(event, request.message):
            self.logger.info("notify_skipped_dedup", extra={"request_id": request_id, "event": event.value})
            result = NotifyResult(
                status="skipped",
                summary="",
                state=event,
                backend="none",
                played=False,
                dedup_skipped=True,
            )
            self._save_history(request, result, request_id=request_id)
            return result

        if request.skip_summarization:
            summary_text = request.message
            self.logger.info("summarization_skipped", extra={"request_id": request_id})
        elif request.precomputed_summary:
            summary_text = str(request.precomputed_summary).strip()
            self.logger.info("summary_precomputed_used", extra={"request_id": request_id, "summary_length": len(summary_text)})
        else:
            with self._timed("summarize", request_id, event=event.value):
                summary = self._summarize(request.message, event, request_id=request_id)
            summary_text = summary.summary
            self.logger.info("summary_ready", extra={"request_id": request_id, "summary_length": len(summary_text)})

        spoken_session_name, spoken_message, spoken_summary = self._prepare_spoken_summary(
            event=event,
            session_name=request.session_name,
            summary_text=summary_text,
        )

        self.logger.debug(
            "summary_and_input",
            extra={
                "request_id": request_id,
                "event": event.value,
                "message_text": request.message,
                "summary_text": spoken_summary,
                "message_length": len(request.message),
                "summary_length": len(spoken_summary),
            },
        )
        result = self._play_synthesized_summary(
            event=event,
            spoken_session_name=spoken_session_name,
            spoken_message=spoken_message,
            spoken_summary=spoken_summary,
            request_id=request_id,
            include_event_sound=True,
        )

        self._save_history(request, result, request_id=request_id)
        return result

    def replay_summary(self, *, summary: str, event: MessageEvent) -> NotifyResult:
        request_id = uuid4().hex[:12]
        spoken_session_name, spoken_message, spoken_summary = self._prepare_spoken_summary(
            event=event,
            session_name=None,
            summary_text=summary,
        )
        return self._play_synthesized_summary(
            event=event,
            spoken_session_name=spoken_session_name,
            spoken_message=spoken_message,
            spoken_summary=spoken_summary,
            request_id=request_id,
            include_event_sound=False,
            force_play_audio=True,
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
        fail_fast = bool(self.config.get("fallback", "fail_fast", default=False))

        # Skip summarization for short messages
        if len(message) <= max_chars:
            self.logger.info(
                "summarization_skipped_short_message",
                extra={"request_id": request_id, "message_length": len(message), "max_chars": max_chars},
            )
            return SummaryResult(summary=message, state=event)

        for provider in provider_order:
            self.logger.debug("summarizer_try", extra={"request_id": request_id, "provider": provider})

            # Skip remote providers based on privacy settings
            if provider in {"openai", "cerebras"}:
                if privacy_mode == "local_only" or (privacy_mode == "prefer_local" and not allow_remote):
                    self.logger.info("summarizer_skipped_privacy", extra={"request_id": request_id, "provider": provider, "privacy_mode": privacy_mode})
                    continue

            try:
                summarizer = self.registry.get_summarizer(provider)
                result = summarizer.summarize(message, event, max_chars)

                if not result.summary.strip():
                    self.logger.warning("summarizer_empty_output_fallback", extra={"request_id": request_id, "provider": provider})
                    if fail_fast:
                        raise AdapterError(f"{provider} summarizer returned empty output")
                    continue

                self.logger.info("summarizer_selected", extra={"request_id": request_id, "provider": provider})
                return result

            except AdapterError as exc:
                self.logger.warning("summarizer_failed", extra={"request_id": request_id, "provider": provider, "error": str(exc)})
                if fail_fast:
                    raise
                continue

        if fail_fast:
            raise AdapterError("No summarizer backend succeeded")

        self.logger.info("summarizer_fallback_rule_based", extra={"request_id": request_id})
        return self.registry.get_summarizer("rule_based").summarize(message, event, max_chars)

    def _resolve_voice(self, provider: str, role: str) -> str:
        provider_cfg = self.config.get("providers", provider, default={})
        return (
            _clean_voice(provider_cfg.get(f"{role}_voice"))
            or _provider_default_voice(provider, provider_cfg)
            or _clean_voice(self.config.get("tts", "voice", default="default"))
            or "default"
        )

    def _should_skip_unconfigured_tts_provider(
        self,
        provider: str,
        resolved_voice: str,
        *,
        request_id: str,
        fail_fast: bool,
    ) -> bool:
        if provider != "elevenlabs" or resolved_voice != "default":
            return False

        provider_cfg = self.config.get("providers", provider, default={})
        if _provider_default_voice(provider, provider_cfg):
            return False

        if fail_fast:
            raise AdapterError("ElevenLabs voice_id is not configured")

        self.logger.info(
            "tts_skipped_unconfigured",
            extra={"request_id": request_id, "provider": provider, "reason": "missing_voice_id"},
        )
        return True

    def _synthesize(
        self,
        text: str,
        *,
        request_id: str,
        voice: str | None = None,
        speed: float | None = None,
        provider_override: str | None = None,
    ):
        provider_order = self.config.get("tts", "provider_order", default=["macos", "omlx"])
        output_dir = Path(self.config.get("tts", "save_audio_dir", default=str(runtime_temp_dir() / "audio")))
        resolved_voice = voice or self.config.get("tts", "voice", default="default")
        resolved_speed = float(speed if speed is not None else self.config.get("tts", "speed", default=1.0))
        audio_format = self.config.get("tts", "audio_format", default="wav")
        privacy_mode = self.config.get("privacy", "mode", default="prefer_local")
        allow_remote = bool(self.config.get("privacy", "allow_remote_fallback", default=True))
        fail_fast = bool(self.config.get("fallback", "fail_fast", default=False))

        providers = [provider_override] if provider_override else provider_order

        for provider in providers:
            # Skip remote providers based on privacy settings
            if provider in {"elevenlabs", "openai", "gemini"}:
                if privacy_mode == "local_only" or (privacy_mode == "prefer_local" and not allow_remote):
                    self.logger.info("tts_skipped_privacy", extra={"request_id": request_id, "provider": provider, "privacy_mode": privacy_mode})
                    continue

            if not self.registry.has_tts(provider):
                self.logger.warning("tts_unknown_provider", extra={"request_id": request_id, "provider": provider})
                continue

            if self._should_skip_unconfigured_tts_provider(
                provider,
                resolved_voice,
                request_id=request_id,
                fail_fast=fail_fast,
            ):
                continue

            try:
                adapter = self.registry.get_tts(provider)
                self.logger.debug("tts_try", extra={"request_id": request_id, "provider": provider, "voice": resolved_voice})
                audio = adapter.synthesize(text, output_dir, voice=resolved_voice, speed=resolved_speed, audio_format=audio_format)
                self.logger.info("tts_selected", extra={"request_id": request_id, "provider": provider, "voice": resolved_voice, "audio_kind": audio.kind})
                return audio, provider
            except AdapterError as exc:
                self.logger.warning("tts_failed", extra={"request_id": request_id, "provider": provider, "error": str(exc)})
                if fail_fast:
                    raise
                continue

        return None, "none"

    def _synthesize_segments(self, *, session_name: str | None, summary_text: str, request_id: str):
        provider_order = self.config.get("tts", "provider_order", default=["macos", "omlx"])
        default_speed = float(self.config.get("tts", "speed", default=1.0))
        session_speed = float(self.config.get("tts", "session_name_speed", default=default_speed))
        message_speed = float(self.config.get("tts", "message_speed", default=default_speed))
        partial_results = []
        partial_backend = "none"
        for provider in provider_order:
            results = []

            if session_name:
                title_audio, _ = self._synthesize(
                    str(session_name),
                    request_id=request_id,
                    voice=self._resolve_voice(provider, "title"),
                    speed=session_speed,
                    provider_override=provider,
                )
                if title_audio is None:
                    continue
                results.append(title_audio)
                partial_results = list(results)
                partial_backend = provider

            if summary_text:
                message_audio, _ = self._synthesize(
                    summary_text,
                    request_id=request_id,
                    voice=self._resolve_voice(provider, "message"),
                    speed=message_speed,
                    provider_override=provider,
                )
                if message_audio is None:
                    continue
                results.append(message_audio)

            return results, provider

        return partial_results, partial_backend

    def _event_sound_path(self, event: MessageEvent, *, request_id: str) -> Path | None:
        event_key = event.value
        enabled = bool(self.config.get("event_sounds", "enabled", default=True))
        if not enabled:
            self.logger.debug("event_sound_disabled", extra={"request_id": request_id, "event": event_key})
            return None

        mapping = self.config.get("event_sounds", "files", default={})
        path_value = mapping.get(event_key)
        if not path_value:
            self.logger.debug("event_sound_not_configured", extra={"request_id": request_id, "event": event_key})
            return None

        path = Path(path_value)
        if not path.exists():
            self.logger.warning(
                "event_sound_missing",
                extra={"request_id": request_id, "event": event_key, "path": path_value},
            )
            return None

        self.logger.debug("event_sound_selected", extra={"request_id": request_id, "event": event_key, "path": path_value})
        return path
