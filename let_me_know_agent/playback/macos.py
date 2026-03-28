from __future__ import annotations

import subprocess
from pathlib import Path

from .base import PlaybackAdapter
from ..errors import AdapterError


class MacOSPlaybackAdapter(PlaybackAdapter):
    name = "macos_afplay"

    def play_file(self, path: Path) -> None:
        if not path.exists():
            raise AdapterError(f"Audio file does not exist: {path}")
        try:
            subprocess.run(["afplay", str(path)], check=True, capture_output=True)
        except Exception as exc:
            raise AdapterError(f"Playback failed: {exc}") from exc
