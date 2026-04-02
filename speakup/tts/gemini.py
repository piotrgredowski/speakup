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


class GeminiTTSAdapter(TTSAdapter):
    """Gemini TTS adapter using the Google Gemini API for text-to-speech."""

    name: ClassVar[str] = "gemini"

    def __init__(self, api_key_env: str, model: str = "gemini-2.5-flash-preview-tts", voice: str = "en-US-Neural2-C", timeout: float = 30.0):
        self.api_key_env = api_key_env
        self.model = model
        self.default_voice = voice
        self.timeout = timeout

    def synthesize(self, text: str, output_dir: Path, *, voice: str = "default", speed: float = 1.0, audio_format: str = "mp3") -> AudioResult:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise AdapterError(f"Missing Gemini API key in env: {self.api_key_env}")

        # Gemini TTS uses generateContent endpoint with speech generation
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={api_key}"
        
        selected_voice = self.default_voice if voice == "default" else voice
        
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": text
                        }
                    ]
                }
            ],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": selected_voice
                        }
                    }
                }
            }
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                content_type = resp.headers.get("Content-Type", "")
                response_data = resp.read()
        except Exception as exc:
            raise AdapterError(f"Gemini TTS request failed: {exc}") from exc

        # Parse JSON response to extract audio data
        try:
            response_json = json.loads(response_data.decode("utf-8"))
            
            # Check for API errors
            if "error" in response_json:
                error_msg = response_json["error"].get("message", str(response_json["error"]))
                raise AdapterError(f"Gemini TTS API error: {error_msg}")
            
            # Extract audio data from response
            audio_data = None
            if "candidates" in response_json and len(response_json["candidates"]) > 0:
                candidate = response_json["candidates"][0]
                if "content" in candidate and "parts" in candidate["content"]:
                    for part in candidate["content"]["parts"]:
                        if "inlineData" in part:
                            import base64
                            audio_data = base64.b64decode(part["inlineData"]["data"])
                            break
            
            if audio_data is None:
                raise AdapterError(f"Gemini TTS returned no audio data: {response_json}")
                
        except json.JSONDecodeError as exc:
            raise AdapterError(f"Gemini TTS returned invalid JSON: {exc}") from exc
        except KeyError as exc:
            raise AdapterError(f"Gemini TTS response missing expected fields: {exc}") from exc

        # Determine output format and file extension
        format_value = "mp3" if audio_format not in {"mp3", "wav", "aiff"} else audio_format
        suffix = format_value
        mime_type = f"audio/{format_value}"
        if format_value == "mp3":
            mime_type = "audio/mpeg"

        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"tts-{uuid4().hex}.{suffix}"
        out_path.write_bytes(audio_data)
        return AudioResult(kind="file", value=str(out_path), provider=self.name, mime_type=mime_type)
