from __future__ import annotations

import json
import urllib.request

from .base import Summarizer
from ..errors import AdapterError
from ..models import MessageEvent, SummaryResult


class LMStudioSummarizer(Summarizer):
    name = "lmstudio"

    def __init__(self, base_url: str, model: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def summarize(
        self, message: str, event: MessageEvent, max_chars: int
    ) -> SummaryResult:
        prompt = f"""You create very short spoken summaries for a TTS engine.
Return only plain text, maximum 2 to 3 short sentences, and stay within {max_chars} characters.
Event={event.value}.
Focus only on what the user must know now:
- required user actions
- important breakthroughs or successes
- important answers or final outcomes
Keep it easy to understand when read aloud.
Do not include markdown, links, code, tables, emojis, or formatting.
Use only letters, numbers, and spaces. Do not use punctuation or symbols.
Text to summarize:"""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt},
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
            raise AdapterError(f"LMStudio summarization failed: {exc}") from exc

        text = data["choices"][0]["message"]["content"].strip()
        if len(text) > max_chars:
            text = text[: max_chars - 1].rstrip() + "…"
        return SummaryResult(
            summary=text,
            state=event,
            user_action_required=event == MessageEvent.NEEDS_INPUT,
        )
