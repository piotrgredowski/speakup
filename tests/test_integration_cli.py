from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from .conftest import run_cli


def test_cli_given_needs_input_message_then_returns_spoken_summary(base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    result = run_cli(["--config", str(base_config), "--message", "Could you confirm the deploy region?", "--event", "needs_input"], env=env_with_fake_audio)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["state"] == "needs_input"
    assert payload["summary"] == "Could you confirm the deploy region?"
    assert payload["played"] is True
    assert payload["backend"] == "macos"


def test_cli_given_progress_duplicate_then_skips_second_time(base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    args = ["--config", str(base_config), "--message", "Still indexing files", "--event", "progress"]
    first = run_cli(args, env=env_with_fake_audio)
    second = run_cli(args, env=env_with_fake_audio)

    assert first.returncode == 0
    assert second.returncode == 0

    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)

    assert first_payload["status"] == "ok"
    assert second_payload["status"] == "skipped"
    assert second_payload["dedup_skipped"] is True


def test_cli_given_event_sound_mapping_then_plays_sound_and_tts(tmp_path: Path, base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    beep = tmp_path / "beep.aiff"
    beep.write_text("beep")

    config = json.loads(base_config.read_text())
    config["event_sounds"]["files"] = {"error": str(beep)}
    base_config.write_text(json.dumps(config))

    result = run_cli(["--config", str(base_config), "--message", "Build failed due to timeout", "--event", "error"], env=env_with_fake_audio)
    assert result.returncode == 0

    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"

    play_log = Path(env_with_fake_audio["PLAY_LOG"])
    lines = [ln.strip() for ln in play_log.read_text().splitlines() if ln.strip()]
    assert str(beep) in lines
    assert any("tts-" in line for line in lines)


def test_cli_given_playback_failure_then_returns_partial_success(tmp_path: Path, base_config: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    say_script = bin_dir / "say"
    say_script.write_text(
        "#!/bin/sh\n"
        "OUT=\"\"\n"
        "while [ $# -gt 0 ]; do\n"
        "  if [ \"$1\" = \"-o\" ]; then\n"
        "    shift\n"
        "    OUT=\"$1\"\n"
        "  fi\n"
        "  shift\n"
        "done\n"
        "echo 'FAKEAUDIO' > \"$OUT\"\n"
    )
    say_script.chmod(say_script.stat().st_mode | stat.S_IEXEC)

    afplay_script = bin_dir / "afplay"
    afplay_script.write_text("#!/bin/sh\nexit 1\n")
    afplay_script.chmod(afplay_script.stat().st_mode | stat.S_IEXEC)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

    result = run_cli(["--config", str(base_config), "--message", "Done", "--event", "final"], env=env)
    assert result.returncode == 0

    payload = json.loads(result.stdout)
    assert payload["status"] == "partial_success"
    assert payload["played"] is False
    assert payload["backend"] == "macos"
    assert payload["error"] is not None
