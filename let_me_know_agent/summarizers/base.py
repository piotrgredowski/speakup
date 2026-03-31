from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from ..models import MessageEvent, SummaryResult


class Summarizer(ABC):
    """Base class for message summarizers."""

    name: ClassVar[str] = ""

    @abstractmethod
    def summarize(self, message: str, event: MessageEvent, max_chars: int) -> SummaryResult:
        """Summarize a message for TTS output."""
        raise NotImplementedError
