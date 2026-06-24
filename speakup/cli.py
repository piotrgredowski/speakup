from __future__ import annotations

import json
import logging
import platform
import shlex
import subprocess
import sys
from enum import Enum
from pathlib import Path
from typing import Optional

import typer

from .app_logging import redact_payload, setup_logging
from .config import (
    Config,
    _load_config_for_write,
    _write_json_atomic,
    active_repo_config_payload,
    deep_merge,
    get_default_log_file_path,
    load_config_without_repository_registration,
    load_config_with_repository_registration,
    register_repository_config,
    repository_config_key,
    validate_config,
    write_default_config,
)
from .context_naming import SpokenContext, project_config_path
from .errors import AdapterError
from .history import NotificationHistory
from .models import MessageEvent, NotifyRequest
from .playback.macos import MacOSPlaybackAdapter
from .provider_catalog import REMOTE_PRONUNCIATION_PROVIDERS
from .service import NotifyService, build_registry_from_config
from .text_transform import transform_text_for_reading
from .version import get_version

app = typer.Typer(
    name="speakup",
    help="Speak concise agent status updates with pluggable local/remote backends",
    rich_markup_mode="rich",
)


class SummarizerProvider(str, Enum):
    """Available summarization providers."""

    rule_based = "rule_based"
    lmstudio = "lmstudio"
    openai = "openai"
    command = "command"
    cerebras = "cerebras"
    gemini = "gemini"
    omlx = "omlx"


class PronunciationProvider(str, Enum):
    """Available pronunciation adaptation providers."""

    lmstudio = "lmstudio"
    openai = "openai"
    command = "command"
    cerebras = "cerebras"
    gemini = "gemini"
    omlx = "omlx"


def _resolve_summary_model_target(
    cfg: Config, summary_provider: Optional[str]
) -> tuple[str, str]:
    provider = summary_provider
    if not provider:
        provider_order = cfg.get("summarization", "provider_order", default=["lmstudio"])
        provider = provider_order[0] if provider_order else "lmstudio"

    if provider == "openai":
        return "openai", "summary_model"
    if provider == "cerebras":
        return "cerebras", "model"
    if provider == "gemini":
        return "gemini", "summary_model"
    if provider == "omlx":
        return "omlx", "summary_model"
    return "lmstudio", "model"


def _resolve_pronunciation_model_target(
    cfg: Config, pronunciation_provider: Optional[str]
) -> tuple[str, str]:
    provider = pronunciation_provider
    if not provider:
        provider_order = cfg.get("pronunciation", "provider_order", default=["omlx"])
        provider = provider_order[0] if provider_order else "omlx"

    if provider == "openai":
        return "openai", "summary_model"
    if provider == "gemini":
        return "gemini", "summary_model"
    if provider == "omlx":
        return "omlx", "summary_model"
    if provider == "cerebras":
        return "cerebras", "model"
    return "lmstudio", "model"


def _summary_model_targets(cfg: Config, summary_provider: Optional[str]) -> list[tuple[str, str]]:
    if summary_provider:
        return [_resolve_summary_model_target(cfg, summary_provider)]
    return [
        ("lmstudio", "model"),
        ("openai", "summary_model"),
        ("cerebras", "model"),
        ("gemini", "summary_model"),
        ("omlx", "summary_model"),
    ]


def _resolve_tts_model_target(cfg: Config, tts_provider: Optional[str]) -> tuple[str, str]:
    provider = tts_provider
    if not provider:
        provider_order = cfg.get("tts", "provider_order", default=["lmstudio"])
        provider = provider_order[0] if provider_order else "lmstudio"

    if provider == "lmstudio":
        return "lmstudio", "tts_model"
    return provider, "model"


def _tts_model_targets(cfg: Config, tts_provider: Optional[str]) -> list[tuple[str, str]]:
    if tts_provider:
        return [_resolve_tts_model_target(cfg, tts_provider)]
    return [
        ("lmstudio", "tts_model"),
        ("elevenlabs", "model"),
        ("openai", "model"),
        ("gemini", "model"),
        ("omlx", "model"),
    ]


def _resolve_tts_voice_provider(cfg: Config, tts_provider: Optional[str]) -> str:
    if tts_provider:
        return tts_provider
    provider_order = cfg.get("tts", "provider_order", default=["lmstudio"])
    return provider_order[0] if provider_order else "lmstudio"


def _merge_cli_provider_config(payload: dict[str, object], provider: str, key: str, value: object) -> None:
    providers = payload.setdefault("providers", {})
    if not isinstance(providers, dict):
        providers = {}
        payload["providers"] = providers
    provider_cfg = providers.setdefault(provider, {})
    if not isinstance(provider_cfg, dict):
        provider_cfg = {}
        providers[provider] = provider_cfg
    provider_cfg[key] = value


