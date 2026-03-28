from __future__ import annotations

import subprocess
from pathlib import Path
from uuid import uuid4

from .base import TTSAdapter
from ..errors import AdapterError
from ..models import AudioResult


class MacOSTTSAdapter(TTSAdapter):
    name = "macos"

    def synthesize(self, text: str, output_dir: Path, *, voice: str = "default", speed: float = 1.0, audio_format: str = "aiff") -> AudioResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"tts-{uuid4().hex}.aiff"

        command = ["say", "-o", str(out_path)]
        if voice != "default":
            command += ["-v", voice]
        # macOS say does not directly support precise speed in same way as providers.
        command += [text]

        try:
            subprocess.run(command, check=True, capture_output=True)
        except Exception as exc:
            raise AdapterError(f"macOS TTS failed: {exc}") from exc

        return AudioResult(kind="file", value=str(out_path), provider=self.name, mime_type="audio/aiff")
