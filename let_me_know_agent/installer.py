from __future__ import annotations

import shutil
import subprocess

from .errors import AdapterError


def kokoro_command_available(command: str = "kokoro") -> bool:
    return shutil.which(command) is not None


def install_kokoro(*, python_executable: str = "python") -> str:
    """Install kokoro Python package into the current environment.

    Returns a human-readable status message.
    """
    if kokoro_command_available("kokoro"):
        return "kokoro already available"

    cmd = [python_executable, "-m", "pip", "install", "kokoro"]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except Exception as exc:
        raise AdapterError(f"Failed to install kokoro: {exc}") from exc

    if not kokoro_command_available("kokoro"):
        return "kokoro installed (command not found in PATH yet; restart shell)"
    return "kokoro installed"
