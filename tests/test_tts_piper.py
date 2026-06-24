from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from speakup.errors import AdapterError
from speakup.tts.piper import PiperTTSAdapter, _speed_to_length_scale


class _FakeResponse:
    def __init__(self, body: bytes = b"", *, status: int = 200, content_type: str = "audio/wav"):
        self._body = body
        self.status = status
        self.headers = {"Content-Type": content_type}

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int | None = None) -> bytes:
        if size is None:
            return self._body
        return self._body[:size]


@pytest.mark.parametrize(
    "speed,expected",
    [
        (0.5, 2.0),
        (1.0, 1.0),
        (2.0, 0.5),
        (4.0, 0.5),
        (0.1, 2.0),
        (0.0, 1.0),
    ],
)
def test_speed_to_length_scale_given_speakup_speed_then_returns_piper_scale(speed: float, expected: float) -> None:
    assert _speed_to_length_scale(speed) == expected


def test_piper_tts_given_healthy_server_then_posts_json_and_writes_wav(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []

    def fake_urlopen(req, timeout: float = 0):
        url = req.full_url
        requests.append({"url": url, "method": req.get_method(), "data": getattr(req, "data", None), "timeout": timeout})
        if url.endswith("/voices"):
            return _FakeResponse(b"{}", content_type="application/json")
        return _FakeResponse(b"RIFF_FAKE_WAV", content_type="audio/wav")

    monkeypatch.setattr("speakup.tts.piper.urllib.request.urlopen", fake_urlopen)

    adapter = PiperTTSAdapter(base_url="http://127.0.0.1:5000", auto_start=False, voice="pl_PL-bass-high")
    result = adapter.synthesize("Czesc", tmp_path, voice="pl_PL-mc_speech-medium", speed=2.0, audio_format="mp3")

    out_path = Path(str(result.value))
    assert result.kind == "file"
    assert result.provider == "piper"
    assert result.mime_type == "audio/wav"
    assert out_path.suffix == ".wav"
    assert out_path.read_bytes() == b"RIFF_FAKE_WAV"

    payload = json.loads(requests[-1]["data"].decode("utf-8"))
    assert requests[-1]["url"] == "http://127.0.0.1:5000/"
    assert payload == {
        "text": "Czesc",
        "voice": "pl_PL-mc_speech-medium",
        "length_scale": 0.5,
    }


def test_piper_tts_given_non_audio_response_then_raises_adapter_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(req, timeout: float = 0):
        if req.full_url.endswith("/voices"):
            return _FakeResponse(b"{}", content_type="application/json")
        return _FakeResponse(b"<html>error</html>", content_type="text/html")

    monkeypatch.setattr("speakup.tts.piper.urllib.request.urlopen", fake_urlopen)

    adapter = PiperTTSAdapter(auto_start=False)
    with pytest.raises(AdapterError, match="non-audio response"):
        adapter.synthesize("Czesc", tmp_path)


def test_piper_tts_given_piper_server_wav_with_text_html_content_type_then_accepts_riff_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(req, timeout: float = 0):
        if req.full_url.endswith("/voices"):
            return _FakeResponse(b"{}", content_type="application/json")
        return _FakeResponse(b"RIFF_FAKE_WAV", content_type="text/html; charset=utf-8")

    monkeypatch.setattr("speakup.tts.piper.urllib.request.urlopen", fake_urlopen)

    adapter = PiperTTSAdapter(auto_start=False)
    result = adapter.synthesize("Czesc", tmp_path)

    assert result.mime_type == "audio/wav"
    assert Path(str(result.value)).read_bytes() == b"RIFF_FAKE_WAV"


def test_piper_tts_given_server_unavailable_and_no_autostart_then_raises_adapter_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(req, timeout: float = 0):
        raise OSError("connection refused")

    monkeypatch.setattr("speakup.tts.piper.urllib.request.urlopen", fake_urlopen)

    adapter = PiperTTSAdapter(base_url="http://127.0.0.1:5000", auto_start=False)
    with pytest.raises(AdapterError, match="not reachable"):
        adapter.synthesize("Czesc", tmp_path)
