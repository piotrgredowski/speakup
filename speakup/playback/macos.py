from __future__ import annotations

import subprocess
from pathlib import Path
from typing import ClassVar

from .base import PlaybackAdapter
from ..errors import AdapterError


class MacOSPlaybackAdapter(PlaybackAdapter):
    """macOS audio playback using the 'afplay' command."""

    name: ClassVar[str] = "macos_afplay"

    def play_file(self, path: Path) -> None:
        if not path.exists():
            raise AdapterError(f"Audio file does not exist: {path}")
        try:
            subprocess.run(["afplay", str(path)], check=True, capture_output=True)
        except Exception as exc:
            raise AdapterError(f"Playback failed: {exc}") from exc
