from __future__ import annotations

from types import SimpleNamespace

from speakup import process_watchdog


def test_process_watchdog_given_idle_record_then_terminates_pid(monkeypatch) -> None:
    killed: list[tuple[int, int]] = []
    deleted: list[tuple[str, int]] = []

    class _Store:
        def get_provider_process(self, provider: str):
            return SimpleNamespace(pid=123, last_seen_at=10.0, payload={"command": ["python", "-m", "server"]})

        def pid_is_alive(self, pid: int) -> bool:
            return True

        def delete_provider_process_if_pid(self, provider: str, pid: int) -> None:
            deleted.append((provider, pid))

    monkeypatch.setattr("speakup.process_watchdog.RuntimeStateStore", lambda: _Store())
    monkeypatch.setattr("speakup.process_watchdog.time.sleep", lambda seconds: None)
    monkeypatch.setattr("speakup.process_watchdog.time.time", lambda: 700.0)
    monkeypatch.setattr("speakup.process_watchdog._current_command", lambda pid: "python -m server")
    monkeypatch.setattr("speakup.process_watchdog.os.kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(
        "speakup.process_watchdog.argparse.ArgumentParser.parse_args",
        lambda self: SimpleNamespace(provider="piper", pid=123, idle_timeout_seconds=600.0, check_interval_seconds=1.0),
    )

    process_watchdog.main()

    assert killed == [(123, process_watchdog.signal.SIGTERM)]
    assert deleted == [("piper", 123)]


def test_process_watchdog_given_same_pid_with_different_command_then_deletes_without_kill(monkeypatch) -> None:
    killed: list[tuple[int, int]] = []
    deleted: list[tuple[str, int]] = []

    class _Store:
        def get_provider_process(self, provider: str):
            return SimpleNamespace(pid=123, last_seen_at=10.0, payload={"command": ["python", "-m", "server"]})

        def pid_is_alive(self, pid: int) -> bool:
            return True

        def delete_provider_process_if_pid(self, provider: str, pid: int) -> None:
            deleted.append((provider, pid))

    monkeypatch.setattr("speakup.process_watchdog.RuntimeStateStore", lambda: _Store())
    monkeypatch.setattr("speakup.process_watchdog.time.sleep", lambda seconds: None)
    monkeypatch.setattr("speakup.process_watchdog._current_command", lambda pid: "python other.py")
    monkeypatch.setattr("speakup.process_watchdog.os.kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(
        "speakup.process_watchdog.argparse.ArgumentParser.parse_args",
        lambda self: SimpleNamespace(provider="piper", pid=123, idle_timeout_seconds=600.0, check_interval_seconds=1.0),
    )

    process_watchdog.main()

    assert killed == []
    assert deleted == [("piper", 123)]


def test_process_watchdog_given_replaced_process_record_then_exits_without_kill(monkeypatch) -> None:
    killed: list[tuple[int, int]] = []

    class _Store:
        def get_provider_process(self, provider: str):
            return SimpleNamespace(pid=456, last_seen_at=10.0, payload={"command": ["python", "-m", "server"]})

    monkeypatch.setattr("speakup.process_watchdog.RuntimeStateStore", lambda: _Store())
    monkeypatch.setattr("speakup.process_watchdog.time.sleep", lambda seconds: None)
    monkeypatch.setattr("speakup.process_watchdog.os.kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(
        "speakup.process_watchdog.argparse.ArgumentParser.parse_args",
        lambda self: SimpleNamespace(provider="piper", pid=123, idle_timeout_seconds=600.0, check_interval_seconds=1.0),
    )

    process_watchdog.main()

    assert killed == []
