from __future__ import annotations

from ..models import MessageEvent


def build_summary_system_prompt(event: MessageEvent, max_chars: int) -> str:
    """Build the generic system prompt for LLM summarizers.

    This prompt instructs the LLM to create brief, action-oriented spoken
    summaries suitable for text-to-speech playback.

    Args:
        event: The message event type (FINAL, ERROR, NEEDS_INPUT, etc.)
        max_chars: Maximum character limit for the summary

    Returns:
        A system prompt string for the LLM.
    """
    return f"""You create brief spoken alerts for a notification system.
Return preferrably 1 sentence, but not more than 3 sentences.
The event type is: {event.value.upper()}.

Your goal: Tell the user exactly what they need to know when they return to their computer.

For each event type:
- NEEDS_INPUT: State what decision or input is needed
- ERROR: State what failed and if action is needed
- FINAL: Provide key outcome
- PROGRESS: Summarize current status
- INFO: Share the key information

Rules:
- Start with the action or outcome, not context
- Use conversational spoken English
- No markdown, links, code, emojis, or symbols
- No quotes, brackets, or special punctuation
- Only letters, numbers, basic punctuation, and spaces.

Here is the message to summarize:"""
