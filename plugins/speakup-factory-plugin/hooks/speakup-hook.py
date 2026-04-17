#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "structlog>=25.5.0",
# ]
# ///

import json
import logging
import os
import platform
import re
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog

DEFAULT_REQUEST_ID = "-"
LOG_FIELD_ORDER = ("request_id", "timestamp", "level", "logger", "event")
LEVEL_COLOR_CODES = {
    "debug": "\x1b[2m",
    "info": "\x1b[36m",
    "warning": "\x1b[33m",
    "error": "\x1b[31m",
    "critical": "\x1b[1;31m",
}
ANSI_RESET = "\x1b[0m"

_RESERVED_RECORD_KEYS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "asctime",
    "message",
}

logger = logging.getLogger("speakup-droid")
_CURRENT_REQUEST_ID = DEFAULT_REQUEST_ID

_HEX_LIKE_NAME_PATTERN = re.compile(r"[0-9a-fA-F]{7,40}")
_SPEAKUP_VERSION: str | None = None


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            record.request_id = _CURRENT_REQUEST_ID
        return True


def _copy_extra_record_fields(_: logging.Logger, __: str, event_dict: dict) -> dict:
    record = event_dict.get("_record")
    if not record:
        return event_dict
    for key, value in record.__dict__.items():
        if key.startswith("_") or key in _RESERVED_RECORD_KEYS or value is None:
            continue
        event_dict.setdefault(key, value)
    return event_dict


def _ensure_request_id(_: logging.Logger, __: str, event_dict: dict) -> dict:
    event_dict.setdefault("request_id", DEFAULT_REQUEST_ID)
    return event_dict


def _reorder_event_dict(_: logging.Logger, __: str, event_dict: dict) -> dict:
    ordered: dict = {}
    for key in LOG_FIELD_ORDER:
        if key in event_dict:
            ordered[key] = event_dict[key]
    for key, value in event_dict.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def _build_shared_processors(config: dict) -> list:
    include_timestamps = bool(config.get("include_timestamps", True))
    include_module = bool(config.get("include_module", True))
    include_pid = bool(config.get("include_pid", False))

    processors = [structlog.stdlib.add_log_level]
    if include_module:
        processors.append(structlog.stdlib.add_logger_name)
    processors.extend([
        _copy_extra_record_fields,
        structlog.processors.format_exc_info,
    ])
    if include_timestamps:
        processors.append(structlog.processors.TimeStamper(fmt="iso"))
    if include_pid:
        processors.append(
            structlog.processors.CallsiteParameterAdder(
                parameters={structlog.processors.CallsiteParameter.PROCESS}
            )
        )

    processors.extend([_ensure_request_id, _reorder_event_dict])
    return processors


def _render_text_value(value) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)

    text = str(value)
    if not text:
        return '""'
    if any(char.isspace() for char in text) or any(char in text for char in ('"', "=")):
        return json.dumps(text, ensure_ascii=False)
    return text


def _render_text_log_line(_: logging.Logger, __: str, event_dict: dict) -> str:
    return " ".join(
        f"{key}={_render_text_value(value)}"
        for key, value in event_dict.items()
        if value is not None
    )


def _render_text_log_line_with_colors(_: logging.Logger, __: str, event_dict: dict) -> str:
    line = _render_text_log_line(_, __, event_dict)
    color = LEVEL_COLOR_CODES.get(str(event_dict.get("level", "")).lower())
    if not color:
        return line
    return f"{color}{line}{ANSI_RESET}"


def make_formatter(config: dict, *, colors: bool = False) -> logging.Formatter:
    processors = _build_shared_processors(config)

    if config.get("format", "text") == "json":
        def _safe_json_dumps(obj, **kwargs) -> str:
            kwargs.setdefault("default", str)
            return json.dumps(obj, **kwargs)

        processor = structlog.processors.JSONRenderer(serializer=_safe_json_dumps)
    else:
        processor = _render_text_log_line_with_colors if colors else _render_text_log_line

    return structlog.stdlib.ProcessorFormatter(
        processor=processor,
        foreign_pre_chain=processors,
    )


