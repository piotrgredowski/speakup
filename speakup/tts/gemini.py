from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import urllib.request
import wave
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

from .base import TTSAdapter
from ..errors import AdapterError
from ..models import AudioResult

_SUPPORTED_VOICES = {
    "Achernar",
    "Achird",
    "Algenib",
    "Algieba",
    "Alnilam",
    "Aoede",
    "Autonoe",
    "Callirrhoe",
    "Charon",
    "Despina",
    "Enceladus",
    "Erinome",
    "Fenrir",
    "Gacrux",
    "Iapetus",
    "Kore",
    "Laomedeia",
    "Leda",
    "Orus",
    "Puck",
    "Pulcherrima",
    "Rasalgethi",
    "Sadachbia",
    "Sadaltager",
    "Schedar",
    "Sulafat",
    "Umbriel",
    "Vindemiatrix",
    "Zephyr",
    "Zubenelgenubi",
}
_GEMINI_API_KEY_ENV_ALIASES = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
_PCM_SAMPLE_RATE = 24_000
_PCM_CHANNELS = 1
_PCM_SAMPLE_WIDTH_BYTES = 2


class GeminiTTSAdapter(TTSAdapter):
    """Gemini TTS adapter using the Google Gemini API for text-to-speech."""

    name: ClassVar[str] = "gemini"

    def __init__(self, api_key_env: str, model: str = "gemini-2.5-flash-preview-tts", voice: str = "Kore", timeout: float = 30.0):
        self.api_key_env = api_key_env
        self.model = model
        self.default_voice = voice
        self.timeout = timeout

    def _resolve_api_key(self) -> str:
        env_names = [self.api_key_env]
        if self.api_key_env in _GEMINI_API_KEY_ENV_ALIASES:
            env_names.extend(name for name in _GEMINI_API_KEY_ENV_ALIASES if name != self.api_key_env)

        for env_name in env_names:
            api_key = os.environ.get(env_name)
            if api_key:
                return api_key

        checked = ", ".join(env_names)
        raise AdapterError(f"Missing Gemini API key in env: {self.api_key_env} (checked: {checked})")

    def _resolve_voice(self, voice: str) -> str:
        selected_voice = self.default_voice if voice == "default" else voice
        if selected_voice not in _SUPPORTED_VOICES:
            raise AdapterError(f"Unsupported Gemini voice: {selected_voice}")
        return selected_voice

    def _write_wav(self, pcm_data: bytes, path: Path) -> None:
        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(_PCM_CHANNELS)
            wav_file.setsampwidth(_PCM_SAMPLE_WIDTH_BYTES)
            wav_file.setframerate(_PCM_SAMPLE_RATE)
            wav_file.writeframes(pcm_data)

    def _ffmpeg_bin(self) -> str:
        return os.environ.get("SPEAKUP_FFMPEG_BIN", "ffmpeg")

    def _ffmpeg_available(self) -> bool:
        return shutil.which(self._ffmpeg_bin()) is not None

    def _build_audio_result(self, path: Path, format_value: str) -> AudioResult:
        mime_type = "audio/mpeg" if format_value == "mp3" else "audio/aiff"
        if format_value == "wav":
            mime_type = "audio/wav"
        return AudioResult(kind="file", value=str(path), provider=self.name, mime_type=mime_type)

    def _transcode_audio(self, source_path: Path, target_path: Path) -> None:
        command = [
            self._ffmpeg_bin(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source_path),
            str(target_path),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True)
        except Exception as exc:
            target_path.unlink(missing_ok=True)
            detail = exc.stderr.decode("utf-8", errors="replace").strip() if isinstance(exc, subprocess.CalledProcessError) and exc.stderr else str(exc)
            raise AdapterError(f"Gemini TTS audio conversion failed: {detail}") from exc

    def synthesize(self, text: str, output_dir: Path, *, voice: str = "default", speed: float = 1.0, audio_format: str = "mp3") -> AudioResult:
        api_key = self._resolve_api_key()

        # Gemini TTS uses generateContent endpoint with speech generation
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={api_key}"

        selected_voice = self._resolve_voice(voice)

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

        output_dir.mkdir(parents=True, exist_ok=True)
        audio_id = uuid4().hex
        wav_path = output_dir / f"tts-{audio_id}.wav"
        self._write_wav(audio_data, wav_path)

        if format_value == "wav":
            return self._build_audio_result(wav_path, "wav")

        if not self._ffmpeg_available():
            return self._build_audio_result(wav_path, "wav")

        out_path = output_dir / f"tts-{audio_id}.{format_value}"
        try:
            self._transcode_audio(wav_path, out_path)
        except AdapterError:
            wav_path.unlink(missing_ok=True)
            raise

        wav_path.unlink(missing_ok=True)
        return self._build_audio_result(out_path, format_value)
