---
description: Control speakup notifications (on/off/status/replay)
disable-model-invocation: true
---

# Speakup Control Command

Control the speakup plugin settings for Droid notifications.

Usage: `/speakup [on|off|status|replay [N]]`

## Arguments

- `on` - Enable speakup notifications
- `off` - Disable speakup notifications  
- `status` - Show current speakup status (default)
- `replay [N]` - Replay the last `N` notifications for the current Droid session (default: `1`)

## Instructions

$ARGUMENTS

If the user provides arguments, parse them:

1. If argument is "on":
   - Update the speakup config file at `~/.config/speakup/config.jsonc` (or legacy `config.json` if present)
   - Set `droid.enabled` to `true`
   - Confirm to user that speakup is enabled

2. If argument is "off":
   - Update the speakup config file at `~/.config/speakup/config.jsonc` (or legacy `config.json` if present)
   - Set `droid.enabled` to `false`
   - Confirm to user that speakup is disabled

3. If argument is "status" or no argument provided:
   - Read the speakup config file at `~/.config/speakup/config.jsonc` (or legacy `config.json` if present)
   - Check the value of `droid.enabled`
   - Report current status to user

4. If argument starts with `replay`:
   - Parse an optional integer count after `replay`; default to `1`
   - Determine the current working directory
   - Convert that cwd into the speakup pointer slug by replacing `/`, `\`, and `:` with `-`
   - Read the pointer file at `~/.config/speakup/droid-session-pointers/<cwd-slug>.json`
   - Extract `session_key` from that JSON file
   - If the pointer file or `session_key` is missing, stop and tell the user that no current Droid session was recorded yet
   - Run:
     - `speakup replay <count> --agent droid --session-key <session_key>`
   - Report success or failure to the user
   - Do not fall back to session titles or fuzzy matching

If the config file doesn't exist, assume default settings (enabled: true).

Always use the Read tool to check the current config, then use the Edit tool to update it if needed. For replay, read the pointer JSON first and only then invoke `speakup replay`.
