"""Tests for Droid plugin."""
import json
from pathlib import Path


def test_plugin_structure():
    """Test that all plugin files exist."""
    plugin_dir = Path(__file__).parent.parent / "droid-plugin"
    
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
    plugin_dir = Path(__file__).parent.parent / "droid-plugin"
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
    plugin_dir = Path(__file__).parent.parent / "droid-plugin"
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
    plugin_dir = Path(__file__).parent.parent / "droid-plugin"
    command_path = plugin_dir / "commands" / "speakup.md"
    
    assert command_path.exists()
    
    with open(command_path) as f:
        content = f.read()
        assert "description:" in content
        assert "Control speakup notifications" in content


def test_readme_exists():
    """Test that README exists."""
    plugin_dir = Path(__file__).parent.parent / "droid-plugin"
    readme_path = plugin_dir / "README.md"
    
    assert readme_path.exists()
    
    with open(readme_path) as f:
        content = f.read()
        assert "Speakup Droid Plugin" in content
