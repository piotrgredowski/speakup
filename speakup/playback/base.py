from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar


class PlaybackAdapter(ABC):
    """Base class for audio playback adapters."""

    name: ClassVar[str] = ""

    @abstractmethod
    def play_file(self, path: Path) -> None:
        """Play an audio file."""
        raise NotImplementedError

    def play_files(self, paths: Sequence[Path]) -> None:
        """Play multiple audio files in order."""
        for path in paths:
            self.play_file(path)
