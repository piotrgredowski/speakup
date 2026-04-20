from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from ..app_logging import setup_logging as setup_app_logging
from ..config import Config
from ..history import NotificationHistory
from ..models import MessageEvent, NotifyRequest
from ..service import NotifyService

logger = logging.getLogger(__name__)

_PAYLOAD_FILE_ARG = "--payload-file"


def build_droid_notify_request(
    *,
    message: str,
    event: str,
    session_name: str | None = None,
    session_id: str | None = None,
    session_key: str | None = None,
    cwd: str | None = None,
) -> NotifyRequest:
    try:
        message_event = MessageEvent(event)
    except Exception:
        message_event = MessageEvent.FINAL

    return NotifyRequest(
        message=message,
        event=message_event,
        session_name=session_name,
        session_id=session_id or (session_key if session_key else None),
        session_key=session_key,
        agent="droid",
        metadata={"cwd": cwd} if cwd else {},
    )


def build_replay_command(session_key: str, count: int = 1) -> str:
    return f"speakup replay {count} --agent droid --session-key {session_key}"


def _serialize_request(request: NotifyRequest) -> dict[str, object]:
    payload = asdict(request)
    payload["event"] = request.event.value
    return payload


def _deserialize_request(payload: dict[str, object]) -> NotifyRequest:
    event = payload.get("event", MessageEvent.FINAL.value)
    try:
        payload["event"] = MessageEvent(str(event))
    except Exception:
        payload["event"] = MessageEvent.FINAL
    return NotifyRequest(**payload)


def _write_payload_file(request: NotifyRequest, config_path: str | Path | None) -> Path:
    fd, raw_path = tempfile.mkstemp(prefix="speakup-droid-", suffix=".json")
    payload_path = Path(raw_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "request": _serialize_request(request),
                    "config_path": str(config_path) if config_path else None,
                },
                handle,
            )
    except Exception:
        payload_path.unlink(missing_ok=True)
        raise
    return payload_path


def _detach_stdio() -> None:
    try:
        devnull = open(os.devnull, "a", encoding="utf-8")
    except OSError:
        return

    sys.stdin = devnull
    sys.stdout = devnull
    sys.stderr = devnull


def _notify_worker(request: NotifyRequest, config_path: str | None) -> None:
    _detach_stdio()
    config = Config.load(Path(config_path) if config_path else None)
    setup_app_logging(config.get("logging", default={}))
    NotifyService(config, history=NotificationHistory()).notify(request)


def _run_payload_file(payload_path: str | Path) -> None:
    path = Path(payload_path)
    try:
        payload = json.loads(path.read_text())
    finally:
        path.unlink(missing_ok=True)

    request = _deserialize_request(dict(payload["request"]))
    config_path = payload.get("config_path")
    _notify_worker(request, str(config_path) if config_path else None)


def notify_in_background(request: NotifyRequest, *, config_path: str | Path | None = None) -> int:
    payload_path = _write_payload_file(request, config_path)
    cmd = [
        sys.executable,
        "-m",
        "speakup.integrations.droid",
        _PAYLOAD_FILE_ARG,
        str(payload_path),
    ]
    try:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        payload_path.unlink(missing_ok=True)
        raise
    return process.pid or 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] != _PAYLOAD_FILE_ARG:
        raise SystemExit(f"Usage: python -m speakup.integrations.droid {_PAYLOAD_FILE_ARG} <path>")

    _run_payload_file(args[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
