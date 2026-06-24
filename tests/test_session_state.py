from __future__ import annotations

from pathlib import Path

from speakup.session_state import SessionStateStore


def test_session_state_store_upserts_and_reads_exact_agent_session_pair(tmp_path: Path) -> None:
    store = SessionStateStore(tmp_path / "state.db")

    store.upsert(agent="codex", session_key="abc", session_name="Morning Work", spoken_language="pl")
    store.upsert(agent="pi", session_key="abc", session_name="Other Work", spoken_language="en")
    store.upsert(agent="codex", session_key="abc", session_name="Morning Work", spoken_language="pl")

    state = store.get(agent="codex", session_key="abc")
    other_agent_state = store.get(agent="pi", session_key="abc")

    assert state is not None
    assert state.agent == "codex"
    assert state.session_key == "abc"
    assert state.session_name == "Morning Work"
    assert state.spoken_language == "pl"
    assert state.updated_at >= state.created_at
    assert other_agent_state is not None
    assert other_agent_state.spoken_language == "en"
