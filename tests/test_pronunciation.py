from __future__ import annotations

import json
import sys

import pytest

from speakup.errors import AdapterError
from speakup.config import Config, default_config
from speakup.pronunciation import (
    CallablePronunciationAdapter,
    CommandPronunciationAdapter,
    OpenAICompatiblePronunciationAdapter,
)
from speakup.service import build_registry_from_config


class _FakeResponse:
    def __init__(self, data: dict[str, object]) -> None:
        self._data = json.dumps(data).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return self._data


def test_pronunciation_adapter_given_json_response_then_returns_adapted_segments() -> None:
    payloads = []

    def complete(payload: dict[str, object]) -> str:
        payloads.append(payload)
        return '{"spoken_language": "pl", "title": "spikap mówi", "message": "GitHab ekszyn fejld"}'

    adapter = CallablePronunciationAdapter(name="fake", complete=complete)

    result = adapter.adapt(title="speakup says", message="GitHub action failed", spoken_language=None)

    assert result.spoken_language == "pl"
    assert result.title == "spikap mówi"
    assert result.message.lower() == "githab ekszyn fejld"
    assert payloads == [
        {
            "spoken_language": None,
            "title": "speakup says",
            "message": "GitHub action failed",
        }
    ]


def test_pronunciation_adapter_given_fenced_json_response_then_returns_adapted_segments() -> None:
    adapter = CallablePronunciationAdapter(
        name="fake",
        complete=lambda _: (
            '```json\n{"spoken_language": "pl", "title": "speakup says", '
            '"message": "GitHab ekszyn fejld"}\n```'
        ),
    )

    result = adapter.adapt(title="speakup says", message="GitHub action failed", spoken_language="pl")

    assert result.spoken_language == "pl"
    assert result.title == "speakup says"
    assert result.message == "GitHab ekszyn fejld"


def test_pronunciation_adapter_given_invalid_json_then_raises_adapter_error() -> None:
    adapter = CallablePronunciationAdapter(name="fake", complete=lambda _: "not json")

    with pytest.raises(AdapterError, match="invalid JSON"):
        adapter.adapt(title=None, message="GitHub action failed", spoken_language="pl")


def test_pronunciation_adapter_given_empty_message_then_raises_adapter_error() -> None:
    adapter = CallablePronunciationAdapter(
        name="fake",
        complete=lambda _: '{"spoken_language": "pl", "title": null, "message": ""}',
    )

    with pytest.raises(AdapterError, match="empty message"):
        adapter.adapt(title=None, message="GitHub action failed", spoken_language="pl")


def test_command_pronunciation_given_message_placeholder_then_sends_pronunciation_prompt() -> None:
    adapter = CommandPronunciationAdapter(
        command=sys.executable,
        args=[
            "-c",
            (
                "import sys; "
                "sys.exit(2) if 'Adapt final spoken notification text' not in sys.argv[1] "
                "else print('{{\"spoken_language\":\"pl\",\"title\":null,\"message\":\"GitHab ekszyn fejld\"}}')"
            ),
            "{message}",
        ],
    )

    result = adapter.adapt(title=None, message="GitHub action failed", spoken_language="pl")

    assert result.message.lower() == "githab ekszyn fejld"


def test_omlx_pronunciation_disables_thinking_in_chat_template_kwargs(monkeypatch) -> None:
    requests = []

    def fake_urlopen(req, timeout):
        requests.append(json.loads(req.data))
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"spoken_language":"pl","title":null,"message":"GitHab ekszyn fejld"}',
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    cfg = Config(default_config())
    adapter = build_registry_from_config(cfg).get_pronunciation("omlx")

    result = adapter.adapt(title=None, message="GitHub action failed", spoken_language="pl")

    assert result.message == "GitHab ekszyn fejld"
    assert requests[0]["chat_template_kwargs"] == {
        "enable_thinking": False,
        "preserve_thinking": False,
    }


def test_openai_compatible_pronunciation_sends_user_agent(monkeypatch) -> None:
    headers = {}

    def fake_urlopen(req, timeout):
        headers.update(dict(req.headers))
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"spoken_language":"pl","title":null,"message":"GitHab ekszyn fejld"}',
                        }
                    }
                ]
            }
        )

    monkeypatch.setenv("FAKE_API_KEY", "test-key")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    adapter = OpenAICompatiblePronunciationAdapter(
        name="fake",
        base_url="https://example.test/v1",
        api_key_env="FAKE_API_KEY",
        model="fake-model",
    )

    adapter.adapt(title=None, message="GitHub action failed", spoken_language="pl")

    assert headers["User-agent"] == "speakup/0.1.0"
