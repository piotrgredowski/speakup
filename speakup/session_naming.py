from __future__ import annotations

import re

from .models import NotifyRequest

_HEX_LIKE_NAME_PATTERN = re.compile(r"[0-9a-fA-F]{7,40}")


def _is_random_hex_like_name(value: object) -> bool:
    if not isinstance(value, str):
        return False

    stripped = value.strip()
    if not stripped:
        return False

    normalized = stripped.replace("-", "").replace("_", "").replace(" ", "")
    return bool(_HEX_LIKE_NAME_PATTERN.fullmatch(normalized))


def normalize_session_name_candidate(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    stripped = value.strip()
    if not stripped or stripped.casefold() == "new session" or _is_random_hex_like_name(stripped):
        return None

    return stripped


def resolve_session_name(request: NotifyRequest, config: dict[str, object] | None = None) -> str | None:
    explicit_name = normalize_session_name_candidate(request.session_name)
    if explicit_name:
        return explicit_name

    if isinstance(config, dict) and not bool(config.get("enabled", True)):
        return None

    return None
