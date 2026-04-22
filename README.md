# speakup

[![PyPI version](https://badge.fury.io/py/speakup.svg)](https://badge.fury.io/py/speakup)
[![Python](https://img.shields.io/pypi/pyversions/speakup.svg)](https://pypi.org/project/speakup/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub release](https://img.shields.io/github/release/piotrgredowski/speakup.svg)](https://github.com/piotrgredowski/speakup/releases)
[![CI](https://github.com/piotrgredowski/speakup/workflows/CI/badge.svg)](https://github.com/piotrgredowski/speakup/actions)

Turn agent output into short spoken updates.

This project is being developed on macOS right now, and `speakup` should be considered supported on macOS for now. Support for other platforms is planned in the future, but there is no timeline yet.

## What it is

`speakup` is a Python CLI for:

- speaking concise agent status updates
- summarizing long messages before playback
- routing through local or remote TTS backends with fallback
- replaying recent notifications from history
- integrating with tools like Droid and Pi

Supported event types are `final`, `error`, `needs_input`, `progress`, and `info`.

## Install

Install the CLI:

```bash
uv tool install speakup
```

Run it once without installing:

```bash
uvx --from speakup speakup --message "Done implementing the feature." --event final
```

For local development, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Quick start

The easiest way to get `speakup` working end-to-end is to use Gemini for both summarization and TTS:

```bash
export GOOGLE_API_KEY=your_api_key_here
speakup init-config
```

Then set your config to a Gemini-only setup like this:

```jsonc
{
  "summarization": {
    "provider_order": ["gemini", "rule_based"]
  },
  "tts": {
    "provider_order": ["gemini"],
    "audio_format": "wav"
  },
  "providers": {
    "gemini": {
      "api_key_env": "GOOGLE_API_KEY",
      "summary_model": "gemini-2.5-flash",
      "model": "gemini-2.5-flash-preview-tts",
      "voice": "Kore"
    }
  }
}
```

After that, this should work immediately:

```bash
speakup --message "Done implementing the feature." --event final
```

If you want to run locally, use OMLX for TTS and keep summarization local too:

```bash
speakup init-config
```

Then point `speakup` at your local OMLX server:

```jsonc
{
  "privacy": {
    "mode": "local_only",
    "allow_remote_fallback": false
  },
  "summarization": {
    "provider_order": ["rule_based"]
  },
  "tts": {
    "provider_order": ["omlx"],
    "audio_format": "wav"
  },
  "providers": {
    "omlx": {
      "base_url": "http://127.0.0.1:8000/v1",
      "api_key_env": "OMLX_API_KEY",
      "model": "Kokoro-82M-bf16",
      "voice": "af_heart"
    }
  }
}
```

If your local OMLX server expects an API key, set it before running `speakup`:

```bash
export OMLX_API_KEY=1234
```

Speak a simple completion update:

```bash
speakup --message "Done implementing the feature." --event final
```

Speak an input request:

```bash
speakup --message "Could you confirm the deployment region?" --event needs_input
```

Send a JSON payload instead of individual flags:

```bash
speakup --input-json '{"message":"Build failed in CI","event":"error","agent":"droid"}'
```

Generate audio without playing it locally:

```bash
speakup --no-play --message "Background task finished." --event final
```

Preview how text will sound after normalization:

```bash
speakup verbalize --text "Room 402 opens at 3:30 in 1980."
```

## Use with the Droid plugin

If you want spoken updates inside Droid, the fastest path is:

```bash
uv tool install speakup
droid plugin marketplace add https://github.com/piotrgredowski/speakup
droid plugin install speakup@speakup
```

What the current plugin wires up automatically:

- `Notification` events are spoken as `needs_input`
- `Stop` events are spoken as `final`

Useful Droid commands after install:

- `/speakup status`
- `/speakup on`
- `/speakup off`
- `/speakup replay 1`

If you want to verify the CLI itself first:

```bash
speakup --message "Speakup is installed." --event final
```

For deeper plugin details, see [plugins/speakup-factory-plugin/README.md](plugins/speakup-factory-plugin/README.md).

## Minimal config

You only need config when you want to change provider order, privacy rules, plugin behavior, logging, or playback settings.

For the fewest moving parts:

- use **Gemini-only** if you want the fastest hosted setup
- use **OMLX + rule_based** if you want a local-first setup

Create a starter config:

```bash
speakup init-config
```

Open it:

```bash
speakup show-config
```

Show the path in use:

```bash
speakup show-config-path
```

Default config path:

```text
~/.config/speakup/config.jsonc
```

Minimal example:

```jsonc
{
  "privacy": {
    "mode": "prefer_local",
    "allow_remote_fallback": true
  },
  "summarization": {
    "max_chars": 220,
    "provider_order": ["gemini", "rule_based"]
  },
  "tts": {
    "provider_order": ["gemini"],
    "voice": "default",
    "speed": 1.0,
    "audio_format": "wav"
  },
  "providers": {
    "gemini": {
      "api_key_env": "GOOGLE_API_KEY",
      "summary_model": "gemini-2.5-flash",
      "model": "gemini-2.5-flash-preview-tts",
      "voice": "Kore"
    }
  },
  "droid": {
    "enabled": true,
    "events": {
      "notification": true,
      "stop": true,
      "subagent_stop": false,
      "session_start": false
    }
  }
}
```

## Providers

Current TTS providers:

- `macos`
- `lmstudio`
- `elevenlabs`
- `openai`
- `gemini`
- `omlx`

Current summarization providers:

- `rule_based`
- `lmstudio`
- `openai`
- `command`
- `cerebras`
- `gemini`

## Common commands

```bash
speakup self-test
speakup doctor
speakup replay 3
speakup show-config
speakup show-config-path
speakup show-logs
speakup show-logs-path
speakup desktop
```

## Integrations

### Pi

```bash
pi install https://github.com/piotrgredowski/speakup
```

Then run `/reload` in Pi.

### Droid

Use the GitHub plugin install flow shown above.

## Where to go next

- [plugins/speakup-factory-plugin/README.md](plugins/speakup-factory-plugin/README.md) — Droid plugin details
- [CONTRIBUTING.md](CONTRIBUTING.md) — local development and release flow
- [docs/speakup-spec.md](docs/speakup-spec.md) — project spec
- [CHANGELOG.md](CHANGELOG.md) — version history
