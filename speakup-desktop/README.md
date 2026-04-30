# Speakup Desktop

A Tauri-based development viewer for local `speakup` notification history.

## Status

This app is currently source-checkout/development-only. It is not packaged as part of the PyPI `speakup` CLI distribution.

## Features

- View notification history from the local SQLite database.
- Filter by agent, event type, or search text.
- Inspect notification metadata.
- Open saved audio files with the system player when available.

## Database path

The desktop app reads the same runtime history path as Python `speakup`:

```text
<system temp dir>/speakup/history.db
```

On macOS this is usually under `/var/folders/.../T/speakup/history.db`, not necessarily `/tmp/speakup/history.db`.

## Development

Prerequisites:

- Rust: https://rustup.rs
- Tauri CLI v2: `cargo install tauri-cli --version "^2.0.0"`

Run:

```bash
cd speakup-desktop
cargo tauri dev
```

Build:

```bash
cd speakup-desktop
cargo tauri build
```

## Launching from the Python CLI

From a source checkout with the desktop app built:

```bash
speakup desktop
```

For development mode:

```bash
speakup desktop --dev
```
