"""Integration tests for pronunciation adapters using the selected real provider.

These tests run against the selected integration provider, auto-detected from available API keys by default.
They require the selected provider API key.
Set SPEAKUP_INTEGRATION_TEST_MODEL to override the selected provider model.
"""

from __future__ import annotations

import os
from typing import TypedDict

import pytest

from speakup.config import Config, default_config
from speakup.pronunciation import PronunciationAdapter
from speakup.service import build_registry_from_config

from .conftest import (
    integration_provider_has_key,
    integration_provider_requires_key,
    selected_integration_provider,
)


def _selected_provider_is_available() -> bool:
    provider = selected_integration_provider()
    if not provider:
        return False
    return not integration_provider_requires_key(provider) or integration_provider_has_key(provider)


pytestmark = pytest.mark.skipif(
    not _selected_provider_is_available(),
    reason="Pronunciation integration tests require a selected integration provider and required API key if remote",
)


def _configured_pronunciation_adapter() -> PronunciationAdapter:
    provider = selected_integration_provider()
    raw = default_config()
    raw["privacy"]["mode"] = "prefer_local"
    raw["privacy"]["allow_remote_fallback"] = True
    raw["pronunciation"]["provider_order"] = [provider]
    if model := os.environ.get("SPEAKUP_INTEGRATION_TEST_MODEL", "").strip():
        raw["providers"].setdefault(provider, {})["model"] = model

    registry = build_registry_from_config(Config(raw))
    if not registry.has_pronunciation(provider):
        pytest.skip(f"{provider} is not a pronunciation provider")
    return registry.get_pronunciation(provider)


class PronunciationCase(TypedDict):
    id: str
    case_name: str
    title: str | None
    message: str
    spoken_language: str | None
    expected_title: str | None
    expected_message: str


PRONUNCIATION_CASE_FIELDS = (
    "case_name",
    "title",
    "message",
    "spoken_language",
    "expected_title",
    "expected_message",
)


def _parametrize_cases(cases: list[PronunciationCase]) -> list[pytest.ParameterSet]:
    return [
        pytest.param(
            *(case[field] for field in PRONUNCIATION_CASE_FIELDS),
            id=case["id"],
        )
        for case in cases
    ]


