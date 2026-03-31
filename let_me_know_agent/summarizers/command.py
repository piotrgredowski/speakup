from __future__ import annotations

import subprocess
from typing import ClassVar

from .base import Summarizer
from ..errors import AdapterError
from ..models import MessageEvent, SummaryResult


class CommandSummarizer(Summarizer):
    """Summarizer that delegates to an external command."""

    name: ClassVar[str] = "command"

    def __init__(
        self,
        *,
        command: str,
        args: list[str] | None = None,
        timeout_seconds: int = 30,
        trim_output: bool = True,
    ):
        self.command = command
        self.args = args or ["-p", "{message}"]
        self.timeout_seconds = timeout_seconds
        self.trim_output = trim_output

    def summarize(self, message: str, event: MessageEvent, max_chars: int) -> SummaryResult:
        argv = [self.command, *self._render_args(message=message, event=event, max_chars=max_chars)]

        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise AdapterError(f"Summary command not found: {self.command}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AdapterError(f"Summary command timed out after {self.timeout_seconds}s") from exc
        except OSError as exc:
            raise AdapterError(f"Summary command failed to start: {exc}") from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise AdapterError(f"Summary command failed with exit code {completed.returncode}: {detail}")

        summary = completed.stdout
        if self.trim_output:
            summary = summary.strip()
        if len(summary) > max_chars:
            summary = summary[: max_chars - 1].rstrip() + "…"

        return SummaryResult(summary=summary, state=event)

    def _render_args(self, *, message: str, event: MessageEvent, max_chars: int) -> list[str]:
        rendered: list[str] = []
        for arg in self.args:
            rendered.append(
                arg.format(
                    message=message,
                    event=event.value,
                    max_chars=max_chars,
                )
            )
        return rendered
