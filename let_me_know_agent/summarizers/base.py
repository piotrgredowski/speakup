from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import MessageEvent, SummaryResult


class Summarizer(ABC):
    name: str

    @abstractmethod
    def summarize(self, message: str, event: MessageEvent, max_chars: int) -> SummaryResult:
        raise NotImplementedError
