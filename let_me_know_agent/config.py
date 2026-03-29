from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigValidationError(ValueError):
    """Raised when config JSON is invalid."""


_ALLOWED_PRIVACY_MODES = {"prefer_local", "local_only"}
_ALLOWED_SUMMARIZERS = {"rule_based", "lmstudio", "openai"}
_ALLOWED_TTS = {"kokoro_cli", "macos", "kokoro", "lmstudio", "elevenlabs", "openai"}
_ALLOWED_AUDIO_FORMATS = {"mp3", "wav", "aiff"}
_ALLOWED_EVENT_KEYS = {"final", "error", "needs_input", "progress", "info"}
_ALLOWED_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
_ALLOWED_LOG_FORMATS = {"text", "json"}
_ALLOWED_LOG_DESTINATIONS = {"stderr", "file", "both"}


def default_config_path() -> Path:
    return Path.home() / ".config" / "let-me-know-agent" / "config.json"


def runtime_temp_dir() -> Path:
    return Path(tempfile.gettempdir()) / "let-me-know-agent"


@dataclass(slots=True)
class Config:
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
            validate_config(raw)
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


def deep_merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    result = dict(a)
    for key, value in b.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _require_dict(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigValidationError(f"{path} must be an object")
    return value


def _require_bool(value: Any, path: str) -> None:
    if not isinstance(value, bool):
        raise ConfigValidationError(f"{path} must be a boolean")


def _require_str(value: Any, path: str) -> None:
    if not isinstance(value, str):
        raise ConfigValidationError(f"{path} must be a string")


def _require_positive_int(value: Any, path: str) -> None:
    if not isinstance(value, int) or value <= 0:
        raise ConfigValidationError(f"{path} must be a positive integer")


def _require_number(value: Any, path: str) -> None:
    if not isinstance(value, (int, float)):
        raise ConfigValidationError(f"{path} must be a number")


def _require_list_of_known(values: Any, allowed: set[str], path: str) -> None:
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise ConfigValidationError(f"{path} must be an array of strings")
    unknown = [v for v in values if v not in allowed]
    if unknown:
        raise ConfigValidationError(f"{path} contains unknown values: {unknown}")


def validate_config(raw: dict[str, Any]) -> None:
    if not isinstance(raw, dict):
        raise ConfigValidationError("Config root must be an object")

    privacy = _require_dict(raw.get("privacy", {}), "privacy")
    mode = privacy.get("mode", "prefer_local")
    if mode not in _ALLOWED_PRIVACY_MODES:
        raise ConfigValidationError(f"privacy.mode must be one of {_ALLOWED_PRIVACY_MODES}")
    _require_bool(privacy.get("allow_remote_fallback", True), "privacy.allow_remote_fallback")

    events = _require_dict(raw.get("events", {}), "events")
    for key in ("speak_on_final", "speak_on_error", "speak_on_needs_input", "speak_on_progress"):
        _require_bool(events.get(key, True), f"events.{key}")

    summarization = _require_dict(raw.get("summarization", {}), "summarization")
    _require_positive_int(summarization.get("max_chars", 220), "summarization.max_chars")
    _require_list_of_known(summarization.get("provider_order", ["rule_based"]), _ALLOWED_SUMMARIZERS, "summarization.provider_order")

    event_sounds = _require_dict(raw.get("event_sounds", {}), "event_sounds")
    _require_bool(event_sounds.get("enabled", True), "event_sounds.enabled")
    files = _require_dict(event_sounds.get("files", {}), "event_sounds.files")
    for key, value in files.items():
        if key not in _ALLOWED_EVENT_KEYS:
            raise ConfigValidationError(f"event_sounds.files has unknown event key: {key}")
        _require_str(value, f"event_sounds.files.{key}")

    tts = _require_dict(raw.get("tts", {}), "tts")
    _require_list_of_known(tts.get("provider_order", ["kokoro_cli", "macos"]), _ALLOWED_TTS, "tts.provider_order")
    _require_str(tts.get("voice", "default"), "tts.voice")
    _require_number(tts.get("speed", 1.0), "tts.speed")
    _require_bool(tts.get("play_audio", True), "tts.play_audio")
    audio_format = tts.get("audio_format", "mp3")
    if audio_format not in _ALLOWED_AUDIO_FORMATS:
        raise ConfigValidationError(f"tts.audio_format must be one of {_ALLOWED_AUDIO_FORMATS}")
    _require_str(tts.get("save_audio_dir", ".cache/audio"), "tts.save_audio_dir")

    dedup = _require_dict(raw.get("dedup", {}), "dedup")
    _require_bool(dedup.get("enabled", True), "dedup.enabled")
    _require_positive_int(dedup.get("window_seconds", 30), "dedup.window_seconds")
    _require_str(dedup.get("cache_file", ".cache/last_progress.json"), "dedup.cache_file")

    log_cfg = _require_dict(raw.get("logging", {}), "logging")
    _require_bool(log_cfg.get("enabled", True), "logging.enabled")
    level = str(log_cfg.get("level", "INFO")).upper()
    if level not in _ALLOWED_LOG_LEVELS:
        raise ConfigValidationError(f"logging.level must be one of {_ALLOWED_LOG_LEVELS}")
    fmt = log_cfg.get("format", "text")
    if fmt not in _ALLOWED_LOG_FORMATS:
        raise ConfigValidationError(f"logging.format must be one of {_ALLOWED_LOG_FORMATS}")
    destination = log_cfg.get("destination", "stderr")
    if destination not in _ALLOWED_LOG_DESTINATIONS:
        raise ConfigValidationError(f"logging.destination must be one of {_ALLOWED_LOG_DESTINATIONS}")
    _require_str(log_cfg.get("file_path", str(runtime_temp_dir() / "let-me-know-agent.log")), "logging.file_path")
    _require_positive_int(log_cfg.get("rotate_max_bytes", 1_048_576), "logging.rotate_max_bytes")
    _require_positive_int(log_cfg.get("rotate_backup_count", 3), "logging.rotate_backup_count")
    _require_bool(log_cfg.get("include_timestamps", True), "logging.include_timestamps")
    _require_bool(log_cfg.get("include_module", True), "logging.include_module")
    _require_bool(log_cfg.get("include_pid", False), "logging.include_pid")
    _require_bool(log_cfg.get("log_message_text", False), "logging.log_message_text")
    _require_bool(log_cfg.get("log_provider_payloads", False), "logging.log_provider_payloads")
    _require_bool(log_cfg.get("redact_sensitive", True), "logging.redact_sensitive")

    providers = _require_dict(raw.get("providers", {}), "providers")
    for provider_name in ("lmstudio", "elevenlabs", "openai", "kokoro", "kokoro_cli"):
        provider = _require_dict(providers.get(provider_name, {}), f"providers.{provider_name}")
        for key, value in provider.items():
            if key.endswith("_env") or key in {"base_url", "model", "voice_id", "summary_model", "voice", "tts_model", "command", "lang_code", "repo_id"}:
                _require_str(value, f"providers.{provider_name}.{key}")
            if provider_name == "kokoro" and key == "offline":
                _require_bool(value, f"providers.{provider_name}.{key}")
            if provider_name == "kokoro_cli" and key == "args":
                if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                    raise ConfigValidationError("providers.kokoro_cli.args must be an array of strings")
            if provider_name == "kokoro_cli" and key == "timeout_seconds":
                _require_positive_int(value, "providers.kokoro_cli.timeout_seconds")


def default_config() -> dict[str, Any]:
    runtime_dir = runtime_temp_dir()
    return {
        "privacy": {
            "mode": "prefer_local",
            "allow_remote_fallback": True,
        },
        "events": {
            "speak_on_final": True,
            "speak_on_error": True,
            "speak_on_needs_input": True,
            "speak_on_progress": True,
        },
        "summarization": {
            "max_chars": 220,
            "provider_order": ["rule_based", "lmstudio", "openai"],
        },
        "event_sounds": {
            "enabled": True,
            "files": {
                "final": "/System/Library/Sounds/Glass.aiff",
                "error": "/System/Library/Sounds/Basso.aiff",
                "needs_input": "/System/Library/Sounds/Funk.aiff",
                "progress": "/System/Library/Sounds/Pop.aiff",
                "info": "/System/Library/Sounds/Ping.aiff",
            },
        },
        "tts": {
            "provider_order": ["kokoro_cli", "macos", "kokoro", "lmstudio", "elevenlabs", "openai"],
            "voice": "default",
            "speed": 1.0,
            "play_audio": True,
            "audio_format": "mp3",
            "save_audio_dir": str(runtime_dir / "audio"),
        },
        "dedup": {
            "enabled": True,
            "window_seconds": 30,
            "cache_file": str(runtime_dir / "last_progress.json"),
        },
        "logging": {
            "enabled": True,
            "level": "INFO",
            "format": "json",
            "destination": "stderr",
            "file_path": str(runtime_dir / "let-me-know-agent.log"),
            "rotate_max_bytes": 1_048_576,
            "rotate_backup_count": 3,
            "include_timestamps": True,
            "include_module": True,
            "include_pid": False,
            "log_message_text": False,
            "log_provider_payloads": False,
            "redact_sensitive": True,
        },
        "providers": {
            "lmstudio": {
                "base_url": "http://localhost:1234/v1",
                "model": "local-model",
                "tts_model": "local-tts-model",
            },
            "elevenlabs": {
                "api_key_env": "ELEVENLABS_API_KEY",
                "voice_id": "",
            },
            "openai": {
                "api_key_env": "OPENAI_API_KEY",
                "model": "gpt-4o-mini-tts",
                "summary_model": "gpt-4o-mini",
                "voice": "alloy",
            },
            "kokoro": {
                "lang_code": "a",
                "voice": "af_heart",
                "repo_id": "hexgrad/Kokoro-82M",
                "offline": True,
            },
            "kokoro_cli": {
                "command": "kokoro",
                "args": ["-o", "{output}", "-m", "{voice}", "-s", "{speed}", "-t", "{text}"],
                "voice": "af_heart",
                "timeout_seconds": 60,
            },
        },
    }


def write_default_config(path: str | Path | None = None, *, force: bool = False) -> Path:
    target = Path(path) if path is not None else default_config_path()
    if target.exists() and not force:
        raise FileExistsError(f"Config already exists: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(default_config(), indent=2) + "\n"
    target.write_text(content)
    return target
