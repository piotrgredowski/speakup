from __future__ import annotations

import subprocess

import pytest

from let_me_know_agent.errors import AdapterError
from let_me_know_agent.installer import install_kokoro


def test_install_kokoro_returns_already_available(monkeypatch) -> None:
    monkeypatch.setattr("let_me_know_agent.installer.kokoro_command_available", lambda command="kokoro": True)
    assert install_kokoro() == "kokoro already available"


def test_install_kokoro_runs_pip_when_missing(monkeypatch) -> None:
    states = iter([False, True])
    monkeypatch.setattr("let_me_know_agent.installer.kokoro_command_available", lambda command="kokoro": next(states))

    called: dict[str, list[str]] = {}

    def fake_run(cmd, check, capture_output, text):
        called["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("subprocess.run", fake_run)
    msg = install_kokoro(python_executable="python3")

    assert called["cmd"] == ["python3", "-m", "pip", "install", "kokoro"]
    assert msg == "kokoro installed"


def test_install_kokoro_raises_adapter_error_on_install_failure(monkeypatch) -> None:
    monkeypatch.setattr("let_me_know_agent.installer.kokoro_command_available", lambda command="kokoro": False)

    def fake_run(cmd, check, capture_output, text):
        raise subprocess.CalledProcessError(returncode=1, cmd=cmd)

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(AdapterError):
        install_kokoro(python_executable="python3")
