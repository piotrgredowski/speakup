"""Backward-compatible entry point for let-me-know-pi command."""

import sys

from .cli import app


def main() -> None:
    """Thin wrapper that delegates to the unified Typer app."""
    app(["pi", *sys.argv[1:]])


if __name__ == "__main__":
    main()
