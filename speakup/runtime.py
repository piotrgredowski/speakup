from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import runtime_temp_dir


@dataclass(slots=True)
class ProviderProcess:
    provider: str
    pid: int
    base_url: str
    host: str
    port: int
    payload: dict[str, Any]
    started_at: float
    last_seen_at: float


class RuntimeStateStore:
    """SQLite-backed runtime state for long-lived local provider processes."""

    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or runtime_temp_dir() / "runtime.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_processes (
                    provider TEXT PRIMARY KEY,
                    pid INTEGER NOT NULL,
                    base_url TEXT NOT NULL,
                    host TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    last_seen_at REAL NOT NULL
                )
                """
            )

    def get_provider_process(self, provider: str) -> ProviderProcess | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT provider, pid, base_url, host, port, payload, started_at, last_seen_at
                FROM provider_processes
                WHERE provider = ?
                """,
                (provider,),
            ).fetchone()
        return self._row_to_process(row) if row else None

    def save_provider_process(
        self,
        *,
        provider: str,
        pid: int,
        base_url: str,
        host: str,
        port: int,
        payload: dict[str, Any] | None = None,
        timestamp: float | None = None,
    ) -> None:
        now = time.time() if timestamp is None else timestamp
        payload_json = json.dumps(payload or {}, sort_keys=True)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO provider_processes
                (provider, pid, base_url, host, port, payload, started_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider) DO UPDATE SET
                    pid = excluded.pid,
                    base_url = excluded.base_url,
                    host = excluded.host,
                    port = excluded.port,
                    payload = excluded.payload,
                    started_at = excluded.started_at,
                    last_seen_at = excluded.last_seen_at
                """,
                (provider, pid, base_url, host, port, payload_json, now, now),
            )

    def mark_seen(self, provider: str, *, timestamp: float | None = None) -> None:
        now = time.time() if timestamp is None else timestamp
        with self._connect() as conn:
            conn.execute(
                "UPDATE provider_processes SET last_seen_at = ? WHERE provider = ?",
                (now, provider),
            )

    def delete_provider_process(self, provider: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM provider_processes WHERE provider = ?", (provider,))

    @staticmethod
    def pid_is_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def delete_provider_process_if_pid(self, provider: str, pid: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM provider_processes WHERE provider = ? AND pid = ?",
                (provider, pid),
            )

    @staticmethod
    def _row_to_process(row: sqlite3.Row) -> ProviderProcess:
        try:
            payload = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        return ProviderProcess(
            provider=str(row["provider"]),
            pid=int(row["pid"]),
            base_url=str(row["base_url"]),
            host=str(row["host"]),
            port=int(row["port"]),
            payload=payload,
            started_at=float(row["started_at"]),
            last_seen_at=float(row["last_seen_at"]),
        )
