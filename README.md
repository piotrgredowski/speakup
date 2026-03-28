# let-me-know-agent

Python library + CLI to turn agent responses into short spoken updates.

## Features

- Summarizes agent output into concise spoken text
- Speaks on: final, error, needs_input, progress
- Per-event sound cues (earcons) before speech
- Provider fallback chains for summarization and TTS
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

Pi payload through dedicated wrapper command:

```bash
echo '{"message":"Could you confirm deployment region?","event":"needs_input"}' | let-me-know-pi --config config.json
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
  "tts": {
    "provider_order": ["macos", "kokoro", "lmstudio", "elevenlabs", "openai"],
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
- Pi adapter: `pi-extensions/let-me-know-agent.ts` (calls `let-me-know-pi` as a subprocess)

### Install via `pi install` (recommended)

```bash
pi install https://github.com/piotrgredowski/let-me-know-agent
```

This works because the repo is a Pi package (`package.json` + `pi.extensions`).
After install, run `/reload` in Pi.

> Note: The extension shells out to `let-me-know-pi`, so the Python package must also be installed in your environment.
> 
> ```bash
> pip install let-me-know-agent
> # or local dev
> pip install -e .
> ```

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
