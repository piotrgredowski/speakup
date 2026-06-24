from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

from .base import TTSAdapter
from ..errors import AdapterError
from ..models import AudioResult
from ..runtime import RuntimeStateStore


def _speed_to_length_scale(speed: float) -> float:
    if speed <= 0:
        return 1.0
    return min(2.0, max(0.5, 1.0 / speed))


class PiperTTSAdapter(TTSAdapter):
    """Piper TTS adapter using the local Piper HTTP server."""

    name: ClassVar[str] = "piper"

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:5000",
        auto_start: bool = True,
        host: str = "127.0.0.1",
        port: int = 5000,
        data_dir: str = "~/.local/share/speakup/piper-voices",
        model: str = "pl_PL-bass-high",
        voice: str = "pl_PL-bass-high",
        timeout: float = 20.0,
        startup_timeout: float = 10.0,
        extra_args: list[str] | None = None,
        runtime_store: RuntimeStateStore | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.auto_start = auto_start
        self.host = host
        self.port = int(port)
        self.data_dir = str(Path(data_dir).expanduser())
        self.model = model
        self.default_voice = voice
        self.timeout = timeout
        self.startup_timeout = startup_timeout
        self.extra_args = list(extra_args or [])
        self.runtime_store = runtime_store or RuntimeStateStore()

    def synthesize(
        self,
        text: str,
        output_dir: Path,
        *,
        voice: str = "default",
        speed: float = 1.0,
        audio_format: str = "wav",
    ) -> AudioResult:
        del audio_format
        base_url = self._ensure_server()
        selected_voice = self.default_voice if voice == "default" else voice
        payload = {
            "text": text,
            "voice": selected_voice,
            "length_scale": _speed_to_length_scale(speed),
        }
        req = urllib.request.Request(
            f"{base_url}/",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                content_type = resp.headers.get("Content-Type", "")
                audio = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read(200).decode("utf-8", errors="replace")
            raise AdapterError(f"Piper TTS failed ({exc.code}): {detail}") from exc
        except Exception as exc:
            raise AdapterError(f"Piper TTS request failed: {exc}") from exc

        if not content_type.lower().startswith("audio/") and not audio.startswith(b"RIFF"):
            preview = audio[:200].decode("utf-8", errors="replace")
            raise AdapterError(f"Piper TTS returned non-audio response (Content-Type: {content_type}): {preview}")
        if not audio:
            raise AdapterError("Piper TTS produced no audio")

        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"tts-{uuid4().hex}.wav"
        out_path.write_bytes(audio)
        return AudioResult(kind="file", value=str(out_path), provider=self.name, mime_type="audio/wav")

    def _ensure_server(self) -> str:
        if self._is_healthy(self.base_url):
            return self.base_url

        process = self.runtime_store.get_provider_process(self.name)
        if process and process.payload.get("data_dir") == self.data_dir and self._is_healthy(process.base_url):
            self.runtime_store.mark_seen(self.name)
            return process.base_url
        if process:
            self.runtime_store.delete_provider_process(self.name)

        if not self.auto_start:
            raise AdapterError(f"Piper server is not reachable at {self.base_url}")

        self._ensure_optional_dependency()
        port = self.port if self._port_available(self.host, self.port) else self._find_free_port(self.host)
        base_url = f"http://{self.host}:{port}"
        command = [
            sys.executable,
            "-m",
            "piper.http_server",
            "--data-dir",
            self.data_dir,
            "--model",
            self.model,
            "--host",
            self.host,
            "--port",
            str(port),
            *self.extra_args,
        ]

        stderr = tempfile.TemporaryFile()
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=stderr,
                start_new_session=True,
            )
        except Exception as exc:
            stderr.close()
            raise AdapterError(f"Piper server failed to start: {exc}") from exc

        self._wait_until_healthy(base_url, process, stderr)
        stderr.close()
        self.runtime_store.save_provider_process(
            provider=self.name,
            pid=process.pid,
            base_url=base_url,
            host=self.host,
            port=port,
            payload={"data_dir": self.data_dir, "model": self.model},
        )
        return base_url

    def _wait_until_healthy(self, base_url: str, process: subprocess.Popen[bytes], stderr) -> None:
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AdapterError(
                    f"Piper server exited during startup with code {process.returncode}: {self._process_stderr(stderr)}"
                )
            if self._is_healthy(base_url, timeout=0.5):
                return
            time.sleep(0.1)
        process.terminate()
        raise AdapterError(f"Piper server did not become ready at {base_url}: {self._process_stderr(stderr)}")

    def _is_healthy(self, base_url: str, *, timeout: float | None = None) -> bool:
        req = urllib.request.Request(f"{base_url.rstrip('/')}/voices", method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout if timeout is None else timeout) as resp:
                return 200 <= resp.status < 300
        except Exception:
            return False

    @staticmethod
    def _ensure_optional_dependency() -> None:
        try:
            spec = importlib.util.find_spec("piper.http_server")
        except ModuleNotFoundError:
            spec = None
        if spec is None:
            raise AdapterError("Piper TTS requires the optional dependency: pip install 'speakup[piper]'")

    @staticmethod
    def _port_available(host: str, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            return sock.connect_ex((host, port)) != 0

    @staticmethod
    def _find_free_port(host: str) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, 0))
            return int(sock.getsockname()[1])

    @staticmethod
    def _process_stderr(stderr) -> str:
        try:
            stderr.flush()
            stderr.seek(0)
            detail = stderr.read().decode("utf-8", errors="replace").strip()
        except Exception:
            return "stderr unavailable"
        return detail or "no stderr"
