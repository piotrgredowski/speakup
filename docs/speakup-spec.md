# SpeakUp Specification

## Overview

**SpeakUp** is a tool that improves developer experience when working with AI coding agents on **Open Mercato** by using an **agent-agnostic CLI**, **agent-specific extensions**, and **domain-specific knowledge** to detect when human input is needed, summarize the issue, and deliver a focused voice notification.

The first planned integrations are:
- **Codex**
- **Pi Coding Agent**

Nice-to-have integrations:
- **Claude Code**
- **OpenCode**

---

## Problem

When developers work with AI coding agents, they often need to constantly monitor terminal output or agent sessions in case the agent becomes blocked, needs clarification, or requires approval.

This leads to:
- attention fragmentation
- wasted time
- missed requests for input
- slower human-agent collaboration

This problem becomes even more important on a convention-heavy codebase like **Open Mercato**, where architectural patterns and stack-specific choices matter.

---

## Vision

SpeakUp acts as a **human-in-the-loop voice escalation layer** for AI-assisted development.

When an agent encounters a situation that requires a human, SpeakUp should:
1. detect that intervention is needed,
2. summarize the issue in short, clear language,
3. enrich the summary with project/domain-specific context,
4. notify the developer with a concise voice prompt.

The goal is to let developers **stay in flow** instead of **babysitting the agent session**.

---

## Product Shape

### Core product
An **agent-agnostic CLI** that provides commands for:
- ingesting agent events
- classifying whether human input is needed
- summarizing issues
- speaking notifications
- storing notification history
- applying project/domain profiles

### Extensions
Agent-specific extensions/adapters that translate a given agent's output into SpeakUp events.

Initial extensions:
- Codex
- Pi Coding Agent

Nice to have:
- Claude Code
- OpenCode

---

## Open Mercato connection

Although SpeakUp is designed to be agent-agnostic, it will support **domain-specific knowledge** so notifications can be more useful when working on **Open Mercato**.

That means SpeakUp should understand or recognize concepts like:
- MikroORM migrations
- Awilix dependency injection patterns
- zod validation choices
- Next.js architecture and conventions
- module-specific terminology in the Open Mercato codebase

This allows voice prompts to be short but still highly relevant.

Example:
- Generic prompt: “The agent needs input before continuing.”
- Open Mercato-aware prompt: “Codex needs input. This may affect a MikroORM migration in Open Mercato.”

---

## High-level workflow

1. A coding agent is working on an Open Mercato task.
2. The agent becomes blocked, uncertain, or needs approval.
3. An agent-specific extension emits an event into SpeakUp.
4. The SpeakUp CLI classifies the event.
5. SpeakUp enriches the summary using domain-specific knowledge.
6. SpeakUp delivers a short voice notification.
7. The developer returns only when needed and provides input.

---

## Example positioning

> I’m building **SpeakUp**, a tool that improves developer experience when working with AI coding agents on **Open Mercato** by using an agent-agnostic CLI and domain-specific knowledge to detect when human input is needed, summarize the issue, and deliver a focused voice notification; the first extensions will support **Codex** and **Pi Coding Agent**, with **Claude Code** and **OpenCode** planned as nice-to-have integrations.

---

## Why this fits the hackathon track

According to the Open Mercato track brief, projects should improve how developers work with coding agents on the Open Mercato codebase.

SpeakUp fits because it directly improves:
- developer attention management
- speed of human-agent handoff
- clarity of escalation
- productivity in agent-assisted workflows

It also has good demo potential because it can be shown live on a real coding task.

---

## MVP scope

### Must-have
- agent-agnostic CLI
- structured event ingestion
- detection of “needs human input” moments
- short summary generation
- local voice notification
- Open Mercato-aware domain enrichment
- initial extension for Codex
- initial extension for Pi Coding Agent

### Nice-to-have
- Claude Code extension
- OpenCode extension
- notification history view
- cooldown / deduplication
- desktop notification support
- better prioritization or urgency levels

---

## Example CLI directions

Potential commands:
- `speakup emit`
- `speakup classify`
- `speakup summarize`
- `speakup speak`
- `speakup notify`
- `speakup watch`
- `speakup history`
- `speakup config`

These commands would make the tool reusable across multiple agents and workflows.

---

## Example use cases

### Clarification
The agent finds two valid patterns in Open Mercato and asks which one to follow.

### Confirmation
The agent is about to generate a migration or apply a risky change.

### Blocked state
The agent is stalled or cannot continue without domain context.

### Review-ready
The agent has completed work and wants a human review.

---

## Key value proposition

SpeakUp is not another coding agent.
It is the **interrupt layer** between coding agents and developers.

Its value is:
- less terminal babysitting
- faster responses to agent questions
- more focused human input
- smoother collaboration on Open Mercato

---

## Presentation framing

A strong framing for demo day:

- **Problem:** developers must babysit coding agents.
- **Solution:** SpeakUp adds a voice-based human escalation layer.
- **Differentiator:** it is agent-agnostic, extension-based, and can apply Open Mercato domain knowledge.
- **Outcome:** developers stay in flow and intervene only when needed.

---

## Current presentation asset

A simple Manim overview animation currently exists at:
- `scripts/speakup_manim_simple.py`

Render example:
```bash
manim -pqh scripts/speakup_manim_simple.py SpeakUpSimple
```
