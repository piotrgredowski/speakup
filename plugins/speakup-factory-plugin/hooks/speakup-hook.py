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


def get_config_path():
    """Get speakup config path."""
    return Path.home() / ".config" / "speakup" / "config.json"


def load_full_config() -> dict:
    """Load full speakup configuration."""
    config_path = get_config_path()
    if not config_path.exists():
        return {}
    try:
        with open(config_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to load config: {e}")
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
                content = entry["content"]
                # Handle both string and list content formats
                if isinstance(content, str):
                    logger.debug(f"Found assistant message ({len(content)} chars)")
                    return content
                elif isinstance(content, list):
                    # Extract text from content blocks
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            text_parts.append(block)
                    result = " ".join(text_parts).strip() if text_parts else None
                    if result:
                        logger.debug(f"Found assistant message from blocks ({len(result)} chars)")
                    return result
            elif entry.get("type") == "assistant" and entry.get("message"):
                # Alternative format
                msg = entry["message"]
                if isinstance(msg, dict):
                    content = msg.get("content", "")
                    logger.debug(f"Found assistant message (alt format, {len(content)} chars)")
                    return content
                logger.debug(f"Found assistant message (alt format, str)")
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

    logger.info(f"Running speakup: event={event}, session={session_name}, message_len={len(message)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            logger.info("speakup completed successfully")
        else:
            logger.warning(f"speakup exited with code {result.returncode}: {result.stderr}")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error("speakup timed out")
        return False
    except FileNotFoundError:
        logger.error("speakup command not found")
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
    session_id = input_data.get("session_id", "")
    session_name = f"session {session_id[:8]}" if session_id else None

    # Run speakup
    run_speakup(message, speakup_event, session_name)

    # Exit cleanly - we don't want to block Droid
    sys.exit(0)


if __name__ == "__main__":
    main()
