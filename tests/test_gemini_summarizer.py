from __future__ import annotations

import json

import pytest

from speakup.errors import AdapterError
from speakup.models import MessageEvent
from speakup.summarizers.gemini import GeminiSummarizer


class _FakeResponse:
    def __init__(self, data: dict, status: int = 200):
        self._data = json.dumps(data).encode("utf-8")
        self.status = status
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, n: int = -1) -> bytes:
        return self._data[: n if n >= 0 else None]


def _success_response(text: str) -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": text},
                    ]
                }
            }
        ]
    }


def test_gemini_summarizer_given_missing_api_key_then_raises(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    summarizer = GeminiSummarizer(api_key_env="GOOGLE_API_KEY")
    with pytest.raises(AdapterError, match="Missing Gemini API key"):
        summarizer.summarize("Test message", MessageEvent.FINAL, max_chars=220)


def test_gemini_summarizer_given_gemini_api_key_alias_then_uses_it(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    request_data = {}

    def fake_urlopen(req, timeout):
        request_data["url"] = req.full_url
        request_data["body"] = json.loads(req.data)
        return _FakeResponse(_success_response("Summary text"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    summarizer = GeminiSummarizer(api_key_env="GOOGLE_API_KEY", model="gemini-2.5-flash")
    result = summarizer.summarize("Test message", MessageEvent.FINAL, max_chars=220)

    assert result.summary == "Summary text"
    assert "key=test-gemini-key" in request_data["url"]
    assert request_data["body"]["systemInstruction"]["parts"][0]["text"]
    assert request_data["body"]["contents"][0]["parts"][0]["text"] == "Test message"


def test_gemini_summarizer_given_successful_response_then_returns_summary(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    def fake_urlopen(req, timeout):
        return _FakeResponse(_success_response("Test successful completion"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    summarizer = GeminiSummarizer(api_key_env="GOOGLE_API_KEY")
    result = summarizer.summarize("Test message", MessageEvent.FINAL, max_chars=220)

    assert result.summary == "Test successful completion"
    assert result.state == MessageEvent.FINAL
    assert result.user_action_required is False


def test_gemini_summarizer_given_needs_input_event_then_sets_flag(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    def fake_urlopen(req, timeout):
        return _FakeResponse(_success_response("User input required"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    summarizer = GeminiSummarizer(api_key_env="GOOGLE_API_KEY")
    result = summarizer.summarize(
        "Waiting for input", MessageEvent.NEEDS_INPUT, max_chars=220
    )

    assert result.summary == "User input required"
    assert result.state == MessageEvent.NEEDS_INPUT
    assert result.user_action_required is True


def test_gemini_summarizer_given_long_response_then_truncates(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    long_text = "x" * 300
    expected = "x" * 219 + "…"

    def fake_urlopen(req, timeout):
        return _FakeResponse(_success_response(long_text))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    summarizer = GeminiSummarizer(api_key_env="GOOGLE_API_KEY")
    result = summarizer.summarize("Long message", MessageEvent.PROGRESS, max_chars=220)

    assert result.summary == expected
    assert len(result.summary) == 220


def test_gemini_summarizer_given_api_error_then_raises(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    def fake_urlopen(req, timeout):
        return _FakeResponse({"error": {"message": "quota exceeded"}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    summarizer = GeminiSummarizer(api_key_env="GOOGLE_API_KEY")
    with pytest.raises(AdapterError, match="Gemini summarization API error: quota exceeded"):
        summarizer.summarize("Test", MessageEvent.FINAL, max_chars=220)


def test_gemini_summarizer_given_custom_base_url_then_uses_it(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    request_data = {}

    def fake_urlopen(req, timeout):
        request_data["url"] = req.full_url
        return _FakeResponse(_success_response("Summary"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    summarizer = GeminiSummarizer(
        api_key_env="GOOGLE_API_KEY",
        base_url="https://custom.gemini.example/v1beta",
    )
    result = summarizer.summarize("Test", MessageEvent.FINAL, max_chars=220)

    assert result.summary == "Summary"
    assert (
        request_data["url"]
        == "https://custom.gemini.example/v1beta/models/gemini-2.5-flash:generateContent?key=test-key"
    )
