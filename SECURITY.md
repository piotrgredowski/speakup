# Security policy

## Reporting a vulnerability

Please report security issues privately by emailing the maintainer listed in `pyproject.toml`, or by opening a private GitHub vulnerability report if available.

Do not include secrets, private source code, or full agent transcripts in public issues.

## Sensitive data expectations

`speakup` may process coding-agent output. That output can contain source code, file paths, prompts, or credentials. The default configuration is local-first, does not store raw messages in history, and does not log raw message text.

Hosted providers are opt-in. If enabled, the selected provider may receive message text for summarization or TTS.
