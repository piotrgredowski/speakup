from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar


class PlaybackAdapter(ABC):
    """Base class for audio playback adapters."""

    name: ClassVar[str] = ""

    @abstractmethod
    def play_file(self, path: Path) -> None:
        """Play an audio file."""
        raise NotImplementedError