def _build_cli_override_payload(
    cfg: Config,
    *,
    no_play: bool = False,
    fail_fast: bool = False,
    speed: Optional[float] = None,
    summary_provider: Optional[str] = None,
    tts_provider: Optional[str] = None,
    pronunciation_provider: Optional[str] = None,
    summary_model: Optional[str] = None,
    tts_model: Optional[str] = None,
    tts_voice: Optional[str] = None,
    tts_title_voice: Optional[str] = None,
    tts_message_voice: Optional[str] = None,
    pronunciation_model: Optional[str] = None,
    dedup_mode: Optional[str] = None,
    dedup_on_skip: Optional[str] = None,
    no_pronounce: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {}
    if no_play:
        payload.setdefault("tts", {})["play_audio"] = False
    if fail_fast:
        payload.setdefault("fallback", {})["fail_fast"] = True
    if speed is not None:
        payload.setdefault("tts", {})["speed"] = speed
    if summary_provider:
        payload.setdefault("summarization", {})["provider_order"] = [summary_provider]
    if tts_provider:
        payload.setdefault("tts", {})["provider_order"] = [tts_provider]
    if pronunciation_provider:
        payload.setdefault("pronunciation", {})["provider_order"] = [pronunciation_provider]
    if no_pronounce:
        payload.setdefault("pronunciation", {})["enabled"] = False
    if summary_model:
        for provider_name, key_name in _summary_model_targets(cfg, summary_provider):
            _merge_cli_provider_config(payload, provider_name, key_name, summary_model)
    if tts_model:
        for provider_name, key_name in _tts_model_targets(cfg, tts_provider):
            _merge_cli_provider_config(payload, provider_name, key_name, tts_model)
    if tts_voice:
        provider_name = _resolve_tts_voice_provider(cfg, tts_provider)
        _merge_cli_provider_config(payload, provider_name, "voice", tts_voice)
        _merge_cli_provider_config(payload, provider_name, "title_voice", tts_voice)
        _merge_cli_provider_config(payload, provider_name, "message_voice", tts_voice)
    if tts_title_voice:
        provider_name = _resolve_tts_voice_provider(cfg, tts_provider)
        _merge_cli_provider_config(payload, provider_name, "title_voice", tts_title_voice)
    if tts_message_voice:
        provider_name = _resolve_tts_voice_provider(cfg, tts_provider)
        _merge_cli_provider_config(payload, provider_name, "message_voice", tts_message_voice)
    if pronunciation_model:
        provider_name, key_name = _resolve_pronunciation_model_target(cfg, pronunciation_provider)
        _merge_cli_provider_config(payload, provider_name, key_name, pronunciation_model)
    if dedup_mode:
        payload.setdefault("dedup", {})["mode"] = dedup_mode
    if dedup_on_skip:
        payload.setdefault("dedup", {})["on_skip"] = dedup_on_skip
    return payload


def _active_repo_config_payload(cfg: Config, cwd: Path) -> dict[str, object]:
    return active_repo_config_payload(cfg, cwd)


def _open_with_default_app(path: Path) -> None:
    system = platform.system()
    if system == "Darwin":
        command = ["open", str(path)]
    elif system == "Linux":
        command = ["xdg-open", str(path)]
    else:
        print(f"Unsupported platform for default config opener: {system}", file=sys.stderr)
        raise typer.Exit(1)

    try:
        subprocess.Popen(command)
    except FileNotFoundError:
        print(f"Default opener command not found: {command[0]}", file=sys.stderr)
        raise typer.Exit(127)
    except Exception as exc:
        print(f"Failed to open config: {exc}", file=sys.stderr)
        raise typer.Exit(1)


def _open_with_command(command: str, path: Path) -> None:
    parts = shlex.split(command) + [str(path)]
    try:
        subprocess.Popen(parts)
    except FileNotFoundError:
        print(f"Config viewer command not found: {parts[0]}", file=sys.stderr)
        raise typer.Exit(127)
    except Exception as exc:
        print(f"Failed to open config: {exc}", file=sys.stderr)
        raise typer.Exit(1)


def _open_config_file(path: Path, viewer_command: str | None) -> None:
    if viewer_command:
        _open_with_command(viewer_command, path)
        return
    _open_with_default_app(path)


class TTSProvider(str, Enum):
    """Available TTS providers."""

    macos = "macos"
    lmstudio = "lmstudio"
    edge = "edge"
    elevenlabs = "elevenlabs"
    openai = "openai"
    gemini = "gemini"
    omlx = "omlx"
    piper = "piper"


class DedupMode(str, Enum):
    """Available deduplication modes."""

    duplicate = "duplicate"
    window = "window"
    duplicate_or_window = "duplicate_or_window"


class DedupOnSkip(str, Enum):
    """Behavior when dedup suppresses speech."""

    skip = "skip"
    sound_only = "sound_only"


def _apply_cli_overrides(
    cfg: Config,
    *,
    no_play: bool = False,
    fail_fast: bool = False,
    speed: Optional[float] = None,
    summary_provider: Optional[str] = None,
    tts_provider: Optional[str] = None,
    pronunciation_provider: Optional[str] = None,
    summary_model: Optional[str] = None,
    tts_model: Optional[str] = None,
    tts_voice: Optional[str] = None,
    tts_title_voice: Optional[str] = None,
    tts_message_voice: Optional[str] = None,
    pronunciation_model: Optional[str] = None,
    dedup_mode: Optional[str] = None,
    dedup_on_skip: Optional[str] = None,
    no_pronounce: bool = False,
) -> None:
    """Apply CLI overrides to config using proper Config methods."""
    logger = logging.getLogger(__name__)

    if no_play:
        cfg.set_tts_play_audio(False)
        logger.info("playback_disabled_via_cli")

    if fail_fast:
        cfg.set_fail_fast(True)
        logger.info("fallback_fail_fast_enabled_via_cli")

    if speed is not None:
        cfg.set_tts_speed(speed)
        logger.info("tts_speed_overridden", extra={"speed": speed})

    if summary_provider:
        cfg.set_summarizer_provider_order([summary_provider])
        logger.info("summary_provider_overridden", extra={"provider": summary_provider})

    if tts_provider:
        cfg.set_tts_provider_order([tts_provider])
        logger.info("tts_provider_overridden", extra={"provider": tts_provider})

    if pronunciation_provider:
        cfg.raw.setdefault("pronunciation", {})["provider_order"] = [pronunciation_provider]
        logger.info("pronunciation_provider_overridden", extra={"provider": pronunciation_provider})

    if no_pronounce:
        cfg.raw.setdefault("pronunciation", {})["enabled"] = False
        logger.info("pronunciation_disabled_via_cli")

    if summary_model:
        provider_name, key_name = _resolve_summary_model_target(cfg, summary_provider)
        cfg.set_provider_config(provider_name, key_name, summary_model)
        logger.info(
            "summary_model_overridden",
            extra={"provider": provider_name, "model": summary_model},
        )

    if tts_model:
        provider_name, key_name = _resolve_tts_model_target(cfg, tts_provider)
        cfg.set_provider_config(provider_name, key_name, tts_model)
        logger.info(
            "tts_model_overridden", extra={"provider": provider_name, "model": tts_model}
        )

    if tts_voice:
        provider_name = _resolve_tts_voice_provider(cfg, tts_provider)
        cfg.set_provider_config(provider_name, "voice", tts_voice)
        cfg.set_provider_config(provider_name, "title_voice", tts_voice)
        cfg.set_provider_config(provider_name, "message_voice", tts_voice)
        logger.info("tts_voice_overridden", extra={"provider": provider_name, "voice": tts_voice})

    if tts_title_voice:
        provider_name = _resolve_tts_voice_provider(cfg, tts_provider)
        cfg.set_provider_config(provider_name, "title_voice", tts_title_voice)
        logger.info("tts_title_voice_overridden", extra={"provider": provider_name, "voice": tts_title_voice})

    if tts_message_voice:
        provider_name = _resolve_tts_voice_provider(cfg, tts_provider)
        cfg.set_provider_config(provider_name, "message_voice", tts_message_voice)
        logger.info("tts_message_voice_overridden", extra={"provider": provider_name, "voice": tts_message_voice})

    if pronunciation_model:
        provider_name, key_name = _resolve_pronunciation_model_target(cfg, pronunciation_provider)
        cfg.set_provider_config(provider_name, key_name, pronunciation_model)
        logger.info(
            "pronunciation_model_overridden",
            extra={"provider": provider_name, "model": pronunciation_model},
        )

    if dedup_mode:
        cfg.set_dedup_mode(dedup_mode)
        logger.info("dedup_mode_overridden", extra={"mode": dedup_mode})

    if dedup_on_skip:
        cfg.set_dedup_on_skip(dedup_on_skip)
        logger.info("dedup_on_skip_overridden", extra={"on_skip": dedup_on_skip})


def _run_notify(
    *,
    config: Optional[Path],
    message: Optional[str],
    event: str,
    session_name: Optional[str],
    source_tool: Optional[str],
    conversation_id: Optional[str],
    session_id: Optional[str],
    agent: Optional[str],
    session_key: Optional[str],
    input_json: Optional[str],
    input_file: Optional[Path],
    message_file: Optional[Path],
    no_play: bool,
    no_title: bool,
    no_summarize: bool,
    no_pronounce: bool,
    fail_fast: bool,
    speed: Optional[float],
    log_level: Optional[str],
    log_format: Optional[str],
    log_file: Optional[Path],
    debug: bool,
    summary_provider: Optional[SummarizerProvider],
    tts_provider: Optional[TTSProvider],
    pronunciation_provider: Optional[PronunciationProvider],
    summary_model: Optional[str],
    tts_model: Optional[str],
    tts_voice: Optional[str],
    tts_title_voice: Optional[str],
    tts_message_voice: Optional[str],
    pronunciation_model: Optional[str],
    dedup_mode: Optional[DedupMode],
    dedup_on_skip: Optional[DedupOnSkip],
) -> None:
    _setup_logging_from_options(
        None, debug, log_level, log_format, str(log_file) if log_file else None
    )
    logger = logging.getLogger(__name__)
    logger.info(
        "cli_start",
        extra={
            "has_message": bool(message),
            "has_input_json": bool(input_json),
            "has_input_file": bool(input_file),
        },
    )

    cfg = load_config_without_repository_registration(config)
    _setup_logging_from_options(
        cfg, debug, log_level, log_format, str(log_file) if log_file else None
    )
    logger.info("config_loaded", extra={"config_path": config or "default"})

    _apply_cli_overrides(
        cfg,
        no_play=no_play,
        fail_fast=fail_fast,
        speed=speed,
        summary_provider=summary_provider.value if summary_provider else None,
        tts_provider=tts_provider.value if tts_provider else None,
        pronunciation_provider=pronunciation_provider.value if pronunciation_provider else None,
        summary_model=summary_model,
        tts_model=tts_model,
        tts_voice=tts_voice,
        tts_title_voice=tts_title_voice,
        tts_message_voice=tts_message_voice,
        pronunciation_model=pronunciation_model,
        dedup_mode=dedup_mode.value if dedup_mode else None,
        dedup_on_skip=dedup_on_skip.value if dedup_on_skip else None,
        no_pronounce=no_pronounce,
    )

    request = _load_payload(
        message=message,
        event=event,
        session_name=session_name,
        source_tool=source_tool,
        conversation_id=conversation_id,
        session_id=session_id,
        agent=agent,
        input_json=input_json,
        input_file=str(input_file) if input_file else None,
        session_key=session_key,
        message_file=str(message_file) if message_file else None,
    )
    if not isinstance(request.metadata, dict):
        request.metadata = {}
    request.metadata.setdefault("cwd", str(Path.cwd().resolve()))
    cli_override_payload = _build_cli_override_payload(
        cfg,
        no_play=no_play,
        fail_fast=fail_fast,
        speed=speed,
        summary_provider=summary_provider.value if summary_provider else None,
        tts_provider=tts_provider.value if tts_provider else None,
        pronunciation_provider=pronunciation_provider.value if pronunciation_provider else None,
        summary_model=summary_model,
        tts_model=tts_model,
        tts_voice=tts_voice,
        tts_title_voice=tts_title_voice,
        tts_message_voice=tts_message_voice,
        pronunciation_model=pronunciation_model,
        dedup_mode=dedup_mode.value if dedup_mode else None,
        dedup_on_skip=dedup_on_skip.value if dedup_on_skip else None,
        no_pronounce=no_pronounce,
    )
    if cli_override_payload:
        request.metadata["_speakup_cli_overrides"] = cli_override_payload
    if speed is not None:
        request.metadata["cli_speed"] = speed
    if no_title:
        request.metadata["_speakup_skip_title"] = True
    request.skip_summarization = no_summarize
    register_repository_config(cfg, config, request.metadata.get("cwd"))
    logger.info(
        "request_loaded",
        extra={
            "event": request.event.value,
            "message_length": len(request.message),
            "skip_summarization": request.skip_summarization,
        },
    )

    result = NotifyService(
        cfg,
        history=NotificationHistory(retention_days=int(cfg.get("history", "retention_days", default=30))),
    ).notify(request)
    logger.info(
        "notify_completed",
        extra={
            "status": result.status,
            "backend": result.backend,
            "played": result.played,
        },
    )
    json.dump(result.to_dict(), sys.stdout)
    sys.stdout.write("\n")


@app.command()
def init_config(
    force: bool = typer.Option(
        False, "--force", "-f", help="Overwrite config file if it exists"
    ),
) -> None:
    """Write default config to ~/.config/speakup/config.jsonc."""
    try:
        path = write_default_config(force=force)
    except FileExistsError as exc:
        json.dump({"status": "error", "error": str(exc)}, sys.stdout)
        sys.stdout.write("\n")
        raise typer.Exit(2)
    json.dump({"status": "ok", "config_path": str(path)}, sys.stdout)
    sys.stdout.write("\n")


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    message: Optional[str] = typer.Option(
        None, "--message", "-m", help="Raw message text"
    ),
    message_file: Optional[Path] = typer.Option(
        None,
        "--message-file",
        help="Path to file containing raw message text to summarize",
    ),
    input_json: Optional[str] = typer.Option(
        None,
        "--input-json",
        "-j",
        help="JSON payload string using NotifyRequest schema",
    ),
    input_file: Optional[Path] = typer.Option(
        None,
        "--input-file",
        "-f",
        help="Path to JSON payload using NotifyRequest schema",
    ),
    event: str = typer.Option(
        "final", "--event", "-e", help="final|error|needs_input|progress|info"
    ),
    session_name: Optional[str] = typer.Option(
        None, "--session-name", "-s", help="Optional session label spoken at the start"
    ),
    source_tool: Optional[str] = typer.Option(
        None, "--source-tool", help="Optional source tool name used in speech title rendering"
    ),
    conversation_id: Optional[str] = typer.Option(
        None, "--conversation-id", help="Optional stable conversation identifier for session-name generation"
    ),
    session_id: Optional[str] = typer.Option(
        None, "--session-id", help="Optional stable session identifier for session-name generation"
    ),
    agent: Optional[str] = typer.Option(
        None, "--agent", help="Agent name to persist in history and use for replay filtering"
    ),
    session_key: Optional[str] = typer.Option(
        None, "--session-key", help="Exact unique session identifier used for history lookup"
    ),
    no_summarize: bool = typer.Option(
        False, "--no-summarize", help="Skip summarization, use raw message for TTS"
    ),
    no_pronounce: bool = typer.Option(
        False, "--no-pronounce", help="Skip pronunciation adaptation for this run"
    ),
    speed: Optional[float] = typer.Option(
        None, "--speed", help="Override TTS speed for this run"
    ),
    summary_provider: Optional[SummarizerProvider] = typer.Option(
        None, "--summary-provider", help="Override summarization provider"
    ),
    summary_model: Optional[str] = typer.Option(
        None, "--summary-model", help="Override summary model for this run"
    ),
    tts_provider: Optional[TTSProvider] = typer.Option(
        None, "--tts-provider", "-t", help="Override TTS provider"
    ),
    pronunciation_provider: Optional[PronunciationProvider] = typer.Option(
        None, "--pronunciation-provider", help="Override pronunciation adaptation provider"
    ),
    tts_model: Optional[str] = typer.Option(
        None, "--tts-model", help="Override TTS model for this run"
    ),
    tts_voice: Optional[str] = typer.Option(
        None, "--tts-voice", help="Override TTS voice for this run"
    ),
    tts_title_voice: Optional[str] = typer.Option(
        None, "--tts-title-voice", help="Override TTS title voice for this run"
    ),
    tts_message_voice: Optional[str] = typer.Option(
        None, "--tts-message-voice", help="Override TTS message voice for this run"
    ),
    pronunciation_model: Optional[str] = typer.Option(
        None, "--pronunciation-model", help="Override pronunciation adaptation model for this run"
    ),
    dedup_mode: Optional[DedupMode] = typer.Option(
        None,
        "--dedup-mode",
        help="Override dedup mode: duplicate|window|duplicate_or_window",
    ),
    dedup_on_skip: Optional[DedupOnSkip] = typer.Option(
        None,
        "--dedup-on-skip",
        help="Override dedup skip behavior: skip|sound_only",
    ),
    fail_fast: bool = typer.Option(
        False,
        "--fail-fast",
        help="Do not fall back to later providers after a provider error",
    ),
    no_play: bool = typer.Option(
        False, "--no-play", help="Synthesize audio but skip local playback"
    ),
    no_title: bool = typer.Option(
        False, "--no-title", help="Skip reading the spoken title; read only the notification message"
    ),
    log_level: Optional[str] = typer.Option(
        None,
        "--log-level",
        "-l",
        help="Override logging level (DEBUG|INFO|WARNING|ERROR|CRITICAL)",
    ),
    log_format: Optional[str] = typer.Option(
        None, "--log-format", help="Override log format (text|json)"
    ),
    log_file: Optional[Path] = typer.Option(
        None, "--log-file", help="Write logs to file path"
    ),
    debug: bool = typer.Option(
        False, "--debug", "-d", help="Shortcut for --log-level DEBUG"
    ),
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config.jsonc"
    ),
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit",
        is_eager=True,
    ),
) -> None:
    """speakup: Speak concise agent status updates."""
    if version:
        print(get_version())
        raise typer.Exit()

    if ctx.invoked_subcommand is None:
        _run_notify(
            config=config,
            message=message,
            event=event,
            session_name=session_name,
            source_tool=source_tool,
            conversation_id=conversation_id,
            session_id=session_id,
            agent=agent,
            session_key=session_key,
            input_json=input_json,
            input_file=input_file,
            message_file=message_file,
            no_play=no_play,
            no_title=no_title,
            no_summarize=no_summarize,
            no_pronounce=no_pronounce,
            fail_fast=fail_fast,
            speed=speed,
            log_level=log_level,
            log_format=log_format,
            log_file=log_file,
            debug=debug,
            summary_provider=summary_provider,
            tts_provider=tts_provider,
            pronunciation_provider=pronunciation_provider,
            summary_model=summary_model,
            tts_model=tts_model,
            tts_voice=tts_voice,
            tts_title_voice=tts_title_voice,
            tts_message_voice=tts_message_voice,
            pronunciation_model=pronunciation_model,
            dedup_mode=dedup_mode,
            dedup_on_skip=dedup_on_skip,
        )
        raise typer.Exit()

