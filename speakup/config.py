from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Annotated, Any, Literal, Union

from .lib.schema import Gt, from_dict, SchemaValidationError


class ConfigValidationError(ValueError):
    """Raised when config JSON is invalid."""


def default_config_path() -> Path:
    return Path.home() / ".config" / "speakup" / "config.jsonc"


def _strip_json_comments(text: str) -> str:
    result: list[str] = []
    i = 0
    in_string = False
    escape = False
    length = len(text)

    while i < length:
        char = text[i]
        next_char = text[i + 1] if i + 1 < length else ""

        if in_string:
            result.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            i += 1
            continue

        if char == '"':
            in_string = True
            result.append(char)
            i += 1
            continue

        if char == "/" and next_char == "/":
            i += 2
            while i < length and text[i] not in "\r\n":
                i += 1
            continue

        if char == "/" and next_char == "*":
            i += 2
            while i + 1 < length and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue

        result.append(char)
        i += 1

    return "".join(result)


def _load_jsonc(path: Path) -> dict[str, Any]:
    return json.loads(_strip_json_comments(path.read_text()))


def runtime_temp_dir() -> Path:
    return Path(tempfile.gettempdir()) / "speakup"


def get_default_log_dir() -> Path:
    if os.name == "posix" and "darwin" in os.sys.platform:
        return Path.home() / "Library" / "Logs" / "speakup"
    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home) / "speakup"
    return Path.home() / ".local" / "state" / "speakup"


def get_default_log_file_path() -> Path:
    return get_default_log_dir() / "speakup.log"


SpeechTemplateField = Literal["source_tool", "agent", "session_name", "summary", "raw_message", "event"]


@dataclass
class PlaybackConfig:
    queue_enabled: bool = True
    compose_segments: bool = True
    compose_lead_in_ms: Annotated[int, Gt(0)] = 120
    compose_gap_ms: Annotated[int, Gt(0)] = 60


@dataclass
class PrivacyConfig:
    mode: Literal["prefer_local", "local_only"] = "prefer_local"
    allow_remote_fallback: bool = True


@dataclass
class EventsConfig:
    speak_on_final: bool = True
    speak_on_error: bool = True
    speak_on_needs_input: bool = True
    speak_on_progress: bool = True


@dataclass
class SummarizationConfig:
    max_chars: Annotated[int, Gt(0)] = 220
    provider_order: list[Literal["rule_based", "lmstudio", "openai", "command", "cerebras", "gemini", "omlx"]] = field(
        default_factory=lambda: ["cerebras", "omlx", "openai", "gemini", "command", "rule_based", "lmstudio"]
    )


@dataclass
class FallbackConfig:
    fail_fast: bool = False


@dataclass
class EventSoundsConfig:
    enabled: bool = True
    files: dict[Literal["final", "error", "needs_input", "progress", "info"], str] = field(
        default_factory=lambda: {
            "final": "/System/Library/Sounds/Glass.aiff",
            "error": "/System/Library/Sounds/Basso.aiff",
            "needs_input": "/System/Library/Sounds/Funk.aiff",
            "progress": "/System/Library/Sounds/Pop.aiff",
            "info": "/System/Library/Sounds/Ping.aiff",
        }
    )


@dataclass
class TTSConfig:
    @dataclass
    class ProjectOverride:
        provider: Literal["macos", "lmstudio", "edge", "elevenlabs", "openai", "gemini", "omlx"] | None = None
        speed: float = 1.0

    provider_order: list[Literal["macos", "lmstudio", "edge", "elevenlabs", "openai", "gemini", "omlx"]] = field(
        default_factory=lambda: ["omlx", "edge", "elevenlabs", "openai", "gemini", "lmstudio", "macos"]
    )
    voice: str = "default"
    speed: float = 1.0
    project_overrides: dict[str, ProjectOverride] = field(default_factory=dict)
    session_name_speed: float | None = None
    message_speed: float | None = None
    play_audio: bool = True
    audio_format: Literal["mp3", "wav", "aiff"] = "wav"
    save_audio_dir: str = field(default_factory=lambda: str(runtime_temp_dir() / "audio"))


@dataclass
class SessionNamingConfig:
    enabled: bool = True


@dataclass
class DedupConfig:
    enabled: bool = True
    window_seconds: Annotated[int, Gt(0)] = 30
    cache_file: str = field(default_factory=lambda: str(runtime_temp_dir() / "last_progress.json"))
    mode: Literal["duplicate", "window", "duplicate_or_window"] = "duplicate"
    on_skip: Literal["skip", "sound_only"] = "skip"


