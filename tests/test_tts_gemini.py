from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from let_me_know_agent.errors import AdapterError
from let_me_know_agent.tts.gemini import GeminiTTSAdapter


class _FakeResponse:
    def __init__(self, data: bytes, content_type: str = "application/json"):
        self._data = data
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._data


def _make_gemini_response(audio_data: bytes) -> dict:
    import base64
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "inlineData": {
                                "data": base64.b64encode(audio_data).decode("utf-8"),
                                "mimeType": "audio/mp3"
                            }
                        }
                    ]
                }
            }
        ]
    }


def test_gemini_tts_given_valid_response_then_writes_audio(tmp_path, monkeypatch):
    audio_bytes = b"fake_audio_data_12345"
    response_json = _make_gemini_response(audio_bytes)
    response_data = json.dumps(response_json).encode("utf-8")

    fake_response = _FakeResponse(response_data, content_type="application/json")

    def fake_urlopen(req, timeout):  # noqa: ARG001
        return fake_response

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-123")

    adapter = GeminiTTSAdapter("GOOGLE_API_KEY", model="gemini-2.5-flash-preview-tts", voice="Kore")
    result = adapter.synthesize("Hello world", tmp_path, voice="default", speed=1.0, audio_format="mp3")

    assert result.kind == "file"
    assert result.provider == "gemini"
    assert result.mime_type == "audio/mpeg"

    from pathlib import Path
    out_path = Path(str(result.value))
    assert out_path.exists()
    assert out_path.read_bytes() == audio_bytes


def test_gemini_tts_missing_api_key_then_raises(tmp_path):
    adapter = GeminiTTSAdapter("MISSING_API_KEY", model="gemini-2.5-flash-preview-tts")
    with pytest.raises(AdapterError, match="Missing Gemini API key"):
        adapter.synthesize("test", tmp_path)


def test_gemini_tts_api_error_then_raises(tmp_path, monkeypatch):
    error_response = {
        "error": {
            "message": "Invalid API key",
            "code": 403
        }
    }
    response_data = json.dumps(error_response).encode("utf-8")
    fake_response = _FakeResponse(response_data, content_type="application/json")

    def fake_urlopen(req, timeout):  # noqa: ARG001
        return fake_response

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setenv("GOOGLE_API_KEY", "invalid-key")

    adapter = GeminiTTSAdapter("GOOGLE_API_KEY")
    with pytest.raises(AdapterError, match="Gemini TTS API error"):
        adapter.synthesize("test", tmp_path)


def test_gemini_tts_no_audio_data_then_raises(tmp_path, monkeypatch):
    response_json = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "No audio here"}
                    ]
                }
            }
        ]
    }
    response_data = json.dumps(response_json).encode("utf-8")
    fake_response = _FakeResponse(response_data, content_type="application/json")

    def fake_urlopen(req, timeout):  # noqa: ARG001
        return fake_response

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    adapter = GeminiTTSAdapter("GOOGLE_API_KEY")
    with pytest.raises(AdapterError, match="Gemini TTS returned no audio data"):
        adapter.synthesize("test", tmp_path)


def test_gemini_tts_uses_custom_voice(tmp_path, monkeypatch):
    audio_bytes = b"fake_audio"
    response_json = _make_gemini_response(audio_bytes)
    response_data = json.dumps(response_json).encode("utf-8")

    captured_request = {}

    def fake_urlopen(req, timeout):
        captured_request["data"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse(response_data, content_type="application/json")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    adapter = GeminiTTSAdapter("GOOGLE_API_KEY", voice="Kore")
    adapter.synthesize("test", tmp_path, voice="Charon")

    # Verify the custom voice was used in the request
    voice_config = captured_request["data"]["generationConfig"]["speechConfig"]["voiceConfig"]
    assert voice_config["prebuiltVoiceConfig"]["voiceName"] == "Charon"
