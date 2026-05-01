# Agent Instructions

## Project context

- This is a Python package/CLI named `speakup`; source lives in `speakup/`, plugins in `plugins/`, and tests in `tests/`.
- The project uses Python >=3.13 and `uv` for running project commands.
- Keep runtime dependencies in `pyproject.toml`; avoid adding new dependencies unless the existing codebase already uses them or they are clearly necessary.

## Coding conventions

- Match the existing style and keep changes focused.
- Ruff is configured for Python 3.13 with line length 120; avoid broad formatting-only churn.
- Prefer structured logging patterns already used in the codebase; never log secrets, API keys, raw private context, or full config values.

## Testing and verification

For normal verification, run:

```bash
uv run pytest tests/ -q --ignore-glob="tests/test_integration_*.py"
```

For linting, run:

```bash
uv run ruff check .
```

- Run focused tests for touched areas during development, then the full non-integration test command before finishing.
- Do not run integration tests by default; they may require network access, audio tools, local services, or credentials.

## CLI and config changes

- When changing CLI behavior, add or update tests under `tests/test_cli.py` or the relevant `tests/test_integration_*.py` file.
- When changing config schema/defaults, update `config.example.jsonc` and related validation tests.
