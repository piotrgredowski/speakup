from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class PlaybackAdapter(ABC):
    name: str

    @abstractmethod
    def play_file(self, path: Path) -> None:
        raise NotImplementedError
