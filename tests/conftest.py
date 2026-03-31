from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def fake_audio_bin(tmp_path: Path) -> tuple[Path, Path]:
    """Creates fake `say` and `afplay` commands and returns (bin_dir, play_log)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    play_log = tmp_path / "play.log"

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
        "if [ -z \"$OUT\" ]; then\n"
        "  echo 'missing -o output' >&2\n"
        "  exit 2\n"
        "fi\n"
        "echo 'FAKEAUDIO' > \"$OUT\"\n"
    )
    say_script.chmod(say_script.stat().st_mode | stat.S_IEXEC)

    afplay_script = bin_dir / "afplay"
    afplay_script.write_text(
        "#!/bin/sh\n"
        "echo \"$1\" >> \"${PLAY_LOG}\"\n"
    )
    afplay_script.chmod(afplay_script.stat().st_mode | stat.S_IEXEC)

    return bin_dir, play_log


@pytest.fixture
def base_config(tmp_path: Path) -> Path:
    config = {
        "privacy": {"mode": "prefer_local", "allow_remote_fallback": False},
        "events": {
            "speak_on_final": True,
            "speak_on_error": True,
            "speak_on_needs_input": True,
            "speak_on_progress": True,
        },
        "event_sounds": {"enabled": True, "files": {}},
        "summarization": {"max_chars": 160, "provider_order": ["rule_based"]},
        "tts": {
            "provider_order": ["macos"],
            "voice": "default",
            "speed": 1.0,
            "audio_format": "mp3",
            "save_audio_dir": str(tmp_path / "audio"),
        },
        "dedup": {"enabled": True, "window_seconds": 30, "cache_file": str(tmp_path / "dedup.json")},
        "providers": {"lmstudio": {}, "elevenlabs": {}, "openai": {}},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    return path


def run_cli(args: list[str], *, env: dict[str, str] | None = None, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "let_me_know_agent.cli", *args]
    return subprocess.run(command, text=True, capture_output=True, env=env, input=stdin)


def run_pi_cli(args: list[str], *, env: dict[str, str] | None = None, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "let_me_know_agent.cli", "pi", *args]
    return subprocess.run(command, text=True, capture_output=True, env=env, input=stdin)


@pytest.fixture
def env_with_fake_audio(fake_audio_bin: tuple[Path, Path]) -> dict[str, str]:
    bin_dir, play_log = fake_audio_bin
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["PLAY_LOG"] = str(play_log)
    return env
