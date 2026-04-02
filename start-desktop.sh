#!/bin/bash
# Build and start the speakup desktop app

set -e
cd "$(dirname "$0")/speakup-desktop"

if [ "$1" = "build" ]; then
    echo "Building desktop app for production..."
    cargo tauri build
    echo "Build complete. App bundle available in src-tauri/target/release/bundle/"
else
    echo "Starting desktop app in development mode..."
    cargo tauri dev
fi
