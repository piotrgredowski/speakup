from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from speakup.errors import AdapterError
from speakup.tts.edge import EdgeTTSAdapter, _speed_to_rate


class _FakeCommunicate:
    calls: list[dict[str, str]] = []
    should_fail = False

    def __init__(self, text: str, voice: str, *, rate: str = "+0%") -> None:
        self.text = text
        self.voice = voice
        self.rate = rate
        self.calls.append({"text": text, "voice": voice, "rate": rate})

    async def save(self, path: str) -> None:
        if self.should_fail:
            raise RuntimeError("edge unavailable")
        Path(path).write_bytes(b"FAKE_MP3")


@pytest.mark.parametrize(
    "speed,expected",
    [
        (0.5, "-50%"),
        (1.0, "+0%"),
        (1.25, "+25%"),
        (2.0, "+100%"),
        (3.0, "+100%"),
        (0.1, "-90%"),
    ],
)
def test_speed_to_rate_given_speakup_speed_then_returns_edge_rate(speed: float, expected: str) -> None:
    assert _speed_to_rate(speed) == expected


def test_edge_tts_given_default_voice_then_writes_mp3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeCommunicate.calls = []
    monkeypatch.setattr("speakup.tts.edge._load_edge_tts", lambda: SimpleNamespace(Communicate=_FakeCommunicate))

    adapter = EdgeTTSAdapter(voice="en-US-AriaNeural")
    result = adapter.synthesize("Hello world", tmp_path, voice="default", speed=1.25, audio_format="wav")

    out_path = Path(str(result.value))
    assert result.kind == "file"
    assert result.provider == "edge"
    assert result.mime_type == "audio/mpeg"
    assert out_path.exists()
    assert out_path.suffix == ".mp3"
    assert out_path.read_bytes() == b"FAKE_MP3"
    assert _FakeCommunicate.calls == [{"text": "Hello world", "voice": "en-US-AriaNeural", "rate": "+25%"}]


def test_edge_tts_given_voice_override_then_uses_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeCommunicate.calls = []
    monkeypatch.setattr("speakup.tts.edge._load_edge_tts", lambda: SimpleNamespace(Communicate=_FakeCommunicate))

    adapter = EdgeTTSAdapter(voice="en-US-AriaNeural")
    adapter.synthesize("Hello world", tmp_path, voice="en-GB-SoniaNeural")

    assert _FakeCommunicate.calls[0]["voice"] == "en-GB-SoniaNeural"


def test_edge_tts_given_failed_synthesis_then_cleans_up_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeCommunicate.calls = []
    _FakeCommunicate.should_fail = True
    monkeypatch.setattr("speakup.tts.edge._load_edge_tts", lambda: SimpleNamespace(Communicate=_FakeCommunicate))

    adapter = EdgeTTSAdapter()
    with pytest.raises(AdapterError, match="Edge TTS failed: edge unavailable"):
        adapter.synthesize("Hello world", tmp_path)

    assert list(tmp_path.iterdir()) == []
    _FakeCommunicate.should_fail = False


def test_edge_tts_given_missing_optional_dependency_then_raises_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_edge_tts():
        raise AdapterError("Edge TTS requires the optional dependency: pip install 'speakup[edge]'")

    monkeypatch.setattr("speakup.tts.edge._load_edge_tts", missing_edge_tts)

    adapter = EdgeTTSAdapter()
    with pytest.raises(AdapterError, match=r"pip install 'speakup\[edge\]'"):
        adapter.synthesize("Hello world", tmp_path)

    assert list(tmp_path.iterdir()) == []
