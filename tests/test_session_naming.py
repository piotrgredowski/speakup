from __future__ import annotations

from speakup.models import MessageEvent, NotifyRequest
from speakup.session_naming import (
    POLISH_GIVEN_NAMES,
    SESSION_NAME_ADJECTIVES,
    generate_session_name,
    normalize_session_name_candidate,
    resolve_session_name,
)


def test_normalize_session_name_candidate_accepts_meaningful_name() -> None:
    assert normalize_session_name_candidate("  Release Train  ") == "Release Train"


def test_normalize_session_name_candidate_rejects_placeholder_and_hex_like_values() -> None:
    assert normalize_session_name_candidate("New Session") is None
    assert normalize_session_name_candidate("deadbeefcafebabe") is None
    assert normalize_session_name_candidate("") is None


def test_generate_session_name_returns_deterministic_adjective_and_polish_name() -> None:
    generated = generate_session_name("conv-123")

    assert generated is not None
    adjective, name = generated.split(" ", 1)
    assert adjective in SESSION_NAME_ADJECTIVES
    assert name in POLISH_GIVEN_NAMES
    assert generate_session_name("conv-123") == generated


def test_session_name_wordlists_are_curated_and_unique() -> None:
    assert len(SESSION_NAME_ADJECTIVES) >= 50
    assert len(SESSION_NAME_ADJECTIVES) == len(set(SESSION_NAME_ADJECTIVES))
    assert len(POLISH_GIVEN_NAMES) >= 35
    assert len(POLISH_GIVEN_NAMES) == len(set(POLISH_GIVEN_NAMES))


def test_resolve_session_name_prefers_explicit_meaningful_name() -> None:
    request = NotifyRequest(
        message="Done",
        event=MessageEvent.FINAL,
        session_name="Nightly Run",
        conversation_id="conv-123",
        session_id="sess-456",
    )

    assert resolve_session_name(request, {"enabled": True}) == "Nightly Run"


def test_resolve_session_name_prefers_conversation_id_then_session_id() -> None:
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

    assert resolve_session_name(with_conversation, {"enabled": True}) == generate_session_name("conv-123")
    assert resolve_session_name(with_session_only, {"enabled": True}) == generate_session_name("sess-456")


def test_resolve_session_name_falls_back_to_session_id_when_conversation_id_is_blank() -> None:
    request = NotifyRequest(
        message="Done",
        event=MessageEvent.FINAL,
        session_name="",
        conversation_id="   ",
        session_id="sess-456",
    )

    assert resolve_session_name(request, {"enabled": True}) == generate_session_name("sess-456")


def test_resolve_session_name_returns_none_when_generation_disabled() -> None:
    request = NotifyRequest(
        message="Done",
        event=MessageEvent.FINAL,
        session_name="",
        conversation_id="conv-123",
    )

    assert resolve_session_name(request, {"enabled": False}) is None
