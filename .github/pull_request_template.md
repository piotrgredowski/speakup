## Summary

-

## Validation

- [ ] `uv run pytest tests/ -v`
- [ ] `uv run ruff check .`
- [ ] `uv run python -m build`
- [ ] `uv run twine check dist/*`
- [ ] If hosted-provider integration behavior changed: `SPEAKUP_INTEGRATION_TEST_PROVIDER=cerebras SPEAKUP_INTEGRATION_TEST_MODEL=zai-glm-4.7 CEREBRAS_API_KEY=... uv run pytest tests/test_integration_cerebras.py tests/test_integration_pronunciation.py -v -m "integration_cerebras or integration_pronunciation"`

## Privacy/security notes

- [ ] This change does not log or store raw agent messages unexpectedly.
- [ ] Hosted providers remain explicit opt-in.