def _setup_logging_from_options(
    config: Optional[Config],
    debug: bool,
    log_level: Optional[str],
    log_format: Optional[str],
    log_file: Optional[str],
) -> None:
    if config:
        setup_logging(
            config.get("logging", default={}),
            level_override="DEBUG" if debug else log_level,
            format_override=log_format,
            file_override=log_file,
        )
    else:
        setup_logging(
            {},
            level_override="DEBUG" if debug else log_level,
            format_override=log_format,
            file_override=log_file,
        )


def _self_test_audio(config: Config) -> dict:
    logger = logging.getLogger(__name__)
    playback = MacOSPlaybackAdapter()
    event_sound_path = Path(
        config.get("event_sounds", "files", default={}).get("info", "/System/Library/Sounds/Ping.aiff")
    )
    checks: dict[str, dict[str, str | bool | None]] = {
        "event_sound": {
            "ok": False,
            "error": None,
            "path": str(event_sound_path),
        },
    }

    try:
        playback.play_file(event_sound_path)
        checks["event_sound"]["ok"] = True
    except AdapterError as exc:
        checks["event_sound"]["error"] = str(exc)
        logger.warning("self_test_event_sound_failed", extra={"error": str(exc)})

    overall_ok = bool(checks["event_sound"]["ok"])
    return {"status": "ok" if overall_ok else "error", "checks": checks}


