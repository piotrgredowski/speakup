from __future__ import annotations

import json
from pathlib import Path

from speakup.integrations.codex import (
    build_codex_notify_request,
    build_hook_output,
    build_replay_command,
    detect_plan_approval_message,
    extract_session_key,
    get_session_pointer_path,
    mark_plan_approval_seen,
    plan_approval_seen,
    request_from_codex_payload,
    save_current_session_pointer,
)


def test_request_from_codex_payload_given_notification_then_maps_to_needs_input() -> None:
    request = request_from_codex_payload(
        {
            "hook_event_name": "Notification",
            "message": "Approve this command?",
            "session_id": "sess-123",
            "cwd": "/tmp/project",
            "session": {"name": "Implement Codex support"},
        }
    )

    assert request.message == "Approve this command?"
    assert request.event.value == "needs_input"
    assert request.agent == "codex"
    assert request.session_key == "sess-123"
    assert request.session_id == "sess-123"
    assert request.session_name == "Implement Codex support"
    assert request.metadata == {"cwd": "/tmp/project"}


def test_request_from_codex_payload_given_stop_then_maps_to_final() -> None:
    request = request_from_codex_payload(
        {
            "hook_event_name": "Stop",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Implemented the feature."}],
            },
            "conversation_id": "conv-123",
        }
    )

    assert request.message == "Implemented the feature."
    assert request.event.value == "final"
    assert request.session_key == "conv-123"


def test_request_from_codex_payload_detects_plan_approval() -> None:
    request = request_from_codex_payload(
        {
            "hook_event_name": "Stop",
            "message": "<proposed_plan>\n# Add Codex Support\n\nDo the thing.\n</proposed_plan>",
            "session_id": "sess-123",
        }
    )

    assert request.message == "Codex is waiting for plan approval: Add Codex Support."
    assert request.event.value == "needs_input"
    assert request.precomputed_summary == "Codex is waiting for plan approval: Add Codex Support."
    assert request.skip_summarization is True


def test_detect_plan_approval_message_uses_goal_when_title_missing() -> None:
    message = detect_plan_approval_message("<proposed_plan>\n## Summary\nShip a Codex plugin.\n</proposed_plan>")

    assert message == "Codex is waiting for plan approval. Ship a Codex plugin."


def test_plan_approval_dedupe_tracks_session_and_plan(tmp_path: Path, monkeypatch) -> None:
    import speakup.integrations.codex as codex

    monkeypatch.setattr(codex.Path, "home", lambda: tmp_path)
    dedupe_key = "plan:abc123"

    assert plan_approval_seen("sess-123", dedupe_key) is False

    mark_plan_approval_seen("sess-123", dedupe_key)

    assert plan_approval_seen("sess-123", dedupe_key) is True


def test_build_codex_notify_request_sets_codex_fields() -> None:
    request = build_codex_notify_request(
        message="hello",
        event="info",
        session_name="Session Name",
        session_id="sess-123",
        session_key="sess-123",
        cwd="/tmp/project",
        source_tool="Codex",
        precomputed_summary="hello",
        skip_summarization=True,
    )

    assert request.message == "hello"
    assert request.event.value == "info"
    assert request.session_name == "Session Name"
    assert request.session_id == "sess-123"
    assert request.session_key == "sess-123"
    assert request.agent == "codex"
    assert request.source_tool == "Codex"
    assert request.precomputed_summary == "hello"
    assert request.skip_summarization is True
    assert request.metadata == {"cwd": "/tmp/project"}


def test_extract_session_key_prefers_stable_codex_fields() -> None:
    assert (
        extract_session_key(
            {
                "conversation_id": "conv-123",
                "session_id": "sess-123",
                "session": {"id": "nested-123"},
            }
        )
        == "conv-123"
    )


def test_save_current_session_pointer_writes_cwd_scoped_pointer(tmp_path: Path, monkeypatch) -> None:
    import speakup.integrations.codex as codex

    monkeypatch.setattr(codex.Path, "home", lambda: tmp_path)

    save_current_session_pointer("/tmp/project", "sess-123", "Codex Session")

    pointer_path = get_session_pointer_path("/tmp/project")
    payload = json.loads(pointer_path.read_text())
    assert payload["session_key"] == "sess-123"
    assert payload["session_name"] == "Codex Session"


def test_build_replay_command_uses_codex_agent() -> None:
    assert build_replay_command("sess-123", 3) == "speakup replay 3 --agent codex --session-key sess-123"


def test_build_hook_output_includes_replay_command() -> None:
    assert (
        build_hook_output("sess-123", "Codex Session")
        == "Session: Codex Session\nReplay cmd: speakup replay 1 --agent codex --session-key sess-123"
    )
