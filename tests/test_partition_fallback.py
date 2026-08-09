"""Issue #17: run.sh submits to exactly one partition, and a rejected
partition (routine on a shared cluster) fails the whole submission. These
tests cover the ordered fallback ladder (SLURM_PARTITION_FALLBACK) and the
per-partition walltime cap (SLURM_PARTITION_WALLTIME_CAP) described there.

Two seams:
  - unit: the walltime helpers, called directly after `source run.sh`. The
    CLI dispatch at the bottom of run.sh is guarded so sourcing does not run
    a subcommand.
  - CLI: `run.sh run` / `run.sh array` driven as a subprocess against a
    stub ssh, as in test_dispatcher_ledger.py.
"""
import os
import subprocess

import pytest

from lib import campaign


def _call(unity_dir, expr):
    return subprocess.run(
        ["bash", "-c", f'source "{unity_dir}/run.sh" && {expr}'],
        capture_output=True, text=True,
    )


@pytest.fixture
def unity_dir(tmp_project, materialise):
    return materialise(tmp_project, "cpu")


@pytest.mark.parametrize("walltime,seconds", [
    ("08:00:00", 28800),
    ("1-08:00:00", 115200),
    ("45:30", 2730),
    # A zero-padded day count is a plain SLURM walltime, and bash reads a
    # leading-zero number as octal: `08` and `09` are not valid octal, so
    # arithmetic on them aborts the script rather than mis-clamping quietly.
    ("08-00:00:00", 691200),
    ("09-12:00:00", 820800),
])
def test_walltime_seconds_parses_accepted_formats(unity_dir, walltime, seconds):
    result = _call(unity_dir, f'_walltime_seconds "{walltime}"')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(seconds)


def test_capped_walltime_passes_a_request_under_the_cap_through_unchanged(unity_dir):
    result = _call(unity_dir, '_capped_walltime "04:00:00" "08:00:00"')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "04:00:00"


def test_capped_walltime_clamps_a_request_over_the_cap(unity_dir):
    result = _call(unity_dir, '_capped_walltime "12:00:00" "08:00:00"')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "08:00:00"


def test_capped_walltime_with_no_cap_is_a_no_op(unity_dir):
    result = _call(unity_dir, '_capped_walltime "12:00:00" ""')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "12:00:00"


def test_walltime_cap_for_finds_the_matching_partition(unity_dir):
    result = _call(
        unity_dir,
        'SLURM_PARTITION_WALLTIME_CAP="ood-shared=08:00:00,cpu-preempt=02:00:00" '
        '_walltime_cap_for "ood-shared"')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "08:00:00"


def test_walltime_cap_for_a_partition_with_no_entry_is_empty(unity_dir):
    result = _call(
        unity_dir,
        'SLURM_PARTITION_WALLTIME_CAP="ood-shared=08:00:00" _walltime_cap_for "cpu"')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


# ─── CLI seam: run.sh run/array driven against a partition-aware stub ssh ───

STUB_SSH = r"""#!/usr/bin/env bash
# stub ssh: last argument is the remote command. sbatch's reply depends on
# which --partition= the command carries, so the fallback ladder has
# something real to retry against.
cmd="${!#}"
echo "$cmd" >>"$STUB_LOG"
case "$cmd" in
    *"cat >"*)
        if [ -n "${STUB_PAYLOAD_LOG:-}" ]; then
            cat >>"$STUB_PAYLOAD_LOG"
        else
            cat >/dev/null
        fi
        ;;
    *sbatch*)
        partition="$(printf '%s' "$cmd" | sed -n 's/.*--partition=\([^ ]*\).*/\1/p')"
        reject=0
        for p in ${STUB_REJECT_PARTITIONS:-}; do
            [ "$p" = "$partition" ] && reject=1
        done
        [ "${STUB_REJECT_ALL:-0}" = "1" ] && reject=1
        if [ "$reject" = "1" ]; then
            # A real rejection: sbatch says why on stderr and exits non-zero.
            printf 'sbatch: error: Batch job submission failed: Invalid partition specified: %s\n' "$partition" >&2
            exit 1
        elif [ "${STUB_SBATCH_UNPARSEABLE:-0}" = "1" ]; then
            # Accepted -- the job IS queued -- but the reply cannot be parsed
            # for a job id. An ssh hiccup after submit, or a warning-prefixed
            # reply, looks exactly like this.
            printf 'sbatch: Warning: unrecognised reply format\n'
            exit 0
        else
            printf 'Submitted batch job %s\n' "${STUB_SBATCH_JOB_ID:-12345}"
        fi
        ;;
    *sacct*)   printf '%s\n' "$STUB_SACCT" ;;
    *"test -d"*) exit "${STUB_REMOTE_RESULTS:-1}" ;;
    *tail*)    printf 'log line one\nlog line two\n' ;;
    *)         exit 0 ;;
esac
"""

