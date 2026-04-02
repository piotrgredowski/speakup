def get_config_path():
    """Get speakup config path."""
    return Path.home() / ".config" / "speakup" / "config.json"


def load_droid_config():
    """Load droid-specific configuration from speakup config."""
    config_path = get_config_path()
    
    defaults = {
        "enabled": True,
        "events": {
            "notification": True,
            "stop": True,
            "subagent_stop": True,
            "session_start": True
        }
    }
    
    if not config_path.exists():
        return defaults
    
    try:
        with open(config_path) as f:
            config = json.load(f)
        # Use the droid key from the config
        return config.get("droid", defaults)
    except (json.JSONDecodeError, IOError):
        return defaults


def map_event_to_speakup(droid_event: str) -> str:
    """Map Droid events to speakup events."""
    mapping = {
        "Notification": "needs_input",
        "Stop": "final",
        "SubagentStop": "progress",
        "SessionStart": "info"
    }
    return mapping.get(droid_event, "info")


def extract_message_from_transcript(transcript_path: str, max_lines: int = 50) -> str | None:
    """Extract last assistant message from transcript file.
    
    Args:
        transcript_path: Path to transcript JSONL file
        max_lines: Maximum number of lines to read from the end
        
    Returns:
        Last assistant message text or None if not found
    """
    path = Path(transcript_path)
    if not path.exists():
        return None
    
    try:
        # Read last N lines to find the most recent assistant message
        with open(path) as f:
            lines = f.readlines()
        
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
                    return content
                elif isinstance(content, list):
                    # Extract text from content blocks
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            text_parts.append(block)
                    return " ".join(text_parts).strip() if text_parts else None
            elif entry.get("type") == "assistant" and entry.get("message"):
                # Alternative format
                msg = entry["message"]
                if isinstance(msg, dict):
                    return msg.get("content", "")
                return str(msg)
        
        return None
    except IOError:
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
        return input_data.get("message")
    
    elif droid_event in ("Stop", "SubagentStop"):
        # Extract from transcript
        transcript_path = input_data.get("transcript_path")
        if transcript_path:
            return extract_message_from_transcript(transcript_path)
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
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
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
    
    # Load configuration
    config = load_droid_config()
    
    # Check if plugin is enabled
    if not config.get("enabled", True):
        sys.exit(0)
    
    # Check if this event type is enabled
    event_config = config.get("events", {})
    # Map event names to config keys (Notification -> notification, etc.)
    event_key = {
        "Notification": "notification",
        "Stop": "stop",
        "SubagentStop": "subagent_stop",
        "SessionStart": "session_start"
    }.get(droid_event, droid_event.lower())
    
    if not event_config.get(event_key, True):
        sys.exit(0)
    
    # Extract message based on event type
    message = extract_message(input_data, droid_event)
    if not message:
        sys.exit(0)
    
    # Map to speakup event type
    speakup_event = map_event_to_speakup(droid_event)
    
    # Get session name (optional)
    session_id = input_data.get("session_id", "")
    session_name = f"session {session_id[:8]}" if session_id else None
    
    # Run speakup
    success = run_speakup(message, speakup_event, session_name)
    
    # Exit cleanly - we don't want to block Droid
    sys.exit(0 if success else 0)


if __name__ == "__main__":
    main()

