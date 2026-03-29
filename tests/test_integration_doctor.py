from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from .conftest import run_cli


def test_cli_doctor_given_working_kokoro_cli_then_returns_ok(tmp_path: Path, base_config: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    kokoro_script = bin_dir / "kokoro"
    kokoro_script.write_text(
        "#!/bin/sh\n"
        "OUT=''\n"
        "while [ $# -gt 0 ]; do\n"
        "  if [ \"$1\" = \"--output\" ] || [ \"$1\" = \"-o\" ]; then\n"
        "    shift\n"
        "    OUT=\"$1\"\n"
        "  fi\n"
        "  shift\n"
        "done\n"
        "echo 'FAKEAUDIO' > \"$OUT\"\n"
    )
    kokoro_script.chmod(kokoro_script.stat().st_mode | stat.S_IEXEC)

    config = json.loads(base_config.read_text())
    config.setdefault("providers", {})["kokoro_cli"] = {
        "command": "kokoro",
        "args": ["--output", "{output}", "--voice", "{voice}", "--speed", "{speed}", "{text}"],
        "timeout_seconds": 10,
    }
    config_path = tmp_path / "config_doctor.json"
    config_path.write_text(json.dumps(config))

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

    result = run_cli(["--config", str(config_path), "--doctor"], env=env)
    assert result.returncode == 0

    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["checks"]["kokoro_cli"]["ok"] is True
    assert payload["checks"]["kokoro_cli"]["audio_path"]


def test_cli_doctor_given_missing_kokoro_cli_then_returns_error(base_config: Path) -> None:
    result = run_cli(["--config", str(base_config), "--doctor"], env={"PATH": ""})
    assert result.returncode == 1

    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["checks"]["kokoro_cli"]["ok"] is False
    assert "not found" in (payload["checks"]["kokoro_cli"]["error"] or "")