PRONUNCIATION_CASES: list[PronunciationCase] = [
    {
        "id": "github-action-failed",
        "case_name": "github_action_failed",
        "title": None,
        "message": "GitHub action failed",
        "spoken_language": "pl",
        "expected_title": None,
        "expected_message": "GitHab ekszyn fejld",
    },
    {
        "id": "build-failed-polish-context",
        "case_name": "build_failed_in_polish_sentence",
        "title": None,
        "message": "Build failed w module płatności",
        "spoken_language": "pl",
        "expected_title": None,
        "expected_message": "Bild fejld w module płatności",
    },
    {
        "id": "tests-passed",
        "case_name": "tests_passed",
        "title": None,
        "message": "Tests passed",
        "spoken_language": "pl",
        "expected_title": None,
        "expected_message": "Tests pasd",
    },
    {
        "id": "pull-request-ready",
        "case_name": "pull_request_ready",
        "title": None,
        "message": "Pull request ready for review",
        "spoken_language": "pl",
        "expected_title": None,
        "expected_message": "Pul rikłest redi for rewju",
    },
    {
        "id": "merge-conflict",
        "case_name": "merge_conflict_detected",
        "title": None,
        "message": "Merge conflict detected",
        "spoken_language": "pl",
        "expected_title": None,
        "expected_message": "Merdż konflikt detekted",
    },
    {
        "id": "npm-install-failed",
        "case_name": "npm_install_failed",
        "title": None,
        "message": "npm install failed",
        "spoken_language": "pl",
        "expected_title": None,
        "expected_message": "en pi em instal fejld",
    },
    {
        "id": "docker-build-complete",
        "case_name": "docker_build_complete",
        "title": None,
        "message": "Docker build complete",
        "spoken_language": "pl",
        "expected_title": None,
        "expected_message": "Doker bild komplit",
    },
    {
        "id": "typecheck-failed",
        "case_name": "typecheck_failed",
        "title": None,
        "message": "Typecheck failed",
        "spoken_language": "pl",
        "expected_title": None,
        "expected_message": "Tajpczek fejld",
    },
    {
        "id": "lint-errors-found",
        "case_name": "lint_errors_found",
        "title": None,
        "message": "Lint errors found",
        "spoken_language": "pl",
        "expected_title": None,
        "expected_message": "Lint erors faund",
    },
    {
        "id": "deployment-finished",
        "case_name": "deployment_finished",
        "title": None,
        "message": "Deployment finished",
        "spoken_language": "pl",
        "expected_title": None,
        "expected_message": "Diplojment finiszd",
    },
    {
        "id": "cache-warmup-complete",
        "case_name": "cache_warmup_complete",
        "title": None,
        "message": "Cache warmup zakończony",
        "spoken_language": "pl",
        "expected_title": None,
        "expected_message": "Kesz łormap zakończony",
    },
    {
        "id": "webhook-payload-invalid",
        "case_name": "webhook_payload_invalid",
        "title": None,
        "message": "Webhook payload jest invalid",
        "spoken_language": "pl",
        "expected_title": None,
        "expected_message": "Łebhuk pejload jest invalid",
    },
    {
        "id": "rate-limit-exceeded",
        "case_name": "rate_limit_exceeded",
        "title": None,
        "message": "Rate limit przekroczony",
        "spoken_language": "pl",
        "expected_title": None,
        "expected_message": "Rejt limit przekroczony",
    },
    {
        "id": "schema-validation-failed",
        "case_name": "schema_validation_failed",
        "title": None,
        "message": "Schema validation nie przeszła",
        "spoken_language": "pl",
        "expected_title": None,
        "expected_message": "Skima walidejszyn nie przeszła",
    },
    {
        "id": "token-refresh-needed",
        "case_name": "token_refresh_needed",
        "title": None,
        "message": "Potrzebny token refresh",
        "spoken_language": "pl",
        "expected_title": None,
        "expected_message": "Potrzebny token rifresz",
    },
    {
        "id": "workspace-index-ready",
        "case_name": "workspace_index_ready",
        "title": None,
        "message": "Workspace index gotowy",
        "spoken_language": "pl",
        "expected_title": None,
        "expected_message": "Łorkspejs indeks gotowy",
    },
    {
        "id": "migration-rollback-started",
        "case_name": "migration_rollback_started",
        "title": None,
        "message": "Migration rollback wystartował",
        "spoken_language": "pl",
        "expected_title": None,
        "expected_message": "Majgrejszyn rolbak wystartował",
    },
    {
        "id": "parser-timeout",
        "case_name": "parser_timeout",
        "title": None,
        "message": "Parser złapał timeout",
        "spoken_language": "pl",
        "expected_title": None,
        "expected_message": "Parser złapał tajmaut",
    },
    {
        "id": "release-draft-published",
        "case_name": "release_draft_published",
        "title": None,
        "message": "Release draft opublikowany",
        "spoken_language": "pl",
        "expected_title": None,
        "expected_message": "Rilis draft opublikowany",
    },
    {
        "id": "snapshot-upload-failed",
        "case_name": "snapshot_upload_failed",
        "title": None,
        "message": "Snapshot upload się nie udał",
        "spoken_language": "pl",
        "expected_title": None,
        "expected_message": "Snapshot upload się nie udał",
    },
    {
        "id": "queue-drained",
        "case_name": "queue_drained",
        "title": None,
        "message": "Queue jest puste",
        "spoken_language": "pl",
        "expected_title": None,
        "expected_message": "Kju jest puste",
    },
    {
        "id": "feature-flag-enabled",
        "case_name": "feature_flag_enabled",
        "title": None,
        "message": "Feature flag włączony",
        "spoken_language": "pl",
        "expected_title": None,
        "expected_message": "Ficzer flag włączony",
    },
]


@pytest.mark.integration_pronunciation
@pytest.mark.parametrize(
    PRONUNCIATION_CASE_FIELDS,
    _parametrize_cases(PRONUNCIATION_CASES),
)
def test_real_pronunciation_provider_adapts_segments(
    case_name: str,
    title: str | None,
    message: str,
    spoken_language: str | None,
    expected_title: str | None,
    expected_message: str,
) -> None:
    adapter = _configured_pronunciation_adapter()

    print(f"\nInput title:\n{title}")
    print(f"\nInput message:\n{message}")
    print(f"\nExpected title:\n{expected_title}")
    print(f"\nExpected message:\n{expected_message}")

    result = adapter.adapt(title=title, message=message, spoken_language=spoken_language)

    print(f"\nOutput title:\n{result.title}")
    print(f"\nOutput message:\n{result.message}")

    assert result.title == expected_title
    assert result.message == expected_message
