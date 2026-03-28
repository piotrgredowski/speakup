from __future__ import annotations

import argparse
import json
import sys

from .config import Config, write_default_config
from .errors import AdapterError
from .installer import install_kokoro
from .models import MessageEvent, NotifyRequest
from .service import NotifyService


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
    parser.add_argument("--install-kokoro", action="store_true", help="Install kokoro TTS runtime in current Python environment")
    return parser


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

    if args.install_kokoro:
        try:
            message = install_kokoro(python_executable=sys.executable)
        except AdapterError as exc:
            json.dump({"status": "error", "error": str(exc)}, sys.stdout)
            sys.stdout.write("\n")
            raise SystemExit(2)
        json.dump({"status": "ok", "message": message}, sys.stdout)
        sys.stdout.write("\n")
        return

    config = Config.load(args.config)
    if args.no_play:
        config.raw.setdefault("tts", {})["play_audio"] = False
    request = _load_payload(args)

    result = NotifyService(config).notify(request)
    json.dump(result.to_dict(), sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
