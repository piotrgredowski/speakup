from __future__ import annotations

import json
import urllib.request
from typing import ClassVar

from .base import Summarizer
from .prompts import build_summary_system_prompt
from ..errors import AdapterError
from ..models import MessageEvent, SummaryResult


class LMStudioSummarizer(Summarizer):
    """LM Studio-based summarizer using local LLM endpoints."""

    name: ClassVar[str] = "lmstudio"

    def __init__(self, base_url: str, model: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def summarize(
        self, message: str, event: MessageEvent, max_chars: int
    ) -> SummaryResult:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": build_summary_system_prompt(event, max_chars)},
                {"role": "user", "content": message},
            ],
            "temperature": 0.2,
        }
        try:
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise AdapterError(f"LM Studio summarization request failed: {exc}") from exc

        text = data["choices"][0]["message"]["content"].strip()
        if len(text) > max_chars:
            text = text[: max_chars - 1].rstrip() + "…"
        return SummaryResult(
            summary=text,
            state=event,
            user_action_required=event == MessageEvent.NEEDS_INPUT,
        )
