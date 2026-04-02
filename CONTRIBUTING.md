# Contributing to speakup

Thank you for your interest in contributing to speakup! This document provides guidelines and instructions for contributing.

## Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/piotrgredowski/speakup.git
   cd speakup
   ```

2. Install development dependencies:
   ```bash
   uv sync --all-groups
   ```

3. Run tests:
   ```bash
   uv run pytest tests/ -v
   ```

## Release Process

This project uses an automated release process with TestPyPI for testing before production deployment.

### Prerequisites

- Repository maintainers only
- `TESTPYPI_API_TOKEN` secret must be configured in GitHub
- `PYPI_API_TOKEN` secret must be configured in GitHub

### Creating a Release

#### Option 1: Using the Helper Script (Recommended)

```bash
./scripts/create_release.sh
```

This interactive script will:
- Validate your git status
- Prompt for version number
- Show recent commits
- Trigger the release workflow

#### Option 2: Manual Workflow Trigger

1. Go to [GitHub Actions](https://github.com/piotrgredowski/speakup/actions/workflows/create-release.yml)
2. Click "Run workflow"
3. Enter the version number (e.g., `1.0.0`)
4. Click "Run workflow"

#### Option 3: Manual Tag Creation

```bash
# Update version in pyproject.toml
sed -i 's/^version = .*/version = "1.0.0"/' pyproject.toml

# Commit and tag
git commit -am "chore: bump version to 1.0.0"
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin main --tags
```

### Release Workflow

Once a version tag is created:

1. **Automatic TestPyPI Publication**
   - The `publish-testpypi.yml` workflow triggers automatically
   - Package is built and published to TestPyPI
   - A GitHub prerelease is created with auto-generated changelog

2. **Testing**
   - Wait for the workflow to complete
   - Test installation:
     ```bash
     pip install --index-url https://test.pypi.org/simple/ speakup==1.0.0
     ```
   - Verify functionality

3. **Promotion to PyPI** (if tests pass)
   - Go to [PyPI Publish Workflow](https://github.com/piotrgredowski/speakup/actions/workflows/publish-pypi.yml)
   - Click "Run workflow"
   - Enter the version number (e.g., `1.0.0`)
   - Click "Run workflow"
   - Package is downloaded from TestPyPI and published to PyPI
   - GitHub prerelease is converted to a full release

### Version Management

- **Semantic Versioning**: We follow [SemVer](https://semver.org/) (MAJOR.MINOR.PATCH)
- **Git Tags**: Tags must be in format `vX.Y.Z` (e.g., `v1.0.0`)
- **pyproject.toml**: Version is automatically updated during release
- **Dynamic Versioning**: Runtime uses `dunamai` for git-based version detection

### Changelog

- **Auto-generated**: GitHub releases automatically generate changelogs from git commits
- **CHANGELOG.md**: Maintained manually for significant releases
- **Format**: Follows [Keep a Changelog](https://keepachangelog.com/)

## Code Style

- Follow PEP 8 guidelines
- Use type hints where appropriate
- Write docstrings for public functions and classes
- Keep functions focused and concise

## Testing

- Write tests for new functionality
- Ensure all tests pass before submitting PRs
- Use `pytest` for testing
- Mark integration tests with `@pytest.mark.integration_*`

## Pull Request Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Add/update tests
5. Ensure tests pass
6. Commit your changes (`git commit -am 'Add amazing feature'`)
7. Push to the branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

## Questions or Issues?

- Open an issue on [GitHub Issues](https://github.com/piotrgredowski/speakup/issues)
- Check existing issues before creating new ones
