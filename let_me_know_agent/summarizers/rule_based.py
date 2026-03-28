from __future__ import annotations

import re

from .base import Summarizer
from ..models import MessageEvent, SummaryResult


class RuleBasedSummarizer(Summarizer):
    name = "rule_based"

    def summarize(self, message: str, event: MessageEvent, max_chars: int) -> SummaryResult:
        cleaned = _clean(message)
        short = _truncate(cleaned, max_chars)

        if event == MessageEvent.NEEDS_INPUT:
            prompt = _extract_question(cleaned)
            text = f"Action needed: {prompt}" if prompt else f"Action needed: {short}"
            return SummaryResult(
                summary=_truncate(text, max_chars),
                state=event,
                user_action_required=True,
                action_prompt=prompt,
            )

        if event == MessageEvent.ERROR:
            return SummaryResult(
                summary=_truncate(f"There was an issue: {short}", max_chars),
                state=event,
            )

        if event == MessageEvent.PROGRESS:
            return SummaryResult(
                summary=_truncate(f"Progress update: {short}", max_chars),
                state=event,
            )

        if event == MessageEvent.FINAL:
            return SummaryResult(
                summary=_truncate(f"Done: {short}", max_chars),
                state=event,
            )

        return SummaryResult(summary=short, state=event)


def _clean(message: str) -> str:
    text = re.sub(r"```.*?```", "", message, flags=re.DOTALL)
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _extract_question(text: str) -> str | None:
    for sentence in re.split(r"(?<=[.?!])\s+", text):
        if "?" in sentence:
            return sentence.strip()
    return None
