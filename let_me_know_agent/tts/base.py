from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from ..models import AudioResult


class TTSAdapter(ABC):
    """Base class for text-to-speech adapters."""

    name: ClassVar[str] = ""

    @abstractmethod
    def synthesize(self, text: str, output_dir: Path, *, voice: str = "default", speed: float = 1.0, audio_format: str = "mp3") -> AudioResult:
        """Synthesize text to audio and return the result."""
        raise NotImplementedError
