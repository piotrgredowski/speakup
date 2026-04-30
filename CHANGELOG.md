# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Made defaults local-first and hosted providers explicit opt-in.
- Added privacy-focused history and logging guidance.
- Clarified desktop viewer as source/development-only until packaged separately.
- Improved collaboration docs, security policy, and issue/PR templates.

### Fixed
- Removed unregistered `omlx` summarizer from default summarization order.
- Corrected Droid and Pi plugin command examples.
- Documented Edge TTS and current Droid hook behavior.

## [0.3.0] - 2026-04-30

### Added
- Configurable dedup behavior.
- Optional Edge TTS provider.
- JSONC config path support.
- `show-config`, `show-config-path`, `show-logs`, and `show-logs-path` commands.
- Droid AskUser prompt support and exact session replay pointers.

### Changed
- Replaced manual config validation with typed dataclass schema validation.
- Moved logs to user state directories by default.
- Renamed and reorganized the Droid plugin under `plugins/speakup-factory-plugin`.

### Fixed
- Skipped non-informative summaries such as `NO_SPEAKUP_SUMMARY`.
- Improved short notification handling and hook summaries.

## [0.1.0] - 2025-04-02

### Added
- Initial release.
- Core TTS functionality with multiple provider support.
- Agent status summarization.
- CLI interface.
- Pi integration.
- Event-driven spoken notifications.
- Configuration management.
- Deduplication for progress messages.

[Unreleased]: https://github.com/piotrgredowski/speakup/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/piotrgredowski/speakup/releases/tag/v0.3.0
[0.1.0]: https://github.com/piotrgredowski/speakup/releases/tag/v0.1.0