STUB_TIMEOUT = r"""#!/usr/bin/env bash
printf 'timeout %s\n' "$*" >>"$STUB_LOG"
shift 2
exec "$@"
"""


@pytest.fixture
def dispatcher(tmp_project, materialise, tmp_path):
    unity_dir = materialise(tmp_project, "cpu")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("ssh", STUB_SSH), ("timeout", STUB_TIMEOUT)):
        p = bin_dir / name
        p.write_text(body)
        p.chmod(0o755)

    log = tmp_path / "stub.log"
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["STUB_LOG"] = str(log)
    env["STUB_SACCT"] = ""

    def run(*args, **overrides):
        call_env = dict(env)
        call_env.update({k: str(v) for k, v in overrides.items()})
        return subprocess.run(
            ["bash", str(unity_dir / "run.sh"), *args],
            capture_output=True, text=True, env=call_env, cwd=str(tmp_project),
        )

    run.project = tmp_project
    run.log = log
    return run


def _sbatch_calls(dispatcher):
    return [line for line in dispatcher.log.read_text().splitlines()
            if line.startswith("cd ") and "&& sbatch" in line]


def test_unset_fallback_keeps_todays_behaviour_exactly(dispatcher):
    """No SLURM_PARTITION_FALLBACK -> exactly one sbatch call, no synthetic
    --partition/--time override args added to it."""
    result = dispatcher("run", "smoke", "--campaign", "c1")
    assert result.returncode == 0, result.stderr
    calls = _sbatch_calls(dispatcher)
    assert len(calls) == 1
    assert "--partition=" not in calls[0]
    assert "--time=" not in calls[0]
    assert campaign.jobs(dispatcher.project, "c1")[0]["partition"] == "cpu"


def test_a_rejected_primary_falls_back_to_the_next_partition(dispatcher):
    result = dispatcher(
        "run", "smoke", "--campaign", "c1",
        SLURM_PARTITION_FALLBACK="cpu cpu-preempt ood-shared",
        STUB_REJECT_PARTITIONS="cpu",
    )
    assert result.returncode == 0, result.stderr
    calls = _sbatch_calls(dispatcher)
    assert len(calls) == 2
    assert "--partition=cpu " in calls[0] or calls[0].endswith("--partition=cpu")
    assert "--partition=cpu-preempt" in calls[1]

    rows = campaign.jobs(dispatcher.project, "c1")
    assert rows[0]["partition"] == "cpu-preempt"


def test_an_explicit_caller_partition_disables_the_ladder(dispatcher):
    """The caller named a partition for this one invocation, so it is honored
    alone -- even when every attempt is rejected and a fallback list is
    configured, the ladder must not kick in and try the other partitions."""
    result = dispatcher(
        "run", "smoke", "--campaign", "c1",
        SLURM_PARTITION="cpu",
        SLURM_PARTITION_FALLBACK="cpu cpu-preempt ood-shared",
        STUB_REJECT_ALL="1",
    )
    assert "WARNING" in result.stderr
    calls = _sbatch_calls(dispatcher)
    assert len(calls) == 1, calls
    assert "--partition=" not in calls[0]
    assert campaign.jobs(dispatcher.project, "c1") == []


