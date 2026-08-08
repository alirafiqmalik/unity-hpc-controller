"""Shipping-safety guards — the shipped code surface must stay free of the
author's real identifiers, so the plugin is safe to install for anyone.

Ported from the phd-agentic-tools marketplace suite when plugins moved into
standalone repositories.

Scoped to the generic code surface (lib/, scripts/, mcp/, bin/, tests/). The
plugin's own docs (README, skills, docs/) legitimately describe the author's
environment and are a separate "make public" decision — not scanned here.
"""

import subprocess
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

CODE_DIRS = ("lib", "scripts", "mcp", "bin", "tests")
AGENT_DIR = "agents"
BANNED = ("pi_taqi_umass_edu", "ahmalik", "autoresearch")

# Guard tests legitimately name the banned tokens in their own assertions, so
# they are excluded — a guard cannot scan another guard's token list without
# false-positiving on it.
EXCLUDED = {Path(__file__).name, "test_scaffold.py"}
SKIP_PARTS = {"__pycache__", ".git"}


def _code_files():
    for top in CODE_DIRS:
        for path in (PLUGIN_ROOT / top).rglob("*"):
            if not path.is_file() or SKIP_PARTS & set(path.parts):
                continue
            if path.name in EXCLUDED:
                continue
            if path.suffix in {".py", ".sh", ""}:
                yield path


def _text_files():
    """Every user-facing file in the plugin.

    The plugin's own `tests/` are excluded: guard tests legitimately name these
    placeholders inside their assertions, and a token in a test is an assertion
    about the placeholder, not a placeholder shipped to a user.
    """
    for path in PLUGIN_ROOT.rglob("*"):
        if not path.is_file() or SKIP_PARTS & set(path.parts):
            continue
        if "tests" in path.parts or path.name in EXCLUDED:
            continue
        if path.suffix in {".md", ".sh", ".py", ""}:
            yield path


def test_no_author_identifiers_in_shipped_code():
    offenders = []
    for path in _code_files():
        text = path.read_text(errors="replace")
        for token in BANNED:
            if token in text:
                offenders.append(f"{path.relative_to(PLUGIN_ROOT)}: {token}")
    assert not offenders, (
        "author identifiers leaked into shipped code — use neutral "
        f"placeholders (e.g. pi_yourlab_umass_edu):\n  " + "\n  ".join(offenders)
    )


def test_no_unresolvable_plugin_dir_placeholder():
    """`<plugin_dir>` is a docs placeholder that never resolves at runtime."""
    offenders = [
        str(p.relative_to(PLUGIN_ROOT))
        for p in _text_files()
        if "<plugin_dir>" in p.read_text(errors="replace")
    ]
    assert not offenders, f"<plugin_dir> still present in: {offenders}"


def test_agents_have_no_author_identifiers():
    offenders = []
    for path in (PLUGIN_ROOT / AGENT_DIR).rglob("*"):
        if not path.is_file() or SKIP_PARTS & set(path.parts):
            continue
        text = path.read_text(errors="replace")
        for token in BANNED:
            if token in text:
                offenders.append(f"{path.relative_to(PLUGIN_ROOT)}: {token}")
    assert not offenders, f"author identifiers leaked into agents: {offenders}"


def test_noninteractive_ssh_paths_are_bounded():
    offenders = []
    candidates = list((PLUGIN_ROOT / "scripts").glob("*"))
    candidates.append(PLUGIN_ROOT / "templates" / "scaffold" / "common" / "sync.sh")
    for path in candidates:
        if not path.is_file():
            continue
        if path.name in {"hpc-ssh", "release-check"}:
            continue
        for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "ssh" not in stripped:
                continue
            if path.name == "hpc-tmux" and "attach" in stripped:
                continue
            if "timeout" not in stripped and "SSH=(" not in stripped:
                offenders.append(f"{path.relative_to(PLUGIN_ROOT)}:{lineno}")
    assert not offenders, f"unbounded noninteractive SSH calls: {offenders}"


def test_release_tree_has_no_tracked_cache_files():
    result = subprocess.run(
        ["git", "ls-files", "*__pycache__*", "*.pyc", "*.pyo"],
        cwd=PLUGIN_ROOT, capture_output=True, text=True, check=True,
    )
    assert not result.stdout.strip(), "release tree tracks Python cache files"
