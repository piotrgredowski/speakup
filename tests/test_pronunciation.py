from __future__ import annotations

import sys

import pytest

from speakup.errors import AdapterError
from speakup.pronunciation import CallablePronunciationAdapter, CommandPronunciationAdapter


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
