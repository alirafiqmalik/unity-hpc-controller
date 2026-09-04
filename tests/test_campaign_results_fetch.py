"""Issue #22: campaign-keyed results tree and prefer-if-present fetch.

Spec: docs/scaffold-axes-spec.md §6 / docs/design-decisions.md §3.6.
`REMOTE_RESULTS_DIR` is the artifacts *base*; `cmd_fetch` prefers
`<base>/<campaign>` when that subdirectory exists remotely -- so a later
campaign does not re-pay the rsync cost of every earlier one sharing the same
base -- and falls back to today's whole-tree rsync when it does not, so a
project whose remote job still writes a flat `_results/` keeps working.

These tests drive the real generated run.sh with a stub ssh/rsync on PATH, as
in test_cancel.py. The stub's `test -d` branch tells campaign-subdir probes
apart from base-dir probes by matching the tail of the quoted remote path, so
each of the three scenarios below can steer them independently.
"""

import os
import subprocess

import pytest

STUB_SSH = r"""#!/usr/bin/env bash
cmd="${!#}"
echo "$cmd" >>"$STUB_LOG"
case "$cmd" in
    *"cat >"*)      cat >/dev/null ;;
    *sbatch*)       printf '%s\n' "$STUB_SBATCH" ;;
    *sacct*)        printf '%s\n' "$STUB_SACCT" ;;
    *"test -d '"*"/${STUB_CAMPAIGN:-__unset__}'"*) exit "${STUB_CAMPAIGN_DIR_RC:-1}" ;;
    *"test -d '"*"/_results'"*) exit "${STUB_BASE_DIR_RC:-1}" ;;
    *"test -d"*)    exit 1 ;;
    *tail*)         printf 'log line one\nlog line two\n' ;;
    *)              exit 0 ;;
esac
"""