@dataclass
class LoggingConfig:
    enabled: bool = True
    level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = "INFO"
    format: Literal["text", "json"] = "text"
    destination: list[Literal["stderr", "stdout", "file"]] = field(default_factory=lambda: ["stderr"])
    file_path: str = field(default_factory=lambda: str(get_default_log_file_path()))
    file_path_color: Union[str, None] = None
    rotate_max_bytes: Annotated[int, Gt(0)] = 1_048_576
    rotate_backup_count: Annotated[int, Gt(0)] = 3
    include_timestamps: bool = True
    include_module: bool = True
    include_pid: bool = False
    log_message_text: bool = False
    log_provider_payloads: bool = False
    redact_sensitive: bool = True


@dataclass
class LogViewerConfig:
    command: str = "tail -n 25 -f"


@dataclass
class ConfigViewerConfig:
    command: str | None = None


@dataclass
class MacOSConfig:
    voice: str = "default"
    title_voice: str | None = None
    message_voice: str | None = None
    available_voices: list[str] = field(default_factory=list)


@dataclass
class SpeechTemplatePartConfig:
    text: str | None = None
    field: SpeechTemplateField | None = None
    when: SpeechTemplateField | None = None
    fallback: SpeechTemplateField | None = None


@dataclass
class SpeechSegmentTemplateConfig:
    separator: str = " "
    parts: list[SpeechTemplatePartConfig] = field(default_factory=list)


@dataclass
class SpeechTemplateConfig:
    title: SpeechSegmentTemplateConfig = field(
        default_factory=lambda: SpeechSegmentTemplateConfig(
            parts=[
                SpeechTemplatePartConfig(field="source_tool", fallback="agent"),
                SpeechTemplatePartConfig(text="from session", when="session_name"),
                SpeechTemplatePartConfig(field="session_name", when="session_name"),
                SpeechTemplatePartConfig(text="says"),
            ]
        )
    )
    message: SpeechSegmentTemplateConfig = field(
        default_factory=lambda: SpeechSegmentTemplateConfig(
            parts=[SpeechTemplatePartConfig(field="summary")]
        )
    )


@dataclass
class LMStudioConfig:
    base_url: str = "http://localhost:1234/v1"
    model: str = "local-model"
    tts_model: str = "local-tts-model"
    title_voice: str | None = None
    message_voice: str | None = None
    available_voices: list[str] = field(default_factory=list)


@dataclass
class ElevenLabsConfig:
    api_key_env: str = "ELEVENLABS_API_KEY"
    voice_id: str = ""
    title_voice: str | None = None
    message_voice: str | None = None
    available_voices: list[str] = field(default_factory=list)


@dataclass
class EdgeConfig:
    voice: str = "en-US-AriaNeural"
    title_voice: str | None = None
    message_voice: str | None = None
    available_voices: list[str] = field(default_factory=list)


@dataclass
class OpenAIConfig:
    api_key_env: str = "OPENAI_API_KEY"
    model: str = "gpt-4o-mini-tts"
    summary_model: str = "gpt-4o-mini"
    voice: str = "alloy"
    title_voice: str | None = None
    message_voice: str | None = None
    available_voices: list[str] = field(default_factory=list)


@dataclass
class CerebrasConfig:
    api_key_env: str = "CEREBRAS_API_KEY"
    model: str = "llama3.1-8b"
    base_url: str = "https://api.cerebras.ai/v1"


@dataclass
class GeminiConfig:
    api_key_env: str = "GOOGLE_API_KEY"
    model: str = "gemini-2.5-flash-preview-tts"
    summary_model: str = "gemini-2.5-flash"
    voice: str = "Kore"
    title_voice: str | None = None
    message_voice: str | None = None
    available_voices: list[str] = field(default_factory=list)


@dataclass
class OMLXConfig:
    base_url: str = "http://127.0.0.1:8000/v1"
    api_key_env: str = "OMLX_API_KEY"
    model: str = "Kokoro-82M-bf16"
    voice: str = "af_heart"
    title_voice: str | None = None
    message_voice: str | None = None
    available_voices: list[str] = field(default_factory=list)
    timeout: float = 60.0


@dataclass
class CommandSummaryConfig:
    command: str = "pi"
    args: list[str] = field(default_factory=lambda: ["-p", "{message}"])
    timeout_seconds: Annotated[int, Gt(0)] = 30
    trim_output: bool = True


