---
description: Control speakup notifications (on/off/status)
disable-model-invocation: true
---

# Speakup Control Command

Control the speakup plugin settings for Droid notifications.

Usage: `/speakup [on|off|status]`

## Arguments

- `on` - Enable speakup notifications
- `off` - Disable speakup notifications  
- `status` - Show current speakup status (default)

## Instructions

$ARGUMENTS

If the user provides arguments, parse them:

1. If argument is "on":
   - Update the speakup config file at `~/.config/speakup/config.json`
   - Set `droid.enabled` to `true`
   - Confirm to user that speakup is enabled

2. If argument is "off":
   - Update the speakup config file at `~/.config/speakup/config.json`
   - Set `droid.enabled` to `false`
   - Confirm to user that speakup is disabled

3. If argument is "status" or no argument provided:
   - Read the speakup config file at `~/.config/speakup/config.json`
   - Check the value of `droid.enabled`
   - Report current status to user

If the config file doesn't exist, assume default settings (enabled: true).

Always use the Read tool to check the current config, then use the Edit tool to update it if needed.
