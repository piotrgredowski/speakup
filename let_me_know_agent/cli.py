from __future__ import annotations

import json
import logging
import os
import sys
from enum import Enum
from pathlib import Path
from typing import Optional

import typer

from .app_logging import setup_logging
from .config import Config, write_default_config
from .errors import AdapterError
from .models import MessageEvent, NotifyRequest
from .playback.macos import MacOSPlaybackAdapter
from .service import NotifyService
from .tts.kokoro import KokoroTTSAdapter
from .tts.kokoro_cli import KokoroCliTTSAdapter
from .version import get_version

app = typer.Typer(
    name="let-me-know",
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


class TTSProvider(str, Enum):
    """Available TTS providers."""

    kokoro_cli = "kokoro_cli"
    macos = "macos"
    kokoro = "kokoro"
    lmstudio = "lmstudio"
    elevenlabs = "elevenlabs"
    openai = "openai"
    gemini = "gemini"
    omlx = "omlx"


def _apply_cli_overrides(
    cfg: Config,
    *,
    no_play: bool = False,
    fail_fast: bool = False,
    summary_provider: Optional[str] = None,
    tts_provider: Optional[str] = None,
    summary_model: Optional[str] = None,
    tts_model: Optional[str] = None,
) -> None:
    """Apply CLI overrides to config using proper Config methods."""
    logger = logging.getLogger(__name__)

    if no_play:
        cfg.set_tts_play_audio(False)
        logger.info("playback_disabled_via_cli")

    if fail_fast:
        cfg.set_fail_fast(True)
        logger.info("fallback_fail_fast_enabled_via_cli")

    if summary_provider:
        cfg.set_summarizer_provider_order([summary_provider])
        logger.info("summary_provider_overridden", extra={"provider": summary_provider})

    if tts_provider:
        cfg.set_tts_provider_order([tts_provider])
        logger.info("tts_provider_overridden", extra={"provider": tts_provider})

    if summary_model:
        cfg.set_provider_config("lmstudio", "model", summary_model)
        logger.info(
            "summary_model_overridden",
            extra={"provider": "lmstudio", "model": summary_model},
        )

    if tts_model:
        cfg.set_provider_config("lmstudio", "tts_model", tts_model)
        logger.info(
            "tts_model_overridden", extra={"provider": "lmstudio", "model": tts_model}
        )


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config.json"
    ),
    message: Optional[str] = typer.Option(
        None, "--message", "-m", help="Raw message text"
    ),
    event: str = typer.Option(
        "final", "--event", "-e", help="final|error|needs_input|progress|info"
    ),
    session_name: Optional[str] = typer.Option(
        None, "--session-name", "-s", help="Optional session label spoken at the start"
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
    message_file: Optional[Path] = typer.Option(
        None,
        "--message-file",
        help="Path to file containing raw message text to summarize",
    ),
    no_play: bool = typer.Option(
        False, "--no-play", help="Synthesize audio but skip local playback"
    ),
    no_summarize: bool = typer.Option(
        False, "--no-summarize", help="Skip summarization, use raw message for TTS"
    ),
    fail_fast: bool = typer.Option(
        False,
        "--fail-fast",
        help="Do not fall back to later providers after a provider error",
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
    summary_provider: Optional[SummarizerProvider] = typer.Option(
        None, "--summary-provider", help="Override summarization provider"
    ),
    tts_provider: Optional[TTSProvider] = typer.Option(
        None, "--tts-provider", "-t", help="Override TTS provider"
    ),
    summary_model: Optional[str] = typer.Option(
        None, "--summary-model", help="Override LM Studio summary model for this run"
    ),
    tts_model: Optional[str] = typer.Option(
        None, "--tts-model", help="Override LM Studio TTS model for this run"
    ),
    legacy_init_config: bool = typer.Option(
        False,
        "--init-config",
        help="[legacy] Write default config to ~/.config/let-me-know-agent/config.json",
        hidden=True,
    ),
    legacy_self_test: bool = typer.Option(
        False,
        "--self-test",
        help="[legacy] Run event sound + Kokoro diagnostics",
        hidden=True,
    ),
    legacy_doctor: bool = typer.Option(
        False,
        "--doctor",
        help="[legacy] Run Kokoro CLI health check",
        hidden=True,
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="[legacy] Overwrite config file when used with --init-config",
        hidden=True,
    ),
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit",
        is_eager=True,
    ),
) -> None:
    """let-me-know: Speak concise agent status updates."""
    if version:
        print(get_version())
        raise typer.Exit()

    if ctx.invoked_subcommand is None:
        # Backward-compatibility for legacy argparse-style flags.
        if legacy_init_config:
            ctx.invoke(init_config, force=force)
            raise typer.Exit()
        if legacy_self_test:
            ctx.invoke(
                self_test,
                config=config,
                log_level=log_level,
                log_format=log_format,
                log_file=log_file,
                debug=debug,
            )
            raise typer.Exit()
        if legacy_doctor:
            ctx.invoke(
                doctor,
                config=config,
                log_level=log_level,
                log_format=log_format,
                log_file=log_file,
                debug=debug,
            )
            raise typer.Exit()

        # Default behavior: run notify with the provided options
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

        cfg = Config.load(config)
        _setup_logging_from_options(
            cfg, debug, log_level, log_format, str(log_file) if log_file else None
        )
        logger.info("config_loaded", extra={"config_path": config or "default"})

        _apply_cli_overrides(
            cfg,
            no_play=no_play,
            fail_fast=fail_fast,
            summary_provider=summary_provider.value if summary_provider else None,
            tts_provider=tts_provider.value if tts_provider else None,
            summary_model=summary_model,
            tts_model=tts_model,
        )

        request = _load_payload(
            message,
            event,
            session_name,
            input_json,
            str(input_file) if input_file else None,
            str(message_file) if message_file else None,
        )
        request.skip_summarization = no_summarize
        logger.info(
            "request_loaded",
            extra={
                "event": request.event.value,
                "message_length": len(request.message),
                "skip_summarization": request.skip_summarization,
            },
        )

        result = NotifyService(cfg).notify(request)
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
    checks: dict[str, dict[str, str | bool | None]] = {
        "event_sound": {
            "ok": False,
            "error": None,
            "path": "/System/Library/Sounds/Ping.aiff",
        },
        "kokoro_tts": {"ok": False, "error": None, "audio_path": None},
    }

    try:
        event_sound_path = Path("/System/Library/Sounds/Ping.aiff")
        playback.play_file(event_sound_path)
        checks["event_sound"]["ok"] = True
    except AdapterError as exc:
        checks["event_sound"]["error"] = str(exc)
        logger.warning("self_test_event_sound_failed", extra={"error": str(exc)})

    kk = config.get("providers", "kokoro", default={})
    tts = config.get("tts", default={})
    output_dir = Path(tts.get("save_audio_dir", "/tmp/let-me-know-agent/audio"))
    audio_format = tts.get("audio_format", "mp3")
    speed = float(tts.get("speed", 1.0))
    voice = tts.get("voice", "default")

    def _run_kokoro_self_test(offline: bool) -> Path:
        adapter = KokoroTTSAdapter(
            lang_code=kk.get("lang_code", "a"),
            default_voice=kk.get("voice", "af_heart"),
            repo_id=kk.get("repo_id", "hexgrad/Kokoro-82M"),
            offline=offline,
        )
        audio = adapter.synthesize(
            "Self test. If you hear this, Kokoro text to speech is working.",
            output_dir,
            voice=voice,
            speed=speed,
            audio_format=audio_format,
        )
        return Path(str(audio.value))

    try:
        audio_path = _run_kokoro_self_test(offline=bool(kk.get("offline", True)))
    except AdapterError as exc:
        # First-run bootstrap: if offline mode is enabled and local artifacts are
        # missing, retry once in online mode so dependencies/models can be cached.
        if bool(kk.get("offline", True)) and "offline mode" in str(exc):
            logger.info("self_test_kokoro_retry_online")
            prev_hf_offline = os.environ.pop("HF_HUB_OFFLINE", None)
            prev_transformers_offline = os.environ.pop("TRANSFORMERS_OFFLINE", None)
            try:
                audio_path = _run_kokoro_self_test(offline=False)
            except AdapterError as retry_exc:
                checks["kokoro_tts"]["error"] = str(retry_exc)
                logger.warning(
                    "self_test_kokoro_failed", extra={"error": str(retry_exc)}
                )
                audio_path = None
            finally:
                if prev_hf_offline is not None:
                    os.environ["HF_HUB_OFFLINE"] = prev_hf_offline
                if prev_transformers_offline is not None:
                    os.environ["TRANSFORMERS_OFFLINE"] = prev_transformers_offline
        else:
            checks["kokoro_tts"]["error"] = str(exc)
            logger.warning("self_test_kokoro_failed", extra={"error": str(exc)})
            audio_path = None

    if audio_path is not None:
        playback.play_file(audio_path)
        checks["kokoro_tts"]["ok"] = True
        checks["kokoro_tts"]["audio_path"] = str(audio_path)

    overall_ok = bool(checks["event_sound"]["ok"] and checks["kokoro_tts"]["ok"])
    return {"status": "ok" if overall_ok else "error", "checks": checks}


