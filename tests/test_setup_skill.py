"""Shipped runner instructions must reference available plugin resources."""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_skills_reference_registered_tools_and_existing_docs():
    module = ast.parse((ROOT / "mcp" / "hpc_server.py").read_text())
    registered = {
        keyword.value.value
        for node in ast.walk(module)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Tool"
        for keyword in node.keywords
        if keyword.arg == "name" and isinstance(keyword.value, ast.Constant)
    }
    for path in (ROOT / "skills").glob("*/SKILL.md"):
        text = path.read_text()
        tools = set(re.findall(r"mcp__unity-hpc__(unity_\w+)", text))
        assert tools, f"{path.name} must reference the plugin's tools"
        assert tools <= registered, f"{path}: unknown tools {tools - registered}"
        for target in re.findall(r"\]\((\.\.?/[^)]+)\)", text):
            assert (path.parent / target).is_file(), f"{path}: missing {target}"


def test_connect_has_no_unresolvable_plugin_placeholder():
    text = (ROOT / "skills" / "connect" / "SKILL.md").read_text()
    assert "<plugin_dir>" not in text
    assert "claude-plugins-official" not in text
    assert "superpowers" not in text
