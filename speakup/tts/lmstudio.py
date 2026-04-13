from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

from .base import TTSAdapter
from ..errors import AdapterError
from ..models import AudioResult


class LMStudioTTSAdapter(TTSAdapter):
    name: ClassVar[str] = "lmstudio"

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float = 20.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def synthesize(self, text: str, output_dir: Path, *, voice: str = "default", speed: float = 1.0, audio_format: str = "mp3") -> AudioResult:
        payload = {
            "model": self.model,
            "input": text,
            "voice": voice,
            "speed": speed,
            "format": audio_format,
        }
        req = urllib.request.Request(
            f"{self.base_url}/audio/speech",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if not content_type.lower().startswith("audio/"):
                    body = resp.read(200).decode("utf-8", errors="replace")
                    raise AdapterError(f"LMStudio TTS returned unexpected content-type ({content_type}): {body}")
                audio_bytes = resp.read()
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(f"LMStudio TTS generation failed: {exc}") from exc

        if not audio_bytes:
            raise AdapterError("LMStudio TTS produced no audio")

        output_dir.mkdir(parents=True, exist_ok=True)
        extension = {
            "audio/mpeg": "mp3",
            "audio/mp3": "mp3",
            "audio/wav": "wav",
            "audio/x-wav": "wav",
            "audio/flac": "flac",
        }.get(content_type.lower(), audio_format)
        out_path = output_dir / f"tts-{uuid4().hex}.{extension}"
        out_path.write_bytes(audio_bytes)
        return AudioResult(kind="file", value=str(out_path), provider=self.name, mime_type=content_type)
