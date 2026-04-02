from __future__ import annotations

import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Any

import structlog


_RESERVED_RECORD_KEYS = {
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
}


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def _copy_extra_record_fields(_: logging.Logger, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    record = event_dict.get("_record")
    if not record:
        return event_dict
    for key, value in record.__dict__.items():
        if key.startswith("_") or key in _RESERVED_RECORD_KEYS or value is None:
            continue
        event_dict.setdefault(key, value)
    return event_dict


def _make_formatter(config: dict[str, Any], *, colors: bool = False) -> logging.Formatter:
    fmt = config.get("format", "text")
    include_timestamps = bool(config.get("include_timestamps", True))
    include_module = bool(config.get("include_module", True))
    include_pid = bool(config.get("include_pid", False))

    pre_chain: list[Any] = [
        structlog.stdlib.add_log_level,
        _copy_extra_record_fields,
        structlog.processors.format_exc_info,
    ]
    if include_module:
        pre_chain.insert(1, structlog.stdlib.add_logger_name)
    if include_timestamps:
        pre_chain.append(structlog.processors.TimeStamper(fmt="iso"))
    if include_pid:
        pre_chain.append(structlog.processors.CallsiteParameterAdder(parameters={structlog.processors.CallsiteParameter.PROCESS}))

    if fmt == "json":
        def _safe_json_dumps(obj: Any, **kwargs: Any) -> str:
            kwargs.setdefault("default", str)
            return json.dumps(obj, **kwargs)

        processor = structlog.processors.JSONRenderer(serializer=_safe_json_dumps)
    else:
        processor = structlog.dev.ConsoleRenderer(colors=colors)

    return structlog.stdlib.ProcessorFormatter(
        processor=processor,
        foreign_pre_chain=pre_chain,
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
    destination = cfg.get("destination", "stderr")
    handlers: list[logging.Handler] = []

    if destination in {"stderr", "both"}:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(_make_formatter(effective_cfg, colors=sys.stderr.isatty()))
        handlers.append(stderr_handler)

    if destination == "stdout":
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setFormatter(_make_formatter(effective_cfg, colors=sys.stdout.isatty()))
        handlers.append(stdout_handler)

    if destination in {"file", "both"} or file_override:
        file_path = file_override or cfg.get("file_path")
        if not file_path:
            file_path = "/tmp/speakup.log"
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        file_handler = RotatingFileHandler(
            file_path,
            maxBytes=int(cfg.get("rotate_max_bytes", 1_048_576)),
            backupCount=int(cfg.get("rotate_backup_count", 3)),
        )
        file_handler.setFormatter(_make_formatter(effective_cfg, colors=False))
        handlers.append(file_handler)

        # Second file with colors
        color_file_path = cfg.get("file_path_color") or f"{file_path}.color"
        os.makedirs(os.path.dirname(color_file_path), exist_ok=True)
        color_file_handler = RotatingFileHandler(
            color_file_path,
            maxBytes=int(cfg.get("rotate_max_bytes", 1_048_576)),
            backupCount=int(cfg.get("rotate_backup_count", 3)),
        )
        color_file_handler.setFormatter(_make_formatter(effective_cfg, colors=True))
        handlers.append(color_file_handler)

    if not handlers:
        fallback = logging.StreamHandler(sys.stderr)
        fallback.setFormatter(_make_formatter(effective_cfg, colors=sys.stderr.isatty()))
        handlers.append(fallback)

    for handler in handlers:
        root.addHandler(handler)

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            _copy_extra_record_fields,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def redact_value(value: str, *, enabled: bool = True) -> str:
    if not enabled:
        return value
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}***{value[-2:]}"
