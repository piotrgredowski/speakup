from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .session_naming import normalize_session_name_candidate


@dataclass(frozen=True)
class SpokenContext:
    kind: str
    name: str


def find_project_root(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    try:
        current = Path(path).expanduser().resolve()
    except OSError:
        current = Path(path).expanduser()
    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current if current.exists() else None


def project_config_path(path: str | Path | None) -> Path | None:
    root = find_project_root(path)
    return root / ".speakup.jsonc" if root is not None else None


def verbalize_project_name(value: object) -> str | None:
    candidate = normalize_session_name_candidate(value)
    if not candidate:
        return None

    candidate = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", candidate)
    candidate = re.sub(r"[._-]+", " ", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip()
    return candidate or None


def resolve_spoken_context(
    *,
    cwd: str | Path | None,
    session_name: str | None,
    config: dict[str, object] | None,
) -> SpokenContext | None:
    cfg = config if isinstance(config, dict) else {}
    if not bool(cfg.get("enabled", True)):
        return None

    source = cfg.get("source", "repository")
    if source not in {"session", "repository", "directory"}:
        source = "session"

    override = verbalize_project_name(cfg.get("spoken_name"))
    if source == "session":
        name = override or normalize_session_name_candidate(session_name)
        return SpokenContext("session", name) if name else None

    root = find_project_root(cwd)
    if source == "repository":
        name = override or verbalize_project_name(root.name if root else None)
        if name:
            return SpokenContext("repository", name)
        fallback = normalize_session_name_candidate(session_name)
        return SpokenContext("session", fallback) if fallback else None

    directory = Path(cwd).expanduser() if cwd else root
    name = override or verbalize_project_name(directory.name if directory else None)
    if name:
        return SpokenContext("directory", name)
    fallback = normalize_session_name_candidate(session_name)
    return SpokenContext("session", fallback) if fallback else None
