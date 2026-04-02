from __future__ import annotations

import json
import os
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

from .base import PlaybackAdapter
from ..config import runtime_temp_dir
from ..errors import AdapterError


@dataclass(slots=True)
class _QueuedJob:
    job_id: int
    paths: list[Path]


class SQLiteQueuedPlayback(PlaybackAdapter):
    """Cross-process queue using SQLite for sequential audio playback."""

    name: ClassVar[str] = "sqlite_queue"
    _LOCK_NAME: ClassVar[str] = "playback"

    def __init__(
        self,
        inner: PlaybackAdapter,
        db_path: Path | None = None,
        *,
        busy_timeout_seconds: float = 30.0,
        stale_processing_timeout_seconds: float = 300.0,
    ):
        self._inner = inner
        self._db_path = db_path or runtime_temp_dir() / "playback_queue.db"
        self._busy_timeout_seconds = busy_timeout_seconds
        self._stale_processing_timeout_seconds = stale_processing_timeout_seconds
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=self._busy_timeout_seconds)
        conn.execute(f"PRAGMA busy_timeout = {int(self._busy_timeout_seconds * 1000)}")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending',
                    created_at REAL NOT NULL,
                    claimed_at REAL,
                    finished_at REAL,
                    last_error TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS worker_lock (
                    name TEXT PRIMARY KEY,
                    owner_id TEXT,
                    owner_pid INTEGER,
                    claimed_at REAL
                )
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO worker_lock (name, owner_id, owner_pid, claimed_at) VALUES (?, NULL, NULL, NULL)",
                (self._LOCK_NAME,),
            )

    def play_file(self, path: Path) -> None:
        self.play_files([path])

    def play_files(self, paths: Sequence[Path]) -> None:
        normalized_paths = [Path(path) for path in paths]
        if not normalized_paths:
            return

        job_id = self._enqueue_job(normalized_paths)
        playback_error = self._drain_queue(target_job_id=job_id)
        if playback_error is not None:
            raise AdapterError(playback_error)

    def _enqueue_job(self, paths: Sequence[Path]) -> int:
        payload = json.dumps([str(path) for path in paths])
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO jobs (payload, state, created_at) VALUES (?, 'pending', ?)",
                (payload, time.time()),
            )
            return int(cursor.lastrowid)

    def _drain_queue(self, *, target_job_id: int | None = None) -> str | None:
        owner_id = uuid4().hex
        if not self._try_acquire_worker(owner_id):
            return None

        target_error: str | None = None
        try:
            while True:
                job = self._claim_next_job()
                if job is None:
                    break

                try:
                    self._inner.play_files(job.paths)
                except AdapterError as exc:
                    self._mark_job_failed(job.job_id, str(exc))
                    if job.job_id == target_job_id:
                        target_error = str(exc)
                    continue
                except Exception as exc:
                    self._mark_job_failed(job.job_id, str(exc))
                    if job.job_id == target_job_id:
                        target_error = str(exc)
                    continue

                self._mark_job_done(job.job_id)
        finally:
            self._release_worker(owner_id)

        return target_error

    def _try_acquire_worker(self, owner_id: str) -> bool:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT owner_id, owner_pid FROM worker_lock WHERE name = ?",
                    (self._LOCK_NAME,),
                ).fetchone()
                owner_pid = row[1] if row is not None else None
                if row is not None and row[0] and self._pid_is_alive(owner_pid):
                    conn.rollback()
                    return False

                conn.execute(
                    "UPDATE worker_lock SET owner_id = ?, owner_pid = ?, claimed_at = ? WHERE name = ?",
                    (owner_id, os.getpid(), time.time(), self._LOCK_NAME),
                )
                conn.commit()
                return True
            except Exception:
                conn.rollback()
                raise

    def _release_worker(self, owner_id: str) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    UPDATE worker_lock
                    SET owner_id = NULL, owner_pid = NULL, claimed_at = NULL
                    WHERE name = ? AND owner_id = ?
                    """,
                    (self._LOCK_NAME, owner_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def _claim_next_job(self) -> _QueuedJob | None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._recover_stale_jobs(conn)
                row = conn.execute(
                    "SELECT id, payload FROM jobs WHERE state = 'pending' ORDER BY id LIMIT 1"
                ).fetchone()
                if row is None:
                    conn.commit()
                    return None

                job_id = int(row[0])
                conn.execute(
                    "UPDATE jobs SET state = 'processing', claimed_at = ?, last_error = NULL WHERE id = ?",
                    (time.time(), job_id),
                )
                conn.commit()
                return _QueuedJob(job_id=job_id, paths=[Path(value) for value in json.loads(row[1])])
            except Exception:
                conn.rollback()
                raise

    def _mark_job_done(self, job_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET state = 'done', finished_at = ?, last_error = NULL WHERE id = ?",
                (time.time(), job_id),
            )

    def _mark_job_failed(self, job_id: int, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET state = 'failed', finished_at = ?, last_error = ? WHERE id = ?",
                (time.time(), error, job_id),
            )

    def _recover_stale_jobs(self, conn: sqlite3.Connection) -> None:
        stale_before = time.time() - self._stale_processing_timeout_seconds
        conn.execute(
            """
            UPDATE jobs
            SET state = 'pending', claimed_at = NULL
            WHERE state = 'processing' AND claimed_at IS NOT NULL AND claimed_at < ?
            """,
            (stale_before,),
        )

    @staticmethod
    def _pid_is_alive(pid: int | None) -> bool:
        if pid is None:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
