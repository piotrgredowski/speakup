from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from .app_logging import setup_logging
from .config import Config, write_default_config
from .errors import AdapterError
from .models import MessageEvent, NotifyRequest
from .playback.macos import MacOSPlaybackAdapter
from .service import NotifyService
from .tts.kokoro import KokoroTTSAdapter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="let-me-know-agent CLI")
    parser.add_argument("--config", help="Path to config.json", default=None)
    parser.add_argument("--message", help="Raw message text", default=None)
    parser.add_argument("--event", help="final|error|needs_input|progress|info", default="final")
    parser.add_argument("--input-json", help="JSON payload string using NotifyRequest schema", default=None)
    parser.add_argument("--input-file", help="Path to JSON payload using NotifyRequest schema", default=None)
    parser.add_argument("--no-play", action="store_true", help="Synthesize audio but skip local playback")
    parser.add_argument("--init-config", action="store_true", help="Write default config to ~/.config/let-me-know-agent/config.json")
    parser.add_argument("--force", action="store_true", help="Overwrite config file when used with --init-config")
    parser.add_argument("--log-level", help="Override logging level (DEBUG|INFO|WARNING|ERROR|CRITICAL)", default=None)
    parser.add_argument("--log-format", help="Override log format (text|json)", default=None)
    parser.add_argument("--log-file", help="Write logs to file path", default=None)
    parser.add_argument("--debug", action="store_true", help="Shortcut for --log-level DEBUG")
    parser.add_argument("--self-test-audio", action="store_true", help="Run event sound + Kokoro synth/playback diagnostics")
    return parser


def _self_test_audio(config: Config) -> dict:
    logger = logging.getLogger(__name__)
    playback = MacOSPlaybackAdapter()
    checks: dict[str, dict[str, str | bool | None]] = {
        "event_sound": {"ok": False, "error": None, "path": "/System/Library/Sounds/Ping.aiff"},
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
                logger.warning("self_test_kokoro_failed", extra={"error": str(retry_exc)})
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


def _load_payload(args: argparse.Namespace) -> NotifyRequest:
    if args.input_json:
        payload = json.loads(args.input_json)
        return NotifyRequest(**payload)

    if args.input_file:
        payload = json.loads(open(args.input_file).read())
        return NotifyRequest(**payload)

    if not args.message:
        raise SystemExit("Provide --message or --input-json/--input-file")

    try:
        event = MessageEvent(args.event)
    except Exception:
        event = MessageEvent.FINAL
    return NotifyRequest(message=args.message, event=event)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    setup_logging(
        {},
        level_override="DEBUG" if args.debug else args.log_level,
        format_override=args.log_format,
        file_override=args.log_file,
    )
    logger = logging.getLogger(__name__)
    logger.info("cli_start", extra={"has_message": bool(args.message), "has_input_json": bool(args.input_json), "has_input_file": bool(args.input_file)})

    if args.init_config:
        try:
            path = write_default_config(force=args.force)
        except FileExistsError as exc:
            json.dump({"status": "error", "error": str(exc)}, sys.stdout)
            sys.stdout.write("\n")
            raise SystemExit(2)
        json.dump({"status": "ok", "config_path": str(path)}, sys.stdout)
        sys.stdout.write("\n")
        return

    config = Config.load(args.config)
    setup_logging(
        config.get("logging", default={}),
        level_override="DEBUG" if args.debug else args.log_level,
        format_override=args.log_format,
        file_override=args.log_file,
    )
    logger.info("config_loaded", extra={"config_path": args.config or "default"})
    if args.self_test_audio:
        result = _self_test_audio(config)
        json.dump(result, sys.stdout)
        sys.stdout.write("\n")
        if result["status"] != "ok":
            raise SystemExit(1)
        return

    if args.no_play:
        config.raw.setdefault("tts", {})["play_audio"] = False
        logger.info("playback_disabled_via_cli")
    request = _load_payload(args)
    logger.info("request_loaded", extra={"event": request.event.value, "message_length": len(request.message)})

    result = NotifyService(config).notify(request)
    logger.info("notify_completed", extra={"status": result.status, "backend": result.backend, "played": result.played})
    json.dump(result.to_dict(), sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
