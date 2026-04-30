from __future__ import annotations

from pathlib import Path

from speakup.context_naming import find_project_root, project_config_path, resolve_spoken_context, verbalize_project_name


def test_verbalize_project_name_splits_common_separators() -> None:
    assert verbalize_project_name("speakup-desktop") == "speakup desktop"
    assert verbalize_project_name("SpeakUpDesktop") == "Speak Up Desktop"


def test_find_project_root_walks_up_to_git_directory(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    nested = root / "packages" / "app"
    (root / ".git").mkdir(parents=True)
    nested.mkdir(parents=True)

    assert find_project_root(nested) == root
    assert project_config_path(nested) == root / ".speakup.jsonc"


def test_resolve_spoken_context_uses_repository_override(tmp_path: Path) -> None:
    repo = tmp_path / "actual-name"
    (repo / ".git").mkdir(parents=True)

    context = resolve_spoken_context(
        cwd=repo,
        session_name="Nightly Run",
        config={"source": "repository", "spoken_name": "Speak Up"},
    )

    assert context is not None
    assert context.kind == "repository"
    assert context.name == "Speak Up"


def test_resolve_spoken_context_defaults_to_session_name() -> None:
    context = resolve_spoken_context(cwd=None, session_name="Nightly Run", config={"source": "session"})

    assert context is not None
    assert context.kind == "session"
    assert context.name == "Nightly Run"
