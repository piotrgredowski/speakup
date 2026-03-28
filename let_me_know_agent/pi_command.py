from __future__ import annotations

import argparse
import json
import sys

from .config import Config, ConfigValidationError
from .integrations.pi_extension import request_from_pi_payload
from .service import NotifyService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pi wrapper command for let-me-know-agent")
    parser.add_argument("--config", default=None, help="Path to config JSON")
    parser.add_argument("--input-file", default=None, help="Path to Pi payload JSON. Defaults to stdin.")
    return parser


def _load_pi_payload(input_file: str | None) -> dict:
    if input_file:
        with open(input_file) as f:
            return json.load(f)
    raw = sys.stdin.read().strip()
    if not raw:
        raise SystemExit("Expected Pi JSON payload via stdin or --input-file")
    return json.loads(raw)


def main() -> None:
    args = build_parser().parse_args()
    try:
        config = Config.load(args.config)
    except ConfigValidationError as exc:
        json.dump({"status": "error", "error": str(exc)}, sys.stdout)
        sys.stdout.write("\n")
        raise SystemExit(2)

    payload = _load_pi_payload(args.input_file)
    request = request_from_pi_payload(payload)
    result = NotifyService(config).notify(request)
    json.dump(result.to_dict(), sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
