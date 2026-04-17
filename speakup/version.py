"""Package-aware version resolution.

Prefers git-derived versions from the speakup source tree itself, not the
caller\'s current working directory.
"""

from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import Optional

_cached_version: Optional[str] = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _normalize_version(value: str) -> str:
    value = value.strip()
    if not value:
        return "0.0.0+unknown"
    return value if value.startswith("v") else f"v{value}"


def get_version() -> str:
    """Get version from git tags using dunamai.

    Returns:
        Version string in format:
        - v1.0.0 (tagged, clean)
        - v1.0.0-5-ga1b2c3d (5 commits after v1.0.0)
        - v1.0.0-5-ga1b2c3d* (dirty working tree)
        - 0.0.0+unknown (not in git repo or error)
    """
    global _cached_version

    if _cached_version is not None:
        return _cached_version

    try:
        from dunamai import Version

        v = Version.from_git(path=_repo_root())
        result = f"v{v.base}"

        if v.commit:
            result += f"-{v.distance}-g{v.commit[:7]}"

        if v.dirty:
            result += "*"

        _cached_version = result
        return result
    except Exception:
        try:
            _cached_version = _normalize_version(package_version("speakup"))
            return _cached_version
        except (PackageNotFoundError, Exception):
            _cached_version = "0.0.0+unknown"
            return _cached_version
