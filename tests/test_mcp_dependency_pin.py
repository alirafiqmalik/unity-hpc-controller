"""Guard: the MCP SDK dependency must carry an upper bound.

`.mcp.json` declared `mcp>=1.0.0`. `uv run --with` re-resolves on every server
start, so the day mcp 2.0.0 shipped, every existing install started resolving
it and the server died at import with:

    AttributeError: 'Server' object has no attribute 'list_tools'

Nothing in the repo changed — the break arrived with the calendar, and hit
already-released versions retroactively. An unbounded major range on the
protocol library is therefore a latent outage, not a style preference.

The version floor is deliberately left alone; only the ceiling is required.
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MCP_JSON = REPO_ROOT / ".mcp.json"
REQUIREMENTS = REPO_ROOT / "mcp" / "requirements.txt"

# e.g. "mcp>=1.0.0,<2" — a bare "mcp>=1.0.0" must fail.
_UPPER_BOUND = re.compile(r"(<|==|~=)")


def _mcp_specs_from_mcp_json() -> list[str]:
    args = json.loads(MCP_JSON.read_text())["mcpServers"]["unity-hpc"]["args"]
    return [a for a in args if a.replace("_", "-").startswith("mcp")]


def test_mcp_json_pins_an_upper_bound():
    specs = _mcp_specs_from_mcp_json()
    assert specs, ".mcp.json no longer declares an mcp dependency — has the launch changed?"
    for spec in specs:
        assert _UPPER_BOUND.search(spec), (
            f".mcp.json declares {spec!r} with no upper bound. uv re-resolves on every "
            "server start, so the next major release breaks every installed version."
        )


def test_requirements_pins_an_upper_bound():
    lines = [
        line.strip()
        for line in REQUIREMENTS.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    mcp_lines = [line for line in lines if re.match(r"^mcp\b", line)]
    assert mcp_lines, "mcp/requirements.txt no longer lists mcp"
    for line in mcp_lines:
        assert _UPPER_BOUND.search(line), (
            f"requirements.txt declares {line!r} with no upper bound — it must agree "
            "with .mcp.json, which is what actually launches the server."
        )


def test_the_two_declarations_agree():
    """requirements.txt documents what .mcp.json launches; drift between them
    means a manual `uv pip install -r` reproduces a different environment."""
    from_json = {s.replace(" ", "") for s in _mcp_specs_from_mcp_json()}
    from_req = {
        line.strip().replace(" ", "")
        for line in REQUIREMENTS.read_text().splitlines()
        if re.match(r"^mcp\b", line.strip())
    }
    assert from_json == from_req, (
        f".mcp.json declares {sorted(from_json)} but requirements.txt declares "
        f"{sorted(from_req)} — keep them identical")
