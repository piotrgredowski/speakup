# Speakup Pi extension

This extension speaks Pi assistant completions through the `speakup pi` wrapper.

## Install

```bash
uv tool install speakup
pi install https://github.com/piotrgredowski/speakup
```

Then run `/reload` in Pi.

## Config

The extension reads `~/.config/speakup/pi-extension.json`:

```json
{
  "enabled": true,
  "command": "speakup",
  "args": ["pi"],
  "onlyAssistant": true
}
```

Use `plugins/pi/pi-extension.example.json` if you want to run from Git with `uvx`.

## Commands

Inside Pi:

- `/speakup status`
- `/speakup on`
- `/speakup off`
- `/speakup replay 1`

Replay requires Pi to expose a stable session key for the current session.