def get_default_log_file_path() -> Path:
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Logs" / "speakup" / "speakup.log"
    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home) / "speakup" / "speakup.log"
    return Path.home() / ".local" / "state" / "speakup" / "speakup.log"


def setup_logging(config: dict) -> None:
    """Set up logging based on speakup config."""
    log_cfg = config.get("logging", {})
    if not log_cfg.get("enabled", True):
        return

    level_name = log_cfg.get("level", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    # Use separate log file for droid hook
    main_file_path = log_cfg.get("file_path", str(get_default_log_file_path()))
    log_dir = os.path.dirname(main_file_path)
    file_path = os.path.join(log_dir, "droid-hook.log") if log_dir else str(get_default_log_file_path().with_name("droid-hook.log"))

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    handler = RotatingFileHandler(
        file_path,
        maxBytes=int(log_cfg.get("rotate_max_bytes", 1_048_576)),
        backupCount=int(log_cfg.get("rotate_backup_count", 3)),
    )

    fmt = log_cfg.get("format", "text")
    if fmt == "json":
        formatter = make_formatter(log_cfg, colors=False)
    else:
        formatter = make_formatter(log_cfg, colors=False)

    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(formatter)

    hook_logger = logging.getLogger("speakup-droid")
    hook_logger.setLevel(level)
    hook_logger.handlers.clear()
    hook_logger.addHandler(handler)
    hook_logger.propagate = False


def redact_payload(value):
    """Redact sensitive payload fields while preserving structure."""
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            lowered = key.lower()
            if any(token in lowered for token in ("api_key", "apikey", "token", "secret", "password", "authorization")):
                redacted[key] = "***"
            else:
                redacted[key] = redact_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    return value


def get_config_path():
    """Get speakup config path, preferring JSONC."""
    config_dir = Path.home() / ".config" / "speakup"
    jsonc_path = config_dir / "config.jsonc"
    if jsonc_path.exists():
        return jsonc_path
    return config_dir / "config.json"


def strip_json_comments(text: str) -> str:
    """Remove JSONC comments while preserving string contents."""
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


def load_full_config() -> dict:
    """Load full speakup configuration."""
    config_path = get_config_path()
    if not config_path.exists():
        return {}
    try:
        return json.loads(strip_json_comments(config_path.read_text()))
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to load config from {config_path}: {e}")
        return {}


def load_droid_config() -> dict:
    """Load droid-specific configuration from speakup config."""
    defaults = {
        "enabled": True,
        "events": {
            "notification": True,
            "stop": True,
            "subagent_stop": False,
            "session_start": False,
        },
    }

    full_config = load_full_config()
    return full_config.get("droid", defaults)


def map_event_to_speakup(droid_event: str) -> str:
    """Map Droid events to speakup events."""
    mapping = {
        "Notification": "needs_input",
        "Stop": "final",
        "SubagentStop": "progress",
        "SessionStart": "info",
    }
    return mapping.get(droid_event, "info")


def extract_message_from_transcript(
    transcript_path: str, max_lines: int = 50
) -> str | None:
    """Extract last assistant message from transcript file.

    Args:
        transcript_path: Path to transcript JSONL file
        max_lines: Maximum number of lines to read from the end

    Returns:
        Last assistant message text or None if not found
    """
    def extract_text_content(content) -> str | None:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    text_parts.append(block)
            return " ".join(text_parts).strip() if text_parts else None
        return None

    path = Path(transcript_path)
    if not path.exists():
        logger.debug(f"Transcript file not found: {transcript_path}")
        return None

    try:
        # Read last N lines to find the most recent assistant message
        with open(path) as f:
            lines = f.readlines()

        logger.debug(f"Read {len(lines)} lines from transcript")

        # Search backwards for assistant message
        for line in reversed(lines[-max_lines:]):
            line = line.strip()
            if not line:
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Check for assistant message with content
            if entry.get("role") == "assistant" and entry.get("content"):
                result = extract_text_content(entry["content"])
                if result:
                    logger.debug(f"Found assistant message ({len(result)} chars)")
                return result
            elif entry.get("type") == "message" and isinstance(entry.get("message"), dict):
                msg = entry["message"]
                if msg.get("role") == "assistant" and msg.get("content"):
                    result = extract_text_content(msg["content"])
                    if result:
                        logger.debug(f"Found assistant message in message envelope ({len(result)} chars)")
                    return result
            elif entry.get("type") == "assistant" and entry.get("message"):
                # Alternative format
                msg = entry["message"]
                if isinstance(msg, dict):
                    result = extract_text_content(msg.get("content", ""))
                    if result:
                        logger.debug(f"Found assistant message (alt format, {len(result)} chars)")
                    return result
                logger.debug("Found assistant message (alt format, str)")
                return str(msg)

        logger.debug("No assistant message found in transcript")
        return None
    except IOError as e:
        logger.warning(f"IO error reading transcript: {e}")
        return None


def extract_message(input_data: dict, droid_event: str) -> str | None:
    """Extract message based on event type.

    Args:
        input_data: Hook input data from Droid
        droid_event: Name of the Droid event

    Returns:
        Message text to speak or None
    """
    if droid_event == "Notification":
        # Use the message field directly
        msg = input_data.get("message")
        if msg:
            logger.debug(f"Extracted notification message ({len(msg)} chars)")
        return msg

    elif droid_event in ("Stop", "SubagentStop"):
        # Extract from transcript
        transcript_path = input_data.get("transcript_path")
        if transcript_path:
            logger.debug(f"Extracting message from transcript for {droid_event}")
            return extract_message_from_transcript(transcript_path)
        logger.debug(f"No transcript_path for {droid_event}")
        return None

    elif droid_event == "SessionStart":
        # Simple announcement
        return "Droid session started"

    return None


def _extract_named_value(source: dict | None, keys: tuple[str, ...]) -> tuple[bool, str | None]:
    if not isinstance(source, dict):
        return False, None

    for key in keys:
        if key in source:
            value = source.get(key)
            if isinstance(value, str):
                return True, value.strip()
            return True, value

    return False, None


def _humanize_session_id(session_id: str) -> str:
    value = session_id.strip()
    if not value:
        return ""
    short = value.split("-", 1)[0]
    return f"session {short}"


def _is_random_hex_like_name(value: object) -> bool:
    if not isinstance(value, str):
        return False

    stripped = value.strip()
    if not stripped:
        return False

    normalized = stripped.replace("-", "").replace("_", "").replace(" ", "")
    return bool(_HEX_LIKE_NAME_PATTERN.fullmatch(normalized))


def _select_session_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    stripped = value.strip()
    if not stripped or stripped == "New Session" or _is_random_hex_like_name(stripped):
        return None

    return stripped


def extract_session_name(input_data: dict) -> str | None:
    """Extract a readable session name from Droid hook payload."""
    found, value = _extract_named_value(
        input_data,
        ("sessionTitle", "session_title", "session_name", "sessionName", "session-name", "title"),
    )
    if found:
        selected = _select_session_name(value)
        if selected:
            return selected

    found, value = _extract_named_value(
        input_data.get("session"),
        ("sessionTitle", "title", "name", "session_title", "session_name", "sessionName"),
    )
    if found:
        selected = _select_session_name(value)
        if selected:
            return selected

    found, value = _extract_named_value(
        input_data.get("metadata"),
        ("sessionTitle", "session_title", "session_name", "sessionName", "session-name", "title"),
    )
    if found:
        selected = _select_session_name(value)
        if selected:
            return selected

    transcript_path = input_data.get("transcript_path")
    if isinstance(transcript_path, str) and transcript_path.strip():
        transcript = Path(transcript_path)
        if transcript.exists():
            try:
                with transcript.open() as handle:
                    first_line = handle.readline().strip()
                if first_line:
                    first_entry = json.loads(first_line)
                    if isinstance(first_entry, dict) and first_entry.get("type") == "session_start":
                        found, value = _extract_named_value(
                            first_entry,
                            ("sessionTitle", "session_title", "session_name", "sessionName", "session-name", "title"),
                        )
                        if found:
                            selected = _select_session_name(value)
                            if selected:
                                return selected
            except (IOError, json.JSONDecodeError):
                logger.debug("Failed to derive session name from transcript", exc_info=True)

    session_id = input_data.get("session_id")
    if isinstance(session_id, str) and session_id.strip():
        return _humanize_session_id(session_id)

    return None


def get_speakup_version() -> str:
    """Get the installed speakup CLI version."""
    global _SPEAKUP_VERSION

    if _SPEAKUP_VERSION is not None:
        return _SPEAKUP_VERSION

    try:
        result = subprocess.run(
            ["speakup", "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        _SPEAKUP_VERSION = "unknown"
        return _SPEAKUP_VERSION

    version = result.stdout.strip() if result.returncode == 0 else ""
    _SPEAKUP_VERSION = version or "unknown"
    return _SPEAKUP_VERSION


def extract_request_id(input_data: dict) -> str:
    """Extract request id from Droid hook payload when available."""
    candidates = (
        input_data,
        input_data.get("request"),
        input_data.get("metadata"),
        input_data.get("session"),
    )
    for source in candidates:
        found, value = _extract_named_value(source, ("request_id", "requestId", "request-id"))
        if found and isinstance(value, str) and value.strip():
            return value.strip()
    return DEFAULT_REQUEST_ID


def run_speakup(message: str, event: str, session_name: str | None = None):
    """Run speakup CLI with the extracted message.

    Args:
        message: Message to speak
        event: Speakup event type
        session_name: Optional session name

    Returns:
        True if successful, False otherwise
    """
    cmd = ["speakup", "--message", message, "--event", event]

    if session_name:
        cmd.extend(["--session-name", session_name])

    logger.info(
        f"Launching speakup {get_speakup_version()}: event={event}, session={session_name}, message_len={len(message)}"
    )

    try:
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info("speakup launched successfully")
        return True
    except FileNotFoundError:
        logger.error("speakup command not found")
        return False
    except OSError as exc:
        logger.error(f"Failed to launch speakup: {exc}")
        return False


def main():
    """Main hook entry point."""
    global _CURRENT_REQUEST_ID

    # Read JSON input from stdin
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    # Get event name
    droid_event = input_data.get("hook_event_name", "")
    if not droid_event:
        sys.exit(0)

    _CURRENT_REQUEST_ID = extract_request_id(input_data)

    # Load full config and set up logging
    full_config = load_full_config()
    setup_logging(full_config)

    logger.info(f"Hook invoked: event={droid_event}")
    logger.debug(f"Hook payload: {json.dumps(redact_payload(input_data), ensure_ascii=False)}")

    # Load droid configuration
    config = load_droid_config()
    logger.debug(f"Droid config loaded: enabled={config.get('enabled')}")

    # Check if plugin is enabled
    if not config.get("enabled", True):
        logger.debug("Plugin disabled, exiting")
        sys.exit(0)

    # Check if this event type is enabled
    event_config = config.get("events", {})
    # Map event names to config keys (Notification -> notification, etc.)
    event_key = {
        "Notification": "notification",
        "Stop": "stop",
        "SubagentStop": "subagent_stop",
        "SessionStart": "session_start",
    }.get(droid_event, droid_event.lower())

    if not event_config.get(event_key, True):
        logger.debug(f"Event type {event_key} disabled, exiting")
        sys.exit(0)

    # Extract message based on event type
    message = extract_message(input_data, droid_event)
    if not message:
        logger.debug("No message extracted, exiting")
        sys.exit(0)

    # Map to speakup event type
    speakup_event = map_event_to_speakup(droid_event)

    # Get session name (optional)
    session_name = extract_session_name(input_data)

    # Run speakup
    run_speakup(message, speakup_event, session_name)

    # Exit cleanly - we don't want to block Droid
    sys.exit(0)


if __name__ == "__main__":
    main()
