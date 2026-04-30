#!/bin/bash

# Release creation helper script for speakup
# This script helps create new releases by validating inputs and triggering GitHub workflows

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${BLUE}ℹ ${NC}$1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

# Check if we're in a git repository
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    print_error "Not in a git repository"
    exit 1
fi

# Check if we're on main branch
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "main" ]; then
    print_warning "Not on main branch (currently on: $CURRENT_BRANCH)"
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check for uncommitted changes
if ! git diff-index --quiet HEAD --; then
    print_error "You have uncommitted changes:"
    git status --short
    echo
    print_info "Please commit or stash your changes first."
    exit 1
fi

print_success "Working directory is clean"

# Get current version from pyproject.toml
CURRENT_VERSION=$(grep -Po '(?<=^version = ")[^"]*' pyproject.toml)
print_info "Current version: $CURRENT_VERSION"

# Prompt for new version
echo
read -p "Enter new version number (e.g., 1.0.0): " NEW_VERSION

# Validate version format
if ! [[ "$NEW_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    print_error "Invalid version format. Must be X.Y.Z (e.g., 1.0.0)"
    exit 1
fi

# Check if tag already exists
if git rev-parse "v$NEW_VERSION" >/dev/null 2>&1; then
    print_error "Tag v$NEW_VERSION already exists"
    exit 1
fi

print_info "Creating release v$NEW_VERSION..."

# Show recent commits for context
echo
print_info "Recent commits since last tag:"
LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
if [ -n "$LAST_TAG" ]; then
    git log "$LAST_TAG"..HEAD --oneline --decorate
else
    git log -10 --oneline --decorate
fi

echo
read -p "Create release v$NEW_VERSION? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    print_info "Aborted"
    exit 1
fi

# Check if gh CLI is available
if command -v gh &> /dev/null; then
    print_info "Using GitHub CLI to trigger workflow..."

    # Trigger the workflow
    gh workflow run create-release.yml -f version="$NEW_VERSION"

    print_success "Workflow triggered successfully!"
    echo
    print_info "Monitor the workflow at:"
    echo "  https://github.com/$(git remote get-url origin | sed 's/.*github.com[/:]\(.*\)\.git/\1/')/actions"
    echo
    print_info "Next steps:"
    echo "  1. Wait for the TestPyPI publish workflow to complete"
    echo "  2. Test the package: uv tool install --index https://test.pypi.org/simple/ speakup==$NEW_VERSION"
    echo "  3. If tests pass, trigger the PyPI publish workflow manually"
else
    print_warning "GitHub CLI not found. Manual steps required:"
    echo
    echo "  1. Update synchronized versions in pyproject.toml, package.json, plugin.json, Cargo.toml, and tauri.conf.json"
    echo "  2. Commit: git commit -am 'chore: bump version to $NEW_VERSION'"
    echo "  3. Tag: git tag -a v$NEW_VERSION -m 'Release v$NEW_VERSION'"
    echo "  4. Push: git push origin main --tags"
    echo
    print_info "Or install GitHub CLI: https://cli.github.com/"
fi
