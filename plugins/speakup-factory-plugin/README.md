# Speakup Droid Plugin

Spoken notifications for Droid events using the [speakup](https://github.com/piotrgredowski/speakup) library.

## Features

- **Spoken notifications** when Droid needs attention or completes tasks
- **Event filtering** - choose which events trigger notifications
- **Configurable** - control via config file or slash command
- **Session tracking** - stores replay pointers for the current Droid session

## Installation

### Prerequisites

1. Install speakup:
   ```bash
   uv tool install speakup
   # or from source
   uv tool install --editable .
   ```

2. Initialize speakup config (optional):
   ```bash
   speakup init-config
   ```

### Install Plugin

From local directory:
```bash
droid plugin marketplace add ./plugins/speakup-factory-plugin
droid plugin install speakup@speakup-factory-plugin
```

From Git repository:
```bash
git clone https://github.com/piotrgredowski/speakup.git
droid plugin marketplace add ./speakup/plugins/speakup-factory-plugin
droid plugin install speakup@speakup-factory-plugin
```

## Usage

### Automatic Notifications

Once installed, the plugin automatically speaks notifications for:

| Droid Event | Speakup Event | Description |
|-------------|---------------|-------------|
| `Notification` | `needs_input` | When Droid needs permission or is waiting for input |
| `PreToolUse` (`AskUser`) | `needs_input` | When Droid presents a structured question |
| `Stop` | `final` | When Droid finishes responding |

The hook implementation can handle `SubagentStop` and `SessionStart`, but the packaged `hooks.json` does not enable them by default.

### Slash Command

Control speakup with the `/speakup` command:

- `/speakup` or `/speakup status` - Show current status
- `/speakup on` - Enable notifications
- `/speakup off` - Disable notifications

## Configuration

Add droid-specific settings to your speakup config at `~/.config/speakup/config.jsonc`:

```json
{
  "droid": {
    "enabled": true,
    "events": {
      "notification": true,
      "stop": true,
      "subagent_stop": true,
      "session_start": true
    }
  }
}
```

### Configuration Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | `true` | Enable/disable all speakup notifications |
| `events.notification` | boolean | `true` | Speak when Droid needs attention |
| `events.stop` | boolean | `true` | Speak when Droid finishes |
| `events.subagent_stop` | boolean | `false` | Speak when subagent completes, if the hook is enabled |
| `events.session_start` | boolean | `false` | Speak when session starts, if the hook is enabled |

## How It Works

1. **Hook Events**: The plugin registers hooks for Droid lifecycle events
2. **Message Extraction**: 
   - For `Notification`: Uses the notification message directly
   - For `Stop`/`SubagentStop`: Reads the transcript file to extract the last assistant message
   - For `SessionStart`: Announces "Droid session started"
3. **Speakup Integration**: Calls the `speakup` CLI with the extracted message
4. **TTS & Playback**: Speakup handles summarization, TTS, and audio playback

## Troubleshooting

### No audio playback

1. Check speakup is working:
   ```bash
   speakup --message "Test message" --event final
   ```

2. Check speakup config:
   ```bash
   cat ~/.config/speakup/config.jsonc
   ```

3. Run speakup diagnostics:
   ```bash
   speakup self-test
   ```

### Plugin not loading

1. Check plugin installation:
   ```bash
   droid plugin list
   ```

2. Verify marketplace:
   ```bash
   droid plugin marketplace list
   ```

### Hooks not triggering

1. Check hooks configuration:
   ```bash
   droid /hooks
   ```

2. Enable debug logging:
   ```bash
   droid --debug
   ```

## Development

### Project Structure

```
plugins/speakup-factory-plugin/
├── .factory-plugin/
│   └── plugin.json          # Plugin manifest
├── hooks/
│   ├── hooks.json            # Hook configuration
│   └── speakup-hook.py       # Hook script
├── commands/
│   └── speakup.md            # Slash command
└── README.md                 # This file
```

### Testing Locally

1. Install from local directory:
   ```bash
   droid plugin marketplace add ./plugins/speakup-factory-plugin
   droid plugin install speakup@speakup-factory-plugin
   ```

2. Test hooks by using Droid normally

3. Test slash command:
   ```
   /speakup status
   ```

## License

MIT
