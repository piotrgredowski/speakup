# Speakup product spec

## Purpose

`speakup` is a local-first voice notification layer for coding agents. It helps developers stop watching terminal output continuously by speaking concise updates only when an agent needs attention, reports progress, fails, or finishes.

## Goals

- Keep developers in flow while agents work.
- Preserve privacy by default.
- Support multiple agents through small integration adapters.
- Support multiple summarization and TTS providers through clear provider interfaces.
- Make replay and session tracking reliable enough for daily use.

## Non-goals

- `speakup` is not a coding agent.
- `speakup` should not require hosted AI services by default.
- Desktop packaging is not part of the PyPI CLI distribution yet.

## Event model

Supported events:

- `needs_input`: the agent requires a user decision or approval.
- `final`: the agent finished a response or task.
- `error`: the agent or tool hit a failure.
- `progress`: useful progress update.
- `info`: low-urgency notification.

Integrations should pass a stable `session_key` when available so replay can target the exact current agent session.

## Data flow

1. Agent plugin receives an event.
2. Plugin maps the event into `NotifyRequest`.
3. `NotifyService` applies config, privacy policy, deduplication, and session naming.
4. A summarizer creates short spoken text.
5. A TTS provider generates audio.
6. Playback runs locally.
7. History stores replay metadata and summaries. Raw messages are not stored by default.

## Privacy principles

- Local providers are the default.
- Hosted providers require explicit provider order/config changes.
- Raw messages are not logged or stored unless explicitly enabled.
- Redaction should apply to payloads that may contain credentials.

## Extension points

- Agent integrations convert external event payloads into `NotifyRequest`.
- Summarizers implement `speakup.summarizers.base.Summarizer`.
- TTS providers implement `speakup.tts.base.TTSAdapter`.
- Playback backends implement `speakup.playback.base.PlaybackAdapter`.

## Public readiness checklist

- Local-first defaults pass tests.
- README documents privacy, providers, and integrations accurately.
- Config examples match embedded defaults.
- CI runs tests, Ruff, package build/check, and desktop crate checks.
- Security and collaboration docs exist.
