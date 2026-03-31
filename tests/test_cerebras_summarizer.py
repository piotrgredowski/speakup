from __future__ import annotations

import json

import pytest

from let_me_know_agent.errors import AdapterError
from let_me_know_agent.models import MessageEvent
from let_me_know_agent.summarizers.cerebras import CerebrasSummarizer


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
        "choices": [
            {
                "message": {
                    "content": text,
                }
            }
        ]
    }


def test_cerebras_summarizer_given_missing_api_key_then_raises(monkeypatch):
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    monkeypatch.delenv("CUSTOM_CEREBRAS_KEY", raising=False)

    summarizer = CerebrasSummarizer(api_key_env="CEREBRAS_API_KEY")
    with pytest.raises(AdapterError) as exc:
        summarizer.summarize("Test message", MessageEvent.FINAL, max_chars=220)

    assert "Missing Cerebras API key" in str(exc.value)


def test_cerebras_summarizer_given_custom_env_key_then_uses_it(monkeypatch):
    monkeypatch.setenv("CUSTOM_CEREBRAS_KEY", "test-custom-key")
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)

    request_data = {}

    def fake_urlopen(req, timeout):
        request_data["url"] = req.full_url
        request_data["headers"] = dict(req.headers)
        request_data["body"] = json.loads(req.data)
        return _FakeResponse(_success_response("Summary text"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    summarizer = CerebrasSummarizer(api_key_env="CUSTOM_CEREBRAS_KEY", model="llama3.1-8b")
    result = summarizer.summarize("Test message", MessageEvent.FINAL, max_chars=220)

    assert result.summary == "Summary text"
    assert request_data["headers"]["Authorization"] == "Bearer test-custom-key"
    assert request_data["body"]["model"] == "llama3.1-8b"


def test_cerebras_summarizer_given_successful_response_then_returns_summary(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-key")

    def fake_urlopen(req, timeout):
        return _FakeResponse(_success_response("Test successful completion"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    summarizer = CerebrasSummarizer(api_key_env="CEREBRAS_API_KEY")
    result = summarizer.summarize("Test message", MessageEvent.FINAL, max_chars=220)

    assert result.summary == "Test successful completion"
    assert result.state == MessageEvent.FINAL
    assert result.user_action_required is False


def test_cerebras_summarizer_given_needs_input_event_then_sets_flag(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-key")

    def fake_urlopen(req, timeout):
        return _FakeResponse(_success_response("User input required"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    summarizer = CerebrasSummarizer(api_key_env="CEREBRAS_API_KEY")
    result = summarizer.summarize("Waiting for input", MessageEvent.NEEDS_INPUT, max_chars=220)

    assert result.summary == "User input required"
    assert result.state == MessageEvent.NEEDS_INPUT
    assert result.user_action_required is True


def test_cerebras_summarizer_given_long_response_then_truncates(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-key")

    long_text = "x" * 300
    expected = "x" * 219 + "…"

    def fake_urlopen(req, timeout):
        return _FakeResponse(_success_response(long_text))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    summarizer = CerebrasSummarizer(api_key_env="CEREBRAS_API_KEY")
    result = summarizer.summarize("Long message", MessageEvent.PROGRESS, max_chars=220)

    assert result.summary == expected
    assert len(result.summary) == 220


def test_cerebras_summarizer_given_custom_model_then_uses_it(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-key")

    request_data = {}

    def fake_urlopen(req, timeout):
        request_data["body"] = json.loads(req.data)
        return _FakeResponse(_success_response("Summary"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    summarizer = CerebrasSummarizer(api_key_env="CEREBRAS_API_KEY", model="llama-3.1-8b")
    result = summarizer.summarize("Test", MessageEvent.FINAL, max_chars=220)

    assert result.summary == "Summary"
    assert request_data["body"]["model"] == "llama-3.1-8b"


def test_cerebras_summarizer_given_custom_base_url_then_uses_it(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-key")

    request_data = {}

    def fake_urlopen(req, timeout):
        request_data["url"] = req.full_url
        return _FakeResponse(_success_response("Summary"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    summarizer = CerebrasSummarizer(
        api_key_env="CEREBRAS_API_KEY",
        base_url="https://custom.cerebras.ai/v1",
    )
    result = summarizer.summarize("Test", MessageEvent.FINAL, max_chars=220)

    assert result.summary == "Summary"
    assert request_data["url"] == "https://custom.cerebras.ai/v1/chat/completions"


def test_cerebras_summarizer_given_api_error_then_raises(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-key")

    def fake_urlopen(req, timeout):
        raise Exception("Connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    summarizer = CerebrasSummarizer(api_key_env="CEREBRAS_API_KEY")
    with pytest.raises(AdapterError) as exc:
        summarizer.summarize("Test", MessageEvent.FINAL, max_chars=220)

    assert "Cerebras summarization request failed" in str(exc.value)


def test_cerebras_summarizer_given_correct_system_prompt_then_uses_it(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-key")

    request_data = {}

    def fake_urlopen(req, timeout):
        request_data["body"] = json.loads(req.data)
        return _FakeResponse(_success_response("Summary"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    summarizer = CerebrasSummarizer(api_key_env="CEREBRAS_API_KEY")
    summarizer.summarize("Test message", MessageEvent.ERROR, max_chars=100)

    system_content = request_data["body"]["messages"][0]["content"]
    assert "1 sentence" in system_content
    assert "event type is: ERROR" in system_content
    assert "notification system" in system_content.lower()
