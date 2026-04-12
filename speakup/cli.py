from __future__ import annotations

import json
import logging
import os
import platform
import shlex
import subprocess
import sys
from enum import Enum
from pathlib import Path
from typing import Optional

import typer

from .app_logging import setup_logging
from .config import Config, get_default_log_file_path, write_default_config
from .errors import AdapterError
from .models import MessageEvent, NotifyRequest
from .playback.macos import MacOSPlaybackAdapter
from .service import NotifyService
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


def _run_notify(
    *,
    config: Optional[Path],
    message: Optional[str],
    event: str,
    session_name: Optional[str],
    input_json: Optional[str],
    input_file: Optional[Path],
    message_file: Optional[Path],
    no_play: bool,
    no_summarize: bool,
    fail_fast: bool,
    log_level: Optional[str],
    log_format: Optional[str],
    log_file: Optional[Path],
    debug: bool,
    summary_provider: Optional[SummarizerProvider],
    tts_provider: Optional[TTSProvider],
    summary_model: Optional[str],
    tts_model: Optional[str],
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
    no_summarize: bool = typer.Option(
        False, "--no-summarize", help="Skip summarization, use raw message for TTS"
    ),
    summary_provider: Optional[SummarizerProvider] = typer.Option(
        None, "--summary-provider", help="Override summarization provider"
    ),
    summary_model: Optional[str] = typer.Option(
        None, "--summary-model", help="Override LM Studio summary model for this run"
    ),
    tts_provider: Optional[TTSProvider] = typer.Option(
        None, "--tts-provider", "-t", help="Override TTS provider"
    ),
    tts_model: Optional[str] = typer.Option(
        None, "--tts-model", help="Override LM Studio TTS model for this run"
    ),
    fail_fast: bool = typer.Option(
        False,
        "--fail-fast",
        help="Do not fall back to later providers after a provider error",
    ),
    no_play: bool = typer.Option(
        False, "--no-play", help="Synthesize audio but skip local playback"
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
            input_json=input_json,
            input_file=input_file,
            message_file=message_file,
            no_play=no_play,
            no_summarize=no_summarize,
            fail_fast=fail_fast,
            log_level=log_level,
            log_format=log_format,
            log_file=log_file,
            debug=debug,
            summary_provider=summary_provider,
            tts_provider=tts_provider,
            summary_model=summary_model,
            tts_model=tts_model,
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
    checks: dict[str, dict[str, str | bool | None]] = {
        "event_sound": {
            "ok": False,
            "error": None,
            "path": "/System/Library/Sounds/Ping.aiff",
        },
    }

    try:
        event_sound_path = Path("/System/Library/Sounds/Ping.aiff")
        playback.play_file(event_sound_path)
        checks["event_sound"]["ok"] = True
    except AdapterError as exc:
        checks["event_sound"]["error"] = str(exc)
        logger.warning("self_test_event_sound_failed", extra={"error": str(exc)})

    overall_ok = bool(checks["event_sound"]["ok"])
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
    cfg = Config.load(config)
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


def _get_config_path(config: Optional[Path]) -> Path:
    return config or Path.home() / ".config" / "speakup" / "config.jsonc"


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
        cfg = Config.load(target_path)
        viewer_command = cfg.get("config_viewer", "command")
    else:
        if not typer.confirm(f"Config file does not exist: {target_path}\nCreate default config?"):
            print(f"Config file not found: {target_path}", file=sys.stderr)
            raise typer.Exit(1)
        target_path = write_default_config(target_path)
        cfg = Config.load(target_path)
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
    log_file = cfg.get("logging", "file_path", default=str(get_default_log_file_path()))
    color_log_file = cfg.get("logging", "file_path_color") or f"{log_file}.color"
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
    cfg = Config.load(config)
    log_file = cfg.get("logging", "file_path", default=str(get_default_log_file_path()))
    color_log_file = cfg.get("logging", "file_path_color") or f"{log_file}.color"

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
