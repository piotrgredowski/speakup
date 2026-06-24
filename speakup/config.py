from __future__ import annotations

import json
import logging
import os
import tempfile
from contextlib import contextmanager
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


SpeechTemplateField = Literal["source_tool", "agent", "session_name", "context_kind", "context_name", "summary", "raw_message", "event"]


@dataclass
class PlaybackConfig:
    queue_enabled: bool = True
    compose_segments: bool = True
    compose_lead_in_ms: Annotated[int, Gt(0)] = 120
    compose_gap_ms: Annotated[int, Gt(0)] = 60


@dataclass
class PrivacyConfig:
    mode: Literal["prefer_local", "local_only"] = "local_only"
    allow_remote_fallback: bool = False


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
        default_factory=lambda: ["omlx", "rule_based"]
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
        provider: Literal["macos", "lmstudio", "edge", "elevenlabs", "openai", "gemini", "omlx", "piper"] | None = None
        speed: float = 1.0

    provider_order: list[Literal["macos", "lmstudio", "edge", "elevenlabs", "openai", "gemini", "omlx", "piper"]] = field(
        default_factory=lambda: ["omlx", "piper", "macos"]
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
class ContextNamingConfig:
    enabled: bool = True
    source: Literal["session", "repository", "directory"] = "repository"
    spoken_name: str | None = None


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
class HistoryConfig:
    enabled: bool = True
    store_messages: bool = False
    retention_days: Annotated[int, Gt(0)] = 30


@dataclass
class LogViewerConfig:
    command: str = "tail -n 25 -f"


@dataclass
class ConfigViewerConfig:
    command: str | None = None


@dataclass
class RepoConfig:
    auto_register: bool = True
    save_active_provider_config: bool = False


RepositoryConfig = dict[str, Any]


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
                SpeechTemplatePartConfig(text="from", when="context_name"),
                SpeechTemplatePartConfig(field="context_kind", when="context_name"),
                SpeechTemplatePartConfig(field="context_name", when="context_name"),
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
    summary_model: str = "unsloth/gemma-4-E4B-it-UD-MLX-4bit"
    voice: str = "af_heart"
    title_voice: str | None = None
    message_voice: str | None = None
    available_voices: list[str] = field(default_factory=list)
    timeout: float = 60.0


@dataclass
class PiperConfig:
    base_url: str = "http://127.0.0.1:5000"
    auto_start: bool = True
    host: str = "127.0.0.1"
    port: Annotated[int, Gt(0)] = 5000
    data_dir: str = "~/.local/share/speakup/piper-voices"
    model: str = "en_GB-alba-medium"
    voice: str = "en_GB-alba-medium"
    title_voice: str | None = None
    message_voice: str | None = None
    available_voices: list[str] = field(
        default_factory=lambda: ["en_GB-alba-medium", "pl_PL-mc_speech-medium", "pl_PL-bass-high"]
    )
    timeout: float = 20.0
    startup_timeout: float = 10.0
    idle_timeout_seconds: int | None = 600
    extra_args: list[str] = field(default_factory=list)


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
    piper: PiperConfig = field(default_factory=PiperConfig)
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
    enabled: bool = True
    playback: PlaybackConfig = field(default_factory=PlaybackConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    events: EventsConfig = field(default_factory=EventsConfig)
    summarization: SummarizationConfig = field(default_factory=SummarizationConfig)
    fallback: FallbackConfig = field(default_factory=FallbackConfig)
    event_sounds: EventSoundsConfig = field(default_factory=EventSoundsConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    session_naming: SessionNamingConfig = field(default_factory=SessionNamingConfig)
    context_naming: ContextNamingConfig = field(default_factory=ContextNamingConfig)
    dedup: DedupConfig = field(default_factory=DedupConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    history: HistoryConfig = field(default_factory=HistoryConfig)
    log_viewer: LogViewerConfig = field(default_factory=LogViewerConfig)
    config_viewer: ConfigViewerConfig = field(default_factory=ConfigViewerConfig)
    repo_config: RepoConfig = field(default_factory=RepoConfig)
    repositories: dict[str, RepositoryConfig] = field(default_factory=dict)
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
    _validate_repositories(raw)


def normalize_config(raw: dict[str, Any]) -> dict[str, Any]:
    try:
        normalized = asdict(from_dict(AppConfig, raw))
    except SchemaValidationError as e:
        raise ConfigValidationError(str(e))
    _validate_repositories(normalized)
    return normalized


def _validate_repositories(raw: dict[str, Any]) -> None:
    repositories = raw.get("repositories", {})
    if not isinstance(repositories, dict):
        raise ConfigValidationError("repositories must be an object")
    for path_value, repository_config in repositories.items():
        if not isinstance(path_value, str) or not path_value.strip():
            raise ConfigValidationError("repositories keys must be non-empty absolute paths")
        path = Path(path_value).expanduser()
        if not path.is_absolute():
            raise ConfigValidationError(f"repositories key '{path_value}' must be an absolute path")
        if not isinstance(repository_config, dict):
            raise ConfigValidationError(f"repositories.{path_value} must be an object")
        if "enabled" in repository_config and not isinstance(repository_config["enabled"], bool):
            raise ConfigValidationError(f"repositories.{path_value}.enabled must be a boolean")


def deep_merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    result = dict(a)
    for key, value in b.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


_SAFE_PROVIDER_CONFIG_KEYS = {
    "api_key_env",
    "args",
    "available_voices",
    "base_url",
    "auto_start",
    "command",
    "data_dir",
    "extra_args",
    "host",
    "idle_timeout_seconds",
    "message_voice",
    "model",
    "port",
    "summary_model",
    "startup_timeout",
    "timeout",
    "timeout_seconds",
    "title_voice",
    "trim_output",
    "tts_model",
    "voice",
    "voice_id",
}


def _provider_config_key(provider: str) -> str:
    return "command_summary" if provider == "command" else provider


def _safe_provider_config(provider_config: object) -> dict[str, object]:
    if not isinstance(provider_config, dict):
        return {}
    return {
        str(key): value
        for key, value in provider_config.items()
        if isinstance(key, str) and key in _SAFE_PROVIDER_CONFIG_KEYS
    }


def _load_config_for_write(path: Path) -> dict[str, Any]:
    if not path.exists():
        return default_config()
    return normalize_config(_load_jsonc(path))


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8") as handle:
        temp_path = Path(handle.name)
        handle.write(json.dumps(payload, indent=2) + "\n")
    temp_path.replace(path)


@contextmanager
def _config_write_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f"{path.name}.lock")
    with lock_path.open("a", encoding="utf-8") as lock_file:
        if os.name == "posix":
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "posix":
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _normalize_existing_path(path: Path) -> str:
    try:
        return str(path.expanduser().resolve())
    except OSError:
        return str(path.expanduser().absolute())


def repository_config_key(cwd: str | Path | None) -> str | None:
    from .context_naming import find_project_root

    if cwd is None:
        cwd = Path.cwd()
    root = find_project_root(cwd)
    if root is not None:
        return _normalize_existing_path(root)
    return _normalize_existing_path(Path(cwd))


def _resolve_project_override_from_config(cfg: "Config", cwd: Path) -> dict[object, object]:
    overrides = cfg.get("tts", "project_overrides", default={})
    if not isinstance(overrides, dict):
        return {}
    resolved_cwd = _normalize_existing_path(cwd)
    for project_path, override in overrides.items():
        if not isinstance(project_path, str) or not isinstance(override, dict):
            continue
        if _normalize_existing_path(Path(project_path)) == resolved_cwd:
            return override
    return {}


def active_repo_config_payload(cfg: "Config", cwd: Path) -> dict[str, object]:
    summary_order = cfg.get("summarization", "provider_order", default=["rule_based"])
    tts_order = cfg.get("tts", "provider_order", default=["macos"])
    if not isinstance(summary_order, list):
        summary_order = ["rule_based"]
    if not isinstance(tts_order, list):
        tts_order = ["macos"]

    project_override = _resolve_project_override_from_config(cfg, cwd)
    project_provider = project_override.get("provider")
    effective_tts_order = [project_provider] if isinstance(project_provider, str) and project_provider.strip() else tts_order

    provider_names = {
        _provider_config_key(provider)
        for provider in [*summary_order, *effective_tts_order]
        if isinstance(provider, str) and provider.strip()
    }
    providers: dict[str, object] = {}
    for provider_name in sorted(provider_names):
        provider_cfg = _safe_provider_config(cfg.get("providers", provider_name, default={}))
        if provider_cfg:
            providers[provider_name] = provider_cfg

    tts_payload: dict[str, object] = {"provider_order": effective_tts_order}
    project_speed = project_override.get("speed")
    if isinstance(project_speed, (int, float)):
        tts_payload["speed"] = project_speed

    payload: dict[str, object] = {
        "summarization": {"provider_order": summary_order},
        "tts": tts_payload,
    }
    if providers:
        payload["providers"] = providers
    return payload


def config_write_path(path: str | Path | None) -> Path:
    return Path(path) if path is not None else default_config_path()


def load_config_without_repository_registration(path: str | Path | None) -> "Config":
    if path is not None and not Path(path).exists():
        return Config(default_config())
    return Config.load(path)


def register_repository_config(cfg: "Config", path: str | Path | None, cwd: str | Path | None = None) -> "Config":
    target_path = config_write_path(path)
    if not bool(cfg.get("repo_config", "auto_register", default=True)):
        return cfg

    repository_path = repository_config_key(cwd)
    if repository_path is None:
        return cfg

    payload = active_repo_config_payload(cfg, Path(repository_path))
    with _config_write_lock(target_path):
        writable_config = _load_config_for_write(target_path)
        repositories = writable_config.setdefault("repositories", {})
        if not isinstance(repositories, dict):
            validate_config(writable_config)
            return cfg
        if repository_path not in repositories:
            repositories[repository_path] = payload
            validate_config(writable_config)
            _write_json_atomic(target_path, writable_config)

        cfg.raw.setdefault("repositories", {})[repository_path] = repositories[repository_path]
    return cfg


def load_config_with_repository_registration(path: str | Path | None, cwd: str | Path | None = None) -> "Config":
    target_path = config_write_path(path)
    if target_path.exists() or path is None:
        cfg = Config.load(path)
    else:
        cfg = Config(default_config())

    return register_repository_config(cfg, target_path, cwd)


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
                base = normalize_config(base)
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

        base = normalize_config(base)
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
