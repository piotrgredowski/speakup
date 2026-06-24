# Configuration

`speakup` loads JSONC config from `~/.config/speakup/config.jsonc` unless `--config` is provided.

## Privacy

```jsonc
{
  "privacy": {
    "mode": "local_only",
    "allow_remote_fallback": false
  }
}
```

- `local_only`: skip hosted providers.
- `prefer_local`: allow configured provider order, but still skip hosted fallback unless `allow_remote_fallback` is `true`.

## History and logging

```jsonc
{
  "history": {
    "enabled": true,
    "store_messages": false,
    "retention_days": 30
  },
  "logging": {
    "log_message_text": false,
    "log_provider_payloads": false,
    "redact_sensitive": true
  }
}
```

Raw agent messages can contain source code, file paths, API keys, or prompt context. Keep `store_messages`, `log_message_text`, and `log_provider_payloads` disabled unless you explicitly want local debugging detail.

## Provider order

```jsonc
{
  "summarization": {
    "provider_order": ["omlx", "rule_based"]
  },
  "tts": {
    "provider_order": ["omlx", "piper", "macos"]
  }
}
```

Provider order controls fallback. Hosted providers receive message text when selected, so place them only in configs where remote processing is acceptable.

## Provider matrix

| Provider | Section | Kind | Remote |
| --- | --- | --- | --- |
| `rule_based` | `summarization.provider_order` | summarizer | no |
| `lmstudio` | both | summarizer/TTS | no, if pointed at localhost |
| `command` | `summarization.provider_order` | summarizer | depends on command |
| `cerebras` | `summarization.provider_order` | summarizer | yes |
| `openai` | both | summarizer/TTS | yes |
| `gemini` | both | summarizer/TTS | yes |
| `macos` | `tts.provider_order` | TTS | no |
| `omlx` | both | summarizer/TTS | no, if pointed at localhost |
| `piper` | `tts.provider_order` | TTS | no |
| `edge` | `tts.provider_order` | TTS | yes |
| `elevenlabs` | `tts.provider_order` | TTS | yes |

## Piper

Piper is a local optional TTS provider. Install it with `speakup[piper]`, download voices into the configured `providers.piper.data_dir`, and enable `piper` in `tts.provider_order`.

```jsonc
{
  "tts": {
    "provider_order": ["omlx", "piper", "macos"]
  },
  "providers": {
    "piper": {
      "base_url": "http://127.0.0.1:5000",
      "auto_start": true,
      "host": "127.0.0.1",
      "port": 5000,
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

When `auto_start` is enabled, SpeakUp starts Piper lazily and records the warm local server in its runtime database so later CLI invocations can reuse it. A small watchdog stops SpeakUp-managed Piper servers after `idle_timeout_seconds` without requests; set it to `0` or `null` to keep them running indefinitely. Piper returns WAV audio; `tts.audio_format` is ignored for this provider. `tts.speed` maps to Piper `length_scale` as `clamp(1 / speed, 0.5, 2.0)`.

## Project overrides

`speakup` can persist per-project voice selections in `.speakup.jsonc` under the project directory. This file is ignored by this repo and should normally remain local.

## Integration toggles

Agent integrations can also be disabled independently from the root `enabled` flag:

```jsonc
{
  "codex": {
    "enabled": true,
    "events": {
      "notification": true,
      "stop": true,
      "plan_approval": true
    }
  },
  "droid": {
    "enabled": true
  }
}
```

For Codex, `notification` covers explicit input or approval prompts, `stop` covers completed turns, and `plan_approval` covers proposed-plan waits.
