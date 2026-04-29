from __future__ import annotations

import asyncio
import importlib
import threading
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

from .base import TTSAdapter
from ..errors import AdapterError
from ..models import AudioResult


def _speed_to_rate(speed: float) -> str:
    percent = round((speed - 1.0) * 100)
    percent = max(-90, min(100, percent))
    sign = "+" if percent >= 0 else ""
    return f"{sign}{percent}%"


def _load_edge_tts():
    try:
        return importlib.import_module("edge_tts")
    except ImportError as exc:
        raise AdapterError("Edge TTS requires the optional dependency: pip install 'speakup[edge]'") from exc


def _run_async(coro) -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)
        return

    error: BaseException | None = None

    def runner() -> None:
        nonlocal error
        try:
            asyncio.run(coro)
        except BaseException as exc:
            error = exc

    thread = threading.Thread(target=runner)
    thread.start()
    thread.join()
    if error is not None:
        raise error


class EdgeTTSAdapter(TTSAdapter):
    """TTS adapter using Microsoft Edge online neural voices."""

    name: ClassVar[str] = "edge"

    def __init__(self, voice: str = "en-US-AriaNeural"):
        self.default_voice = voice

    def synthesize(
        self,
        text: str,
        output_dir: Path,
        *,
        voice: str = "default",
        speed: float = 1.0,
        audio_format: str = "mp3",
    ) -> AudioResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"tts-{uuid4().hex}.mp3"
        selected_voice = self.default_voice if voice == "default" else voice
        rate = _speed_to_rate(speed)

        try:
            edge_tts = _load_edge_tts()
            communicate = edge_tts.Communicate(text, selected_voice, rate=rate)
            _run_async(communicate.save(str(out_path)))
        except AdapterError:
            out_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            out_path.unlink(missing_ok=True)
            raise AdapterError(f"Edge TTS failed: {exc}") from exc

        return AudioResult(kind="file", value=str(out_path), provider=self.name, mime_type="audio/mpeg")
