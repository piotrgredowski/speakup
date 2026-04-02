"""Integration tests for Cerebras summarizer using real API.

These tests require the CEREBRAS_API_KEY environment variable to be set.
They can be run with: pytest -m integration_cerebras

To run only integration tests:
    pytest tests/test_integration_cerebras.py -v

To skip if API key not available:
    pytest tests/test_integration_cerebras.py -v -m "integration_cerebras or skip_if_no_api_key"
"""
from __future__ import annotations

import os

import pytest

from speakup.errors import AdapterError
from speakup.models import MessageEvent
from speakup.summarizers.cerebras import CerebrasSummarizer


# Skip all tests in this module if CEREBRAS_API_KEY is not set
pytestmark = pytest.mark.skipif(
    not os.environ.get("CEREBRAS_API_KEY"),
    reason="CEREBRAS_API_KEY environment variable not set",
)


@pytest.fixture
def cerebras_api_key() -> str:
    """Get Cerebras API key from environment."""
    key = os.environ.get("CEREBRAS_API_KEY")
    if not key:
        pytest.skip("CEREBRAS_API_KEY environment variable not set")
    return key


@pytest.fixture
def cerebras_summarizer(cerebras_api_key: str) -> CerebrasSummarizer:
    """Create CerebrasSummarizer instance with API key from environment."""
    return CerebrasSummarizer(
        api_key_env="CEREBRAS_API_KEY",
        model="llama3.1-8b",
        base_url="https://api.cerebras.ai/v1",
    )


@pytest.mark.integration_cerebras
def test_cerebras_real_api_given_final_event_then_returns_summary(cerebras_summarizer: CerebrasSummarizer):
    """Test real Cerebras API call for FINAL event."""
    message = "The task has been completed successfully. All files have been processed."
    result = cerebras_summarizer.summarize(message, MessageEvent.FINAL, max_chars=220)

    assert result.summary
    assert len(result.summary) <= 220
    assert result.state == MessageEvent.FINAL
    assert result.user_action_required is False
    print(f"\nSummary (FINAL): {result.summary}")


@pytest.mark.integration_cerebras
def test_cerebras_real_api_given_needs_input_event_then_sets_flag(cerebras_summarizer: CerebrasSummarizer):
    """Test real Cerebras API call for NEEDS_INPUT event."""
    message = "Waiting for user to confirm the deployment. Please approve to continue."
    result = cerebras_summarizer.summarize(message, MessageEvent.NEEDS_INPUT, max_chars=220)

    assert result.summary
    assert len(result.summary) <= 220
    assert result.state == MessageEvent.NEEDS_INPUT
    assert result.user_action_required is True
    print(f"\nSummary (NEEDS_INPUT): {result.summary}")


@pytest.mark.integration_cerebras
def test_cerebras_real_api_given_progress_event_then_returns_summary(cerebras_summarizer: CerebrasSummarizer):
    """Test real Cerebras API call for PROGRESS event."""
    message = "Processing files: 45% complete. 23 out of 50 files processed."
    result = cerebras_summarizer.summarize(message, MessageEvent.PROGRESS, max_chars=220)

    assert result.summary
    assert len(result.summary) <= 220
    assert result.state == MessageEvent.PROGRESS
    assert result.user_action_required is False
    print(f"\nSummary (PROGRESS): {result.summary}")


@pytest.mark.integration_cerebras
def test_cerebras_real_api_given_error_event_then_returns_summary(cerebras_summarizer: CerebrasSummarizer):
    """Test real Cerebras API call for ERROR event."""
    message = "Error: Failed to connect to database. Connection timeout after 30 seconds."
    result = cerebras_summarizer.summarize(message, MessageEvent.ERROR, max_chars=220)

    assert result.summary
    assert len(result.summary) <= 220
    assert result.state == MessageEvent.ERROR
    assert result.user_action_required is False
    print(f"\nSummary (ERROR): {result.summary}")


@pytest.mark.integration_cerebras
def test_cerebras_real_api_given_long_message_then_truncates_summary(cerebras_summarizer: CerebrasSummarizer):
    """Test that Cerebras API respects max_chars limit."""
    long_message = """
    This is a very long message that contains multiple paragraphs and details.
    It should be summarized into a much shorter version that fits within the character limit.
    The summarizer should extract only the most important information and present it
    in a concise manner suitable for text-to-speech output. This tests whether the
    summarization and truncation logic works correctly with the real API.
    """ * 3

    max_chars = 100
    result = cerebras_summarizer.summarize(long_message, MessageEvent.FINAL, max_chars=max_chars)

    assert result.summary
    assert len(result.summary) <= max_chars, f"Summary too long: {len(result.summary)} > {max_chars}"
    print(f"\nSummary (truncated to {max_chars}): {result.summary}")


@pytest.mark.integration_cerebras
def test_cerebras_real_api_with_custom_model():
    """Test Cerebras API with a different model."""
    api_key = os.environ.get("CEREBRAS_API_KEY")
    if not api_key:
        pytest.skip("CEREBRAS_API_KEY environment variable not set")

    # Try with a different model if available
    summarizer = CerebrasSummarizer(
        api_key_env="CEREBRAS_API_KEY",
        model="llama3.1-8b",
    )

    result = summarizer.summarize("Test message", MessageEvent.FINAL, max_chars=220)

    assert result.summary
    print(f"\nSummary (custom model): {result.summary}")


@pytest.mark.integration_cerebras
def test_cerebras_real_api_given_invalid_key_then_raises():
    """Test that invalid API key is properly handled."""
    os.environ["INVALID_CEREBRAS_KEY"] = "invalid-key-12345"

    summarizer = CerebrasSummarizer(
        api_key_env="INVALID_CEREBRAS_KEY",
        model="llama3.1-8b",
    )

    with pytest.raises(AdapterError) as exc:
        summarizer.summarize("Test message", MessageEvent.FINAL, max_chars=220)

    assert "Cerebras summarization request failed" in str(exc.value)

    # Cleanup
    del os.environ["INVALID_CEREBRAS_KEY"]


@pytest.mark.integration_cerebras
def test_cerebras_real_api_multiple_requests(cerebras_summarizer: CerebrasSummarizer):
    """Test multiple consecutive API requests to check rate limiting behavior."""
    messages = [
        "First task completed",
        "Second task in progress",
        "Third task waiting for input",
    ]

    summaries = []
    for i, msg in enumerate(messages):
        event = MessageEvent.FINAL if i == 0 else (MessageEvent.PROGRESS if i == 1 else MessageEvent.NEEDS_INPUT)
        result = cerebras_summarizer.summarize(msg, event, max_chars=220)
        summaries.append(result.summary)
        assert result.summary
        print(f"\nRequest {i+1}: {result.summary}")

    assert len(summaries) == 3
    assert all(s for s in summaries)