@dataclass
class ProvidersConfig:
    macos: MacOSConfig = field(default_factory=MacOSConfig)
    lmstudio: LMStudioConfig = field(default_factory=LMStudioConfig)
    edge: EdgeConfig = field(default_factory=EdgeConfig)
    elevenlabs: ElevenLabsConfig = field(default_factory=ElevenLabsConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    cerebras: CerebrasConfig = field(default_factory=CerebrasConfig)
    gemini: GeminiConfig = field(default_factory=GeminiConfig)
    omlx: OMLXConfig = field(default_factory=OMLXConfig)
    command_summary: CommandSummaryConfig = field(default_factory=CommandSummaryConfig)


@dataclass
class DroidEvents:
    notification: bool = True
    stop: bool = True
    subagent_stop: bool = False
    session_start: bool = False


@dataclass
class DroidConfig:
    enabled: bool = True
    events: DroidEvents = field(default_factory=DroidEvents)


@dataclass
class AppConfig:
    playback: PlaybackConfig = field(default_factory=PlaybackConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    events: EventsConfig = field(default_factory=EventsConfig)
    summarization: SummarizationConfig = field(default_factory=SummarizationConfig)
    fallback: FallbackConfig = field(default_factory=FallbackConfig)
    event_sounds: EventSoundsConfig = field(default_factory=EventSoundsConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    session_naming: SessionNamingConfig = field(default_factory=SessionNamingConfig)
    dedup: DedupConfig = field(default_factory=DedupConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    log_viewer: LogViewerConfig = field(default_factory=LogViewerConfig)
    config_viewer: ConfigViewerConfig = field(default_factory=ConfigViewerConfig)
    speech_template: SpeechTemplateConfig = field(default_factory=SpeechTemplateConfig)
    providers: ProvidersConfig = field(default_factory=ProvidersConfig)
    droid: DroidConfig = field(default_factory=DroidConfig)


def default_config() -> dict[str, Any]:
    return asdict(AppConfig())


def validate_config(raw: dict[str, Any]) -> None:
    try:
        from_dict(AppConfig, raw)
    except SchemaValidationError as e:
        raise ConfigValidationError(str(e))


def deep_merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    result = dict(a)
    for key, value in b.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


@dataclass
class Config:
    """Configuration wrapper with validation and typed accessor methods."""

    raw: dict[str, Any]

    @classmethod
    def load(cls, path: str | Path | None) -> "Config":
        logger = logging.getLogger(__name__)
        if path is None:
            default_path = default_config_path()
            if default_path.exists():
                base = _load_jsonc(default_path)
                validate_config(base)
                logger.info("config_loaded", extra={"source": "default_path", "path": str(default_path)})
                return cls(base)

            raw = default_config()
            logger.info("config_loaded", extra={"source": "embedded_defaults"})
            return cls(raw)

        base = _load_jsonc(Path(path))
        local_path = Path(path).with_name("config.local.jsonc")
        if local_path.exists():
            local = _load_jsonc(local_path)
            base = deep_merge(base, local)
            logger.info("config_local_merged", extra={"path": str(local_path)})

        validate_config(base)
        logger.info("config_loaded", extra={"source": "explicit_path", "path": str(path)})
        return cls(base)

    def get(self, *keys: str, default: Any = None) -> Any:
        current: Any = self.raw
        for key in keys:
            if not isinstance(current, dict):
                return default
            current = current.get(key)
            if current is None:
                return default
        return current

    def set_tts_play_audio(self, enabled: bool) -> None:
        self.raw.setdefault("tts", {})["play_audio"] = enabled

    def set_tts_provider_order(self, providers: list[str]) -> None:
        self.raw.setdefault("tts", {})["provider_order"] = providers
        validate_config(self.raw)

    def set_tts_speed(self, speed: float) -> None:
        self.raw.setdefault("tts", {})["speed"] = speed
        validate_config(self.raw)

    def set_summarizer_provider_order(self, providers: list[str]) -> None:
        self.raw.setdefault("summarization", {})["provider_order"] = providers
        validate_config(self.raw)

    def set_fail_fast(self, enabled: bool) -> None:
        self.raw.setdefault("fallback", {})["fail_fast"] = enabled

    def set_dedup_mode(self, mode: str) -> None:
        self.raw.setdefault("dedup", {})["mode"] = mode
        validate_config(self.raw)

    def set_dedup_on_skip(self, on_skip: str) -> None:
        self.raw.setdefault("dedup", {})["on_skip"] = on_skip
        validate_config(self.raw)

    def set_provider_config(self, provider: str, key: str, value: Any) -> None:
        self.raw.setdefault("providers", {}).setdefault(provider, {})[key] = value
        validate_config(self.raw)


def write_default_config(path: str | Path | None = None, *, force: bool = False) -> Path:
    target = Path(path) if path is not None else default_config_path()
    if target.exists() and not force:
        raise FileExistsError(f"Config already exists: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(default_config(), indent=2) + "\n"
    target.write_text(content)
    return target