def _apply_request_cli_overrides(
    request: NotifyRequest,
    *,
    session_name: Optional[str],
    source_tool: Optional[str],
    conversation_id: Optional[str],
    session_id: Optional[str],
    agent: Optional[str],
    session_key: Optional[str],
) -> NotifyRequest:
    if agent:
        request.agent = agent
    if session_key:
        request.session_key = session_key
    if source_tool is not None:
        request.source_tool = source_tool
    if conversation_id is not None:
        request.conversation_id = conversation_id
    if session_id is not None:
        request.session_id = session_id
    if session_name is not None:
        request.session_name = session_name
    if request.session_key and not request.conversation_id and not request.session_id:
        request.session_id = request.session_key
    return request


def _normalize_notify_payload(payload: dict[str, object]) -> dict[str, object]:
    normalized = dict(payload)
    legacy_source_tool = normalized.pop("sourceTool", None)
    if "source_tool" not in normalized and legacy_source_tool is not None:
        normalized["source_tool"] = legacy_source_tool
    return normalized


def _expected_replay_audio_paths(
    service: NotifyService,
    *,
    entry_summary: str,
    event: MessageEvent,
    session_name: str | None,
    context_kind: str | None = None,
    context_name: str | None = None,
    agent: str,
    source_tool: str | None,
) -> int:
    spoken_title, _, spoken_summary = service._prepare_spoken_summary(
        event=event,
        summary_text=entry_summary,
        raw_message=entry_summary,
        session_name=session_name,
        context=SpokenContext(context_kind, context_name) if context_kind and context_name else None,
        agent=agent,
        source_tool=source_tool,
    )
    if not spoken_title:
        return 1
    if session_name or context_name:
        return 2
    if spoken_title and entry_summary == spoken_summary:
        return 2
    return 1


