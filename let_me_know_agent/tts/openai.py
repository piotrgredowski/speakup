from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from uuid import uuid4

from .base import TTSAdapter
from ..errors import AdapterError
from ..models import AudioResult


class OpenAITTSAdapter(TTSAdapter):
    name = "openai"

    def __init__(self, api_key_env: str, model: str = "gpt-4o-mini-tts", voice: str = "alloy", timeout: float = 20.0):
        self.api_key_env = api_key_env
        self.model = model
        self.default_voice = voice
        self.timeout = timeout

    def synthesize(self, text: str, output_dir: Path, *, voice: str = "default", speed: float = 1.0, audio_format: str = "mp3") -> AudioResult:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise AdapterError(f"Missing OpenAI API key in env: {self.api_key_env}")

        format_value = "mp3" if audio_format not in {"mp3", "wav"} else audio_format
        payload = {
            "model": self.model,
            "voice": self.default_voice if voice == "default" else voice,
            "input": text,
            "format": format_value,
            "speed": speed,
        }

        req = urllib.request.Request(
            "https://api.openai.com/v1/audio/speech",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                content_type = resp.headers.get("Content-Type", "")
                audio = resp.read()
        except Exception as exc:
            raise AdapterError(f"OpenAI TTS failed: {exc}") from exc

        if not content_type.lower().startswith("audio/"):
            preview = audio[:200].decode("utf-8", errors="replace")
            raise AdapterError(f"OpenAI TTS returned non-audio response ({content_type}): {preview}")

        suffix = "mp3" if format_value == "mp3" else "wav"
        mime = "audio/mpeg" if suffix == "mp3" else "audio/wav"
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"tts-{uuid4().hex}.{suffix}"
        out_path.write_bytes(audio)
        return AudioResult(kind="file", value=str(out_path), provider=self.name, mime_type=mime)
