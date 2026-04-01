"""Git-based versioning using dunamai."""

from typing import Optional

_cached_version: Optional[str] = None


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

        v = Version.from_git()
        result = f"v{v.base}"

        if v.commit:
            result += f"-{v.distance}-g{v.commit[:7]}"

        if v.dirty:
            result += "*"

        _cached_version = result
        return result
    except Exception:
        _cached_version = "0.0.0+unknown"
        return _cached_version
