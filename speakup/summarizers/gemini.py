from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import ClassVar

from .base import Summarizer
from .prompts import build_summary_system_prompt
from ..errors import AdapterError
from ..models import MessageEvent, SummaryResult

_GEMINI_API_KEY_ENV_ALIASES = ("GEMINI_API_KEY", "GOOGLE_API_KEY")


class GeminiSummarizer(Summarizer):
    """Gemini-based summarizer using the Google Generative Language API."""

    name: ClassVar[str] = "gemini"

    def __init__(
        self,
        api_key_env: str,
        model: str = "gemini-2.5-flash",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout: float = 10.0,
    ):
        self.api_key_env = api_key_env
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _resolve_api_key(self) -> str:
        env_names = [self.api_key_env]
        if self.api_key_env in _GEMINI_API_KEY_ENV_ALIASES:
            env_names.extend(
                name for name in _GEMINI_API_KEY_ENV_ALIASES if name != self.api_key_env
            )

        for env_name in env_names:
            api_key = os.environ.get(env_name)
            if api_key:
                return api_key

        checked = ", ".join(env_names)
        raise AdapterError(
            f"Missing Gemini API key in env: {self.api_key_env} (checked: {checked})"
        )

    def summarize(
        self, message: str, event: MessageEvent, max_chars: int
    ) -> SummaryResult:
        api_key = self._resolve_api_key()
        payload = {
            "systemInstruction": {
                "parts": [{"text": build_summary_system_prompt(event, max_chars)}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": message}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
            },
        }
        query = urllib.parse.urlencode({"key": api_key})
        url = f"{self.base_url}/models/{self.model}:generateContent?{query}"

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "speakup/0.1.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise AdapterError(f"Gemini summarization request failed: {exc}") from exc

        if "error" in data:
            error_msg = data["error"].get("message", str(data["error"]))
            raise AdapterError(f"Gemini summarization API error: {error_msg}")

        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise AdapterError(
                f"Gemini summarization response missing expected fields: {exc}"
            ) from exc

        if len(text) > max_chars:
            text = text[: max_chars - 1].rstrip() + "…"
        return SummaryResult(
            summary=text,
            state=event,
            user_action_required=event == MessageEvent.NEEDS_INPUT,
        )
