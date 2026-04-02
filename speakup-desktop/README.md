# Speakup Desktop

A native desktop application for viewing notification history from the Speakup agent notification system.

## Features

- View notification history with filtering and search
- Filter by agent, event type, or search text
- Detailed view for each notification
- Audio playback support
- Dark mode interface

## Development

### Prerequisites

- Rust (https://rustup.rs)
- Tauri CLI v2: `cargo install tauri-cli --version "^2.0.0"`

### Run in Development Mode

```bash
cd speakup-desktop
cargo tauri dev
```

### Build for Production

```bash
cd speakup-desktop
cargo tauri build
```

The built application will be in `src-tauri/target/release/bundle/`.

## Architecture

- **Backend**: Rust with Tauri v2, reads from SQLite database
- **Frontend**: Vanilla HTML/CSS/JavaScript
- **Database**: Shared SQLite with the Python speakup library (`/tmp/speakup/history.db`)

## Integration

This desktop app reads from the same SQLite database that the main `speakup` Python library writes to. Make sure notifications are being saved to history by using the `NotifyService` with the `NotificationHistory` enabled.

## Launching from CLI

You can also launch the desktop app using the speakup CLI:

```bash
speakup desktop
```

This command is available after installing the main speakup package.
