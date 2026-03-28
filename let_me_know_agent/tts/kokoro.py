from __future__ import annotations

import subprocess
from pathlib import Path
from uuid import uuid4

from .base import TTSAdapter
from ..errors import AdapterError
from ..models import AudioResult


class KokoroTTSAdapter(TTSAdapter):
    name = "kokoro"

    def __init__(self, command: str = "kokoro-tts"):
        self.command = command

    def synthesize(self, text: str, output_dir: Path, *, voice: str = "default", speed: float = 1.0, audio_format: str = "wav") -> AudioResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"tts-{uuid4().hex}.wav"

        cmd = [self.command, "--text", text, "--output", str(out_path)]
        if voice != "default":
            cmd += ["--voice", voice]
        cmd += ["--speed", str(speed)]

        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except Exception as exc:
            raise AdapterError(f"Kokoro TTS failed: {exc}") from exc

        return AudioResult(kind="file", value=str(out_path), provider=self.name, mime_type="audio/wav")
