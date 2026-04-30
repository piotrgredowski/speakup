from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ProviderKind = Literal["summarizer", "tts"]


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    name: str
    kind: ProviderKind
    remote: bool
    config_section: str
    optional_dependency: str | None = None


PROVIDERS: tuple[ProviderDescriptor, ...] = (
    ProviderDescriptor("rule_based", "summarizer", False, "summarization"),
    ProviderDescriptor("lmstudio", "summarizer", False, "providers.lmstudio"),
    ProviderDescriptor("command", "summarizer", False, "providers.command_summary"),
    ProviderDescriptor("cerebras", "summarizer", True, "providers.cerebras"),
    ProviderDescriptor("openai", "summarizer", True, "providers.openai"),
    ProviderDescriptor("gemini", "summarizer", True, "providers.gemini"),
    ProviderDescriptor("macos", "tts", False, "providers.macos"),
    ProviderDescriptor("lmstudio", "tts", False, "providers.lmstudio"),
    ProviderDescriptor("omlx", "tts", False, "providers.omlx"),
    ProviderDescriptor("edge", "tts", True, "providers.edge", "speakup[edge]"),
    ProviderDescriptor("elevenlabs", "tts", True, "providers.elevenlabs"),
    ProviderDescriptor("openai", "tts", True, "providers.openai"),
    ProviderDescriptor("gemini", "tts", True, "providers.gemini"),
)


REMOTE_SUMMARIZERS = {
    provider.name for provider in PROVIDERS if provider.kind == "summarizer" and provider.remote
}
REMOTE_TTS_PROVIDERS = {
    provider.name for provider in PROVIDERS if provider.kind == "tts" and provider.remote
}