def _doctor(config: Config) -> dict:
    kk_cli = config.get("providers", "kokoro_cli", default={})
    tts = config.get("tts", default={})

    command = kk_cli.get("command", "kokoro")
    args = kk_cli.get(
        "args", ["-o", "{output}", "-m", "{voice}", "-s", "{speed}", "-t", "{text}"]
    )
    timeout_seconds = int(kk_cli.get("timeout_seconds", 60))
    output_dir = Path(tts.get("save_audio_dir", "/tmp/let-me-know-agent/audio"))
    voice = tts.get("voice", "default")
    speed = float(tts.get("speed", 1.0))
    audio_format = tts.get("audio_format", "mp3")
    if audio_format not in {"mp3", "wav"}:
        audio_format = "mp3"

    checks: dict[str, dict[str, str | bool | None]] = {
        "kokoro_cli": {
            "ok": False,
            "command": command,
            "audio_path": None,
            "error": None,
        }
    }

    try:
        adapter = KokoroCliTTSAdapter(
            command=command,
            args=args,
            timeout_seconds=timeout_seconds,
            default_voice=kk_cli.get(
                "voice", config.get("providers", "kokoro", "voice", default="af_heart")
            ),
        )
        audio = adapter.synthesize(
            "Doctor test. If you hear this, Kokoro CLI is working.",
            output_dir,
            voice=voice,
            speed=speed,
            audio_format=audio_format,
        )
        checks["kokoro_cli"]["ok"] = True
        checks["kokoro_cli"]["audio_path"] = str(audio.value)
    except AdapterError as exc:
        checks["kokoro_cli"]["error"] = str(exc)

    overall_ok = bool(checks["kokoro_cli"]["ok"])
    return {"status": "ok" if overall_ok else "error", "checks": checks}


