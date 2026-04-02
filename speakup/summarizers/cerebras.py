from __future__ import annotations

import json
import os
import urllib.request
from typing import ClassVar

from .base import Summarizer
from .prompts import build_summary_system_prompt
from ..errors import AdapterError
from ..models import MessageEvent, SummaryResult


class CerebrasSummarizer(Summarizer):
    """Cerebras-based summarizer using OpenAI-compatible Chat Completions API."""

    name: ClassVar[str] = "cerebras"

    def __init__(
        self,
        api_key_env: str,
        model: str = "llama3.1-8b",
        base_url: str = "https://api.cerebras.ai/v1",
        timeout: float = 10.0,
    ):
        self.api_key_env = api_key_env
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def summarize(
        self, message: str, event: MessageEvent, max_chars: int
    ) -> SummaryResult:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise AdapterError(f"Missing Cerebras API key in env: {self.api_key_env}")

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": build_summary_system_prompt(event, max_chars),
                },
                {"role": "user", "content": message},
            ],
            "temperature": 0.2,
        }
        try:
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                    "User-Agent": "speakup/0.1.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise AdapterError(f"Cerebras summarization request failed: {exc}") from exc

        text = data["choices"][0]["message"]["content"].strip()
        if len(text) > max_chars:
            text = text[: max_chars - 1].rstrip() + "…"
        return SummaryResult(
            summary=text,
            state=event,
            user_action_required=event == MessageEvent.NEEDS_INPUT,
        )
