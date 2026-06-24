# speakup

[![PyPI version](https://badge.fury.io/py/speakup.svg)](https://badge.fury.io/py/speakup)
[![Python](https://img.shields.io/pypi/pyversions/speakup.svg)](https://pypi.org/project/speakup/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/piotrgredowski/speakup/workflows/CI/badge.svg)](https://github.com/piotrgredowski/speakup/actions)

`speakup` turns coding-agent events into short spoken updates, with local-first defaults and optional hosted TTS/summarization providers.

`speakup` is currently supported on macOS. Other platforms are not a public support target yet.

For the smoothest fully local macOS experience, Speakup prefers oMLX by default with local fallbacks. See the [local macOS setup guide](docs/local-macos.md) for oMLX, Kokoro TTS, and local summarization.

## What it does

- Speaks concise status updates for `final`, `error`, `needs_input`, `progress`, and `info` events.
- Summarizes long agent output before playback.
- Routes through configurable local or hosted summarization/TTS providers.
- Stores replayable notification history.
- Integrates with Codex, Droid, and Pi.

## Install

```bash
uv tool install speakup
```

Run once without installing:

```bash
uvx --from speakup speakup --message "Done implementing the feature." --event final
```

For local development, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Quick start: local-first

The default config is local-first. It tries local oMLX first for summarization, pronunciation adaptation, and TTS, then local Piper TTS, then falls back to the built-in rule-based summarizer and macOS `say`, so no agent text is sent to hosted APIs by default.

```bash
speakup init-config
speakup --message "Done implementing the feature." --event final
```

Default config path:

```text
~/.config/speakup/config.jsonc
```

## Hosted setup example: Gemini

Hosted providers require explicit configuration and API keys. For Gemini summarization and TTS:

```bash
export GOOGLE_API_KEY=your_api_key_here
```

```jsonc
{
  "privacy": {
    "mode": "prefer_local",
    "allow_remote_fallback": true
  },
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

## Local server setup example: OMLX

For the smoothest fully local macOS setup with oMLX, Kokoro TTS, and Gemma summarization, see [docs/local-macos.md](docs/local-macos.md).

```jsonc
{
  "privacy": {
    "mode": "local_only",
    "allow_remote_fallback": false
  },
  "summarization": {
    "provider_order": ["omlx", "rule_based"]
  },
  "pronunciation": {
    "enabled": true,
    "provider_order": ["omlx"]
  },
  "tts": {
    "provider_order": ["omlx", "piper", "macos"],
    "audio_format": "wav"
  },
  "providers": {
    "omlx": {
      "base_url": "http://127.0.0.1:8000/v1",
      "api_key_env": "OMLX_API_KEY",
      "summary_model": "unsloth/gemma-4-E4B-it-UD-MLX-4bit",
      "model": "Kokoro-82M-bf16",
      "voice": "af_heart"
    },
    "piper": {
      "auto_start": true,
      "data_dir": "~/.local/share/speakup/piper-voices",
      "model": "en_GB-alba-medium",
      "voice": "en_GB-alba-medium",
      "available_voices": [
        "en_GB-alba-medium",
        "pl_PL-mc_speech-medium",
        "pl_PL-bass-high"
      ],
      "idle_timeout_seconds": 600
    }
  }
}
```

## Local TTS setup example: Piper

Piper support is optional:

```bash
pip install 'speakup[piper]'
python -m piper.download_voices --download-dir ~/.local/share/speakup/piper-voices \
  en_GB-alba-medium \
  pl_PL-mc_speech-medium \
  pl_PL-bass-high
```

SpeakUp can autostart and reuse a local Piper HTTP server. The server speaks through `POST /` with a JSON body, exposes `GET /voices` for readiness checks, and stops after 10 idle minutes by default.

## Privacy model

By default:

- `privacy.mode` is `local_only`.
- `privacy.allow_remote_fallback` is `false`.
- summarization tries `omlx`, then `rule_based`.
- pronunciation adaptation tries `omlx`.
- TTS tries `omlx`, then `piper`, then `macos`.
- notification history does not store raw messages unless `history.store_messages` is enabled.
- logs do not include raw message text unless `logging.log_message_text` is enabled.

Hosted providers may receive the message text that needs summarization or speech. Enable them only when that is acceptable for your project.

## Common commands

```bash
speakup --message "Done implementing the feature." --event final
speakup --input-json '{"message":"Build failed in CI","event":"error","agent":"droid"}'
speakup --no-play --message "Background task finished." --event final
speakup verbalize --text "Room 402 opens at 3:30 in 1980."
speakup pronounce --message "GitHub action failed" --spoken-language pl
speakup self-test
speakup doctor
speakup replay 3
speakup show-config
speakup show-config-path
speakup show-logs
speakup show-logs-path
```

`speakup desktop` is currently a source-checkout/development feature for the Tauri history viewer, not a packaged PyPI desktop distribution.

## Providers

| Provider | Summarization | TTS | Local by default | Notes |
| --- | --- | --- | --- | --- |
| `rule_based` | yes | no | yes | Built-in fallback summarizer |
| `macos` | no | yes | yes | Uses `say` and `afplay` |
| `lmstudio` | yes | yes | yes | Assumes local LM Studio-compatible server |
| `omlx` | yes | yes | yes | Assumes local OpenAI-compatible oMLX server |
| `piper` | no | yes | yes | Requires `speakup[piper]`; uses a local Piper HTTP server |
| `command` | yes | no | depends | Runs a configured local command |
| `edge` | no | yes | no | Requires `speakup[edge]` and Microsoft Edge TTS service |
| `openai` | yes | yes | no | Hosted OpenAI APIs |
| `gemini` | yes | yes | no | Hosted Google Gemini APIs |
| `cerebras` | yes | no | no | Hosted Cerebras API |
| `elevenlabs` | no | yes | no | Hosted ElevenLabs API |

## Integrations

### Codex

The Codex plugin lives in `plugins/speakup-codex-plugin`.

The packaged plugin wires:

- `Notification` to `needs_input`
- `Stop` to `final`
- proposed-plan waits to `needs_input`

Replay current Codex sessions with:

```bash
speakup replay 1 --agent codex --session-key <session_key>
```

See [plugins/speakup-codex-plugin/README.md](plugins/speakup-codex-plugin/README.md).

### Droid

```bash
uv tool install speakup
git clone https://github.com/piotrgredowski/speakup.git
droid plugin marketplace add ./speakup/plugins/speakup-factory-plugin
droid plugin install speakup@speakup-factory-plugin
```

The packaged plugin wires:

- `Notification` to `needs_input`
- `PreToolUse` for `AskUser` to `needs_input`
- `Stop` to `final`

Useful Droid commands:

- `/speakup status`
- `/speakup on`
- `/speakup off`
- `/speakup replay 1`

See [plugins/speakup-factory-plugin/README.md](plugins/speakup-factory-plugin/README.md).

### Pi

```bash
pi install https://github.com/piotrgredowski/speakup
```

Then run `/reload` in Pi. See [plugins/pi/README.md](plugins/pi/README.md).

## Extending speakup

Public extension points are intentionally small:

- `NotifyRequest` and `NotifyResult` in `speakup.models`
- `NotifyService` in `speakup.service`
- `Summarizer`, `TTSAdapter`, and `PlaybackAdapter` base classes
- agent integrations under `speakup.integrations`

New providers should define a focused adapter class, add tests with mocked network/subprocess behavior, and register the provider through the central service registry until a plugin-entry-point API is introduced.

## Project docs

- [CONTRIBUTING.md](CONTRIBUTING.md) — local development, validation, and release flow
- [docs/configuration.md](docs/configuration.md) — config reference
- [docs/integrations.md](docs/integrations.md) — Droid/Pi and provider extension notes
- [SECURITY.md](SECURITY.md) — supported security reporting process
- [CHANGELOG.md](CHANGELOG.md) — version history