def _load_payload(
    message: Optional[str],
    event: str,
    session_name: Optional[str],
    input_json: Optional[str],
    input_file: Optional[str],
    message_file: Optional[str] = None,
) -> NotifyRequest:
    if input_json:
        payload = json.loads(input_json)
        return NotifyRequest(**payload)

    if input_file:
        payload = json.loads(open(input_file).read())
        return NotifyRequest(**payload)

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
    except Exception:
        msg_event = MessageEvent.FINAL
    return NotifyRequest(message=message, event=msg_event, session_name=session_name)


@app.command()
def notify(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config.json"
    ),
    message: Optional[str] = typer.Option(
        None, "--message", "-m", help="Raw message text"
    ),
    event: str = typer.Option(
        "final", "--event", "-e", help="final|error|needs_input|progress|info"
    ),
    session_name: Optional[str] = typer.Option(
        None, "--session-name", "-s", help="Optional session label spoken at the start"
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
    message_file: Optional[Path] = typer.Option(
        None,
        "--message-file",
        help="Path to file containing raw message text to summarize",
    ),
    no_play: bool = typer.Option(
        False, "--no-play", help="Synthesize audio but skip local playback"
    ),
    no_summarize: bool = typer.Option(
        False, "--no-summarize", help="Skip summarization, use raw message for TTS"
    ),
    fail_fast: bool = typer.Option(
        False,
        "--fail-fast",
        help="Do not fall back to later providers after a provider error",
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
    summary_provider: Optional[SummarizerProvider] = typer.Option(
        None, "--summary-provider", help="Override summarization provider"
    ),
    tts_provider: Optional[TTSProvider] = typer.Option(
        None, "--tts-provider", "-t", help="Override TTS provider"
    ),
    summary_model: Optional[str] = typer.Option(
        None, "--summary-model", help="Override LM Studio summary model for this run"
    ),
    tts_model: Optional[str] = typer.Option(
        None, "--tts-model", help="Override LM Studio TTS model for this run"
    ),
) -> None:
    """Send a notification (default command)."""
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

    cfg = Config.load(config)
    _setup_logging_from_options(
        cfg, debug, log_level, log_format, str(log_file) if log_file else None
    )
    logger.info("config_loaded", extra={"config_path": config or "default"})

    _apply_cli_overrides(
        cfg,
        no_play=no_play,
        fail_fast=fail_fast,
        summary_provider=summary_provider.value if summary_provider else None,
        tts_provider=tts_provider.value if tts_provider else None,
        summary_model=summary_model,
        tts_model=tts_model,
    )

    request = _load_payload(
        message,
        event,
        session_name,
        input_json,
        str(input_file) if input_file else None,
        str(message_file) if message_file else None,
    )
    request.skip_summarization = no_summarize
    logger.info(
        "request_loaded",
        extra={
            "event": request.event.value,
            "message_length": len(request.message),
            "skip_summarization": request.skip_summarization,
        },
    )

    result = NotifyService(cfg).notify(request)
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
    """Write default config to ~/.config/let-me-know-agent/config.json."""
    try:
        path = write_default_config(force=force)
    except FileExistsError as exc:
        json.dump({"status": "error", "error": str(exc)}, sys.stdout)
        sys.stdout.write("\n")
        raise typer.Exit(2)
    json.dump({"status": "ok", "config_path": str(path)}, sys.stdout)
    sys.stdout.write("\n")


@app.command("self-test")
def self_test(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config.json"
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
    """Run event sound + Kokoro synth/playback diagnostics."""
    cfg = Config.load(config)
    _setup_logging_from_options(cfg, debug, log_level, log_format, log_file)

    result = _self_test_audio(cfg)
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    if result["status"] != "ok":
        raise typer.Exit(1)


@app.command()
def doctor(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config.json"
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
    """Run Kokoro CLI health check."""
    cfg = Config.load(config)
    _setup_logging_from_options(
        cfg, debug, log_level, log_format, str(log_file) if log_file else None
    )

    result = _doctor(cfg)
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
        cfg = Config.load(config)
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

    logger.info("pi_payload", extra={"payload": payload})

    request = request_from_pi_payload(payload)
    result = NotifyService(cfg).notify(request)
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


@app.command("show-logs")
def show_logs(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config JSON"
    ),
) -> None:
    """Show and follow log file using configured command."""
    import shlex
    import subprocess

    cfg = Config.load(config)
    log_file = cfg.get("logging", "file_path", default="/tmp/let-me-know-agent/let-me-know-agent.log")
    viewer_command = cfg.get("log_viewer", "command", default="tail -n 25 -f")

    log_path = Path(log_file)
    if not log_path.exists():
        print(f"Log file not found: {log_file}", file=sys.stderr)
        raise typer.Exit(1)

    cmd_parts = shlex.split(viewer_command) + [str(log_path)]
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


@app.command()
def version() -> None:
    """Show version information."""
    print(get_version())


def main() -> None:
    app()


if __name__ == "__main__":
    app()
