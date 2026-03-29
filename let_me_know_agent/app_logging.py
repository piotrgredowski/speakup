from __future__ import annotations

import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
            }:
                continue
            payload[key] = value
        return json.dumps(payload, default=str)


class TextExtrasFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras: list[str] = []
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "asctime",
                "message",
            }:
                continue
            if value is None:
                continue
            extras.append(f"{key}={value}")

        if extras:
            return f"{base} | {' '.join(sorted(extras))}"
        return base


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def _build_text_format(include_timestamps: bool, include_module: bool, include_pid: bool) -> str:
    parts = []
    if include_timestamps:
        parts.append("%(asctime)s")
    parts.append("%(levelname)s")
    if include_pid:
        parts.append("pid=%(process)d")
    if include_module:
        parts.append("%(name)s")
    parts.append("%(message)s")
    return " | ".join(parts)


def _make_formatter(config: dict[str, Any]) -> logging.Formatter:
    fmt = config.get("format", "text")
    if fmt == "json":
        return JsonFormatter()
    return TextExtrasFormatter(
        _build_text_format(
            bool(config.get("include_timestamps", True)),
            bool(config.get("include_module", True)),
            bool(config.get("include_pid", False)),
        )
    )


def setup_logging(config: dict[str, Any] | None = None, *, level_override: str | None = None, format_override: str | None = None, file_override: str | None = None) -> None:
    cfg = config or {}
    enabled = bool(cfg.get("enabled", True))
    if not enabled:
        logging.disable(logging.CRITICAL)
        return

    logging.disable(logging.NOTSET)

    level_name = (level_override or cfg.get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    effective_cfg = dict(cfg)
    if format_override:
        effective_cfg["format"] = format_override
    formatter = _make_formatter(effective_cfg)

    destination = cfg.get("destination", "stderr")
    handlers: list[logging.Handler] = []

    if destination in {"stderr", "both"}:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(formatter)
        handlers.append(stderr_handler)

    if destination in {"file", "both"} or file_override:
        file_path = file_override or cfg.get("file_path")
        if not file_path:
            file_path = "/tmp/let-me-know-agent.log"
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        file_handler = RotatingFileHandler(
            file_path,
            maxBytes=int(cfg.get("rotate_max_bytes", 1_048_576)),
            backupCount=int(cfg.get("rotate_backup_count", 3)),
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    if not handlers:
        fallback = logging.StreamHandler(sys.stderr)
        fallback.setFormatter(formatter)
        handlers.append(fallback)

    for handler in handlers:
        root.addHandler(handler)


def redact_value(value: str, *, enabled: bool = True) -> str:
    if not enabled:
        return value
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}***{value[-2:]}"
