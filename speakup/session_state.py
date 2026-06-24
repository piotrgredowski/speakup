from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from .config import runtime_temp_dir


@dataclass(slots=True)
class SessionState:
    agent: str
    session_key: str
    session_name: str | None
    spoken_language: str | None
    created_at: float
    updated_at: float


class SessionStateStore:
    """SQLite-backed runtime state for exact agent sessions."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or runtime_temp_dir() / "session_state.db"
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
                CREATE TABLE IF NOT EXISTS session_state (
                    agent TEXT NOT NULL,
                    session_key TEXT NOT NULL,
                    session_name TEXT,
                    spoken_language TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (agent, session_key)
                )
                """
            )

    def get(self, *, agent: str, session_key: str) -> SessionState | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT agent, session_key, session_name, spoken_language, created_at, updated_at
                FROM session_state
                WHERE agent = ? AND session_key = ?
                """,
                (agent, session_key),
            ).fetchone()
        if row is None:
            return None
        return SessionState(
            agent=row["agent"],
            session_key=row["session_key"],
            session_name=row["session_name"],
            spoken_language=row["spoken_language"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def upsert(
        self,
        *,
        agent: str,
        session_key: str,
        session_name: str | None,
        spoken_language: str | None,
    ) -> SessionState:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO session_state (agent, session_key, session_name, spoken_language, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent, session_key) DO UPDATE SET
                    session_name = COALESCE(excluded.session_name, session_state.session_name),
                    spoken_language = COALESCE(excluded.spoken_language, session_state.spoken_language),
                    updated_at = excluded.updated_at
                """,
                (agent, session_key, session_name, spoken_language, now, now),
            )
        state = self.get(agent=agent, session_key=session_key)
        if state is None:
            raise RuntimeError("session state upsert did not persist")
        return state
