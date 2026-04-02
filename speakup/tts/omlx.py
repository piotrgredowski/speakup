from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

from .base import TTSAdapter
from ..errors import AdapterError
from ..models import AudioResult


class OmlxTTSAdapter(TTSAdapter):
    """TTS adapter using OMLX local inference server.

    Uses OpenAI-compatible /v1/audio/speech endpoint served by OMLX.
    Supports multiple TTS models including Kokoro.
    """

    name: ClassVar[str] = "omlx"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000/v1",
        api_key_env: str = "OMLX_API_KEY",
        model: str = "Kokoro-82M-bf16",
        voice: str = "af_heart",
        timeout: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.model = model
        self.default_voice = voice
        self.timeout = timeout

    def synthesize(
        self,
        text: str,
        output_dir: Path,
        *,
        voice: str = "default",
        speed: float = 1.0,
        audio_format: str = "wav",
    ) -> AudioResult:
        api_key = os.environ.get(self.api_key_env, "1234")

        format_value = "wav" if audio_format not in {"mp3", "wav"} else audio_format
        payload = {
            "model": self.model,
            "voice": self.default_voice if voice == "default" else voice,
            "input": text,
            "response_format": format_value,
            "speed": speed,
        }

        url = f"{self.base_url}/audio/speech"
        req = urllib.request.Request(
            url,
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
        except urllib.error.HTTPError as exc:
            try:
                error_body = exc.read().decode("utf-8", errors="replace")
                error_msg = (
                    json.loads(error_body).get("error", {}).get("message", error_body)
                )
            except Exception:
                error_msg = str(exc)
            raise AdapterError(
                f"OMLX TTS failed ({exc.code}): {error_msg}"
            ) from exc
        except Exception as exc:
            raise AdapterError(f"OMLX TTS request failed: {exc}") from exc

        if not content_type.lower().startswith("audio/"):
            preview = audio[:200].decode("utf-8", errors="replace")
            raise AdapterError(
                f"OMLX returned non-audio response (Content-Type: {content_type}): {preview}"
            )

        suffix = "mp3" if format_value == "mp3" else "wav"
        mime = "audio/mpeg" if suffix == "mp3" else "audio/wav"
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"tts-{uuid4().hex}.{suffix}"
        out_path.write_bytes(audio)
        return AudioResult(
            kind="file", value=str(out_path), provider=self.name, mime_type=mime
        )
