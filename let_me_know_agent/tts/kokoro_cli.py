from __future__ import annotations

import subprocess
from pathlib import Path
from uuid import uuid4

from .base import TTSAdapter
from ..errors import AdapterError
from ..models import AudioResult


class KokoroCliTTSAdapter(TTSAdapter):
    name = "kokoro_cli"

    def __init__(
        self,
        command: str = "kokoro",
        args: list[str] | None = None,
        timeout_seconds: int = 60,
        default_voice: str = "af_heart",
    ):
        self.command = command
        self.args = args or ["-o", "{output}", "-m", "{voice}", "-s", "{speed}", "-t", "{text}"]
        self.timeout_seconds = timeout_seconds
        self.default_voice = default_voice

    def synthesize(self, text: str, output_dir: Path, *, voice: str = "default", speed: float = 1.0, audio_format: str = "mp3") -> AudioResult:
        if audio_format not in {"mp3", "wav"}:
            raise AdapterError(f"Kokoro CLI adapter supports only mp3/wav output, got: {audio_format}")

        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"tts-{uuid4().hex}.{audio_format}"

        selected_voice = self.default_voice if voice == "default" else voice

        values = {
            "text": text,
            "voice": selected_voice,
            "speed": speed,
            "output": str(out_path),
            "format": audio_format,
        }
        args = [self._interpolate(arg, values) for arg in self.args]
        args = self._normalize_kokoro_args(args)

        try:
            proc = subprocess.run(
                [self.command, *args],
                text=True,
                capture_output=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise AdapterError(
                f"Kokoro CLI not found: {self.command}. Install it and/or set providers.kokoro_cli.command"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise AdapterError(f"Kokoro CLI timed out after {self.timeout_seconds}s") from exc
        except Exception as exc:
            raise AdapterError(f"Kokoro CLI failed to start: {exc}") from exc

        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise AdapterError(f"Kokoro CLI failed with exit code {proc.returncode}: {detail}")

        if not out_path.exists() or out_path.stat().st_size == 0:
            raise AdapterError(f"Kokoro CLI succeeded but did not produce audio file: {out_path}")

        mime = "audio/mpeg" if audio_format == "mp3" else "audio/wav"
        return AudioResult(kind="file", value=str(out_path), provider=self.name, mime_type=mime)

    @staticmethod
    def _interpolate(template: str, values: dict[str, object]) -> str:
        out = template
        for key, value in values.items():
            out = out.replace(f"{{{key}}}", str(value))
        return out

    @staticmethod
    def _normalize_kokoro_args(args: list[str]) -> list[str]:
        """Map common long-form flags to canonical short flags for kokoro CLI.

        Some kokoro CLI builds expose argparse options where `--output` can be
        ambiguous. Converting to short flags avoids that ambiguity.
        """
        mapping = {
            "--output": "-o",
            "--output-file": "-o",
            "--output_file": "-o",
            "--voice": "-m",
            "--model": "-m",
            "--text": "-t",
            "--speed": "-s",
            "--lang": "-l",
            "--language": "-l",
            "--input": "-i",
            "--input-file": "-i",
            "--input_file": "-i",
        }
        return [mapping.get(arg, arg) for arg in args]
