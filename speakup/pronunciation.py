from __future__ import annotations

import json
import os
import subprocess
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, ClassVar

from .errors import AdapterError


@dataclass(slots=True)
class PronunciationResult:
    title: str | None
    message: str
    spoken_language: str | None = None


class PronunciationAdapter(ABC):
    """Adapts final spoken text for a spoken language before TTS."""

    name: ClassVar[str] = ""

    @abstractmethod
    def adapt(self, *, title: str | None, message: str, spoken_language: str | None) -> PronunciationResult:
        raise NotImplementedError


def build_pronunciation_prompt() -> str:
    return """Adapt final spoken notification text for natural TTS pronunciation.
Return only JSON with keys: spoken_language, title, message.

Rules:
- Preserve meaning and segment boundaries.
- Do not translate, summarize, or restyle.
- If spoken_language is null, infer it from the text when practical.
- For spoken_language=pl, keep Polish text as normal Polish text.
- For spoken_language=pl, rewrite English technical insertions into Polish-friendly phonetic spelling.

Examples for spoken_language=pl:
- "GitHub action failed" -> "GitHab ekszyn fejld"
- "Build failed w module płatności" -> "Bild fejld w module płatności"
"""


def parse_pronunciation_result(text: str) -> PronunciationResult:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AdapterError(f"Pronunciation adapter returned invalid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise AdapterError("Pronunciation adapter returned invalid JSON object")

    title = payload.get("title")
    if title is not None and not isinstance(title, str):
        raise AdapterError("Pronunciation adapter returned invalid title")

    message = payload.get("message")
    if not isinstance(message, str):
        raise AdapterError("Pronunciation adapter returned invalid message")
    message = message.strip()
    if not message:
        raise AdapterError("Pronunciation adapter returned empty message")

    spoken_language = payload.get("spoken_language")
    if spoken_language is not None and not isinstance(spoken_language, str):
        raise AdapterError("Pronunciation adapter returned invalid spoken_language")

    return PronunciationResult(
        title=title.strip() if isinstance(title, str) and title.strip() else None,
        message=message,
        spoken_language=spoken_language.strip() if isinstance(spoken_language, str) and spoken_language.strip() else None,
    )


class CallablePronunciationAdapter(PronunciationAdapter):
    """Pronunciation adapter backed by a callable JSON completion provider."""

    def __init__(self, *, name: str, complete: Callable[[dict[str, object]], str]):
        self.name = name
        self._complete = complete

    def adapt(self, *, title: str | None, message: str, spoken_language: str | None) -> PronunciationResult:
        payload = {
            "spoken_language": spoken_language,
            "title": title,
            "message": message,
        }
        return parse_pronunciation_result(self._complete(payload))


class CommandPronunciationAdapter(PronunciationAdapter):
    name: ClassVar[str] = "command"

    def __init__(
        self,
        *,
        command: str,
        args: list[str] | None = None,
        timeout_seconds: int = 30,
        trim_output: bool = True,
    ) -> None:
        self.command = command
        self.args = args or ["-p", "{prompt}\n\nInput JSON:\n{input_json}"]
        self.timeout_seconds = timeout_seconds
        self.trim_output = trim_output

    def adapt(self, *, title: str | None, message: str, spoken_language: str | None) -> PronunciationResult:
        prompt = build_pronunciation_prompt()
        input_json = json.dumps(
            {
                "spoken_language": spoken_language,
                "title": title,
                "message": message,
            },
            ensure_ascii=False,
        )
        argv = [
            self.command,
            *[
                arg.format(
                    prompt=build_pronunciation_prompt(),
                    input_json=input_json,
                    title=title or "",
                    message=f"{prompt}\n\nInput JSON:\n{input_json}",
                    raw_message=message,
                    spoken_language=spoken_language or "",
                )
                for arg in self.args
            ],
        ]

        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise AdapterError(f"Pronunciation command not found: {self.command}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AdapterError(f"Pronunciation command timed out after {self.timeout_seconds}s") from exc
        except OSError as exc:
            raise AdapterError(f"Pronunciation command failed to start: {exc}") from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise AdapterError(f"Pronunciation command failed with exit code {completed.returncode}: {detail}")

        output = completed.stdout.strip() if self.trim_output else completed.stdout
        return parse_pronunciation_result(output)


class OpenAICompatiblePronunciationAdapter(PronunciationAdapter):
    """Pronunciation adapter for OpenAI-compatible chat completion endpoints."""

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        model: str,
        api_key_env: str | None = None,
        default_api_key: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key_env = api_key_env
        self.default_api_key = default_api_key
        self.timeout = timeout

    def _api_key(self) -> str | None:
        if self.api_key_env is None:
            return None
        api_key = os.environ.get(self.api_key_env, self.default_api_key or "")
        if not api_key:
            raise AdapterError(f"Missing {self.name} API key in env: {self.api_key_env}")
        return api_key

    def adapt(self, *, title: str | None, message: str, spoken_language: str | None) -> PronunciationResult:
        user_payload = json.dumps(
            {
                "spoken_language": spoken_language,
                "title": title,
                "message": message,
            },
            ensure_ascii=False,
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": build_pronunciation_prompt()},
                {"role": "user", "content": user_payload},
            ],
            "temperature": 0.2,
        }
        headers = {"Content-Type": "application/json"}
        api_key = self._api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = data["choices"][0]["message"]["content"].strip()
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(f"{self.name} pronunciation request failed: {exc}") from exc
        return parse_pronunciation_result(text)


class GeminiPronunciationAdapter(PronunciationAdapter):
    name: ClassVar[str] = "gemini"

    def __init__(
        self,
        *,
        api_key_env: str,
        model: str,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout: float = 10.0,
    ) -> None:
        self.api_key_env = api_key_env
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _api_key(self) -> str:
        for env_name in [self.api_key_env, "GEMINI_API_KEY", "GOOGLE_API_KEY"]:
            api_key = os.environ.get(env_name)
            if api_key:
                return api_key
        raise AdapterError(f"Missing Gemini API key in env: {self.api_key_env}")

    def adapt(self, *, title: str | None, message: str, spoken_language: str | None) -> PronunciationResult:
        api_key = self._api_key()
        user_payload = json.dumps(
            {
                "spoken_language": spoken_language,
                "title": title,
                "message": message,
            },
            ensure_ascii=False,
        )
        payload = {
            "systemInstruction": {"parts": [{"text": build_pronunciation_prompt()}]},
            "contents": [{"role": "user", "parts": [{"text": user_payload}]}],
            "generationConfig": {"temperature": 0.2},
        }
        query = urllib.parse.urlencode({"key": api_key})
        try:
            req = urllib.request.Request(
                f"{self.base_url}/models/{self.model}:generateContent?{query}",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "speakup/0.1.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if "error" in data:
                error_msg = data["error"].get("message", str(data["error"]))
                raise AdapterError(f"Gemini pronunciation API error: {error_msg}")
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts).strip()
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(f"Gemini pronunciation request failed: {exc}") from exc
        return parse_pronunciation_result(text)
