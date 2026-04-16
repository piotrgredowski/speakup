import json
import logging
import os
import platform
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

logger = logging.getLogger("speakup-droid")


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
        formatter = logging.Formatter(
            '{"time":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","message":"%(message)s"}'
        )
    else:
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

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
            "subagent_stop": True,
            "session_start": True,
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


def extract_session_name(input_data: dict) -> str | None:
    """Extract a readable session name from Droid hook payload."""
    found, value = _extract_named_value(
        input_data,
        ("sessionTitle", "session_title", "session_name", "sessionName", "session-name", "title"),
    )
    if found:
        return value

    found, value = _extract_named_value(
        input_data.get("session"),
        ("sessionTitle", "title", "name", "session_title", "session_name", "sessionName"),
    )
    if found:
        return value

    found, value = _extract_named_value(
        input_data.get("metadata"),
        ("sessionTitle", "session_title", "session_name", "sessionName", "session-name", "title"),
    )
    if found:
        return value

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
                        if found and value and value != "New Session":
                            return value
            except (IOError, json.JSONDecodeError):
                logger.debug("Failed to derive session name from transcript", exc_info=True)

    session_id = input_data.get("session_id")
    if isinstance(session_id, str) and session_id.strip():
        return _humanize_session_id(session_id)

    return None


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

    logger.info(f"Launching speakup: event={event}, session={session_name}, message_len={len(message)}")

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
