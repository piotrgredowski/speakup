# Contributing to speakup

Thank you for helping improve `speakup`.

## Development setup

```bash
git clone https://github.com/piotrgredowski/speakup.git
cd speakup
uv sync --all-groups
```

## Validation

Before opening a pull request, run:

```bash
uv run pytest tests/ -v
uv run ruff check .
uv run python -m build
uv run twine check dist/*
```

For desktop changes, also run:

```bash
cargo check --manifest-path speakup-desktop/src-tauri/Cargo.toml
```

## Privacy rules for contributions

`speakup` handles coding-agent output, which can contain private source code or secrets.

- Do not log raw messages unless gated by `logging.log_message_text`.
- Do not log provider payloads unless gated by `logging.log_provider_payloads` and redaction.
- Keep hosted providers explicit opt-in.
- Prefer local-first defaults.
- Avoid adding test fixtures that contain real tokens, private transcripts, or customer code.

## Code style

- Match existing Python style and type hints.
- Keep adapters small and raise `AdapterError` for provider failures.
- Add tests for new provider/config behavior.
- Keep public dataclass fields backward-compatible unless the release notes call out a breaking change.

## Pull request process

1. Create a feature branch.
2. Make focused changes with tests.
3. Run the validation commands above.
4. Open a PR with a concise summary and privacy/security notes.

## Release process

Releases are maintainer-only and use GitHub Actions.

1. Ensure the working tree is clean and CI passes.
2. Run `./scripts/create_release.sh` or trigger `create-release.yml` manually.
3. The release workflow updates synchronized version metadata in:
   - `pyproject.toml`
   - `package.json`
   - `plugins/speakup-factory-plugin/.factory-plugin/plugin.json`
   - `speakup-desktop/src-tauri/Cargo.toml`
   - `speakup-desktop/src-tauri/tauri.conf.json`
4. Wait for TestPyPI publishing.
5. Test installation from TestPyPI.
6. Promote to PyPI with `publish-pypi.yml`.

## Questions or issues

Open a GitHub issue. Do not post secrets, API keys, or full private agent transcripts in public issues.
