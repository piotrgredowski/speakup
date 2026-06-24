from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


INTEGRATION_PROVIDER_API_KEY_ENVS = {
    "cerebras": ("CEREBRAS_API_KEY",),
    "gemini": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
}


def integration_provider_has_key(provider: str) -> bool:
    return any(os.environ.get(env_name) for env_name in INTEGRATION_PROVIDER_API_KEY_ENVS.get(provider, ()))


def integration_provider_requires_key(provider: str) -> bool:
    return provider in INTEGRATION_PROVIDER_API_KEY_ENVS


def selected_integration_provider() -> str:
    explicit_provider = os.environ.get("SPEAKUP_INTEGRATION_TEST_PROVIDER", "").strip().lower()
    if explicit_provider:
        return explicit_provider
    for provider in INTEGRATION_PROVIDER_API_KEY_ENVS:
        if integration_provider_has_key(provider):
            return provider
    return ""


def selected_integration_model(default: str) -> str:
    return os.environ.get("SPEAKUP_INTEGRATION_TEST_MODEL", default).strip() or default


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or "integration_pronunciation" not in item.keywords:
        return

    output = getattr(report, "capstdout", "").strip()
    if not output:
        return
    pronunciation_outputs = getattr(item.config, "_pronunciation_outputs", [])
    pronunciation_outputs.append((item.nodeid, report.outcome, output))
    item.config._pronunciation_outputs = pronunciation_outputs


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter, exitstatus: int, config: pytest.Config) -> None:
    pronunciation_outputs = getattr(config, "_pronunciation_outputs", [])
    if not pronunciation_outputs:
        return

    terminalreporter.section("pronunciation integration output", sep="-")
    for nodeid, outcome, output in pronunciation_outputs:
        terminalreporter.write_line(f"{nodeid} [{outcome}]")
        terminalreporter.write_line(output)
        terminalreporter.write_line("")


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
        "playback": {"queue_enabled": False},
        "privacy": {"mode": "prefer_local", "allow_remote_fallback": False},
        "events": {
            "speak_on_final": True,
            "speak_on_error": True,
            "speak_on_needs_input": True,
            "speak_on_progress": True,
        },
        "event_sounds": {"enabled": True, "files": {}},
        "summarization": {"max_chars": 160, "provider_order": ["rule_based"]},
        "context_naming": {"source": "session"},
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


def run_cli(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
    cwd: str | Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "speakup.cli", *args]
    if cwd is None and "--config" in args:
        config_index = args.index("--config")
        if config_index + 1 < len(args):
            cwd = Path(args[config_index + 1]).parent
    return subprocess.run(command, text=True, capture_output=True, env=env, input=stdin, cwd=cwd)


def run_pi_cli(args: list[str], *, env: dict[str, str] | None = None, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "speakup.cli", "pi", *args]
    return subprocess.run(command, text=True, capture_output=True, env=env, input=stdin)


@pytest.fixture
def env_with_fake_audio(fake_audio_bin: tuple[Path, Path]) -> dict[str, str]:
    bin_dir, play_log = fake_audio_bin
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["PLAY_LOG"] = str(play_log)
    env["SPEAKUP_SAY_BIN"] = str(bin_dir / "say")
    env["SPEAKUP_AFPLAY_BIN"] = str(bin_dir / "afplay")
    return env
