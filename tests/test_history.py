"""Tests for notification history functionality."""
from __future__ import annotations

from pathlib import Path

import pytest

from speakup.config import Config
from speakup.history import NotificationHistory
from speakup.models import MessageEvent, NotifyRequest, NotifyResult
from speakup.registry import AdapterRegistry
from speakup.service import NotifyService


class MockAudioPlayback:
    """Mock playback adapter for testing."""
    
    def play_file(self, path: Path) -> None:
        pass
    
    def play_files(self, paths: list[Path]) -> None:
        pass


class TestNotificationHistory:
    """Test NotificationHistory class."""

    def test_init_creates_database(self, tmp_path: Path) -> None:
        """Test that database is created on init."""
        db_path = tmp_path / "history.db"
        history = NotificationHistory(db_path)
        
        assert db_path.exists()
        assert history.count() == 0

    def test_add_and_retrieve_notification(self, tmp_path: Path) -> None:
        """Test adding and retrieving notifications."""
        db_path = tmp_path / "history.db"
        history = NotificationHistory(db_path)
        
        # Create test request and result
        request = NotifyRequest(
            message="Test message",
            event=MessageEvent.FINAL,
            agent="test_agent",
            session_name="test_session",
            session_key="session-key-1",
        )
        
        result = NotifyResult(
            status="ok",
            summary="Test summary",
            state=MessageEvent.FINAL,
            backend="test_backend",
            played=True,
        )
        
        # Add to history
        entry_id = history.add(request, result)
        assert entry_id > 0
        
        # Retrieve
        entries = history.get_recent(limit=10)
        assert len(entries) == 1
        
        entry = entries[0]
        assert entry.agent == "test_agent"
        assert entry.event == "final"
        assert entry.message == "Test message"
        assert entry.summary == "Test summary"
        assert entry.status == "ok"
        assert entry.backend == "test_backend"
        assert entry.session_name == "test_session"
        assert entry.session_key == "session-key-1"

    def test_filter_by_agent(self, tmp_path: Path) -> None:
        """Test filtering by agent."""
        db_path = tmp_path / "history.db"
        history = NotificationHistory(db_path)
        
        # Add notifications from different agents
        for agent in ["agent1", "agent2", "agent1"]:
            request = NotifyRequest(message="Test", event=MessageEvent.FINAL, agent=agent)
            result = NotifyResult(status="ok", summary="Summary", state=MessageEvent.FINAL, backend="test", played=True)
            history.add(request, result)
        
        # Filter by agent1
        entries = history.get_by_agent("agent1", limit=10)
        assert len(entries) == 2
        assert all(e.agent == "agent1" for e in entries)
        
        # Filter by agent2
        entries = history.get_by_agent("agent2", limit=10)
        assert len(entries) == 1
        assert entries[0].agent == "agent2"

    def test_get_recent_for_session(self, tmp_path: Path) -> None:
        db_path = tmp_path / "history.db"
        history = NotificationHistory(db_path)

        history.add(
            NotifyRequest(message="A", event=MessageEvent.FINAL, agent="pi", session_key="sess-1"),
            NotifyResult(status="ok", summary="A", state=MessageEvent.FINAL, backend="test", played=True),
            timestamp=1.0,
        )
        history.add(
            NotifyRequest(message="B", event=MessageEvent.FINAL, agent="pi", session_key="sess-2"),
            NotifyResult(status="ok", summary="B", state=MessageEvent.FINAL, backend="test", played=True),
            timestamp=2.0,
        )
        history.add(
            NotifyRequest(message="C", event=MessageEvent.FINAL, agent="pi", session_key="sess-1"),
            NotifyResult(status="ok", summary="C", state=MessageEvent.FINAL, backend="test", played=True),
            timestamp=3.0,
        )

        entries = history.get_recent_for_session("pi", "sess-1", limit=10)

        assert [entry.message for entry in entries] == ["C", "A"]

    def test_get_recent_replayable_skips_skipped_entries(self, tmp_path: Path) -> None:
        db_path = tmp_path / "history.db"
        history = NotificationHistory(db_path)

        history.add(
            NotifyRequest(message="A", event=MessageEvent.PROGRESS, agent="pi", session_key="sess-1"),
            NotifyResult(status="skipped", summary="", state=MessageEvent.PROGRESS, backend="none", played=False),
            timestamp=1.0,
        )
        history.add(
            NotifyRequest(message="B", event=MessageEvent.FINAL, agent="pi", session_key="sess-1"),
            NotifyResult(status="ok", summary="B", state=MessageEvent.FINAL, backend="test", played=True),
            timestamp=2.0,
        )
        history.add(
            NotifyRequest(message="C", event=MessageEvent.FINAL, agent="droid", session_key="sess-2"),
            NotifyResult(status="ok", summary="C", state=MessageEvent.FINAL, backend="test", played=True),
            timestamp=3.0,
        )

        entries = history.get_recent_replayable(limit=10)

        assert [entry.message for entry in entries] == ["C", "B"]

    def test_get_recent_replayable_for_session_skips_skipped_entries(self, tmp_path: Path) -> None:
        db_path = tmp_path / "history.db"
        history = NotificationHistory(db_path)

        history.add(
            NotifyRequest(message="A", event=MessageEvent.PROGRESS, agent="pi", session_key="sess-1"),
            NotifyResult(status="skipped", summary="", state=MessageEvent.PROGRESS, backend="none", played=False),
            timestamp=1.0,
        )
        history.add(
            NotifyRequest(message="B", event=MessageEvent.FINAL, agent="pi", session_key="sess-1"),
            NotifyResult(status="ok", summary="B", state=MessageEvent.FINAL, backend="test", played=True),
            timestamp=2.0,
        )

        entries = history.get_recent_replayable_for_session("pi", "sess-1", limit=10)

        assert [entry.message for entry in entries] == ["B"]

    def test_init_adds_session_key_column_to_existing_database(self, tmp_path: Path) -> None:
        db_path = tmp_path / "history.db"
        history = NotificationHistory(db_path)
        with history._connect() as conn:
            conn.execute("DROP TABLE notifications")
            conn.execute(
                """
                CREATE TABLE notifications (
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
                    metadata TEXT
                )
                """
            )

        migrated = NotificationHistory(db_path)
        with migrated._connect() as conn:
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(notifications)").fetchall()
            }

        assert "session_key" in columns

    def test_filter_by_event(self, tmp_path: Path) -> None:
        """Test filtering by event type."""
        db_path = tmp_path / "history.db"
        history = NotificationHistory(db_path)
        
        # Add notifications with different events
        for event in [MessageEvent.FINAL, MessageEvent.ERROR, MessageEvent.PROGRESS]:
            request = NotifyRequest(message="Test", event=event, agent="test")
            result = NotifyResult(status="ok", summary="Summary", state=event, backend="test", played=True)
            history.add(request, result)
        
        # Filter by final
        entries = history.get_by_event("final", limit=10)
        assert len(entries) == 1
        assert entries[0].event == "final"
        
        # Filter by error
        entries = history.get_by_event("error", limit=10)
        assert len(entries) == 1
        assert entries[0].event == "error"

    def test_search(self, tmp_path: Path) -> None:
        """Test search functionality."""
        db_path = tmp_path / "history.db"
        history = NotificationHistory(db_path)
        
        # Add notifications with different content
        request1 = NotifyRequest(message="Important update", event=MessageEvent.FINAL, agent="test")
        result1 = NotifyResult(status="ok", summary="Summary 1", state=MessageEvent.FINAL, backend="test", played=True)
        history.add(request1, result1)
        
        request2 = NotifyRequest(message="Regular update", event=MessageEvent.PROGRESS, agent="test")
        result2 = NotifyResult(status="ok", summary="Summary 2", state=MessageEvent.PROGRESS, backend="test", played=True)
        history.add(request2, result2)
        
        # Search for "Important"
        entries = history.search("Important", limit=10)
        assert len(entries) == 1
        assert "Important" in entries[0].message
        
        # Search for "Summary"
        entries = history.search("Summary", limit=10)
        assert len(entries) == 2

    def test_get_by_id(self, tmp_path: Path) -> None:
        """Test retrieving by ID."""
        db_path = tmp_path / "history.db"
        history = NotificationHistory(db_path)
        
        request = NotifyRequest(message="Test", event=MessageEvent.FINAL, agent="test")
        result = NotifyResult(status="ok", summary="Summary", state=MessageEvent.FINAL, backend="test", played=True)
        entry_id = history.add(request, result)
        
        # Retrieve by ID
        entry = history.get_by_id(entry_id)
        assert entry is not None
        assert entry.id == entry_id
        assert entry.message == "Test"
        
        # Non-existent ID
        entry = history.get_by_id(9999)
        assert entry is None

    def test_count(self, tmp_path: Path) -> None:
        """Test count functionality."""
        db_path = tmp_path / "history.db"
        history = NotificationHistory(db_path)
        
        assert history.count() == 0
        
        # Add notifications
        for i in range(5):
            request = NotifyRequest(message=f"Test {i}", event=MessageEvent.FINAL, agent="test")
            result = NotifyResult(status="ok", summary="Summary", state=MessageEvent.FINAL, backend="test", played=True)
            history.add(request, result)
        
        assert history.count() == 5

    def test_get_stats(self, tmp_path: Path) -> None:
        """Test statistics functionality."""
        db_path = tmp_path / "history.db"
        history = NotificationHistory(db_path)
        
        # Add notifications
        for agent in ["agent1", "agent1", "agent2"]:
            for event in ["final", "error"]:
                request = NotifyRequest(message="Test", event=MessageEvent(event), agent=agent)
                result = NotifyResult(status="ok", summary="Summary", state=MessageEvent(event), backend="test", played=True)
                history.add(request, result)
        
        stats = history.get_stats()
        assert stats["total"] == 6
        assert stats["by_agent"]["agent1"] == 4
        assert stats["by_agent"]["agent2"] == 2
        assert stats["by_event"]["final"] == 3
        assert stats["by_event"]["error"] == 3
        assert stats["oldest_timestamp"] is not None
        assert stats["newest_timestamp"] is not None

    def test_cleanup_old(self, tmp_path: Path) -> None:
        """Test cleanup of old notifications."""
        db_path = tmp_path / "history.db"
        history = NotificationHistory(db_path, retention_days=1)
        
        # Add a notification
        request = NotifyRequest(message="Test", event=MessageEvent.FINAL, agent="test")
        result = NotifyResult(status="ok", summary="Summary", state=MessageEvent.FINAL, backend="test")
        history.add(request, result, timestamp=9999999999.0)  # Far future
        
        # Add an old notification
        old_request = NotifyRequest(message="Old", event=MessageEvent.FINAL, agent="test")
        old_result = NotifyResult(status="ok", summary="Old", state=MessageEvent.FINAL, backend="test")
        history.add(old_request, old_result, timestamp=0.0)  # Far past
        
        assert history.count() == 2
        
        # Cleanup
        deleted = history.cleanup_old()
        assert deleted >= 1
        assert history.count() == 1


class TestNotifyServiceWithHistory:
    """Test NotifyService integration with history."""

    def test_service_saves_to_history(self, tmp_path: Path) -> None:
        """Test that NotifyService saves to history."""
        # Create minimal config
        config = Config({
            "events": {"speak_on_final": False},  # Disable audio
            "tts": {"play_audio": False},
        })
        
        # Create history
        db_path = tmp_path / "history.db"
        history = NotificationHistory(db_path)
        
        # Create registry with mock playback
        registry = AdapterRegistry()
        playback = MockAudioPlayback()
        registry.set_playback(playback)
        
        # Create service with history
        service = NotifyService(config, registry=registry, history=history)
        
        # Send notification
        request = NotifyRequest(
            message="Test notification for history",
            event=MessageEvent.FINAL,
            agent="test_agent",
        )
        
        service.notify(request)
        
        # Note: Result status might vary based on TTS availability
        # Just check that history was saved
        entries = history.get_recent(limit=10)
        assert len(entries) >= 1
        
        # Find our entry
        found = False
        for entry in entries:
            if entry.agent == "test_agent" and "Test notification" in entry.message:
                found = True
                assert entry.event == "final"
                break
        
        assert found, "History entry not found"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
