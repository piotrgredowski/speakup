from __future__ import annotations

import logging
import multiprocessing
import os
import sys
from pathlib import Path

from ..app_logging import setup_logging as setup_app_logging
from ..config import Config
from ..history import NotificationHistory
from ..models import MessageEvent, NotifyRequest
from ..service import NotifyService

logger = logging.getLogger(__name__)


def build_droid_notify_request(
    *,
    message: str,
    event: str,
    session_name: str | None = None,
    session_id: str | None = None,
    session_key: str | None = None,
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
    )


def build_replay_command(session_key: str, count: int = 1) -> str:
    return f"speakup replay {count} --agent droid --session-key {session_key}"


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


def notify_in_background(request: NotifyRequest, *, config_path: str | Path | None = None) -> int:
    ctx = multiprocessing.get_context("spawn")
    process = ctx.Process(
        target=_notify_worker,
        args=(request, str(config_path) if config_path else None),
        daemon=False,
    )
    process.start()
    return process.pid or 0
