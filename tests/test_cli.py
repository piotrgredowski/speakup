from __future__ import annotations

from speakup.cli import _apply_cli_overrides
from speakup.config import Config, default_config


def test_apply_cli_overrides_given_gemini_summary_provider_then_updates_gemini_summary_model() -> None:
    cfg = Config(default_config())

    _apply_cli_overrides(
        cfg,
        summary_provider="gemini",
        summary_model="gemini-2.5-flash-lite",
    )

    assert cfg.get("summarization", "provider_order") == ["gemini"]
    assert cfg.get("providers", "gemini", "summary_model") == "gemini-2.5-flash-lite"
