from __future__ import annotations

from pathlib import Path
from typing import Callable

from .errors import AdapterError
from .models import AudioResult
from .playback.base import PlaybackAdapter
from .summarizers.base import Summarizer


TTSFactory = Callable[[], "TTSAdapter"]
SummarizerFactory = Callable[[], Summarizer]


class AdapterRegistry:
    """Registry for TTS and summarizer adapters with lazy instantiation."""

    def __init__(self) -> None:
        self._tts_factories: dict[str, TTSFactory] = {}
        self._summarizer_factories: dict[str, SummarizerFactory] = {}
        self._playback: PlaybackAdapter | None = None
        self._tts_instances: dict[str, TTSAdapter] = {}
        self._summarizer_instances: dict[str, Summarizer] = {}

    def register_tts(self, name: str, factory: TTSFactory) -> None:
        """Register a TTS adapter factory."""
        self._tts_factories[name] = factory

    def register_summarizer(self, name: str, factory: SummarizerFactory) -> None:
        """Register a summarizer factory."""
        self._summarizer_factories[name] = factory

    def set_playback(self, playback: PlaybackAdapter) -> None:
        """Set the playback adapter instance."""
        self._playback = playback

    def get_tts(self, name: str) -> TTSAdapter:
        """Get or create a TTS adapter by name."""
        if name not in self._tts_instances:
            if name not in self._tts_factories:
                raise AdapterError(f"Unknown TTS provider: {name}")
            self._tts_instances[name] = self._tts_factories[name]()
        return self._tts_instances[name]

    def get_summarizer(self, name: str) -> Summarizer:
        """Get or create a summarizer by name."""
        if name not in self._summarizer_instances:
            if name not in self._summarizer_factories:
                raise AdapterError(f"Unknown summarizer provider: {name}")
            self._summarizer_instances[name] = self._summarizer_factories[name]()
        return self._summarizer_instances[name]

    def get_playback(self) -> PlaybackAdapter:
        """Get the playback adapter."""
        if self._playback is None:
            raise AdapterError("No playback adapter configured")
        return self._playback

    def has_tts(self, name: str) -> bool:
        """Check if a TTS provider is registered."""
        return name in self._tts_factories

    def has_summarizer(self, name: str) -> bool:
        """Check if a summarizer provider is registered."""
        return name in self._summarizer_factories

    def clear_cache(self) -> None:
        """Clear cached adapter instances (useful for testing)."""
        self._tts_instances.clear()
        self._summarizer_instances.clear()
