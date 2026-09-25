"""Exercise the same Git diff and manifests that the PR release gate reads."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFESTS = (".claude-plugin/plugin.json", ".codex-plugin/plugin.json")


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


def _version(repo, manifest, version):
    (repo / manifest).write_text(json.dumps({"version": version}))


@pytest.fixture
def release_repo(tmp_path):
    repo = tmp_path / "plugin"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")
    for manifest in MANIFESTS:
        (repo / manifest).parent.mkdir()
        _version(repo, manifest, "0.13.0")
    (repo / "scripts").mkdir()
    shutil.copy2(REPO_ROOT / "scripts/release-check", repo / "scripts/release-check")
    (repo / "lib").mkdir()
    (repo / "lib/feature.py").write_text("original\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    return repo


def _check(repo):
    return subprocess.run(
        [sys.executable, str(repo / "scripts/release-check"), "--base", "HEAD~1"],
        capture_output=True, text=True,
    )


def _commit(repo):
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "change")


def test_shipped_change_without_bump_names_file_and_fix(release_repo):
    (release_repo / "lib/feature.py").write_text("changed\n")
    _commit(release_repo)

    result = _check(release_repo)

    assert result.returncode == 1, result.stderr
    assert "still 0.13.0" in result.stderr
    assert "lib/feature.py" in result.stderr
    assert "both plugin manifests" in result.stderr


def test_test_and_workflow_changes_do_not_require_bump(release_repo):
    (release_repo / "tests").mkdir()
    (release_repo / "tests/test_example.py").write_text("pass\n")
    (release_repo / ".github/workflows").mkdir(parents=True)
    (release_repo / ".github/workflows/test.yml").write_text("name: test\n")
    _commit(release_repo)

    result = _check(release_repo)

    assert result.returncode == 0, result.stderr
    assert "no shipped file changed" in result.stdout


def test_shipped_change_with_both_versions_bumped_passes(release_repo):
    (release_repo / "lib/feature.py").write_text("changed\n")
    for manifest in MANIFESTS:
        _version(release_repo, manifest, "0.14.0")
    _commit(release_repo)

    result = _check(release_repo)

    assert result.returncode == 0, result.stderr
    assert "new version" in result.stdout


def test_mismatched_manifest_versions_name_each_manifest(release_repo):
    (release_repo / "lib/feature.py").write_text("changed\n")
    _version(release_repo, MANIFESTS[0], "0.14.0")
    _commit(release_repo)

    result = _check(release_repo)

    assert result.returncode == 1, result.stderr
    assert "manifest versions differ" in result.stderr
    for manifest in MANIFESTS:
        assert manifest in result.stderr
