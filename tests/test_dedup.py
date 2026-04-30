from __future__ import annotations

import json

from speakup.dedup import should_skip_progress


def test_should_skip_progress_given_duplicate_mode_then_only_skips_duplicate(tmp_path) -> None:
    cache_file = tmp_path / "dedup.json"

    first = should_skip_progress("Indexing files", cache_file, 30, mode="duplicate")
    second = should_skip_progress("Indexing files", cache_file, 30, mode="duplicate")
    third = should_skip_progress("Running tests", cache_file, 30, mode="duplicate")

    assert first.skipped is False
    assert second.skipped is True
    assert second.reason == "duplicate"
    assert third.skipped is False


def test_should_skip_progress_given_window_mode_then_skips_any_fast_message(tmp_path) -> None:
    cache_file = tmp_path / "dedup.json"

    first = should_skip_progress("Indexing files", cache_file, 30, mode="window")
    second = should_skip_progress("Running tests", cache_file, 30, mode="window")

    assert first.skipped is False
    assert second.skipped is True
    assert second.reason == "window"


def test_should_skip_progress_given_duplicate_or_window_then_reports_duplicate_first(tmp_path) -> None:
    cache_file = tmp_path / "dedup.json"

    should_skip_progress("Indexing files", cache_file, 30, mode="duplicate_or_window")
    duplicate = should_skip_progress("Indexing files", cache_file, 30, mode="duplicate_or_window")

    assert duplicate.skipped is True
    assert duplicate.reason == "duplicate"


def test_should_skip_progress_given_stale_cache_then_replaces_timestamp(tmp_path, monkeypatch) -> None:
    cache_file = tmp_path / "dedup.json"
    cache_file.write_text(json.dumps({"hash": "old", "timestamp": 100}))
    monkeypatch.setattr("speakup.dedup.time.time", lambda: 200)

    decision = should_skip_progress("Running tests", cache_file, 30, mode="window")

    assert decision.skipped is False
    assert json.loads(cache_file.read_text())["timestamp"] == 200
