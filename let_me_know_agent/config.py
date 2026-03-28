from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigValidationError(ValueError):
    """Raised when config JSON is invalid."""


_ALLOWED_PRIVACY_MODES = {"prefer_local", "local_only"}
_ALLOWED_SUMMARIZERS = {"rule_based", "lmstudio", "openai"}
_ALLOWED_TTS = {"macos", "kokoro", "lmstudio", "elevenlabs", "openai"}
_ALLOWED_AUDIO_FORMATS = {"mp3", "wav", "aiff"}
_ALLOWED_EVENT_KEYS = {"final", "error", "needs_input", "progress", "info"}


def default_config_path() -> Path:
    return Path.home() / ".config" / "let-me-know-agent" / "config.json"


@dataclass(slots=True)
class Config:
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: str | Path | None) -> "Config":
        if path is None:
            default_path = default_config_path()
            if default_path.exists():
                base = json.loads(default_path.read_text())
                validate_config(base)
                return cls(base)

            raw = default_config()
            validate_config(raw)
            return cls(raw)

        base = json.loads(Path(path).read_text())
        local_path = Path(path).with_name("config.local.json")
        if local_path.exists():
            local = json.loads(local_path.read_text())
            base = deep_merge(base, local)

        validate_config(base)
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
    _require_list_of_known(tts.get("provider_order", ["macos"]), _ALLOWED_TTS, "tts.provider_order")
    _require_str(tts.get("voice", "default"), "tts.voice")
    _require_number(tts.get("speed", 1.0), "tts.speed")
    audio_format = tts.get("audio_format", "mp3")
    if audio_format not in _ALLOWED_AUDIO_FORMATS:
        raise ConfigValidationError(f"tts.audio_format must be one of {_ALLOWED_AUDIO_FORMATS}")
    _require_str(tts.get("save_audio_dir", ".cache/audio"), "tts.save_audio_dir")

    dedup = _require_dict(raw.get("dedup", {}), "dedup")
    _require_bool(dedup.get("enabled", True), "dedup.enabled")
    _require_positive_int(dedup.get("window_seconds", 30), "dedup.window_seconds")
    _require_str(dedup.get("cache_file", ".cache/last_progress.json"), "dedup.cache_file")

    providers = _require_dict(raw.get("providers", {}), "providers")
    for provider_name in ("lmstudio", "elevenlabs", "openai"):
        provider = _require_dict(providers.get(provider_name, {}), f"providers.{provider_name}")
        for key, value in provider.items():
            if key.endswith("_env") or key in {"base_url", "model", "voice_id", "summary_model", "voice", "tts_model"}:
                _require_str(value, f"providers.{provider_name}.{key}")


def default_config() -> dict[str, Any]:
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
            "provider_order": ["macos", "kokoro", "lmstudio", "elevenlabs", "openai"],
            "voice": "default",
            "speed": 1.0,
            "audio_format": "mp3",
            "save_audio_dir": ".cache/audio",
        },
        "dedup": {
            "enabled": True,
            "window_seconds": 30,
            "cache_file": ".cache/last_progress.json",
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
