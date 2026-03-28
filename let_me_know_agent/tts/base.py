from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import AudioResult


class TTSAdapter(ABC):
    name: str

    @abstractmethod
    def synthesize(self, text: str, output_dir: Path, *, voice: str = "default", speed: float = 1.0, audio_format: str = "mp3") -> AudioResult:
        raise NotImplementedError
