"""The two safe-name gates must agree on what a name is.

`_require_safe_name` exists twice on purpose. `templates/scaffold/common/run.sh`
is copied into consumer projects and must survive a plugin move, so it cannot
source plugin code; and every file in `scripts/` is symlinked onto the user's
PATH, so a shared helper there would become a user-visible command.

Two copies is the accepted trade. Silent divergence is not: a name that
`hpc-tmux start` accepts but `run.sh render` refuses means the same string names
a session and not the campaign it belongs to. These tests bind the pair.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DISPATCHER = REPO_ROOT / "templates" / "scaffold" / "common" / "run.sh"
TMUX = REPO_ROOT / "scripts" / "hpc-tmux"

# Same corpus the dispatcher's own gate is tested against in test_render.py.
REJECTED = [
    "evil; echo INJECTED", "has space", "back`tick`", "$(id)", "../escape",
    "-leading", ".leading", "pipe|pipe", "", "a" * 65,
]
ACCEPTED = ["baseline", "lr-1e-4", "run_7", "v1.2", "a", "a" * 64]


def _gate(script: Path) -> str:
    """The body of _require_safe_name, with the script's own log prefix removed."""
    text = script.read_text()
    start = text.index("_require_safe_name() {")
    end = text.index("\n}\n", start)
    body = text[start:end]
    return re.sub(r"\b(run\.sh|hpc-tmux):", "PREFIX:", body)


def _verdict(script: Path, name: str) -> int:
    """Exit code of the gate alone, called in a subshell with the name."""
    return subprocess.run(
        ["bash", "-c", f'{_gate(script)}\n}}\n_require_safe_name "name" "$1"',
         "_", name],
        capture_output=True, text=True,
    ).returncode


def test_the_two_gates_are_textually_identical():
    """Only the log prefix may differ. Any other edit must be made in both."""
    assert _gate(DISPATCHER) == _gate(TMUX), (
        "the safe-name gates have diverged — apply the change to both "
        f"{DISPATCHER.name} and {TMUX.name}"
    )


@pytest.mark.parametrize("name", REJECTED)
def test_both_gates_refuse_the_same_names(name):
    assert _verdict(DISPATCHER, name) == 2, f"dispatcher accepted {name!r}"
    assert _verdict(TMUX, name) == 2, f"hpc-tmux accepted {name!r}"


@pytest.mark.parametrize("name", ACCEPTED)
def test_both_gates_accept_the_same_names(name):
    assert _verdict(DISPATCHER, name) == 0, f"dispatcher refused {name!r}"
    assert _verdict(TMUX, name) == 0, f"hpc-tmux refused {name!r}"
