from __future__ import annotations

import json
import urllib.error

import pytest

from speakup.errors import AdapterError
from speakup.models import MessageEvent
from speakup.summarizers.omlx import OmlxSummarizer


class _FakeResponse:
    def __init__(self, data: dict):
        self._data = json.dumps(data).encode("utf-8")
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, n: int = -1) -> bytes:
        return self._data[: n if n >= 0 else None]


def _success_response(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}]}


def test_omlx_summarizer_given_successful_response_then_returns_summary(monkeypatch):
    request_data = {}

    def fake_urlopen(req, timeout):
        request_data["url"] = req.full_url
        request_data["headers"] = dict(req.headers)
        request_data["body"] = json.loads(req.data)
        request_data["timeout"] = timeout
        return _FakeResponse(_success_response("Local summary"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    summarizer = OmlxSummarizer()
    result = summarizer.summarize("Finished changes", MessageEvent.FINAL, max_chars=220)

    assert result.summary == "Local summary"
    assert result.state == MessageEvent.FINAL
    assert result.user_action_required is False
    assert request_data["url"] == "http://127.0.0.1:8000/v1/chat/completions"
    assert request_data["headers"]["Authorization"] == "Bearer 1234"
    assert request_data["body"]["model"] == "unsloth/gemma-4-E4B-it-UD-MLX-4bit"
    assert request_data["body"]["messages"][1]["content"] == "Finished changes"
    assert request_data["timeout"] == 60.0


def test_omlx_summarizer_given_custom_env_key_then_uses_it(monkeypatch):
    monkeypatch.setenv("CUSTOM_OMLX_KEY", "local-key")
    request_data = {}

    def fake_urlopen(req, timeout):
        request_data["headers"] = dict(req.headers)
        request_data["body"] = json.loads(req.data)
        return _FakeResponse(_success_response("Summary"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    summarizer = OmlxSummarizer(api_key_env="CUSTOM_OMLX_KEY", model="custom-summary")
    result = summarizer.summarize("Needs input", MessageEvent.NEEDS_INPUT, max_chars=220)

    assert result.summary == "Summary"
    assert result.user_action_required is True
    assert request_data["headers"]["Authorization"] == "Bearer local-key"
    assert request_data["body"]["model"] == "custom-summary"


def test_omlx_summarizer_given_long_response_then_truncates(monkeypatch):
    long_text = "x" * 300

    def fake_urlopen(req, timeout):
        return _FakeResponse(_success_response(long_text))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = OmlxSummarizer().summarize("Progress", MessageEvent.PROGRESS, max_chars=220)

    assert result.summary == "x" * 219 + "…"
    assert len(result.summary) == 220


def test_omlx_summarizer_given_http_error_then_raises_adapter_error(monkeypatch):
    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(AdapterError, match="oMLX summarization failed"):
        OmlxSummarizer().summarize("Test", MessageEvent.FINAL, max_chars=220)


def test_omlx_summarizer_given_invalid_response_then_raises_adapter_error(monkeypatch):
    def fake_urlopen(req, timeout):
        return _FakeResponse({"choices": []})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(AdapterError, match="invalid response"):
        OmlxSummarizer().summarize("Test", MessageEvent.FINAL, max_chars=220)
