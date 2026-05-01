from __future__ import annotations

from speakup.models import MessageEvent, NotifyRequest
from speakup.session_naming import (
    normalize_session_name_candidate,
    resolve_session_name,
)


def test_normalize_session_name_candidate_accepts_meaningful_name() -> None:
    assert normalize_session_name_candidate("  Release Train  ") == "Release Train"


def test_normalize_session_name_candidate_rejects_placeholder_and_hex_like_values() -> None:
    assert normalize_session_name_candidate("New Session") is None
    assert normalize_session_name_candidate("deadbeefcafebabe") is None
    assert normalize_session_name_candidate("") is None


def test_resolve_session_name_prefers_explicit_meaningful_name() -> None:
    request = NotifyRequest(
        message="Done",
        event=MessageEvent.FINAL,
        session_name="Nightly Run",
        conversation_id="conv-123",
        session_id="sess-456",
    )

    assert resolve_session_name(request, {"enabled": True}) == "Nightly Run"


def test_resolve_session_name_ignores_conversation_id_and_session_id() -> None:
    with_conversation = NotifyRequest(
        message="Done",
        event=MessageEvent.FINAL,
        session_name="",
        conversation_id="conv-123",
        session_id="sess-456",
    )
    with_session_only = NotifyRequest(
        message="Done",
        event=MessageEvent.FINAL,
        session_name="",
        session_id="sess-456",
    )

    assert resolve_session_name(with_conversation, {"enabled": True}) is None
    assert resolve_session_name(with_session_only, {"enabled": True}) is None


def test_resolve_session_name_does_not_fall_back_to_session_id_when_conversation_id_is_blank() -> None:
    request = NotifyRequest(
        message="Done",
        event=MessageEvent.FINAL,
        session_name="",
        conversation_id="   ",
        session_id="sess-456",
    )

    assert resolve_session_name(request, {"enabled": True}) is None


def test_resolve_session_name_returns_none_when_generation_disabled() -> None:
    request = NotifyRequest(
        message="Done",
        event=MessageEvent.FINAL,
        session_name="",
        conversation_id="conv-123",
    )

    assert resolve_session_name(request, {"enabled": False}) is None
