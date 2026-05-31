#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "speakup",
# ]
#
# [tool.uv.sources]
# speakup = { git = "https://github.com/piotrgredowski/speakup" }
# ///

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from speakup import app_logging as _shared_app_logging
    from speakup.config import _strip_json_comments
    from speakup.integrations.codex import (
        build_hook_output,
        detect_plan_approval_message,
        extract_message,
        mark_plan_approval_seen,
        notify_in_background,
        plan_approval_dedupe_key,
        plan_approval_seen,
        request_from_codex_payload,
        save_current_session_pointer,
    )
except ImportError as exc:  # pragma: no cover - exercised by the host app.
    print(f"speakup codex hook import failed: {exc}", file=sys.stderr)
    raise

logger = logging.getLogger("speakup-codex")


def get_config_path() -> Path:
    config_dir = Path.home() / ".config" / "speakup"
    jsonc_path = config_dir / "config.jsonc"
    if jsonc_path.exists():
        return jsonc_path
    return config_dir / "config.json"


def load_full_config() -> dict:
    config_path = get_config_path()
    if not config_path.exists():
        return {}
    try:
        return json.loads(_strip_json_comments(config_path.read_text()))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("failed_to_load_config", extra={"error": str(exc), "config_path": str(config_path)})
        return {}


def merge_nested_defaults(defaults: dict, overrides: object) -> dict:
    if not isinstance(overrides, dict):
        return dict(defaults)

    merged = dict(defaults)
    for key, value in overrides.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = merge_nested_defaults(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_codex_config() -> dict:
    defaults = {
        "enabled": True,
        "events": {
            "notification": True,
            "stop": True,
            "plan_approval": True,
        },
    }

    full_config = load_full_config()
    config = merge_nested_defaults(defaults, full_config.get("codex"))
    if full_config.get("enabled") is False:
        config["enabled"] = False
    return config


def setup_logging(config: dict) -> None:
    logging_config = config.get("logging", {}) if isinstance(config, dict) else {}
    if _shared_app_logging is not None:
        _shared_app_logging.setup_logging(logging_config)
        return
    logging.basicConfig(level=logging.INFO)


def _event_enabled(config: dict, payload: dict, request) -> bool:
    events = config.get("events", {}) if isinstance(config.get("events"), dict) else {}
    raw_message = extract_message(payload) or request.message
    is_plan = bool(detect_plan_approval_message(raw_message))
    if is_plan:
        return bool(events.get("plan_approval", True))
    if request.event.value == "final":
        return bool(events.get("stop", True))
    return bool(events.get("notification", True))


def _claim_plan_approval(payload: dict, request) -> bool:
    raw_message = extract_message(payload) or ""
    if not detect_plan_approval_message(raw_message):
        return True
    dedupe_key = plan_approval_dedupe_key(raw_message)
    dedupe_scope = request.session_key
    if not dedupe_scope and isinstance(request.metadata, dict):
        cwd = request.metadata.get("cwd")
        if isinstance(cwd, str) and cwd.strip():
            dedupe_scope = f"cwd:{cwd.strip()}"
    if not dedupe_scope:
        dedupe_scope = "global"
    if plan_approval_seen(dedupe_scope, dedupe_key):
        return False
    mark_plan_approval_seen(dedupe_scope, dedupe_key)
    return True


def run_speakup(request, config_path: Path | None = None) -> bool:
    try:
        notify_in_background(request, config_path=config_path)
    except OSError as exc:
        logger.error("speakup_launch_failed", extra={"error": str(exc)})
        return False
    return True


def main():
    full_config = load_full_config()
    setup_logging(full_config)
    codex_config = load_codex_config()
    if not bool(codex_config.get("enabled", True)):
        logger.info("codex_notifications_disabled")
        return

    payload = json.load(sys.stdin)
    request = request_from_codex_payload(payload)
    if not request.message:
        logger.info("codex_payload_without_message", extra={"payload_keys": sorted(str(key) for key in payload)})
        return
    if not _event_enabled(codex_config, payload, request):
        logger.info("codex_event_disabled", extra={"event": request.event.value})
        return
    if not _claim_plan_approval(payload, request):
        logger.info("codex_plan_approval_already_seen")
        return

    save_current_session_pointer(
        request.metadata.get("cwd") if isinstance(request.metadata, dict) else None,
        request.session_key,
        request.session_name,
    )
    config_path = get_config_path()
    if run_speakup(request, config_path=config_path if config_path.exists() else None):
        output = build_hook_output(request.session_key, request.session_name)
        if output:
            print(output)


if __name__ == "__main__":
    main()
