# SpeakUp Context

## Agent integration

An Agent integration converts lifecycle events from a coding agent into SpeakUp notification requests.

## Codex plugin

A Codex plugin is the Codex-specific package that listens for Codex lifecycle events and forwards them to SpeakUp.

## Session key

A Session key is the stable identifier for one exact agent session. It is used for replay and session state.

## Needs input

Needs input means the agent is waiting for a user decision, approval, or answer before it can continue.

## Plan approval

Plan approval means Codex has presented an implementation plan and is waiting for the user to accept or revise it.

## Speech output

**Pronunciation adaptation**:
Pronunciation adaptation rewrites the final spoken text so a TTS voice can pronounce mixed-language phrases naturally for the chosen spoken language. It preserves the meaning and speech structure; it does not translate, summarize, or restyle the message.
_Avoid_: transliteration, translation

**Pronunciation adapter**:
A pronunciation adapter applies pronunciation adaptation as its own speech-preparation step. It is separate from summarization and from audio synthesis.
_Avoid_: summarizer, TTS provider

**Spoken language**:
Spoken language is the language whose pronunciation rules should shape the spoken output for one agent session. It belongs to the user session, not to the repository or project being discussed, and may be set by the user or inferred from the session.
_Avoid_: translation language

**Session state**:
Session state is the current mutable information SpeakUp knows about one agent session. It is the source of truth for session-scoped speech behavior, separate from notification history.
_Avoid_: session pointer, notification history
