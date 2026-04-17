from types import SimpleNamespace

import dunamai

import speakup.version as version_module


def test_get_version_uses_package_repo_instead_of_cwd(monkeypatch, tmp_path):
    version_module._cached_version = None
    captured: dict[str, object] = {}

    def fake_from_git(*, path=None, **kwargs):
        captured["path"] = path
        captured["kwargs"] = kwargs
        return SimpleNamespace(base="1.2.3", commit="abcdef1", distance=4, dirty=False)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(dunamai.Version, "from_git", fake_from_git)

    assert version_module.get_version() == "v1.2.3-4-gabcdef1"
    assert captured["path"] == version_module._repo_root()


def test_get_version_falls_back_to_package_metadata(monkeypatch):
    version_module._cached_version = None

    def fake_from_git(*, path=None, **kwargs):  # noqa: ARG001
        raise RuntimeError("not a git checkout")

    monkeypatch.setattr(dunamai.Version, "from_git", fake_from_git)
    monkeypatch.setattr(version_module, "package_version", lambda name: "0.1.0")

    assert version_module.get_version() == "v0.1.0"
