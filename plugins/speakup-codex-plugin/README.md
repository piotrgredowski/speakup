# SpeakUp Codex Plugin

Spoken notifications for Codex events using the [SpeakUp](https://github.com/piotrgredowski/speakup) CLI.

## Features

- Speaks when Codex needs approval or input.
- Speaks when Codex is waiting for plan approval.
- Speaks completed Codex turns.
- Stores a current-session replay pointer for exact replay.

## Installation

Install SpeakUp first:

```bash
uv tool install speakup
speakup init-config
```

Install this plugin from the SpeakUp repository using Codex's local plugin flow. This repo intentionally does not modify your personal Codex marketplace or install state.

## Configuration

Codex-specific settings live in `~/.config/speakup/config.jsonc`:

```json
{
  "codex": {
    "enabled": true,
    "events": {
      "notification": true,
      "stop": true,
      "plan_approval": true
    }
  }
}
```

If root `enabled` is `false`, Codex notifications are disabled too.

## Replay

The hook stores session pointers under:

```text
~/.config/speakup/codex-session-pointers/
```

When a Codex session key is available, replay the current session exactly:

```bash
speakup replay 1 --agent codex --session-key <session_key>
```

## Privacy

The hook does not log raw payloads by default. SpeakUp's normal privacy settings still control whether message text is stored in history or sent to hosted providers.
