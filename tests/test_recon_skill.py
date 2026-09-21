from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent / "controller" / "ops" / "recon.md"


@pytest.fixture
def text():
    return SKILL.read_text()


def test_produces_json_not_prose_profile(text):
    assert "cluster-config.json" in text
    assert "cluster-profile.md" not in text, \
        "recon must stop producing the prose profile that got clobbered (RC-3)"


def test_writes_through_the_locked_cli_not_a_blind_overwrite(text):
    assert "hpc-config-write" in text
    lowered = text.lower()
    assert "overwrite" not in lowered, "no blind create-or-overwrite (RC-3)"


def test_uses_the_path_and_pager_fix(text):
    assert "/modules/user-resources/bin" in text
    assert "PAGER=NONE" in text


def test_is_cluster_neutral(text):
    lowered = text.lower()
    assert "not used by this project" not in lowered
    assert "cluster-neutral" in lowered or "no project" in lowered


def test_mentions_the_ttl_staleness_guard(text):
    assert "UNITY_HPC_RECON_TTL" in text
    assert "--force" in text


def test_resolves_plugin_root(text):
    assert "${CLAUDE_PLUGIN_ROOT}" in text
    assert "<plugin_dir>" not in text
