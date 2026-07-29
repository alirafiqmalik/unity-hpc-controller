from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent / "skills" / "setup" / "SKILL.md"


@pytest.fixture
def text():
    return SKILL.read_text()


def test_no_unresolvable_plugin_dir_placeholder(text):
    assert "<plugin_dir>" not in text, \
        "use ${CLAUDE_PLUGIN_ROOT}; <plugin_dir> cannot be resolved from the skill text"


def test_uses_the_plugin_root_variable(text):
    assert "${CLAUDE_PLUGIN_ROOT}" in text


def test_does_not_reference_another_plugins_path(text):
    assert "claude-plugins-official" not in text
    assert "superpowers" not in text


def test_git_branch_step_is_conditional(text):
    # setup must probe for a git repo before creating a branch, so it never
    # hard-fails in a non-git project.
    assert "git rev-parse --is-inside-work-tree" in text, \
        "setup must probe for a git repo before branching"
    lines = text.splitlines()
    guard_idx = next(
        i for i, line in enumerate(lines)
        if "git rev-parse --is-inside-work-tree" in line
    )
    for i, line in enumerate(lines):
        if "git checkout -b" in line:
            assert i > guard_idx, (
                "git checkout -b must be guarded by the git rev-parse probe, "
                "not run unconditionally"
            )


def test_collector_deployment_is_opt_in(text):
    lowered = text.lower()
    assert "opt-in" in lowered or "ask the user" in lowered
    assert "login node" in lowered
    assert "long-lived" in lowered or "persistent" in lowered


def test_scaffold_generation_is_invoked(text):
    assert "hpc-scaffold" in text
    assert "cpu" in text and "gpu" in text and "ml" in text


def test_setup_is_rerunnable(text):
    lowered = text.lower()
    assert "re-run" in lowered or "rerun" in lowered
    assert ".pre-redesign" in text
