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
    return Path.home() / ".config" / "speakup" / "config.json"


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


# -----------------------------------------------------------------------------
# Configuration Schema
# -----------------------------------------------------------------------------

@dataclass
class PlaybackConfig:
    queue_enabled: bool = True

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
    provider_order: list[Literal["rule_based", "lmstudio", "openai", "command", "cerebras"]] = field(
        default_factory=lambda: ["command", "rule_based", "lmstudio", "openai"]
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
    provider_order: list[Literal["kokoro_cli", "macos", "kokoro", "lmstudio", "elevenlabs", "openai", "gemini", "omlx"]] = field(
        default_factory=lambda: ["kokoro_cli", "macos", "kokoro", "lmstudio", "elevenlabs", "openai", "gemini"]
    )
    voice: str = "default"
    speed: float = 1.0
    play_audio: bool = True
    audio_format: Literal["mp3", "wav", "aiff"] = "wav"
    save_audio_dir: str = field(default_factory=lambda: str(runtime_temp_dir() / "audio"))

@dataclass
class DedupConfig:
    enabled: bool = True
    window_seconds: Annotated[int, Gt(0)] = 30
    cache_file: str = field(default_factory=lambda: str(runtime_temp_dir() / "last_progress.json"))

@dataclass
class LoggingConfig:
    enabled: bool = True
    level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = "INFO"
    format: Literal["text", "json"] = "json"
    destination: Literal["stderr", "stdout", "file", "both"] = "stderr"
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
class LMStudioConfig:
    base_url: str = "http://localhost:1234/v1"
    model: str = "local-model"
    tts_model: str = "local-tts-model"
    tts_mode: Literal["orpheus_completions"] = "orpheus_completions"
    orpheus_voice: str = "tara"

@dataclass
class ElevenLabsConfig:
    api_key_env: str = "ELEVENLABS_API_KEY"
    voice_id: str = ""

@dataclass
class OpenAIConfig:
    api_key_env: str = "OPENAI_API_KEY"
    model: str = "gpt-4o-mini-tts"
    summary_model: str = "gpt-4o-mini"
    voice: str = "alloy"

@dataclass
class CerebrasConfig:
    api_key_env: str = "CEREBRAS_API_KEY"
    model: str = "llama3.1-8b"
    base_url: str = "https://api.cerebras.ai/v1"

@dataclass
class KokoroConfig:
    lang_code: str = "a"
    voice: str = "af_heart"
    repo_id: str = "hexgrad/Kokoro-82M"
    offline: bool = True

@dataclass
class GeminiConfig:
    api_key_env: str = "GOOGLE_API_KEY"
    model: str = "gemini-2.5-flash-preview-tts"
    voice: str = "Kore"

@dataclass
class KokoroCliConfig:
    command: str = "kokoro"
    args: list[str] = field(default_factory=lambda: ["-o", "{output}", "-m", "{voice}", "-s", "{speed}", "-t", "{text}"])
    voice: str = "af_heart"
    timeout_seconds: Annotated[int, Gt(0)] = 60

@dataclass
class OMLXConfig:
    base_url: str = "http://127.0.0.1:8000/v1"
    api_key_env: str = "OMLX_API_KEY"
    model: str = "Kokoro-82M-bf16"
    voice: str = "af_heart"
    timeout: float = 60.0

@dataclass
class CommandSummaryConfig:
    command: str = "pi"
    args: list[str] = field(default_factory=lambda: ["-p", "{message}"])
    timeout_seconds: Annotated[int, Gt(0)] = 30
    trim_output: bool = True

@dataclass
class ProvidersConfig:
    lmstudio: LMStudioConfig = field(default_factory=LMStudioConfig)
    elevenlabs: ElevenLabsConfig = field(default_factory=ElevenLabsConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    cerebras: CerebrasConfig = field(default_factory=CerebrasConfig)
    kokoro: KokoroConfig = field(default_factory=KokoroConfig)
    gemini: GeminiConfig = field(default_factory=GeminiConfig)
    kokoro_cli: KokoroCliConfig = field(default_factory=KokoroCliConfig)
    omlx: OMLXConfig = field(default_factory=OMLXConfig)
    command_summary: CommandSummaryConfig = field(default_factory=CommandSummaryConfig)

@dataclass
class DroidEvents:
    notification: bool = True
    stop: bool = True
    subagent_stop: bool = True
    session_start: bool = True

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
    dedup: DedupConfig = field(default_factory=DedupConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    log_viewer: LogViewerConfig = field(default_factory=LogViewerConfig)
    config_viewer: ConfigViewerConfig = field(default_factory=ConfigViewerConfig)
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
                base = json.loads(default_path.read_text())
                validate_config(base)
                logger.info("config_loaded", extra={"source": "default_path", "path": str(default_path)})
                return cls(base)

            raw = default_config()
            logger.info("config_loaded", extra={"source": "embedded_defaults"})
            return cls(raw)

        base = json.loads(Path(path).read_text())
        local_path = Path(path).with_name("config.local.json")
        if local_path.exists():
            local = json.loads(local_path.read_text())
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
        """Set whether audio playback is enabled."""
        self.raw.setdefault("tts", {})["play_audio"] = enabled

    def set_tts_provider_order(self, providers: list[str]) -> None:
        """Set TTS provider order with validation."""
        self.raw.setdefault("tts", {})["provider_order"] = providers
        validate_config(self.raw)

    def set_summarizer_provider_order(self, providers: list[str]) -> None:
        """Set summarizer provider order with validation."""
        self.raw.setdefault("summarization", {})["provider_order"] = providers
        validate_config(self.raw)

    def set_fail_fast(self, enabled: bool) -> None:
        """Set fail_fast mode for provider fallbacks."""
        self.raw.setdefault("fallback", {})["fail_fast"] = enabled

    def set_provider_config(self, provider: str, key: str, value: Any) -> None:
        """Set a provider-specific configuration value."""
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
