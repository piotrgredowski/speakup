from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from uuid import uuid4

from .base import TTSAdapter
from ..errors import AdapterError
from ..models import AudioResult


class LMStudioTTSAdapter(TTSAdapter):
    name = "lmstudio"

    def __init__(self, base_url: str, model: str, timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def synthesize(self, text: str, output_dir: Path, *, voice: str = "default", speed: float = 1.0, audio_format: str = "mp3") -> AudioResult:
        payload = {
            "model": self.model,
            "input": text,
            "voice": voice,
            "speed": speed,
            "format": "mp3" if audio_format not in {"mp3", "wav"} else audio_format,
        }
        req = urllib.request.Request(
            f"{self.base_url}/audio/speech",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                audio = resp.read()
        except Exception as exc:
            raise AdapterError(f"LMStudio TTS failed: {exc}") from exc

        suffix = "mp3" if payload["format"] == "mp3" else "wav"
        mime = "audio/mpeg" if suffix == "mp3" else "audio/wav"
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"tts-{uuid4().hex}.{suffix}"
        out_path.write_bytes(audio)
        return AudioResult(kind="file", value=str(out_path), provider=self.name, mime_type=mime)
