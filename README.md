# speakup

[![PyPI version](https://badge.fury.io/py/speakup.svg)](https://badge.fury.io/py/speakup)
[![Python](https://img.shields.io/pypi/pyversions/speakup.svg)](https://pypi.org/project/speakup/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub release](https://img.shields.io/github/release/piotrgredowski/speakup.svg)](https://github.com/piotrgredowski/speakup/releases)
[![CI](https://github.com/piotrgredowski/speakup/workflows/CI/badge.svg)](https://github.com/piotrgredowski/speakup/actions)

Turn agent responses into short spoken updates.

## Install

```bash
uv tool install speakup
```

For local development, see [CONTRIBUTING.md](CONTRIBUTING.md).

For one-off runs without installing:

```bash
uvx --from speakup speakup --message "Done implementing the feature." --event final
```

## What it does

- Speaks short updates for events like `final`, `error`, `needs_input`, and `progress`
- Can summarize text before speech
- Supports local and remote TTS backends with fallback order
- Adds optional event sounds before playback
- Works as a standalone CLI and through integrations like Pi and the Droid plugin

## Quick start

```bash
speakup --message "Done implementing the feature." --event final
```

```bash
speakup --input-json '{"message":"Could you confirm deployment region?","event":"needs_input"}'
```

```bash
speakup --no-play --message "Done implementing the feature." --event final
```

```bash
speakup verbalize --text "Room 402 opens at 3:30 in 1980."
```

## Config in 60 seconds

Create a starter config:

```bash
speakup init-config
```

Open the config file in your configured viewer:

```bash
speakup show-config
```

Show which config path is being used:

```bash
speakup show-config-path
```

Main sections:

- `privacy`
- `events`
- `event_sounds`
- `summarization`
- `fallback`
- `tts`
- `dedup`
- `providers`

Tiny example:

```json
{
  "privacy": { "mode": "prefer_local" },
  "summarization": {
    "provider_order": ["command", "rule_based", "lmstudio", "openai"]
  },
  "tts": {
    "provider_order": ["kokoro_cli", "macos", "lmstudio", "openai"],
    "voice": "default",
    "speed": 1.0
  }
}
```

If you do not pass `--config`, speakup uses the default config path when present and falls back to built-in defaults.
The default config path is `~/.config/speakup/config.jsonc`.

## Integrations

### Pi

```bash
pi install https://github.com/piotrgredowski/speakup
```

After install, run `/reload` in Pi.

For Pi integration details, see `plugins/pi` and the package metadata in `package.json`.

### Droid plugin

The Droid plugin adds spoken notifications for Droid lifecycle events.

See [plugins/speakup-factory-plugin/README.md](plugins/speakup-factory-plugin/README.md) for install, config, and usage.

## Common commands

```bash
speakup self-test
speakup init-config
speakup show-config
speakup show-config-path
```

## More docs

- [CONTRIBUTING.md](CONTRIBUTING.md) — development setup and release process
- [plugins/speakup-factory-plugin/README.md](plugins/speakup-factory-plugin/README.md) — Droid plugin
- [docs/speakup-spec.md](docs/speakup-spec.md) — project spec
- [CHANGELOG.md](CHANGELOG.md) — version history
