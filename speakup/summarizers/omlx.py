from __future__ import annotations

import json
import os
import urllib.request
from typing import ClassVar

from .base import Summarizer
from .prompts import build_summary_system_prompt
from ..errors import AdapterError
from ..models import MessageEvent, SummaryResult


class OmlxSummarizer(Summarizer):
    """oMLX summarizer using the local OpenAI-compatible Chat Completions API."""

    name: ClassVar[str] = "omlx"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000/v1",
        api_key_env: str = "OMLX_API_KEY",
        model: str = "unsloth/gemma-4-E4B-it-UD-MLX-4bit",
        timeout: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.model = model
        self.timeout = timeout

    def summarize(self, message: str, event: MessageEvent, max_chars: int) -> SummaryResult:
        api_key = os.environ.get(self.api_key_env, "1234")
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
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                error_body = exc.read().decode("utf-8", errors="replace")
                error_msg = json.loads(error_body).get("error", {}).get("message", error_body)
            except Exception:
                error_msg = str(exc)
            raise AdapterError(f"oMLX summarization failed ({exc.code}): {error_msg}") from exc
        except Exception as exc:
            raise AdapterError(f"oMLX summarization request failed: {exc}") from exc

        try:
            text = data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise AdapterError("oMLX summarization returned an invalid response") from exc

        if len(text) > max_chars:
            text = text[: max_chars - 1].rstrip() + "…"
        return SummaryResult(summary=text, state=event, user_action_required=event == MessageEvent.NEEDS_INPUT)
