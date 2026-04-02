from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path


def should_skip_progress(message: str, cache_file: Path, window_seconds: int) -> bool:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    message_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()

    now = int(time.time())
    if cache_file.exists():
        try:
            previous = json.loads(cache_file.read_text())
        except Exception:
            previous = {}
        if previous.get("hash") == message_hash and now - int(previous.get("timestamp", 0)) <= window_seconds:
            return True

    cache_file.write_text(json.dumps({"hash": message_hash, "timestamp": now}))
    return False
