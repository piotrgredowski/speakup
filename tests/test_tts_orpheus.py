from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

from let_me_know_agent.errors import AdapterError
from let_me_know_agent.tts.orpheus import OrpheusTTSAdapter


def test_orpheus_given_offline_failure_then_retries_online_and_restores_offline_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeModel:
        def __init__(self, model_name: str, max_model_len: int):
            self.model_name = model_name
            self.max_model_len = max_model_len

        def generate_speech(self, prompt: str, voice: str):
            if os.environ.get("HF_HUB_OFFLINE") == "1":
                raise RuntimeError("model not cached")
            yield b"\x00\x00" * 50

    monkeypatch.setitem(sys.modules, "orpheus_tts", types.SimpleNamespace(OrpheusModel=FakeModel))
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)

    adapter = OrpheusTTSAdapter(offline=True)
    result = adapter.synthesize("hello", tmp_path / "out")

    assert result.provider == "orpheus"
    assert Path(str(result.value)).exists()
    assert os.environ.get("HF_HUB_OFFLINE") == "1"
    assert os.environ.get("TRANSFORMERS_OFFLINE") == "1"


def test_orpheus_given_offline_and_online_failure_then_raises_adapter_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeModel:
        def __init__(self, model_name: str, max_model_len: int):
            self.model_name = model_name
            self.max_model_len = max_model_len

        def generate_speech(self, prompt: str, voice: str):
            raise RuntimeError("always fails")

    monkeypatch.setitem(sys.modules, "orpheus_tts", types.SimpleNamespace(OrpheusModel=FakeModel))

    adapter = OrpheusTTSAdapter(offline=True)
    with pytest.raises(AdapterError) as exc:
        adapter.synthesize("hello", tmp_path / "out")

    assert "Online retry also failed" in str(exc.value)
