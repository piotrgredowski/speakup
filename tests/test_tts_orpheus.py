from __future__ import annotations

import json

import pytest

from speakup.errors import AdapterError
from speakup.tts.lmstudio import LMStudioTTSAdapter


class _FakeStreamResponse:
    def __init__(self, lines: list[str], content_type: str = "text/event-stream"):
        self._lines = [line.encode("utf-8") for line in lines]
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        return iter(self._lines)

    def read(self, n: int = -1) -> bytes:
        return b"".join(self._lines)[:n if n >= 0 else None]


def _sse_line(text: str) -> str:
    payload = {"choices": [{"text": text}]}
    return f"data: {json.dumps(payload)}\n"


def test_lmstudio_orpheus_mode_given_stream_tokens_then_writes_wav(tmp_path, monkeypatch):
    lines = [_sse_line(f"<custom_token_{50000 + i}>") for i in range(28)] + ["data: [DONE]\n"]

    def fake_urlopen(req, timeout):  # noqa: ARG001
        return _FakeStreamResponse(lines)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    adapter = LMStudioTTSAdapter(
        "http://127.0.0.1:1234/v1",
        "orpheus-model",
        tts_mode="orpheus_completions",
        orpheus_voice="tara",
    )
    monkeypatch.setattr(adapter, "_decode_multiframe", lambda multiframe: b"\x00\x00" * 256)

    result = adapter.synthesize("hello", tmp_path, voice="default", speed=1.0, audio_format="wav")

    assert result.mime_type == "audio/wav"
    from pathlib import Path

    out = Path(str(result.value))
    assert out.exists()
    assert out.read_bytes().startswith(b"RIFF")


def test_lmstudio_orpheus_mode_given_non_default_speed_then_raises(tmp_path):
    adapter = LMStudioTTSAdapter("http://127.0.0.1:1234/v1", "orpheus-model", tts_mode="orpheus_completions")
    with pytest.raises(AdapterError):
        adapter.synthesize("hello", tmp_path, speed=1.2)