def test_an_accepted_job_whose_reply_is_unreadable_is_never_resubmitted(dispatcher):
    """sbatch exited 0, so the job IS queued -- we just cannot name it.

    Walking to the next partition would queue a SECOND copy of the same job.
    Nothing downstream can clean that up: no job id was parsed, so no ledger
    row exists and the plugin's own scancel path cannot reach either copy.
    Only a non-zero sbatch exit means 'this partition refused the job' and is
    safe to retry."""
    result = dispatcher(
        "run", "smoke", "--campaign", "c1",
        SLURM_PARTITION_FALLBACK="cpu cpu-preempt ood-shared",
        STUB_SBATCH_UNPARSEABLE="1",
    )
    assert result.returncode == 0, result.stderr
    calls = _sbatch_calls(dispatcher)
    assert len(calls) == 1, f"the job was submitted {len(calls)} times: {calls}"
    assert "WARNING" in result.stderr
    assert campaign.jobs(dispatcher.project, "c1") == []


def test_a_rejection_partway_up_the_ladder_still_retries(dispatcher):
    """The guard above must not disarm the ladder: a genuine rejection is a
    non-zero exit, and those still walk to the next partition."""
    result = dispatcher(
        "run", "smoke", "--campaign", "c1",
        SLURM_PARTITION_FALLBACK="cpu cpu-preempt ood-shared",
        STUB_REJECT_PARTITIONS="cpu cpu-preempt",
    )
    assert result.returncode == 0, result.stderr
    assert len(_sbatch_calls(dispatcher)) == 3
    assert campaign.jobs(dispatcher.project, "c1")[0]["partition"] == "ood-shared"


def test_every_rung_rejected_warns_with_every_partition_tried(dispatcher):
    result = dispatcher(
        "run", "smoke", "--campaign", "c1",
        SLURM_PARTITION_FALLBACK="cpu cpu-preempt ood-shared",
        STUB_REJECT_ALL="1",
    )
    assert result.returncode == 0, result.stderr
    calls = _sbatch_calls(dispatcher)
    assert len(calls) == 3, calls
    assert "WARNING" in result.stderr
    assert "cpu cpu-preempt ood-shared" in result.stderr
    assert campaign.jobs(dispatcher.project, "c1") == []


def test_walltime_is_clamped_per_partition_before_each_retry(dispatcher, tmp_project,
                                                              materialise):
    materialise(tmp_project, "cpu", WALLTIME="12:00:00")
    result = dispatcher(
        "run", "smoke", "--campaign", "c1",
        SLURM_PARTITION_FALLBACK="cpu ood-shared",
        SLURM_PARTITION_WALLTIME_CAP="ood-shared=08:00:00",
        STUB_REJECT_PARTITIONS="cpu",
    )
    assert result.returncode == 0, result.stderr
    calls = _sbatch_calls(dispatcher)
    assert len(calls) == 2, calls
    assert "--partition=cpu --time=12:00:00" in calls[0]
    assert "--partition=ood-shared --time=08:00:00" in calls[1]


def test_array_submission_also_falls_back(dispatcher, tmp_path):
    manifest = tmp_path / "variants.txt"
    manifest.write_text("trial-a\ntrial-b\n")
    result = dispatcher(
        "array", str(manifest), "--campaign", "sweep-1",
        SLURM_PARTITION_FALLBACK="cpu cpu-preempt",
        STUB_REJECT_PARTITIONS="cpu",
    )
    assert result.returncode == 0, result.stderr
    calls = _sbatch_calls(dispatcher)
    assert len(calls) == 2, calls
    assert "--partition=cpu-preempt" in calls[1]
    rows = campaign.jobs(dispatcher.project, "sweep-1")
    assert {r["partition"] for r in rows} == {"cpu-preempt"}
