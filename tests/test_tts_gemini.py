from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path

import pytest

from speakup.errors import AdapterError
from speakup.tts.gemini import GeminiTTSAdapter


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
                                "mimeType": "audio/pcm",
                            }
                        }
                    ]
                }
            }
        ]
    }


def test_gemini_tts_given_valid_response_then_writes_wav_audio(tmp_path, monkeypatch):
    audio_bytes = b"\x01\x00\x02\x00\x03\x00\x04\x00"
    response_json = _make_gemini_response(audio_bytes)
    response_data = json.dumps(response_json).encode("utf-8")

    fake_response = _FakeResponse(response_data, content_type="application/json")

    def fake_urlopen(req, timeout):  # noqa: ARG001
        return fake_response

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-123")

    adapter = GeminiTTSAdapter("GOOGLE_API_KEY", model="gemini-2.5-flash-preview-tts", voice="Kore")
    result = adapter.synthesize("Hello world", tmp_path, voice="default", speed=1.0, audio_format="wav")

    assert result.kind == "file"
    assert result.provider == "gemini"
    assert result.mime_type == "audio/wav"

    out_path = Path(str(result.value))
    assert out_path.exists()
    assert out_path.suffix == ".wav"

    with wave.open(str(out_path), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getframerate() == 24_000
        assert wav_file.getsampwidth() == 2
        assert wav_file.readframes(wav_file.getnframes()) == audio_bytes


def test_gemini_tts_given_mp3_output_then_transcodes_from_wav(tmp_path, monkeypatch):
    audio_bytes = b"\x01\x00\x02\x00"
    response_data = json.dumps(_make_gemini_response(audio_bytes)).encode("utf-8")
    fake_response = _FakeResponse(response_data, content_type="application/json")
    captured_command: dict[str, list[str]] = {}

    def fake_urlopen(req, timeout):  # noqa: ARG001
        return fake_response

    def fake_run(command, check, capture_output):  # noqa: ARG001
        captured_command["command"] = command
        Path(command[-1]).write_bytes(b"FAKE_MP3")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-123")

    adapter = GeminiTTSAdapter("GOOGLE_API_KEY", voice="Kore")
    result = adapter.synthesize("Hello world", tmp_path, audio_format="mp3")

    out_path = Path(str(result.value))
    assert out_path.exists()
    assert out_path.suffix == ".mp3"
    assert out_path.read_bytes() == b"FAKE_MP3"
    assert result.mime_type == "audio/mpeg"
    assert captured_command["command"][-2].endswith(".wav")
    assert captured_command["command"][-1].endswith(".mp3")


def test_gemini_tts_given_missing_ffmpeg_then_falls_back_to_wav(tmp_path, monkeypatch):
    audio_bytes = b"\x01\x00\x02\x00"
    response_data = json.dumps(_make_gemini_response(audio_bytes)).encode("utf-8")
    fake_response = _FakeResponse(response_data, content_type="application/json")

    def fake_urlopen(req, timeout):  # noqa: ARG001
        return fake_response

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("shutil.which", lambda command: None)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-123")

    adapter = GeminiTTSAdapter("GOOGLE_API_KEY", voice="Kore")
    result = adapter.synthesize("Hello world", tmp_path, audio_format="mp3")

    out_path = Path(str(result.value))
    assert out_path.exists()
    assert out_path.suffix == ".wav"
    assert result.mime_type == "audio/wav"


def test_gemini_tts_given_failed_transcode_then_cleans_up_temp_files(tmp_path, monkeypatch):
    audio_bytes = b"\x01\x00\x02\x00"
    response_data = json.dumps(_make_gemini_response(audio_bytes)).encode("utf-8")
    fake_response = _FakeResponse(response_data, content_type="application/json")

    def fake_urlopen(req, timeout):  # noqa: ARG001
        return fake_response

    def fake_run(command, check, capture_output):  # noqa: ARG001
        raise subprocess.CalledProcessError(1, command, stderr=b"boom")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("shutil.which", lambda command: command)
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-123")

    adapter = GeminiTTSAdapter("GOOGLE_API_KEY", voice="Kore")
    with pytest.raises(AdapterError, match="Gemini TTS audio conversion failed: boom"):
        adapter.synthesize("Hello world", tmp_path, audio_format="mp3")

    assert list(tmp_path.iterdir()) == []


def test_gemini_tts_missing_api_key_then_raises(tmp_path):
    adapter = GeminiTTSAdapter("MISSING_API_KEY", model="gemini-2.5-flash-preview-tts")
    with pytest.raises(AdapterError, match="Missing Gemini API key"):
        adapter.synthesize("test", tmp_path)


def test_gemini_tts_given_gemini_api_key_alias_then_uses_it(tmp_path, monkeypatch):
    response_data = json.dumps(_make_gemini_response(b"\x01\x00\x02\x00")).encode("utf-8")
    fake_response = _FakeResponse(response_data, content_type="application/json")

    def fake_urlopen(req, timeout):  # noqa: ARG001
        return fake_response

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setenv("GEMINI_API_KEY", "alias-key")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    adapter = GeminiTTSAdapter("GOOGLE_API_KEY", model="gemini-2.5-flash-preview-tts")
    result = adapter.synthesize("test", tmp_path, audio_format="wav")

    assert Path(str(result.value)).exists()


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


def test_gemini_tts_given_invalid_voice_then_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    adapter = GeminiTTSAdapter("GOOGLE_API_KEY")
    with pytest.raises(AdapterError, match="Unsupported Gemini voice: Eclipse"):
        adapter.synthesize("test", tmp_path, voice="Eclipse")


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
