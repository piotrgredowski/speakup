"""Tests for Droid plugin."""
import importlib.util
import json
from pathlib import Path


def load_hook_module():
    plugin_dir = Path(__file__).parent.parent / "plugins" / "speakup-factory-plugin"
    hook_path = plugin_dir / "hooks" / "speakup-hook.py"
    spec = importlib.util.spec_from_file_location("speakup_droid_hook", hook_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plugin_structure():
    """Test that all plugin files exist."""
    plugin_dir = Path(__file__).parent.parent / "plugins" / "speakup-factory-plugin"
    
    # Check manifest exists
    manifest_path = plugin_dir / ".factory-plugin" / "plugin.json"
    assert manifest_path.exists()
    
    with open(manifest_path) as f:
        manifest = json.load(f)
    
    assert manifest["name"] == "speakup"
    assert "description" in manifest
    assert "version" in manifest


def test_hooks_configuration():
    """Test that hooks configuration exists."""
    plugin_dir = Path(__file__).parent.parent / "plugins" / "speakup-factory-plugin"
    hooks_path = plugin_dir / "hooks" / "hooks.json"
    
    assert hooks_path.exists()
    
    with open(hooks_path) as f:
        hooks = json.load(f)
    
    # Check that all expected events are configured
    assert "Notification" in hooks["hooks"]
    assert "Stop" in hooks["hooks"]
    assert "SubagentStop" in hooks["hooks"]
    assert "SessionStart" in hooks["hooks"]


def test_hook_script_exists():
    """Test that hook script exists and is executable."""
    plugin_dir = Path(__file__).parent.parent / "plugins" / "speakup-factory-plugin"
    hook_script = plugin_dir / "hooks" / "speakup-hook.py"
    
    assert hook_script.exists()
    # Check it's a Python file (not executable via shebang on Windows)
    with open(hook_script) as f:
        content = f.read()
        assert "import json" in content
        assert "import subprocess" in content
        assert "def main():" in content


def test_slash_command_exists():
    """Test that slash command exists."""
    plugin_dir = Path(__file__).parent.parent / "plugins" / "speakup-factory-plugin"
    command_path = plugin_dir / "commands" / "speakup.md"
    
    assert command_path.exists()
    
    with open(command_path) as f:
        content = f.read()
        assert "description:" in content
        assert "Control speakup notifications" in content


def test_readme_exists():
    """Test that README exists."""
    plugin_dir = Path(__file__).parent.parent / "plugins" / "speakup-factory-plugin"
    readme_path = plugin_dir / "README.md"
    
    assert readme_path.exists()
    
    with open(readme_path) as f:
        content = f.read()
        assert "Speakup Droid Plugin" in content


def test_hook_prefers_jsonc_config(tmp_path, monkeypatch):
    module = load_hook_module()
    monkeypatch.setattr(module.Path, "home", lambda: tmp_path)

    cfg_dir = tmp_path / ".config" / "speakup"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.jsonc").write_text('{\n  // comment\n  "droid": {"enabled": false}\n}\n')

    assert module.get_config_path() == cfg_dir / "config.jsonc"
    assert module.load_droid_config()["enabled"] is False


def test_hook_falls_back_to_legacy_json_config(tmp_path, monkeypatch):
    module = load_hook_module()
    monkeypatch.setattr(module.Path, "home", lambda: tmp_path)

    cfg_dir = tmp_path / ".config" / "speakup"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(json.dumps({"droid": {"enabled": False}}))

    assert module.get_config_path() == cfg_dir / "config.json"
    assert module.load_droid_config()["enabled"] is False
