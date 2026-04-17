from __future__ import annotations

import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Any

import structlog

from .config import get_default_log_file_path


DEFAULT_REQUEST_ID = "-"
LOG_FIELD_ORDER = ("request_id", "timestamp", "level", "logger", "event")
LEVEL_COLOR_CODES = {
    "debug": "\x1b[2m",
    "info": "\x1b[36m",
    "warning": "\x1b[33m",
    "error": "\x1b[31m",
    "critical": "\x1b[1;31m",
}
ANSI_RESET = "\x1b[0m"

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


def _ensure_request_id(_: logging.Logger, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    event_dict.setdefault("request_id", DEFAULT_REQUEST_ID)
    return event_dict


def _reorder_event_dict(_: logging.Logger, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    ordered: dict[str, Any] = {}
    for key in LOG_FIELD_ORDER:
        if key in event_dict:
            ordered[key] = event_dict[key]
    for key, value in event_dict.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def _build_shared_processors(config: dict[str, Any]) -> list[Any]:
    include_timestamps = bool(config.get("include_timestamps", True))
    include_module = bool(config.get("include_module", True))
    include_pid = bool(config.get("include_pid", False))

    processors: list[Any] = [
        structlog.stdlib.add_log_level,
    ]
    if include_module:
        processors.append(structlog.stdlib.add_logger_name)
    processors.extend([
        _copy_extra_record_fields,
        structlog.processors.format_exc_info,
    ])
    if include_timestamps:
        processors.append(structlog.processors.TimeStamper(fmt="iso"))
    if include_pid:
        processors.append(structlog.processors.CallsiteParameterAdder(parameters={structlog.processors.CallsiteParameter.PROCESS}))

    processors.extend([_ensure_request_id, _reorder_event_dict])
    return processors


def _render_text_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)

    text = str(value)
    if not text:
        return '""'
    if any(char.isspace() for char in text) or any(char in text for char in ('"', "=")):
        return json.dumps(text, ensure_ascii=False)
    return text


def _render_text_log_line(_: logging.Logger, __: str, event_dict: dict[str, Any]) -> str:
    return " ".join(
        f"{key}={_render_text_value(value)}"
        for key, value in event_dict.items()
        if value is not None
    )


def _render_text_log_line_with_colors(_: logging.Logger, __: str, event_dict: dict[str, Any]) -> str:
    line = _render_text_log_line(_, __, event_dict)
    color = LEVEL_COLOR_CODES.get(str(event_dict.get("level", "")).lower())
    if not color:
        return line
    return f"{color}{line}{ANSI_RESET}"


def make_formatter(config: dict[str, Any], *, colors: bool = False) -> logging.Formatter:
    fmt = config.get("format", "text")
    processors = _build_shared_processors(config)

    if fmt == "json":
        def _safe_json_dumps(obj: Any, **kwargs: Any) -> str:
            kwargs.setdefault("default", str)
            return json.dumps(obj, **kwargs)

        processor = structlog.processors.JSONRenderer(serializer=_safe_json_dumps)
    else:
        processor = _render_text_log_line_with_colors if colors else _render_text_log_line

    return structlog.stdlib.ProcessorFormatter(
        processor=processor,
        foreign_pre_chain=processors,
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
    destinations = cfg.get("destination", ["stderr"])
    if isinstance(destinations, str):
        destinations = [destinations]
    selected = set(destinations)
    handlers: list[logging.Handler] = []

    if "stderr" in selected:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(make_formatter(effective_cfg, colors=sys.stderr.isatty()))
        handlers.append(stderr_handler)

    if "stdout" in selected:
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setFormatter(make_formatter(effective_cfg, colors=sys.stdout.isatty()))
        handlers.append(stdout_handler)

    if "file" in selected or file_override:
        file_path = file_override or cfg.get("file_path")
        if not file_path:
            file_path = str(get_default_log_file_path())
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        file_handler = RotatingFileHandler(
            file_path,
            maxBytes=int(cfg.get("rotate_max_bytes", 1_048_576)),
            backupCount=int(cfg.get("rotate_backup_count", 3)),
        )
        file_handler.setFormatter(make_formatter(effective_cfg, colors=False))
        handlers.append(file_handler)

        # Second file with colors
        color_file_path = cfg.get("file_path_color") or f"{file_path}.color"
        os.makedirs(os.path.dirname(color_file_path), exist_ok=True)
        color_file_handler = RotatingFileHandler(
            color_file_path,
            maxBytes=int(cfg.get("rotate_max_bytes", 1_048_576)),
            backupCount=int(cfg.get("rotate_backup_count", 3)),
        )
        color_file_handler.setFormatter(make_formatter(effective_cfg, colors=True))
        handlers.append(color_file_handler)

    if not handlers:
        fallback = logging.StreamHandler(sys.stderr)
        fallback.setFormatter(make_formatter(effective_cfg, colors=sys.stderr.isatty()))
        handlers.append(fallback)

    for handler in handlers:
        root.addHandler(handler)

    shared_processors = _build_shared_processors(effective_cfg)
    structlog.configure(
        processors=[
            *shared_processors,
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