STUB_RSYNC = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >>"$STUB_LOG"
exit 0
"""

# materialise()'s default REMOTE_DIR (tests/conftest.py), appended last in the
# generated .env so it wins over the scaffold template's blank placeholder.
REMOTE_DIR = "/work/pi_test_umass_edu/tester/proj"


@pytest.fixture
def dispatcher(make_dispatcher):
    return make_dispatcher(
        {"ssh": STUB_SSH, "rsync": STUB_RSYNC},
        STUB_SBATCH="Submitted batch job 12345",
        STUB_SACCT="",
    )


def _artifact_rsync_calls(dispatcher):
    """rsync calls that land in `_results/<campaign>/artifacts/` -- distinct
    from the earlier rsync call that always pulls _slurm/*.out/*.err into
    `_results/<campaign>/` itself. The artifacts call's destination is the
    only one ending in `artifacts/`, regardless of REMOTE_RESULTS_DIR."""
    lines = dispatcher.log.read_text().splitlines() if dispatcher.log.exists() else []
    return [line for line in lines
            if line.startswith("-az") and line.rstrip().endswith("artifacts/")]


def _artifact_rsync_source(dispatcher):
    """The single `unity:<src>/` token of the artifacts-pulling rsync call,
    with the `unity:` prefix stripped."""
    calls = _artifact_rsync_calls(dispatcher)
    assert len(calls) == 1, f"expected exactly one artifacts rsync call, got {calls}"
    src = next(p for p in calls[0].split() if p.startswith("unity:"))
    return src[len("unity:"):]


def test_per_invocation_remote_results_dir_override_is_honoured_including_empty(dispatcher):
    """A caller-set REMOTE_RESULTS_DIR, even set to empty, must win over
    whatever .env already pins -- the same SET-not-just-non-empty contract
    every other UNITY_OVERRIDABLE variable gets."""
    env_file = dispatcher.project / "unityHPC" / ".env"
    with env_file.open("a") as fh:
        fh.write('\nREMOTE_RESULTS_DIR="/env/pinned-base"\n')

    # A non-empty per-invocation override replaces the .env value.
    result = dispatcher("fetch", "--campaign", "c1",
                         REMOTE_RESULTS_DIR="/override/base",
                         STUB_CAMPAIGN="c1", STUB_CAMPAIGN_DIR_RC="0")
    assert result.returncode == 0, result.stderr
    assert _artifact_rsync_source(dispatcher) == "/override/base/c1/"
    assert "/env/pinned-base" not in dispatcher.log.read_text()

    dispatcher.log.unlink()

    # Setting it to empty for one invocation must also win -- not be silently
    # re-filled by .env's non-empty value -- and fall back to the built-in
    # default (${REMOTE_DIR}/_results).
    result = dispatcher("fetch", "--campaign", "c1",
                         REMOTE_RESULTS_DIR="",
                         STUB_CAMPAIGN="c1", STUB_CAMPAIGN_DIR_RC="0")
    assert result.returncode == 0, result.stderr
    assert _artifact_rsync_source(dispatcher) == f"{REMOTE_DIR}/_results/c1/"
    assert "/env/pinned-base" not in dispatcher.log.read_text()


def test_campaign_subdir_present_does_not_pull_sibling_campaigns(dispatcher):
    dispatcher("run", "smoke", "--campaign", "c1")

    result = dispatcher("fetch", "--campaign", "c1",
                         STUB_CAMPAIGN="c1", STUB_CAMPAIGN_DIR_RC="0",
                         STUB_BASE_DIR_RC="0")

    assert result.returncode == 0, result.stderr
    # Scoped to the campaign subdir, never the whole _results/ tree, even
    # though the whole-tree base also happens to exist remotely here.
    assert _artifact_rsync_source(dispatcher) == f"{REMOTE_DIR}/_results/c1/"
    assert (dispatcher.project / "_results" / "c1" / "artifacts").is_dir()


def test_campaign_subdir_absent_matches_todays_whole_tree_fetch(dispatcher):
    dispatcher("run", "smoke", "--campaign", "c1")

    result = dispatcher("fetch", "--campaign", "c1",
                         STUB_CAMPAIGN="c1", STUB_CAMPAIGN_DIR_RC="1",
                         STUB_BASE_DIR_RC="0")

    assert result.returncode == 0, result.stderr
    assert _artifact_rsync_source(dispatcher) == f"{REMOTE_DIR}/_results/"
    assert (dispatcher.project / "_results" / "c1" / "artifacts").is_dir()


def test_neither_campaign_nor_base_present_skips_artifacts_fetch(dispatcher):
    dispatcher("run", "smoke", "--campaign", "c1")

    result = dispatcher("fetch", "--campaign", "c1",
                         STUB_CAMPAIGN="c1", STUB_CAMPAIGN_DIR_RC="1",
                         STUB_BASE_DIR_RC="1")

    assert result.returncode == 0, result.stderr
    assert not _artifact_rsync_calls(dispatcher)
    assert not (dispatcher.project / "_results" / "c1" / "artifacts").exists()


# ---------------------------------------------------------------------------
# The job side of §6: the scaffold must hand the job the campaign-keyed path,
# not just teach fetch to look for it. Without a handle, nothing directs a job
# to write where fetch now prefers to read.
# ---------------------------------------------------------------------------

def _resolved_results_dir(script, **env):
    """`$RESULTS_DIR` as the job body will actually see it.

    Replays the rendered script's own export lines in bash rather than
    matching their text: the value is built from three other exports, and a
    quoting bug there reads correctly while bash resolves it to something
    else."""
    wanted = ("EXP", "REMOTE_DIR", "CAMPAIGN", "REMOTE_RESULTS_DIR", "RESULTS_DIR")
    lines = [l for l in script.splitlines()
             if any(l.startswith(f"export {n}=") for n in wanted)]
    prelude = "\n".join(lines)
    return subprocess.run(
        ["bash", "-c", f'set -u\n{prelude}\nprintf %s "$RESULTS_DIR"'],
        capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", **env},
    )


@pytest.mark.parametrize("ptype", ["cpu", "gpu", "ml"])
def test_job_gets_results_dir_pointing_at_the_campaign_subtree(
        tmp_project, materialise, ptype):
    unity_dir = materialise(tmp_project, ptype)
    rendered = subprocess.run(
        ["bash", str(unity_dir / "run.sh"), "render", "baseline"],
        capture_output=True, text=True, env={**os.environ, "CAMPAIGN": "c1"},
    )
    assert rendered.returncode == 0, rendered.stderr

    resolved = _resolved_results_dir(rendered.stdout)
    assert resolved.returncode == 0, resolved.stderr
    assert resolved.stdout == f"{REMOTE_DIR}/_results/c1"


@pytest.mark.parametrize("ptype", ["cpu", "gpu", "ml"])
def test_results_dir_honours_the_remote_results_dir_base(
        tmp_project, materialise, ptype):
    unity_dir = materialise(tmp_project, ptype)
    rendered = subprocess.run(
        ["bash", str(unity_dir / "run.sh"), "render", "baseline"],
        capture_output=True, text=True,
        env={**os.environ, "CAMPAIGN": "c1", "REMOTE_RESULTS_DIR": "/scratch/out"},
    )
    assert rendered.returncode == 0, rendered.stderr

    resolved = _resolved_results_dir(rendered.stdout)
    assert resolved.returncode == 0, resolved.stderr
    assert resolved.stdout == "/scratch/out/c1"


@pytest.mark.parametrize("ptype", ["cpu", "gpu", "ml"])
def test_job_template_does_not_create_results_dir_eagerly(materialise, tmp_project, ptype):
    """An `mkdir -p "$RESULTS_DIR"` in the job body would make fetch's
    prefer-if-present probe succeed for every campaign, including one whose
    job in fact writes a flat `_results/`. Fetch would then scope to an empty
    directory and pull nothing -- the exact fallback §6 exists to preserve."""
    body = (materialise(tmp_project, ptype) / "job_template.sh").read_text()
    assert 'export RESULTS_DIR=' in body
    assert 'mkdir -p "$RESULTS_DIR"' not in body
    assert 'mkdir -p "${RESULTS_DIR}"' not in body


def test_render_rejects_an_invalid_campaign_instead_of_emitting_an_empty_one(
        tmp_project, materialise):
    """`local campaign="$(_campaign)"` takes the exit status of the `local`
    builtin, so `_campaign`'s `exit 2` died in the substitution subshell and
    render printed the rejection, emitted `export CAMPAIGN=''` and exited 0.
    Every other campaign entry point aborts here."""
    unity_dir = materialise(tmp_project, "cpu")
    result = subprocess.run(
        ["bash", str(unity_dir / "run.sh"), "render", "baseline"],
        capture_output=True, text=True, env={**os.environ, "CAMPAIGN": "bad name"},
    )
    assert result.returncode == 2, result.stdout
    assert "invalid campaign name" in result.stderr
    assert "export CAMPAIGN=" not in result.stdout
