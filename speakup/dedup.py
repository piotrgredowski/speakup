from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DedupDecision:
    skipped: bool
    reason: str | None = None


def should_skip_progress(
    message: str,
    cache_file: Path,
    window_seconds: int,
    *,
    mode: str = "duplicate",
) -> DedupDecision:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    message_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()

    now = int(time.time())
    if cache_file.exists():
        try:
            previous = json.loads(cache_file.read_text())
        except Exception:
            previous = {}
        elapsed = now - int(previous.get("timestamp", 0))
        within_window = elapsed <= window_seconds
        is_duplicate = previous.get("hash") == message_hash
        if within_window and is_duplicate and mode in {"duplicate", "duplicate_or_window"}:
            return DedupDecision(skipped=True, reason="duplicate")
        if within_window and mode in {"window", "duplicate_or_window"}:
            return DedupDecision(skipped=True, reason="window")

    cache_file.write_text(json.dumps({"hash": message_hash, "timestamp": now}))
    return DedupDecision(skipped=False)
