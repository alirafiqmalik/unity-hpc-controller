"""Guard: the shipped code surface must stay free of the author's real
Unity identifiers, so the plugin is safe to install for anyone.

Scoped to the generic code surface (lib/, scripts/, mcp/, tests/). The
project's own docs (README, skills, docs/) legitimately describe the
author's environment and are a separate "make public" decision — they are
not scanned here.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCANNED = ("lib", "scripts", "mcp", "tests")
BANNED = ("pi_taqi_umass_edu", "ahmalik", "autoresearch")

# Guard tests legitimately name the banned tokens (in their own banned-list
# assertions), so they are excluded from this scan — a guard can't scan another
# guard's token list without false-positiving on it.
EXCLUDED = {Path(__file__).name, "test_scaffold.py"}


def _code_files():
    for top in SCANNED:
        for path in (REPO_ROOT / top).rglob("*"):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.name in EXCLUDED:
                continue
            if path.suffix in {".py", ".sh", ""}:
                yield path


def test_no_author_identifiers_in_shipped_code():
    offenders = []
    for path in _code_files():
        text = path.read_text(errors="replace")
        for token in BANNED:
            if token in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {token}")
    assert not offenders, (
        "author identifiers leaked into shipped code — use neutral "
        f"placeholders (e.g. pi_yourlab_umass_edu):\n  " + "\n  ".join(offenders)
    )
