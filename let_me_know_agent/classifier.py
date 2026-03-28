from __future__ import annotations

from .models import MessageEvent


NEEDS_INPUT_HINTS = (
    "please provide",
    "could you",
    "can you",
    "need your input",
    "confirm",
    "choose",
    "which",
    "approve",
)

ERROR_HINTS = (
    "error",
    "failed",
    "exception",
    "issue",
    "unable to",
    "could not",
)

DONE_HINTS = (
    "done",
    "completed",
    "finished",
    "all set",
    "implemented",
)


def infer_event(message: str, fallback: MessageEvent) -> MessageEvent:
    text = message.lower()
    if any(h in text for h in NEEDS_INPUT_HINTS):
        return MessageEvent.NEEDS_INPUT
    if any(h in text for h in ERROR_HINTS):
        return MessageEvent.ERROR
    if fallback in (MessageEvent.FINAL, MessageEvent.PROGRESS):
        if any(h in text for h in DONE_HINTS):
            return MessageEvent.FINAL
    return fallback
