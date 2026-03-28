from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from tests.conftest import run_cli


class _NonAudioHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = b'{"error":"model not found"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A003
        return


def _start_server() -> tuple[HTTPServer, int]:
    server = HTTPServer(("127.0.0.1", 0), _NonAudioHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def test_cli_lmstudio_non_audio_response_falls_back_to_text_only(tmp_path: Path, base_config: Path, env_with_fake_audio: dict[str, str]) -> None:
    server, port = _start_server()
    try:
        config = json.loads(base_config.read_text())
        config["tts"]["provider_order"] = ["lmstudio"]
        config["providers"]["lmstudio"] = {
            "base_url": f"http://127.0.0.1:{port}",
            "model": "fake",
            "tts_model": "fake-tts",
        }
        cfg_path = tmp_path / "cfg.json"
        cfg_path.write_text(json.dumps(config))

        result = run_cli(["--config", str(cfg_path), "--message", "Done", "--event", "final"], env=env_with_fake_audio)
        assert result.returncode == 0

        payload = json.loads(result.stdout)
        assert payload["status"] == "degraded_text_only"
        assert payload["backend"] == "none"
        assert payload["played"] is False
    finally:
        server.shutdown()
        server.server_close()
