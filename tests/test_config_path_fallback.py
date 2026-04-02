from __future__ import annotations

import json
from pathlib import Path

from speakup.config import Config


def test_config_load_given_no_path_and_home_config_exists_then_uses_home_file(monkeypatch, tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    config_dir = fake_home / ".config" / "speakup"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.json"

    config_data = {
        "privacy": {"mode": "local_only", "allow_remote_fallback": False},
        "events": {
            "speak_on_final": True,
            "speak_on_error": True,
            "speak_on_needs_input": True,
            "speak_on_progress": True,
        },
        "summarization": {"max_chars": 123, "provider_order": ["rule_based"]},
        "event_sounds": {"enabled": True, "files": {}},
        "tts": {
            "provider_order": ["macos"],
            "voice": "default",
            "speed": 1.0,
            "audio_format": "mp3",
            "save_audio_dir": ".cache/audio",
        },
        "dedup": {"enabled": True, "window_seconds": 30, "cache_file": ".cache/last_progress.json"},
        "providers": {"lmstudio": {}, "elevenlabs": {}, "openai": {}},
    }
    config_path.write_text(json.dumps(config_data))

    monkeypatch.setattr(Path, "home", lambda: fake_home)

    loaded = Config.load(None)
    assert loaded.get("privacy", "mode") == "local_only"
    assert loaded.get("summarization", "max_chars") == 123
