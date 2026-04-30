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
    "provider_order": ["rule_based"]
  },
  "tts": {
    "provider_order": ["macos"]
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
| `omlx` | `tts.provider_order` | TTS | no, if pointed at localhost |
| `edge` | `tts.provider_order` | TTS | yes |
| `elevenlabs` | `tts.provider_order` | TTS | yes |

## Project overrides

`speakup` can persist per-project voice selections in `.speakup.jsonc` under the project directory. This file is ignored by this repo and should normally remain local.
