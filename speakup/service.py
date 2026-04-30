from __future__ import annotations

import json
import logging
import random
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .classifier import infer_event
from .config import Config, _strip_json_comments, runtime_temp_dir
from .dedup import DedupDecision, should_skip_progress
from .errors import AdapterError
from .history import NotificationHistory
from .models import MessageEvent, NotifyRequest, NotifyResult
from .playback.macos import MacOSPlaybackAdapter
from .playback.composite import compose_audio_segments
from .playback.queued import SQLiteQueuedPlayback
from .registry import AdapterRegistry
from .session_naming import resolve_session_name
from .summarizers.cerebras import CerebrasSummarizer
from .summarizers.command import CommandSummarizer
from .summarizers.gemini import GeminiSummarizer
from .summarizers.lmstudio import LMStudioSummarizer
from .summarizers.openai import OpenAISummarizer
from .summarizers.rule_based import RuleBasedSummarizer
from .text_transform import sanitize_text_for_tts
from .tts.edge import EdgeTTSAdapter
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


def _normalize_project_path(value: object) -> str | None:
    if isinstance(value, Path):
        path = value
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        path = Path(stripped).expanduser()
    else:
        return None
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _fallback_spoken_summary(event: MessageEvent) -> str:
    mapping = {
        MessageEvent.FINAL: "Task finished",
        MessageEvent.ERROR: "Task failed",
        MessageEvent.NEEDS_INPUT: "Input needed",
        MessageEvent.PROGRESS: "Task updated",
        MessageEvent.INFO: "Notification",
    }
    return mapping.get(event, "Notification")


_NON_SPEAKABLE_SUMMARY_PATTERNS = (
    "no speakup summary",
    "no_speakup_summary",
    "nothing to summarize",
    "nothing for me to summarize",
    "there is nothing to summarize",
    "there's nothing to summarize",
    "no summary",
    "no summary available",
    "no meaningful update",
    "no meaningful updates",
    "no user-facing update",
    "no user facing update",
)


def _is_blocked_summary(summary: str) -> bool:
    normalized = sanitize_text_for_tts(summary).lower().strip()
    if not normalized:
        return False
    normalized = normalized.strip(" \t\r\n\"'`“”‘’[]{}()<>")
    normalized = normalized.rstrip(".! ")
    normalized = normalized.strip(" \t\r\n\"'`“”‘’[]{}()<>")
    return normalized in _NON_SPEAKABLE_SUMMARY_PATTERNS


