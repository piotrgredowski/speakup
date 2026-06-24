from __future__ import annotations

from speakup.runtime import RuntimeStateStore


def test_runtime_state_store_given_provider_process_then_persists_and_deletes(tmp_path) -> None:
    store = RuntimeStateStore(tmp_path / "runtime.db")

    store.save_provider_process(
        provider="piper",
        pid=123,
        base_url="http://127.0.0.1:5000",
        host="127.0.0.1",
        port=5000,
        payload={"model": "pl_PL-bass-high"},
        timestamp=10.0,
    )

    process = store.get_provider_process("piper")

    assert process is not None
    assert process.provider == "piper"
    assert process.pid == 123
    assert process.base_url == "http://127.0.0.1:5000"
    assert process.payload == {"model": "pl_PL-bass-high"}
    assert process.started_at == 10.0
    assert process.last_seen_at == 10.0

    store.mark_seen("piper", timestamp=15.0)
    assert store.get_provider_process("piper").last_seen_at == 15.0

    store.delete_provider_process("piper")
    assert store.get_provider_process("piper") is None
