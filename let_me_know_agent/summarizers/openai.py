from __future__ import annotations

import json
import os
import urllib.request

from .base import Summarizer
from ..errors import AdapterError
from ..models import MessageEvent, SummaryResult


class OpenAISummarizer(Summarizer):
    name = "openai"

    def __init__(self, api_key_env: str, model: str = "gpt-4o-mini", timeout: float = 10.0):
        self.api_key_env = api_key_env
        self.model = model
        self.timeout = timeout

    def summarize(self, message: str, event: MessageEvent, max_chars: int) -> SummaryResult:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise AdapterError(f"Missing OpenAI API key in env: {self.api_key_env}")

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": f"""You create very short spoken summaries for a TTS engine.
Return only plain text, maximum 2 to 3 short sentences, and stay within {max_chars} characters.
Event={event.value}.
Focus only on what the user must know now:
- required user actions
- important breakthroughs or successes
- important answers or final outcomes
Keep it easy to understand when read aloud.
Do not include markdown, links, code, tables, emojis, or formatting.
Use only letters, numbers, and spaces. Do not use punctuation or symbols.""",
                },
                {"role": "user", "content": message},
            ],
            "temperature": 0.2,
        }
        try:
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise AdapterError(f"OpenAI summarization failed: {exc}") from exc

        text = data["choices"][0]["message"]["content"].strip()
        if len(text) > max_chars:
            text = text[: max_chars - 1].rstrip() + "…"
        return SummaryResult(summary=text, state=event, user_action_required=event == MessageEvent.NEEDS_INPUT)