def _load_payload(
    message: Optional[str],
    event: str,
    session_name: Optional[str],
    source_tool: Optional[str],
    conversation_id: Optional[str],
    session_id: Optional[str],
    agent: Optional[str],
    input_json: Optional[str],
    input_file: Optional[str],
    session_key: Optional[str],
    message_file: Optional[str] = None,
) -> NotifyRequest:
    if input_json:
        payload = _normalize_notify_payload(json.loads(input_json))
        request = NotifyRequest(**payload)
        return _apply_request_cli_overrides(
            request,
            session_name=session_name,
            source_tool=source_tool,
            conversation_id=conversation_id,
            session_id=session_id,
            agent=agent,
            session_key=session_key,
        )

    if input_file:
        payload = _normalize_notify_payload(json.loads(open(input_file).read()))
        request = NotifyRequest(**payload)
        return _apply_request_cli_overrides(
            request,
            session_name=session_name,
            source_tool=source_tool,
            conversation_id=conversation_id,
            session_id=session_id,
            agent=agent,
            session_key=session_key,
        )

    if message_file:
        message = Path(message_file).read_text().strip()
        if not message:
            raise typer.BadParameter(f"Message file is empty: {message_file}")

    if not message:
        raise typer.BadParameter(
            "Provide --message, --message-file, or --input-json/--input-file"
        )

    try:
        msg_event = MessageEvent(event)
    except Exception as exc:
        allowed = "|".join(item.value for item in MessageEvent)
        raise typer.BadParameter(f"event must be one of: {allowed}") from exc
    return NotifyRequest(
        message=message,
        event=msg_event,
        session_name=session_name,
        source_tool=source_tool,
        conversation_id=conversation_id,
        session_id=session_id or (session_key if session_key and not conversation_id else None),
        session_key=session_key,
        agent=agent or "speakup",
    )


@app.command()
def replay(
    count: int = typer.Argument(1, min=1, help="How many notifications to replay"),
    agent: Optional[str] = typer.Option(None, "--agent", help="Agent name to filter by, e.g. droid or pi"),
    session_key: Optional[str] = typer.Option(None, "--session-key", help="Exact unique session identifier to replay"),
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config JSON"
    ),
    log_level: Optional[str] = typer.Option(
        None, "--log-level", "-l", help="Override logging level"
    ),
    log_format: Optional[str] = typer.Option(
        None, "--log-format", help="Override log format"
    ),
    log_file: Optional[Path] = typer.Option(
        None, "--log-file", help="Write logs to file path"
    ),
    debug: bool = typer.Option(
        False, "--debug", "-d", help="Shortcut for --log-level DEBUG"
    ),
) -> None:
    """Replay recent notifications, optionally scoped to an exact agent/session pair."""
    cfg = load_config_with_repository_registration(config)
    _setup_logging_from_options(
        cfg, debug, log_level, log_format, str(log_file) if log_file else None
    )

    if bool(agent) != bool(session_key):
        raise typer.BadParameter("Provide both --agent and --session-key together")

    history = NotificationHistory(retention_days=int(cfg.get("history", "retention_days", default=30)))
    if agent and session_key:
        entries = history.get_recent_replayable_for_session(agent, session_key, limit=count)
        error = f"No replayable notifications found for agent={agent} session_key={session_key}"
    else:
        entries = history.get_recent_replayable(limit=count)
        error = "No replayable notifications found"

    if not entries:
        json.dump(
            {
                "status": "error",
                "error": error,
            },
            sys.stdout,
        )
        sys.stdout.write("\n")
        raise typer.Exit(1)

    service = NotifyService(cfg, history=history)
    replayed = 0
    from_audio = 0
    from_summary = 0
    failed = 0
    replay_sessions: list[dict[str, Optional[str]]] = []
    seen_sessions: set[tuple[str, Optional[str]]] = set()
    for entry in entries:
        if entry.session_key is None:
            replay_sessions.append({"agent": entry.agent, "session_key": entry.session_key})
            continue
        session = (entry.agent, entry.session_key)
        if session in seen_sessions:
            continue
        seen_sessions.add(session)
        replay_sessions.append({"agent": entry.agent, "session_key": entry.session_key})

    for entry in reversed(entries):
        source_tool = entry.metadata.get("source_tool") if isinstance(entry.metadata, dict) else None
        context_kind = entry.metadata.get("context_kind") if isinstance(entry.metadata, dict) else None
        context_name = entry.metadata.get("context_name") if isinstance(entry.metadata, dict) else None
        context_kind = context_kind if isinstance(context_kind, str) else None
        context_name = context_name if isinstance(context_name, str) else None
        metadata_playback_audio_paths = entry.metadata.get("playback_audio_paths", []) if isinstance(entry.metadata, dict) else []
        saved_playback_audio_paths = [Path(str(path)) for path in metadata_playback_audio_paths if path]
        metadata_audio_paths = entry.metadata.get("audio_paths", []) if isinstance(entry.metadata, dict) else []
        replay_audio_paths = [Path(str(path)) for path in metadata_audio_paths if path]
        if saved_playback_audio_paths and all(path.exists() for path in saved_playback_audio_paths):
            try:
                service.registry.get_playback().play_files(saved_playback_audio_paths)
                replayed += 1
                from_audio += 1
                continue
            except AdapterError:
                pass
        expected_audio_paths = _expected_replay_audio_paths(
            service,
            entry_summary=entry.summary,
            event=MessageEvent(entry.event),
            session_name=entry.session_name,
            context_kind=context_kind,
            context_name=context_name,
            agent=entry.agent,
            source_tool=source_tool,
        )
        if (
            len(replay_audio_paths) >= expected_audio_paths
            and all(path.exists() for path in replay_audio_paths)
        ):
            try:
                service.registry.get_playback().play_files(replay_audio_paths)
                replayed += 1
                from_audio += 1
                continue
            except AdapterError:
                pass
        elif not replay_audio_paths and not entry.session_name:
            audio_path = Path(entry.audio_path) if entry.audio_path else None
            if audio_path and audio_path.exists():
                try:
                    service.registry.get_playback().play_files([audio_path])
                    replayed += 1
                    from_audio += 1
                    continue
                except AdapterError:
                    pass

        result = service.replay_summary(
            summary=entry.summary,
            event=MessageEvent(entry.event),
            session_name=entry.session_name,
            context_kind=context_kind,
            context_name=context_name,
            agent=entry.agent,
            source_tool=source_tool,
        )
        if result.played:
            replayed += 1
            from_summary += 1
        elif result.status == "skipped":
            continue
        else:
            failed += 1

    payload = {
        "status": "ok" if failed == 0 else ("partial_success" if replayed > 0 else "error"),
        "requested": count,
        "replayed": replayed,
        "from_audio": from_audio,
        "from_summary": from_summary,
        "failed": failed,
    }
    if len(replay_sessions) == 1:
        payload["agent"] = replay_sessions[0]["agent"]
        payload["session_key"] = replay_sessions[0]["session_key"]
    else:
        payload["sessions"] = replay_sessions

    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")


