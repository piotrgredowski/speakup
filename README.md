# let-me-know-agent

Python library + CLI to turn agent responses into short spoken updates.

## Features

- Summarizes agent output into concise spoken text
- Speaks on: final, error, needs_input, progress
- Kokoro TTS included as Python dependency (`kokoro`)
- Per-event sound cues (earcons) before speech
- Provider fallback chains for summarization and TTS
- Optional fail-fast mode to stop on first provider error
- Privacy modes (`local_only`, `prefer_local`)
- Agent-agnostic core CLI + dedicated Pi wrapper command

## Install

```bash
pip install -e .
```

## Quick usage

```bash
let-me-know --message "Done implementing the feature." --event final
```

Or with normalized JSON input:

```bash
let-me-know --input-json '{"message":"Could you confirm deployment region?","event":"needs_input"}'
```

You can skip local playback (useful in headless runs):

```bash
let-me-know --no-play --message "Done implementing the feature." --event final
```

You can also force fail-fast provider behavior from CLI:

```bash
let-me-know --fail-fast --message "Done implementing the feature." --event final
```


Pi payload through dedicated wrapper command:

```bash
echo '{"session-name":"agent-1","message":"Could you confirm deployment region?","event":"needs_input"}' | let-me-know-pi --config config.json
```

Returns JSON result:

```json
{
  "status": "ok",
  "summary": "Action needed: Could you confirm deployment region?",
  "state": "needs_input",
  "backend": "macos",
  "played": true,
  "audio_path": "/tmp/let-me-know-agent/audio/tts-....aiff",
  "dedup_skipped": false,
  "error": null
}
```

## Configuration

Initialize a default config file:

```bash
let-me-know --init-config
```

This writes to `~/.config/let-me-know-agent/config.json`.
Use `--force` to overwrite an existing file.

You can also pass an explicit config path with `--config config.json`.

If `--config` is omitted, the tool checks:
1. `~/.config/let-me-know-agent/config.json`
2. built-in defaults (if no file is found)

Config is validated on load (types, enums, provider names, event sound keys).
Set `fallback.fail_fast` to `true` to stop on the first provider failure instead of trying later providers.

```json
{
  "privacy": {
    "mode": "prefer_local",
    "allow_remote_fallback": true
  },
  "events": {
    "speak_on_final": true,
    "speak_on_error": true,
    "speak_on_needs_input": true,
    "speak_on_progress": true
  },
  "event_sounds": {
    "enabled": true,
    "files": {
      "final": "/System/Library/Sounds/Glass.aiff",
      "error": "/System/Library/Sounds/Basso.aiff",
      "needs_input": "/System/Library/Sounds/Funk.aiff",
      "progress": "/System/Library/Sounds/Pop.aiff",
      "info": "/System/Library/Sounds/Ping.aiff"
    }
  },
  "summarization": {
    "max_chars": 220,
    "provider_order": ["rule_based", "lmstudio", "openai"]
  },
  "fallback": {
    "fail_fast": false
  },
  "tts": {
    "provider_order": ["kokoro_cli", "macos", "kokoro", "orpheus", "lmstudio", "elevenlabs", "openai"],
    "voice": "default",
    "speed": 1.0,
    "play_audio": true,
    "audio_format": "mp3",
    "save_audio_dir": "/tmp/let-me-know-agent/audio"
  },
  "dedup": {
    "enabled": true,
    "window_seconds": 30,
    "cache_file": "/tmp/let-me-know-agent/last_progress.json"
  },
  "providers": {
    "kokoro_cli": {
      "command": "kokoro",
      "args": ["-o", "{output}", "-m", "{voice}", "-s", "{speed}", "-t", "{text}"],
      "voice": "af_heart",
      "timeout_seconds": 60
    },
    "orpheus": {
      "model_name": "canopylabs/orpheus-tts-0.1-finetune-prod",
      "voice": "tara",
      "max_model_len": 2048,
      "offline": true,
      "timeout_seconds": 120
    },
    "lmstudio": {
      "base_url": "http://localhost:1234/v1",
      "model": "local-model",
      "tts_model": "local-tts-model"
    },
    "elevenlabs": {
      "api_key_env": "ELEVENLABS_API_KEY",
      "voice_id": ""
    },
    "openai": {
      "api_key_env": "OPENAI_API_KEY",
      "model": "gpt-4o-mini-tts",
      "summary_model": "gpt-4o-mini",
      "voice": "alloy"
    }
  }
}
```

## Pi extension install

The Pi integration is intentionally separate from core logic:
- Core logic: Python package (`let_me_know_agent/*`)
- Pi adapter: `pi-extensions/let-me-know-agent.ts` (defaults to `uvx --from git+https://github.com/piotrgredowski/let-me-know-agent let-me-know-pi`)

### Install via `pi install` (recommended)

```bash
pi install https://github.com/piotrgredowski/let-me-know-agent
```

This works because the repo is a Pi package (`package.json` + `pi.extensions`).
After install, run `/reload` in Pi.

> By default the extension uses `uvx --from git+https://github.com/piotrgredowski/let-me-know-agent let-me-know-pi` for near zero setup (no PyPI publish required).
> If `uvx` is unavailable, it will fall back to local `python -m let_me_know_agent.pi_command` / `let-me-know-pi` when present.

### 1) Install Python package

```bash
pip install let-me-know-agent
# or for local dev
pip install -e .
```

### 2) (Alternative manual install) copy Pi extension file

```bash
./pi-extensions/install.sh
```

This copies the extension to:
`~/.pi/agent/extensions/let-me-know-agent.ts`

Then inside Pi run:

```text
/reload
```

### 3) Optional extension config

Copy and edit:

```bash
mkdir -p ~/.config/let-me-know-agent
cp pi-extensions/pi-extension.example.json ~/.config/let-me-know-agent/pi-extension.json
```

You can set a custom command/path and args (for example explicit `--config`).

You can also enable agent-driven headless summarization in the extension:

- `summaryMode: "internal"` (default): let Python backends summarize (`rule_based`/`lmstudio`/`openai`).
- `summaryMode: "agent_headless"`: extension first runs a headless command and passes its summary into `let-me-know-pi`.

When `agent_headless` is enabled, configure `headlessSummary.command/args/model/promptTemplate` as needed.
The command args support placeholders: `{model}`, `{prompt}`, `{text}`, `{event}`, `{maxChars}`.

### 4) Runtime control in Pi

Use command:

```text
/letmeknow on
/letmeknow off
/letmeknow status
```

## Notes

- Lightweight audio format default is `mp3` for remote providers.
- macOS `say` currently writes `aiff`.
- Progress dedup skips repeated progress messages in a time window.
