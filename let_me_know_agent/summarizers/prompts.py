from __future__ import annotations

from ..models import MessageEvent


def build_summary_system_prompt(event: MessageEvent, max_chars: int) -> str:
    """Build the generic system prompt for LLM summarizers.

    This prompt instructs the LLM to create brief, status-oriented spoken
    summaries suitable for text-to-speech playback.

    Args:
        event: The message event type (unused, kept for API compatibility)
        max_chars: Maximum character limit for the summary

    Returns:
        A system prompt string for the LLM.
    """
    _ = event  # Event type is intentionally not exposed to the model
    return """You create brief spoken alerts for a notification system.
Return preferably 1 sentence, but not more than 3 sentences.

Your goal: Tell the user what happened and what to expect when they return to their computer.

Rules:
- If the message asks for a decision, say what the user needs to choose or provide
- If there was an error, describe what went wrong in plain terms without commands
- Otherwise, summarize the status or outcome
- Use simple conversational English that sounds natural when spoken aloud
- Replace all technical syntax with plain descriptions
- Do NOT include commands like brew services start or package names with versions
- Do NOT include file paths, code snippets, or version numbers

Examples of good replacements:
- Instead of "brew services start postgresql@15" say "start the PostgreSQL service"
- Instead of "python:3.12-slim" say "Python 3.12"
- Instead of "myapp:latest" say "your application image"
- Instead of "src/auth/login.py" say "the login file"

Here is the message to summarize:"""
