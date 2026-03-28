from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class MessageEvent(str, Enum):
    FINAL = "final"
    ERROR = "error"
    NEEDS_INPUT = "needs_input"
    PROGRESS = "progress"
    INFO = "info"


@dataclass(slots=True)
class NotifyRequest:
    message: str
    event: MessageEvent = MessageEvent.FINAL
    conversation_id: str | None = None
    task_id: str | None = None
    agent: str = "pi"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SummaryResult:
    summary: str
    state: MessageEvent
    user_action_required: bool = False
    action_prompt: str | None = None


@dataclass(slots=True)
class AudioResult:
    kind: str  # file | bytes | none
    value: str | bytes | None
    provider: str
    mime_type: str | None = None


@dataclass(slots=True)
class NotifyResult:
    status: str
    summary: str
    state: MessageEvent
    backend: str
    played: bool
    audio_path: Path | None = None
    dedup_skipped: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "state": self.state.value,
            "backend": self.backend,
            "played": self.played,
            "audio_path": str(self.audio_path) if self.audio_path else None,
            "dedup_skipped": self.dedup_skipped,
            "error": self.error,
        }
