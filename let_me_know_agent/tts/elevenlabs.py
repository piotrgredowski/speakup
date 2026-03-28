from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from uuid import uuid4

from .base import TTSAdapter
from ..errors import AdapterError
from ..models import AudioResult


class ElevenLabsTTSAdapter(TTSAdapter):
    name = "elevenlabs"

    def __init__(self, api_key_env: str, voice_id: str, model: str = "eleven_multilingual_v2", timeout: float = 20.0):
        self.api_key_env = api_key_env
        self.voice_id = voice_id
        self.model = model
        self.timeout = timeout

    def synthesize(self, text: str, output_dir: Path, *, voice: str = "default", speed: float = 1.0, audio_format: str = "mp3") -> AudioResult:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise AdapterError(f"Missing ElevenLabs API key in env: {self.api_key_env}")
        if not self.voice_id:
            raise AdapterError("ElevenLabs voice_id is not configured")

        payload = {
            "text": text,
            "model_id": self.model,
            "voice_settings": {"stability": 0.4, "similarity_boost": 0.8, "speed": speed},
        }
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "xi-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                audio = resp.read()
        except Exception as exc:
            raise AdapterError(f"ElevenLabs TTS failed: {exc}") from exc

        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"tts-{uuid4().hex}.mp3"
        out_path.write_bytes(audio)
        return AudioResult(kind="file", value=str(out_path), provider=self.name, mime_type="audio/mpeg")