def _load_text_input(
    text: Optional[str],
    input_file: Optional[Path],
) -> str:
    if text is not None:
        return text

    if input_file is not None:
        return input_file.read_text().rstrip("\n")

    stdin_text = sys.stdin.read().rstrip("\n")
    if stdin_text:
        return stdin_text

    raise typer.BadParameter("Provide --text, --input-file, or stdin")


@app.command()
def verbalize(
    text: Optional[str] = typer.Option(
        None, "--text", "-t", help="Text to transform into a TTS-friendly form"
    ),
    input_file: Optional[Path] = typer.Option(
        None, "--input-file", "-f", help="Path to text file to transform"
    ),
) -> None:
    """Transform text into a more readable spoken form."""
    source_text = _load_text_input(text, input_file)
    print(transform_text_for_reading(source_text))


@app.command()
def pronounce(
    message: str = typer.Option(..., "--message", "-m", help="Message segment to adapt"),
    title: Optional[str] = typer.Option(None, "--title", help="Optional title segment to adapt"),
    spoken_language: Optional[str] = typer.Option(None, "--spoken-language", help="Known spoken language for adaptation"),
    plain: bool = typer.Option(False, "--plain", help="Print only the adapted message text"),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to config.jsonc"),
    pronunciation_provider: Optional[PronunciationProvider] = typer.Option(
        None, "--pronunciation-provider", help="Override pronunciation adaptation provider"
    ),
    pronunciation_model: Optional[str] = typer.Option(
        None, "--pronunciation-model", help="Override pronunciation adaptation model for this run"
    ),
    fail_fast: bool = typer.Option(False, "--fail-fast", help="Fail instead of falling back on provider errors"),
) -> None:
    """Adapt final spoken text for TTS pronunciation without playback."""
    if plain and title:
        json.dump(
            {
                "status": "error",
                "error": "plain output requires a single message segment",
            },
            sys.stdout,
        )
        sys.stdout.write("\n")
        raise typer.Exit(2)

    cfg = load_config_with_repository_registration(config)
    _apply_cli_overrides(
        cfg,
        fail_fast=fail_fast,
        pronunciation_provider=pronunciation_provider.value if pronunciation_provider else None,
        pronunciation_model=pronunciation_model,
    )
    registry = build_registry_from_config(cfg)
    provider_order = cfg.get("pronunciation", "provider_order", default=["omlx"])
    fail_fast_config = bool(cfg.get("fallback", "fail_fast", default=False))
    privacy_mode = cfg.get("privacy", "mode", default="local_only")
    allow_remote = bool(cfg.get("privacy", "allow_remote_fallback", default=False))
    last_error: str | None = None
    for provider in provider_order:
        if provider in REMOTE_PRONUNCIATION_PROVIDERS:
            if privacy_mode == "local_only" or (privacy_mode == "prefer_local" and not allow_remote):
                continue
        try:
            result = registry.get_pronunciation(str(provider)).adapt(
                title=title,
                message=message,
                spoken_language=spoken_language,
            )
            if plain:
                print(result.message)
            else:
                json.dump(
                    {
                        "spoken_language": result.spoken_language,
                        "title": result.title,
                        "message": result.message,
                    },
                    sys.stdout,
                    ensure_ascii=False,
                )
                sys.stdout.write("\n")
            return
        except AdapterError as exc:
            last_error = str(exc)
            if fail_fast_config:
                json.dump({"status": "error", "error": last_error}, sys.stdout)
                sys.stdout.write("\n")
                raise typer.Exit(1)

    if plain:
        print(message)
    else:
        json.dump(
            {
                "spoken_language": spoken_language,
                "title": title,
                "message": message,
                "fallback": True,
                "error": last_error,
            },
            sys.stdout,
            ensure_ascii=False,
        )
        sys.stdout.write("\n")


@app.command("self-test")
def self_test(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config.jsonc"
    ),
    log_level: Optional[str] = typer.Option(
        None, "--log-level", "-l", help="Override logging level"
    ),
    log_format: Optional[str] = typer.Option(
        None, "--log-format", help="Override log format"
    ),
    log_file: Optional[Path] = typer.Option(
        None, "--log-file", help="Write logs to file path"
    ),
    debug: bool = typer.Option(
        False, "--debug", "-d", help="Shortcut for --log-level DEBUG"
    ),
) -> None:
    """Run event sound playback diagnostics."""
    cfg = load_config_with_repository_registration(config)
    _setup_logging_from_options(cfg, debug, log_level, log_format, log_file)

    result = _self_test_audio(cfg)
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    if result["status"] != "ok":
        raise typer.Exit(1)