_DEFAULT_SPEECH_TEMPLATE = {
    "title": {
        "separator": " ",
        "parts": [
            {"field": "source_tool", "fallback": "agent"},
            {"text": "from session", "when": "session_name"},
            {"field": "session_name", "when": "session_name"},
            {"text": "says"},
        ],
    },
    "message": {
        "separator": " ",
        "parts": [{"field": "summary"}],
    },
}


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
            voice=gem.get("voice", "Kore"),
        )

    def make_elevenlabs() -> ElevenLabsTTSAdapter:
        el = config.get("providers", "elevenlabs", default={})
        return ElevenLabsTTSAdapter(
            el.get("api_key_env", "ELEVENLABS_API_KEY"),
            el.get("voice_id", ""),
            model=el.get("model", "eleven_multilingual_v2"),
        )

    def make_edge_tts() -> EdgeTTSAdapter:
        ed = config.get("providers", "edge", default={})
        return EdgeTTSAdapter(
            voice=ed.get("voice", "en-US-AriaNeural"),
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
    registry.register_tts("edge", make_edge_tts)
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

    def make_gemini_summarizer() -> GeminiSummarizer:
        gem = config.get("providers", "gemini", default={})
        return GeminiSummarizer(
            api_key_env=gem.get("api_key_env", "GOOGLE_API_KEY"),
            model=gem.get("summary_model", "gemini-2.5-flash"),
        )

    registry.register_summarizer("rule_based", make_rule_based)
    registry.register_summarizer("command", make_command_summarizer)
    registry.register_summarizer("lmstudio", make_lmstudio_summarizer)
    registry.register_summarizer("openai", make_openai_summarizer)
    registry.register_summarizer("cerebras", make_cerebras_summarizer)
    registry.register_summarizer("gemini", make_gemini_summarizer)

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

    def _template_context(
        self,
        *,
        event: MessageEvent,
        summary_text: str,
        raw_message: str,
        session_name: str | None,
        agent: str | None,
        source_tool: str | None,
    ) -> dict[str, str | None]:
        return {
            "source_tool": sanitize_text_for_tts(str(source_tool or "")) or None,
            "agent": sanitize_text_for_tts(str(agent or "")) or None,
            "session_name": sanitize_text_for_tts(str(session_name or "")) or None,
            "summary": sanitize_text_for_tts(summary_text),
            "raw_message": sanitize_text_for_tts(raw_message),
            "event": event.value,
        }

    def _resolve_template_value(
        self,
        context: dict[str, str | None],
        *,
        field_name: object,
        fallback_name: object = None,
    ) -> str | None:
        if not isinstance(field_name, str):
            return None
        value = context.get(field_name)
        if value:
            return value
        if isinstance(fallback_name, str):
            fallback_value = context.get(fallback_name)
            if fallback_value:
                return fallback_value
        return None

    def _render_speech_segment(self, segment_name: str, context: dict[str, str | None]) -> str | None:
        segment = self.config.get("speech_template", segment_name, default=_DEFAULT_SPEECH_TEMPLATE.get(segment_name, {}))
        if not isinstance(segment, dict):
            return None

        separator = segment.get("separator", " ")
        if not isinstance(separator, str) or not separator:
            separator = " "

        parts = segment.get("parts", [])
        if not isinstance(parts, list):
            return None

        rendered_parts: list[str] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            when_name = part.get("when")
            if isinstance(when_name, str) and not context.get(when_name):
                continue

            text = part.get("text")
            if isinstance(text, str):
                rendered = sanitize_text_for_tts(text)
            else:
                rendered = self._resolve_template_value(
                    context,
                    field_name=part.get("field"),
                    fallback_name=part.get("fallback"),
                )

            if rendered:
                rendered_parts.append(rendered)

        if not rendered_parts:
            return None

        return " ".join(separator.join(rendered_parts).split())

    @staticmethod
    def _strip_title_prefix(message: str, title: str | None, session_name: str | None) -> str:
        if not message:
            return message

        prefixes = []
        if title:
            prefixes.extend([
                f"{title}: ",
                f"{title}:",
                f"{title} - ",
                f"{title} — ",
                f"{title} ",
            ])
        if session_name:
            prefixes.extend([
                f"{session_name}: ",
                f"{session_name}:",
            ])

        for prefix in prefixes:
            if message.startswith(prefix):
                return message[len(prefix):].strip()
        return message

    def _prepare_spoken_summary(
        self,
        *,
        event: MessageEvent,
        summary_text: str,
        raw_message: str,
        session_name: str | None,
        agent: str | None,
        source_tool: str | None,
    ) -> tuple[str | None, str, str]:
        context = self._template_context(
            event=event,
            summary_text=summary_text,
            raw_message=raw_message,
            session_name=session_name,
            agent=agent,
            source_tool=source_tool,
        )
        spoken_title = self._render_speech_segment("title", context)
        spoken_message = self._render_speech_segment("message", context) or ""
        spoken_message = self._strip_title_prefix(spoken_message, spoken_title, context.get("session_name"))
        if not spoken_message:
            spoken_message = _fallback_spoken_summary(event)

        spoken_summary = (
            f"{spoken_title} {spoken_message}".strip()
            if spoken_title
            else spoken_message
        )
        return spoken_title, spoken_message, spoken_summary

    def _resolve_project_override(self, project_path: str | None) -> dict[object, object]:
        normalized_project_path = _normalize_project_path(project_path)
        if not normalized_project_path:
            return {}

        overrides = self.config.get("tts", "project_overrides", default={})
        if not isinstance(overrides, dict):
            return {}

        for candidate_path, override in overrides.items():
            if _normalize_project_path(candidate_path) == normalized_project_path and isinstance(override, dict):
                return override
        return {}

    def _resolve_project_provider(self, project_path: str | None) -> str | None:
        provider = self._resolve_project_override(project_path).get("provider")
        return provider.strip() if isinstance(provider, str) and provider.strip() else None

    def _project_config_path(self, project_path: str | None) -> Path | None:
        normalized_project_path = _normalize_project_path(project_path)
        if not normalized_project_path:
            return None
        return Path(normalized_project_path) / ".speakup.jsonc"

    def _load_project_config(self, project_path: str | None) -> dict[str, object]:
        config_path = self._project_config_path(project_path)
        if config_path is None or not config_path.exists():
            return {}
        try:
            payload = json.loads(_strip_json_comments(config_path.read_text()))
        except Exception as exc:
            self.logger.warning("project_config_load_failed", extra={"path": str(config_path), "error": str(exc)})
            return {}
        if not isinstance(payload, dict):
            self.logger.warning("project_config_invalid_root", extra={"path": str(config_path), "root_type": type(payload).__name__})
            return {}
        return payload

    def _save_project_provider_voices(
        self,
        project_path: str | None,
        provider: str,
        *,
        title_voice: str | None = None,
        message_voice: str | None = None,
    ) -> None:
        config_path = self._project_config_path(project_path)
        if config_path is None:
            return

        payload = self._load_project_config(project_path)
        providers = payload.setdefault("providers", {})
        if not isinstance(providers, dict):
            providers = {}
            payload["providers"] = providers

        provider_cfg = providers.setdefault(provider, {})
        if not isinstance(provider_cfg, dict):
            provider_cfg = {}
            providers[provider] = provider_cfg

        changed = False
        if title_voice and not _clean_voice(provider_cfg.get("title_voice")):
            provider_cfg["title_voice"] = title_voice
            changed = True
        if message_voice and not _clean_voice(provider_cfg.get("message_voice")):
            provider_cfg["message_voice"] = message_voice
            changed = True

        if not changed:
            return

        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(payload, indent=2) + "\n")

    def _project_provider_config(self, provider: str, project_path: str | None) -> dict[object, object]:
        payload = self._load_project_config(project_path)
        providers = payload.get("providers", {})
        if not isinstance(providers, dict):
            return {}
        provider_cfg = providers.get(provider, {})
        return provider_cfg if isinstance(provider_cfg, dict) else {}

    def _available_voices(self, provider_cfg: dict[object, object]) -> list[str]:
        voices = provider_cfg.get("available_voices", [])
        if not isinstance(voices, list):
            return []
        return [voice.strip() for voice in voices if isinstance(voice, str) and voice.strip()]

    def _choose_project_role_voice(self, provider: str, role: str, project_path: str | None) -> str | None:
        project_provider_cfg = self._project_provider_config(provider, project_path)
        persisted_voice = _clean_voice(project_provider_cfg.get(f"{role}_voice"))
        if persisted_voice:
            return persisted_voice

        provider_cfg = self.config.get("providers", provider, default={})
        available_voices = self._available_voices(provider_cfg)
        if not available_voices:
            return None

        selected_voice = random.choice(available_voices)
        if role == "title":
            self._save_project_provider_voices(project_path, provider, title_voice=selected_voice)
        else:
            self._save_project_provider_voices(project_path, provider, message_voice=selected_voice)
        return selected_voice

    def _resolve_base_voice(self, provider: str, project_path: str | None) -> str:
        provider_cfg = self.config.get("providers", provider, default={})
        return (
            _provider_default_voice(provider, provider_cfg)
            or _clean_voice(self.config.get("tts", "voice", default="default"))
            or "default"
        )

    def _resolve_base_speed(self, project_path: str | None, cli_speed: float | None = None) -> float:
        if cli_speed is not None:
            return float(cli_speed)
        project_speed = self._resolve_project_override(project_path).get("speed")
        if isinstance(project_speed, (int, float)):
            return float(project_speed)
        return float(self.config.get("tts", "speed", default=1.0))

    def _play_synthesized_summary(
        self,
        *,
        event: MessageEvent,
        spoken_title: str | None,
        spoken_message: str,
        spoken_summary: str,
        request_id: str,
        include_event_sound: bool,
        force_play_audio: bool | None = None,
        project_path: str | None = None,
        cli_speed: float | None = None,
    ) -> NotifyResult:
        with self._timed("tts", request_id):
            tts_results, backend = self._synthesize_segments(
                title_text=spoken_title,
                summary_text=spoken_message,
                request_id=request_id,
                project_path=project_path,
                cli_speed=cli_speed,
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
        playback_audio_paths: list[Path] = []
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
                playback_paths = self._prepare_playback_paths(playback_paths, request_id=request_id)
                playback_audio_paths = list(playback_paths)

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
            audio_paths=audio_paths,
            playback_audio_paths=playback_audio_paths,
            error=playback_error,
        )

    def _prepare_playback_paths(self, paths: list[Path], *, request_id: str) -> list[Path]:
        normalized_paths = [Path(path) for path in paths]
        if len(normalized_paths) < 2:
            return normalized_paths

        if not bool(self.config.get("playback", "compose_segments", default=True)):
            return normalized_paths

        lead_in_ms = int(self.config.get("playback", "compose_lead_in_ms", default=120))
        gap_ms = int(self.config.get("playback", "compose_gap_ms", default=60))
        try:
            composed_path = compose_audio_segments(
                normalized_paths,
                output_dir=runtime_temp_dir() / "playback",
                lead_in_ms=lead_in_ms,
                gap_ms=gap_ms,
            )
        except AdapterError as exc:
            self.logger.warning(
                "playback_compose_failed",
                extra={
                    "request_id": request_id,
                    "segment_count": len(normalized_paths),
                    "error": str(exc),
                },
            )
            return normalized_paths

        self.logger.info(
            "playback_composed",
            extra={
                "request_id": request_id,
                "segment_count": len(normalized_paths),
                "composed_path": str(composed_path),
                "lead_in_ms": lead_in_ms,
                "gap_ms": gap_ms,
            },
        )
        return [composed_path]

    def notify(self, request: NotifyRequest) -> NotifyResult:
        request_id = uuid4().hex[:12]
        metadata = request.metadata if isinstance(request.metadata, dict) else {}
        project_path = _normalize_project_path(metadata.get("cwd"))
        cli_speed = float(metadata["cli_speed"]) if isinstance(metadata.get("cli_speed"), (int, float)) else None
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

        dedup_decision = self._dedup_progress(event, request.message)
        if dedup_decision.skipped:
            self.logger.info(
                "notify_skipped_dedup",
                extra={"request_id": request_id, "event": event.value, "reason": dedup_decision.reason},
            )
            if self.config.get("dedup", "on_skip", default="skip") == "sound_only":
                result = self._play_event_sound_only(event, request_id=request_id)
                result.dedup_skipped = True
            else:
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

        if _is_blocked_summary(summary_text):
            self.logger.info("notify_skipped_non_speakable_summary", extra={"request_id": request_id, "event": event.value})
            result = NotifyResult(
                status="skipped",
                summary="",
                state=event,
                backend="none",
                played=False,
            )
            self._save_history(request, result, request_id=request_id)
            return result

        spoken_title, spoken_message, spoken_summary = self._prepare_spoken_summary(
            event=event,
            summary_text=summary_text,
            raw_message=request.message,
            session_name=request.session_name,
            agent=request.agent,
            source_tool=request.source_tool,
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
            spoken_title=spoken_title,
            spoken_message=spoken_message,
            spoken_summary=spoken_summary,
            request_id=request_id,
            include_event_sound=True,
            project_path=project_path,
            cli_speed=cli_speed,
        )

        self._save_history(request, result, request_id=request_id)
        return result

    def replay_summary(
        self,
        *,
        summary: str,
        event: MessageEvent,
        session_name: str | None = None,
        agent: str = "speakup",
        source_tool: str | None = None,
    ) -> NotifyResult:
        request_id = uuid4().hex[:12]
        if _is_blocked_summary(summary):
            self.logger.info("replay_skipped_non_speakable_summary", extra={"request_id": request_id, "event": event.value})
            return NotifyResult(
                status="skipped",
                summary="",
                state=event,
                backend="none",
                played=False,
            )

        spoken_title, spoken_message, spoken_summary = self._prepare_spoken_summary(
            event=event,
            summary_text=summary,
            raw_message=summary,
            session_name=session_name,
            agent=agent,
            source_tool=source_tool,
        )
        return self._play_synthesized_summary(
            event=event,
            spoken_title=spoken_title,
            spoken_message=spoken_message,
            spoken_summary=spoken_summary,
            request_id=request_id,
            include_event_sound=False,
            force_play_audio=True,
        )

    def _play_event_sound_only(self, event: MessageEvent, *, request_id: str) -> NotifyResult:
        event_sound_path = self._event_sound_path(event, request_id=request_id)
        play_audio = bool(self.config.get("tts", "play_audio", default=True))
        if event_sound_path is None or not play_audio:
            return NotifyResult(
                status="skipped",
                summary="",
                state=event,
                backend="none",
                played=False,
            )

        try:
            playback_paths = self._prepare_playback_paths([event_sound_path], request_id=request_id)
            self.registry.get_playback().play_files(playback_paths)
        except AdapterError as exc:
            self.logger.warning("event_sound_playback_failed", extra={"request_id": request_id, "error": str(exc)})
            return NotifyResult(
                status="skipped",
                summary="",
                state=event,
                backend="none",
                played=False,
                error=str(exc),
            )

        return NotifyResult(
            status="ok",
            summary="",
            state=event,
            backend="none",
            played=True,
            playback_audio_paths=playback_paths,
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

    def _dedup_progress(self, event: MessageEvent, message: str) -> DedupDecision:
        enabled = self.config.get("dedup", "enabled", default=True)
        if not enabled or event != MessageEvent.PROGRESS:
            return DedupDecision(skipped=False)
        cache_file = Path(self.config.get("dedup", "cache_file", default=str(runtime_temp_dir() / "last_progress.json")))
        window = int(self.config.get("dedup", "window_seconds", default=30))
        mode = str(self.config.get("dedup", "mode", default="duplicate"))
        return should_skip_progress(message, cache_file, window, mode=mode)

    def _summarize(self, message: str, event: MessageEvent, *, request_id: str):
        provider_order = self.config.get("summarization", "provider_order", default=["rule_based"])
        max_chars = int(self.config.get("summarization", "max_chars", default=220))
        privacy_mode = self.config.get("privacy", "mode", default="prefer_local")
        allow_remote = bool(self.config.get("privacy", "allow_remote_fallback", default=True))
        fail_fast = bool(self.config.get("fallback", "fail_fast", default=False))

        for provider in provider_order:
            self.logger.debug("summarizer_try", extra={"request_id": request_id, "provider": provider})

            # Skip remote providers based on privacy settings
            if provider in {"openai", "cerebras", "gemini"}:
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
        try:
            return self.registry.get_summarizer("rule_based").summarize(message, event, max_chars)
        except AdapterError:
            return RuleBasedSummarizer().summarize(message, event, max_chars)

    def _resolve_voice(self, provider: str, role: str, project_path: str | None = None) -> str:
        provider_cfg = self.config.get("providers", provider, default={})
        return (
            self._choose_project_role_voice(provider, role, project_path)
            or
            _clean_voice(provider_cfg.get(f"{role}_voice"))
            or self._resolve_base_voice(provider, project_path)
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
        project_path: str | None = None,
        cli_speed: float | None = None,
    ):
        provider_order = self.config.get("tts", "provider_order", default=["macos", "omlx"])
        output_dir = Path(self.config.get("tts", "save_audio_dir", default=str(runtime_temp_dir() / "audio")))
        current_provider = provider_override or (provider_order[0] if provider_order else "macos")
        resolved_voice = voice or self._resolve_base_voice(current_provider, project_path)
        resolved_speed = float(speed if speed is not None else self._resolve_base_speed(project_path, cli_speed))
        audio_format = self.config.get("tts", "audio_format", default="wav")
        privacy_mode = self.config.get("privacy", "mode", default="prefer_local")
        allow_remote = bool(self.config.get("privacy", "allow_remote_fallback", default=True))
        fail_fast = bool(self.config.get("fallback", "fail_fast", default=False))

        providers = [provider_override] if provider_override else provider_order

        for provider in providers:
            # Skip remote providers based on privacy settings
            if provider in {"elevenlabs", "openai", "gemini", "edge"}:
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

    def _synthesize_segments(
        self,
        *,
        title_text: str | None,
        summary_text: str,
        request_id: str,
        project_path: str | None = None,
        cli_speed: float | None = None,
    ):
        project_provider = self._resolve_project_provider(project_path)
        provider_order = [project_provider] if project_provider else self.config.get("tts", "provider_order", default=["macos", "omlx"])
        default_speed = self._resolve_base_speed(project_path, cli_speed)
        if cli_speed is not None:
            session_speed = float(cli_speed)
            message_speed = float(cli_speed)
        else:
            session_speed = float(self.config.get("tts", "session_name_speed", default=default_speed))
            message_speed = float(self.config.get("tts", "message_speed", default=default_speed))
        partial_results = []
        partial_backend = "none"
        for provider in provider_order:
            results = []

            if title_text:
                title_audio, _ = self._synthesize(
                    str(title_text),
                    request_id=request_id,
                    voice=self._resolve_voice(provider, "title", project_path),
                    speed=session_speed,
                    provider_override=provider,
                    project_path=project_path,
                    cli_speed=cli_speed,
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
                    voice=self._resolve_voice(provider, "message", project_path),
                    speed=message_speed,
                    provider_override=provider,
                    project_path=project_path,
                    cli_speed=cli_speed,
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
