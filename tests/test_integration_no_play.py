from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import run_cli


def test_cli_no_play_skips_playback_and_still_synthesizes(base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    result = run_cli(
        ["--config", str(base_config), "--no-play", "--message", "Done", "--event", "final"],
        env=env_with_fake_audio,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["played"] is False
    assert payload["audio_path"] is not None
    assert payload["error"] is None
