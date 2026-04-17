from __future__ import annotations

import hashlib
import re

from .models import NotifyRequest

_HEX_LIKE_NAME_PATTERN = re.compile(r"[0-9a-fA-F]{7,40}")

SESSION_NAME_ADJECTIVES = (
    "Agile",
    "Bright",
    "Calm",
    "Clever",
    "Curious",
    "Daring",
    "Eager",
    "Gentle",
    "Jolly",
    "Kind",
    "Lively",
    "Nimble",
    "Quick",
    "Sharp",
    "Steady",
    "Wise",
)

POLISH_GIVEN_NAMES = (
    "Ania",
    "Bartek",
    "Celina",
    "Dawid",
    "Ewa",
    "Filip",
    "Gosia",
    "Hubert",
    "Iga",
    "Jan",
    "Kasia",
    "Lena",
    "Marek",
    "Natalia",
    "Olek",
    "Piotr",
    "Szymon",
    "Tomek",
    "Wiktoria",
    "Zosia",
)


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


def generate_session_name(seed: str | None) -> str | None:
    if not isinstance(seed, str):
        return None

    value = seed.strip()
    if not value:
        return None

    digest = hashlib.sha256(value.encode("utf-8")).digest()
    adjective = SESSION_NAME_ADJECTIVES[int.from_bytes(digest[:2], "big") % len(SESSION_NAME_ADJECTIVES)]
    name = POLISH_GIVEN_NAMES[int.from_bytes(digest[2:4], "big") % len(POLISH_GIVEN_NAMES)]
    return f"{adjective} {name}"


def _normalize_seed(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None

    stripped = value.strip()
    return stripped or None


def resolve_session_name(request: NotifyRequest, config: dict[str, object] | None = None) -> str | None:
    explicit_name = normalize_session_name_candidate(request.session_name)
    if explicit_name:
        return explicit_name

    if isinstance(config, dict) and not bool(config.get("enabled", True)):
        return None

    return generate_session_name(_normalize_seed(request.conversation_id) or _normalize_seed(request.session_id))
