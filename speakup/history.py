from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import runtime_temp_dir
from .models import NotifyRequest, NotifyResult


@dataclass(slots=True)
class HistoryEntry:
    """Single notification history entry."""
    id: int | None = None
    timestamp: float = 0.0
    agent: str = ""
    event: str = ""
    message: str = ""
    summary: str = ""
    audio_path: str | None = None
    status: str = ""
    backend: str = ""
    session_name: str | None = None
    session_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "agent": self.agent,
            "event": self.event,
            "message": self.message,
            "summary": self.summary,
            "audio_path": self.audio_path,
            "status": self.status,
            "backend": self.backend,
            "session_name": self.session_name,
            "session_key": self.session_key,
            "metadata": self.metadata,
        }


class NotificationHistory:
    """SQLite-backed notification history storage."""

    def __init__(self, db_path: Path | None = None, *, retention_days: int = 30):
        self._db_path = db_path or runtime_temp_dir() / "history.db"
        self._retention_days = retention_days
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
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    agent TEXT NOT NULL,
                    event TEXT NOT NULL,
                    message TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    audio_path TEXT,
                    status TEXT NOT NULL,
                    backend TEXT NOT NULL,
                    session_name TEXT,
                    session_key TEXT,
                    metadata TEXT
                )
                """
            )
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(notifications)").fetchall()
            }
            if "session_key" not in columns:
                conn.execute("ALTER TABLE notifications ADD COLUMN session_key TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_notifications_timestamp ON notifications(timestamp DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_notifications_agent ON notifications(agent)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_notifications_event ON notifications(event)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_notifications_agent_session_key_timestamp ON notifications(agent, session_key, timestamp DESC)"
            )

    def add(
        self,
        request: NotifyRequest,
        result: NotifyResult,
        *,
        timestamp: float | None = None,
    ) -> int:
        """Add a notification to history. Returns the inserted row ID."""
        ts = time.time() if timestamp is None else timestamp
        metadata = self._metadata_to_dict(request.metadata)
        if request.source_tool:
            metadata["source_tool"] = request.source_tool
        if result.audio_paths:
            metadata["audio_paths"] = [str(path) for path in result.audio_paths]
        metadata_json = json.dumps(metadata) if metadata else "{}"

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO notifications 
                (timestamp, agent, event, message, summary, audio_path, status, backend, session_name, session_key, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts,
                    request.agent,
                    result.state.value,
                    request.message,
                    result.summary,
                    str(result.audio_path) if result.audio_path else None,
                    result.status,
                    result.backend,
                    request.session_name,
                    request.session_key,
                    metadata_json,
                ),
            )
            return int(cursor.lastrowid)

    def get_recent(self, limit: int = 100, offset: int = 0) -> list[HistoryEntry]:
        """Get recent notifications, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, agent, event, message, summary, audio_path, status, backend, session_name, session_key, metadata
                FROM notifications
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

            return [self._row_to_entry(row) for row in rows]

    def get_by_agent(self, agent: str, limit: int = 100) -> list[HistoryEntry]:
        """Get notifications filtered by agent."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, agent, event, message, summary, audio_path, status, backend, session_name, session_key, metadata
                FROM notifications
                WHERE agent = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (agent, limit),
            ).fetchall()

            return [self._row_to_entry(row) for row in rows]

    def get_by_event(self, event: str, limit: int = 100) -> list[HistoryEntry]:
        """Get notifications filtered by event type."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, agent, event, message, summary, audio_path, status, backend, session_name, session_key, metadata
                FROM notifications
                WHERE event = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (event, limit),
            ).fetchall()

            return [self._row_to_entry(row) for row in rows]

    def search(self, query: str, limit: int = 100) -> list[HistoryEntry]:
        """Search notifications by message or summary text."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, agent, event, message, summary, audio_path, status, backend, session_name, session_key, metadata
                FROM notifications
                WHERE message LIKE ? OR summary LIKE ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (f"%{query}%", f"%{query}%", limit),
            ).fetchall()

            return [self._row_to_entry(row) for row in rows]

    def get_by_id(self, entry_id: int) -> HistoryEntry | None:
        """Get a specific notification by ID."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, timestamp, agent, event, message, summary, audio_path, status, backend, session_name, session_key, metadata
                FROM notifications
                WHERE id = ?
                """,
                (entry_id,),
            ).fetchone()

            return self._row_to_entry(row) if row else None

    def get_recent_for_session(self, agent: str, session_key: str, limit: int = 100) -> list[HistoryEntry]:
        """Get recent notifications for an exact agent/session key pair."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, agent, event, message, summary, audio_path, status, backend, session_name, session_key, metadata
                FROM notifications
                WHERE agent = ? AND session_key = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (agent, session_key, limit),
            ).fetchall()

            return [self._row_to_entry(row) for row in rows]

    def get_recent_replayable(self, limit: int = 100) -> list[HistoryEntry]:
        """Get recent replayable notifications across all agents."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, agent, event, message, summary, audio_path, status, backend, session_name, session_key, metadata
                FROM notifications
                WHERE status != 'skipped'
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

            return [self._row_to_entry(row) for row in rows]

    def get_recent_replayable_for_session(self, agent: str, session_key: str, limit: int = 100) -> list[HistoryEntry]:
        """Get recent replayable notifications for an exact agent/session key pair."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, agent, event, message, summary, audio_path, status, backend, session_name, session_key, metadata
                FROM notifications
                WHERE agent = ? AND session_key = ? AND status != 'skipped'
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (agent, session_key, limit),
            ).fetchall()

            return [self._row_to_entry(row) for row in rows]

    def count(self) -> int:
        """Get total number of notifications."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()
            return int(row[0]) if row else 0

    def cleanup_old(self) -> int:
        """Remove notifications older than retention period. Returns count deleted."""
        cutoff = time.time() - (self._retention_days * 86400)
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM notifications WHERE timestamp < ?",
                (cutoff,),
            )
            return cursor.rowcount

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about notification history."""
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
            
            by_agent = dict(
                conn.execute(
                    "SELECT agent, COUNT(*) as count FROM notifications GROUP BY agent ORDER BY count DESC"
                ).fetchall()
            )
            
            by_event = dict(
                conn.execute(
                    "SELECT event, COUNT(*) as count FROM notifications GROUP BY event ORDER BY count DESC"
                ).fetchall()
            )
            
            oldest = conn.execute(
                "SELECT MIN(timestamp) FROM notifications"
            ).fetchone()[0]
            
            newest = conn.execute(
                "SELECT MAX(timestamp) FROM notifications"
            ).fetchone()[0]

            return {
                "total": total,
                "by_agent": by_agent,
                "by_event": by_event,
                "oldest_timestamp": oldest,
                "newest_timestamp": newest,
            }

    def _row_to_entry(self, row: sqlite3.Row) -> HistoryEntry:
        """Convert a database row to HistoryEntry."""
        metadata = {}
        if row["metadata"]:
            try:
                metadata = self._metadata_to_dict(json.loads(row["metadata"]))
            except json.JSONDecodeError:
                pass

        return HistoryEntry(
            id=row["id"],
            timestamp=row["timestamp"],
            agent=row["agent"],
            event=row["event"],
            message=row["message"],
            summary=row["summary"],
            audio_path=row["audio_path"],
            status=row["status"],
            backend=row["backend"],
            session_name=row["session_name"],
            session_key=row["session_key"],
            metadata=metadata,
        )

    @staticmethod
    def _metadata_to_dict(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return dict(value)
        return {"_raw": value}
