"""Integration tests for Gemini TTS using real API.

These tests require the GOOGLE_API_KEY environment variable to be set.
They can be run with: pytest -m integration_gemini

To run only integration tests:
    pytest tests/test_integration_gemini.py -v

To skip if API key not available:
    pytest tests/test_integration_gemini.py -v -m "integration_gemini or skip_if_no_api_key"
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from .conftest import run_cli


# Skip all tests in this module if GOOGLE_API_KEY is not set
pytestmark = pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="GOOGLE_API_KEY environment variable not set",
)


@pytest.fixture
def config_with_gemini(tmp_path: Path) -> Path:
    """Create a config that uses Gemini TTS."""
    config = {
        "privacy": {"mode": "prefer_local", "allow_remote_fallback": True},
        "events": {
            "speak_on_final": True,
            "speak_on_error": True,
            "speak_on_needs_input": True,
            "speak_on_progress": True,
        },
        "event_sounds": {"enabled": False, "files": {}},
        "summarization": {"max_chars": 220, "provider_order": ["rule_based"]},
        "tts": {
            "provider_order": ["gemini"],
            "voice": "default",
            "speed": 1.0,
            "audio_format": "mp3",
            "save_audio_dir": str(tmp_path / "audio"),
            "play_audio": True,
        },
        "dedup": {"enabled": False, "window_seconds": 30, "cache_file": str(tmp_path / "dedup.json")},
        "providers": {
            "gemini": {
                "api_key_env": "GOOGLE_API_KEY",
                "model": "gemini-2.5-flash-preview-tts",
                "voice": "Kore",
            },
        },
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    return path


@pytest.mark.integration_gemini
def test_gemini_real_api_given_final_event_then_synthesizes_audio(config_with_gemini: Path, tmp_path: Path):
    """Test real Gemini TTS API call with --tts-provider gemini flag."""
    audio_dir = tmp_path / "audio"

    result = run_cli(
        [
            "--config",
            str(config_with_gemini),
            "--session-name",
            "Droid - let-me-know-agent.",
            "--message",
            "Done. Removed the backward compatibility import and cleaned up unused imports. All 55 tests pass.",
            "--event",
            "final",
            "--fail-fast",
            "--tts-provider",
            "gemini",
        ],
        env=os.environ,
    )

    # Print output for debugging
    print(f"\nSTDOUT: {result.stdout}")
    print(f"\nSTDERR: {result.stderr}")

    assert result.returncode == 0, f"CLI failed: {result.stderr}"

    # Parse JSON output
    output = json.loads(result.stdout)

    assert output["status"] == "ok", f"Expected status 'ok', got: {output}"
    assert output["backend"] == "gemini", f"Expected backend 'gemini', got: {output['backend']}"
    assert output["played"] is True, f"Expected played=True, got: {output['played']}"
    assert output["audio_path"] is not None, f"Expected audio_path to be set, got: {output}"

    # Verify audio file was created
    audio_path = Path(output["audio_path"])
    assert audio_path.exists(), f"Audio file not found: {audio_path}"
    assert audio_path.suffix == ".mp3", f"Expected .mp3 extension, got: {audio_path.suffix}"
    assert audio_path.stat().st_size > 0, f"Audio file is empty: {audio_path}"

    print(f"\nAudio file: {audio_path}")
    print(f"Audio size: {audio_path.stat().st_size} bytes")


@pytest.mark.integration_gemini
def test_gemini_real_api_given_custom_voice_then_synthesizes(tmp_path: Path):
    """Test Gemini TTS with custom voice (Charon)."""
    config_path = tmp_path / "config.json"
    config = {
        "privacy": {"mode": "prefer_local", "allow_remote_fallback": True},
        "events": {"speak_on_final": True},
        "event_sounds": {"enabled": False, "files": {}},
        "summarization": {"max_chars": 220, "provider_order": ["rule_based"]},
        "tts": {
            "provider_order": ["gemini"],
            "voice": "Charon",
            "speed": 1.0,
            "audio_format": "mp3",
            "save_audio_dir": str(tmp_path / "audio"),
            "play_audio": True,
        },
        "dedup": {"enabled": False},
        "providers": {
            "gemini": {
                "api_key_env": "GOOGLE_API_KEY",
                "model": "gemini-2.5-flash-preview-tts",
                "voice": "Charon",
            },
        },
    }
    config_path.write_text(json.dumps(config))

    result = run_cli(
        [
            "--config",
            str(config_path),
            "--message",
            "Testing Gemini TTS with Charon voice.",
            "--event",
            "final",
            "--tts-provider",
            "gemini",
        ],
        env=os.environ,
    )

    assert result.returncode == 0, f"CLI failed: {result.stderr}"

    output = json.loads(result.stdout)
    assert output["backend"] == "gemini"
    assert output["status"] == "ok"


@pytest.mark.integration_gemini
def test_gemini_real_api_given_no_play_then_saves_audio_without_playback(tmp_path: Path):
    """Test Gemini TTS with --no-play flag."""
    config_path = tmp_path / "config.json"
    config = {
        "privacy": {"mode": "prefer_local", "allow_remote_fallback": True},
        "events": {"speak_on_final": True},
        "event_sounds": {"enabled": False, "files": {}},
        "summarization": {"max_chars": 220, "provider_order": ["rule_based"]},
        "tts": {
            "provider_order": ["gemini"],
            "voice": "Kore",
            "speed": 1.0,
            "audio_format": "mp3",
            "save_audio_dir": str(tmp_path / "audio"),
            "play_audio": True,
        },
        "dedup": {"enabled": False},
        "providers": {
            "gemini": {
                "api_key_env": "GOOGLE_API_KEY",
                "model": "gemini-2.5-flash-preview-tts",
                "voice": "Kore",
            },
        },
    }
    config_path.write_text(json.dumps(config))

    result = run_cli(
        [
            "--config",
            str(config_path),
            "--message",
            "Testing Gemini TTS without playback.",
            "--event",
            "final",
            "--tts-provider",
            "gemini",
            "--no-play",
            "--fail-fast",
        ],
        env=os.environ,
    )

    # Print output for debugging
    print(f"\nSTDOUT: {result.stdout}")
    print(f"\nSTDERR: {result.stderr}")

    assert result.returncode == 0, f"CLI failed: {result.stderr}"

    output = json.loads(result.stdout)
    assert output["backend"] == "gemini", f"Expected backend='gemini', got: {output}"
    assert output["played"] is False, "Expected played=False with --no-play"
    assert output["audio_path"] is not None, "Audio should still be saved"


@pytest.mark.integration_gemini
def test_gemini_real_api_given_invalid_api_key_then_fails_gracefully(tmp_path: Path):
    """Test Gemini TTS with invalid API key returns proper error."""
    config_path = tmp_path / "config.json"
    config = {
        "privacy": {"mode": "prefer_local", "allow_remote_fallback": True},
        "events": {"speak_on_final": True},
        "event_sounds": {"enabled": False, "files": {}},
        "summarization": {"max_chars": 220, "provider_order": ["rule_based"]},
        "tts": {
            "provider_order": ["gemini"],
            "voice": "Kore",
            "speed": 1.0,
            "audio_format": "mp3",
            "save_audio_dir": str(tmp_path / "audio"),
            "play_audio": True,
        },
        "dedup": {"enabled": False},
        "providers": {
            "gemini": {
                "api_key_env": "INVALID_GOOGLE_API_KEY_FOR_TEST",
                "model": "gemini-2.5-flash-preview-tts",
                "voice": "Kore",
            },
        },
    }
    config_path.write_text(json.dumps(config))

    # Create a fake env with invalid key
    env = dict(os.environ)
    env["INVALID_GOOGLE_API_KEY_FOR_TEST"] = "fake-invalid-key-12345"

    result = run_cli(
        [
            "--config",
            str(config_path),
            "--message",
            "This should fail.",
            "--event",
            "final",
            "--tts-provider",
            "gemini",
            "--fail-fast",
        ],
        env=env,
    )

    # Should fail with non-zero exit code due to --fail-fast
    assert result.returncode != 0
    assert "Gemini" in result.stderr or "API" in result.stderr
