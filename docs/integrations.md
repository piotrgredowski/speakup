# Integrations and extension points

## Event contract

Agent integrations should emit a `NotifyRequest` with:

- `message`: raw agent output or a short precomputed message
- `event`: `final`, `error`, `needs_input`, `progress`, or `info`
- `agent`: stable agent name such as `droid` or `pi`
- `session_key`: exact replay key for the agent session when available
- `session_name`: human-readable session title when available
- `metadata.cwd`: current project path when available

## Droid plugin

The Droid plugin lives in `plugins/speakup-factory-plugin`.

Packaged hooks:

- `Notification` -> `needs_input`
- `PreToolUse` with `AskUser` -> `needs_input`
- `Stop` -> `final`

The hook stores a session pointer under `~/.config/speakup/droid-session-pointers/` so `/speakup replay N` can replay the current Droid session exactly.

## Pi plugin

The Pi extension lives in `plugins/pi` and calls:

```bash
speakup pi
```

It passes Pi message payloads through stdin and uses `sessionKey` for exact replay when available.

## Adding an agent integration

1. Convert the agent event payload into `NotifyRequest`.
2. Preserve stable session identifiers as `session_key`.
3. Avoid logging full payloads by default.
4. Use `precomputed_summary` only when the agent already produced safe spoken text.
5. Add unit tests for payload variants and replay behavior.

## Adding a provider

1. Implement `Summarizer` or `TTSAdapter`.
2. Raise `AdapterError` for provider failures.
3. Keep API keys in environment variables.
4. Add mocked tests for success, missing credentials, non-audio/non-JSON responses, and truncation/cleanup behavior.
5. Register the provider in `build_registry_from_config()` and update the config schema/docs.
