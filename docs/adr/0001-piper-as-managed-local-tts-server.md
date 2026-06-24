# 0001 Piper as managed local TTS server

## Status

Accepted

## Context

SpeakUp is local-first and already supports configurable TTS providers. Piper can run as a CLI, but repeatedly launching the CLI reloads the voice model and adds avoidable latency to agent notifications. Piper also exposes an HTTP server that can keep voices loaded between requests.

SpeakUp is often invoked from agent hooks as short-lived CLI processes, so in-process adapter caching is not enough to reduce repeat startup cost.

## Decision

Add `piper` as a local TTS provider backed by Piper's HTTP server. The provider supports both an already-running server and lazy autostart. Autostarted Piper processes remain running after the triggering SpeakUp process exits, and SpeakUp records their location in a runtime SQLite database so later CLI invocations can reuse them.

`piper` is packaged as the optional extra `speakup[piper]`. The default TTS order becomes `omlx`, `piper`, `macos`; missing Piper dependencies, voices, or server failures are treated as provider failures and fall back to the next configured provider.

## Consequences

- Repeated notifications can reuse a warm Piper server across SpeakUp CLI invocations.
- The provider owns a small amount of local process lifecycle behavior, which is more complex than a pure HTTP client.
- Runtime process state is stored separately from notification history to keep user-facing history and infrastructure state distinct.
- The integration remains local-only by default and binds autostarted servers to `127.0.0.1`.