@app.command()
def doctor(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config.jsonc"
    ),
    log_level: Optional[str] = typer.Option(
        None, "--log-level", "-l", help="Override logging level"
    ),
    log_format: Optional[str] = typer.Option(
        None, "--log-format", help="Override log format"
    ),
    log_file: Optional[Path] = typer.Option(
        None, "--log-file", help="Write logs to file path"
    ),
    debug: bool = typer.Option(
        False, "--debug", "-d", help="Shortcut for --log-level DEBUG"
    ),
) -> None:
    """Run configured health checks."""
    cfg = load_config_with_repository_registration(config)
    _setup_logging_from_options(
        cfg, debug, log_level, log_format, str(log_file) if log_file else None
    )

    result = _self_test_audio(cfg)
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    if result["status"] != "ok":
        raise typer.Exit(1)


@app.command()
def pi(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config JSON"
    ),
    input_file: Optional[Path] = typer.Option(
        None, "--input-file", "-f", help="Path to Pi payload JSON. Defaults to stdin."
    ),
) -> None:
    """Pi coding agent wrapper command."""
    from .config import ConfigValidationError
    from .integrations.pi_extension import request_from_pi_payload

    _setup_logging_from_options(None, False, None, None, None)
    logger = logging.getLogger(__name__)

    try:
        cfg = load_config_with_repository_registration(config)
    except ConfigValidationError as exc:
        json.dump({"status": "error", "error": str(exc)}, sys.stdout)
        sys.stdout.write("\n")
        raise typer.Exit(2)

    _setup_logging_from_options(cfg, False, None, None, None)
    logger.info(
        "pi_wrapper_start",
        extra={"has_input_file": bool(input_file), "config_path": config or "default"},
    )

    # Load Pi payload
    if input_file:
        payload = json.loads(input_file.read_text())
    else:
        raw = sys.stdin.read().strip()
        if not raw:
            json.dump(
                {
                    "status": "error",
                    "error": "Expected Pi JSON payload via stdin or --input-file",
                },
                sys.stdout,
            )
            sys.stdout.write("\n")
            raise typer.Exit(1)
        payload = json.loads(raw)

    log_payloads = bool(cfg.get("logging", "log_provider_payloads", default=False))
    if log_payloads:
        logger.info(
            "pi_payload",
            extra={
                "payload": redact_payload(
                    payload,
                    enabled=bool(cfg.get("logging", "redact_sensitive", default=True)),
                )
            },
        )
    else:
        logger.info("pi_payload_loaded", extra={"payload_keys": sorted(str(key) for key in payload.keys())})

    request = request_from_pi_payload(payload)
    result = NotifyService(
        cfg,
        history=NotificationHistory(retention_days=int(cfg.get("history", "retention_days", default=30))),
    ).notify(request)
    logger.info(
        "pi_wrapper_completed",
        extra={
            "status": result.status,
            "state": result.state.value,
            "backend": result.backend,
        },
    )
    json.dump(result.to_dict(), sys.stdout)
    sys.stdout.write("\n")


def _get_config_path(config: Optional[Path]) -> Path:
    return config or Path.home() / ".config" / "speakup" / "config.jsonc"


def _set_enabled(
    enabled: bool,
    *,
    config: Optional[Path] = None,
    repo: bool = False,
    cwd: Optional[Path] = None,
) -> None:
    target_path = _get_config_path(config)
    writable_config = _load_config_for_write(target_path)
    repository_path: str | None = None

    if repo:
        repository_path = repository_config_key(cwd)
        if repository_path is None:
            json.dump({"status": "error", "error": f"No repository root found from: {cwd or Path.cwd()}"}, sys.stdout)
            sys.stdout.write("\n")
            raise typer.Exit(2)

        repositories = writable_config.setdefault("repositories", {})
        if not isinstance(repositories, dict):
            validate_config(writable_config)
            raise typer.Exit(2)
        existing_repo_config = repositories.get(repository_path, {})
        if not isinstance(existing_repo_config, dict):
            existing_repo_config = {}
        repositories[repository_path] = deep_merge(existing_repo_config, {"enabled": enabled})
    else:
        writable_config["enabled"] = enabled

    validate_config(writable_config)
    _write_json_atomic(target_path, writable_config)
    output: dict[str, object] = {"status": "ok", "config_path": str(target_path), "enabled": enabled}
    if repository_path:
        output["repository_path"] = repository_path
    json.dump(output, sys.stdout)
    sys.stdout.write("\n")


@app.command("enable")
def enable(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config JSON"
    ),
    repo: bool = typer.Option(
        False, "--repo", help="Toggle the active repository entry instead of the root config"
    ),
    cwd: Optional[Path] = typer.Option(
        None, "--cwd", help="Project directory to toggle when using --repo"
    ),
) -> None:
    """Enable speakup globally or for a repository."""
    _set_enabled(True, config=config, repo=repo, cwd=cwd)


@app.command("disable")
def disable(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config JSON"
    ),
    repo: bool = typer.Option(
        False, "--repo", help="Toggle the active repository entry instead of the root config"
    ),
    cwd: Optional[Path] = typer.Option(
        None, "--cwd", help="Project directory to toggle when using --repo"
    ),
) -> None:
    """Disable speakup globally or for a repository."""
    _set_enabled(False, config=config, repo=repo, cwd=cwd)


@app.command("show-config")
def show_config(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config JSON"
    ),
) -> None:
    """Open the config file in the default app or configured viewer."""
    target_path = _get_config_path(config)
    viewer_command: str | None = None

    if target_path.exists():
        cfg = load_config_with_repository_registration(target_path)
        viewer_command = cfg.get("config_viewer", "command")
    else:
        if not typer.confirm(f"Config file does not exist: {target_path}\nCreate default config?"):
            print(f"Config file not found: {target_path}", file=sys.stderr)
            raise typer.Exit(1)
        target_path = write_default_config(target_path)
        cfg = load_config_with_repository_registration(target_path)
        viewer_command = cfg.get("config_viewer", "command")

    print(f"Config file: {target_path}")
    _open_config_file(target_path, viewer_command)


@app.command("show-config-path")
def show_config_path(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config JSON"
    ),
) -> None:
    """Print the config file path."""
    print(_get_config_path(config))


@app.command("save-repo-config")
def save_repo_config(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config JSON"
    ),
    cwd: Optional[Path] = typer.Option(
        None, "--cwd", help="Project directory to save central repository config for"
    ),
) -> None:
    """Save active provider settings to the main config repositories section."""
    cfg = load_config_with_repository_registration(config, cwd)
    if not bool(cfg.get("repo_config", "save_active_provider_config", default=False)):
        json.dump(
            {
                "status": "error",
                "error": "repo_config.save_active_provider_config is disabled",
            },
            sys.stdout,
        )
        sys.stdout.write("\n")
        raise typer.Exit(2)

    project_dir = (cwd or Path.cwd()).expanduser()
    repo_config_path = project_config_path(project_dir)
    if repo_config_path is None:
        json.dump({"status": "error", "error": f"No repository root found from: {project_dir}"}, sys.stdout)
        sys.stdout.write("\n")
        raise typer.Exit(2)

    target_path = _get_config_path(config)
    repository_path = str(repo_config_path.parent.resolve())
    payload = _active_repo_config_payload(cfg, repo_config_path.parent)
    writable_config = _load_config_for_write(target_path)
    repositories = writable_config.setdefault("repositories", {})
    existing_repo_config = repositories.get(repository_path, {}) if isinstance(repositories, dict) else {}
    repositories[repository_path] = deep_merge(existing_repo_config, payload)
    validate_config(writable_config)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(writable_config, indent=2) + "\n")
    json.dump({"status": "ok", "config_path": str(target_path), "repository_path": repository_path}, sys.stdout)
    sys.stdout.write("\n")


@app.command("show-logs")
def show_logs(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config JSON"
    ),
) -> None:
    """Show and follow log file using configured command."""
    import shlex
    import subprocess

    cfg = load_config_with_repository_registration(config)
    log_file = cfg.get("logging", "file_path", default=str(get_default_log_file_path()))
    color_log_file = cfg.get("logging", "file_path_color") or f"{log_file}.color"
    log_file = str(Path(log_file).expanduser())
    color_log_file = str(Path(color_log_file).expanduser())
    viewer_command = cfg.get("log_viewer", "command", default="tail -n 25 -f")

    color_log_path = Path(color_log_file)
    log_path = Path(log_file)

    if color_log_path.exists():
        target_path = color_log_path
    elif log_path.exists():
        target_path = log_path
    else:
        print(f"Log file not found: {log_file}", file=sys.stderr)
        raise typer.Exit(1)

    print(f"Log file: {target_path}")
    print()

    cmd_parts = shlex.split(viewer_command) + [str(target_path)]
    try:
        subprocess.run(cmd_parts)
    except KeyboardInterrupt:
        pass
    except FileNotFoundError:
        print(f"Log viewer command not found: {cmd_parts[0]}", file=sys.stderr)
        raise typer.Exit(127)
    except Exception as exc:
        print(f"Log viewer failed: {exc}", file=sys.stderr)
        raise typer.Exit(1)


@app.command("show-logs-path")
def show_logs_path(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config JSON"
    ),
) -> None:
    """Print the configured log file path."""
    cfg = load_config_with_repository_registration(config)
    log_file = cfg.get("logging", "file_path", default=str(get_default_log_file_path()))
    color_log_file = cfg.get("logging", "file_path_color") or f"{log_file}.color"
    log_file = str(Path(log_file).expanduser())
    color_log_file = str(Path(color_log_file).expanduser())

    color_log_path = Path(color_log_file)
    log_path = Path(log_file)

    if color_log_path.exists():
        print(color_log_path)
        return
    print(log_path)


@app.command()
def version() -> None:
    """Show version information."""
    print(get_version())


@app.command()
def desktop(
    dev: bool = typer.Option(False, "--dev", help="Run in development mode"),
) -> None:
    """Launch the desktop notification history viewer.
    
    This opens a native desktop application for browsing and searching
    notification history. Requires the speakup-desktop Tauri app to be built.
    """
    import shutil
    import subprocess
    
    # Determine the path to the desktop app
    repo_root = Path(__file__).parent.parent
    desktop_dir = repo_root / "speakup-desktop"
    
    if not desktop_dir.exists():
        print("Desktop app not found. Please ensure speakup-desktop is built.", file=sys.stderr)
        print(f"Expected location: {desktop_dir}", file=sys.stderr)
        raise typer.Exit(1)
    
    if dev:
        # Run in development mode with cargo tauri dev
        cargo_cmd = shutil.which("cargo")
        if not cargo_cmd:
            print("Cargo not found. Please install Rust to run in dev mode.", file=sys.stderr)
            raise typer.Exit(1)
        
        try:
            subprocess.run([cargo_cmd, "tauri", "dev"], cwd=desktop_dir)
        except KeyboardInterrupt:
            pass
        except FileNotFoundError:
            print("cargo tauri not found. Install with: cargo install tauri-cli", file=sys.stderr)
            raise typer.Exit(1)
    else:
        # Try to find and run the built application
        possible_paths = [
            desktop_dir / "src-tauri" / "target" / "release" / "speakup-desktop",
            desktop_dir / "src-tauri" / "target" / "debug" / "speakup-desktop",
        ]
        
        # On macOS, also check for .app bundle
        if sys.platform == "darwin":
            possible_paths.insert(
                0,
                desktop_dir / "src-tauri" / "target" / "release" / "bundle" / "macos" / "Speakup Desktop.app"
            )
        
        app_path = None
        for path in possible_paths:
            if path.exists():
                app_path = path
                break
        
        if not app_path:
            print("Built desktop app not found.", file=sys.stderr)
            print("Please build it first:", file=sys.stderr)
            print(f"  cd {desktop_dir} && cargo tauri build", file=sys.stderr)
            print("\nOr run in development mode:", file=sys.stderr)
            print("  speakup desktop --dev", file=sys.stderr)
            raise typer.Exit(1)
        
        try:
            if sys.platform == "darwin" and str(app_path).endswith(".app"):
                subprocess.run(["open", str(app_path)])
            else:
                subprocess.run([str(app_path)])
        except KeyboardInterrupt:
            pass
        except Exception as exc:
            print(f"Failed to launch desktop app: {exc}", file=sys.stderr)
            raise typer.Exit(1)


def main() -> None:
    app()


if __name__ == "__main__":
    app()
