"""Issue #21: `run.sh cancel --campaign N [--job parent]`.

Spec: docs/scaffold-axes-spec.md §5 / docs/design-decisions.md §3.6. The
ledger and the array-id convention are internal to run.sh, so cancel lives
there rather than in the plugin. These tests drive the real generated
run.sh with a stub `ssh`/`rsync` on PATH, as in test_partition_fallback.py.
"""

import pytest

from lib import campaign

STUB_SSH = r"""#!/usr/bin/env bash
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
    *sbatch*)  printf '%s\n' "$STUB_SBATCH" ;;
    *sacct*)   printf '%s\n' "$STUB_SACCT" ;;
    *scancel*) exit "${STUB_SCANCEL_RC:-0}" ;;
    *"test -d"*) exit "${STUB_REMOTE_RESULTS:-1}" ;;
    *tail*)    printf 'log line one\nlog line two\n' ;;
    *)         exit 0 ;;
esac
"""

STUB_RSYNC = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >>"$STUB_LOG"
exit 0
"""


@pytest.fixture
def dispatcher(make_dispatcher):
    return make_dispatcher(
        {"ssh": STUB_SSH, "rsync": STUB_RSYNC},
        STUB_SBATCH="Submitted batch job 12345",
        STUB_SACCT="",
    )


def _scancel_calls(dispatcher):
    """The remote command the stub ssh received, not the `timeout` wrapper
    line that also logs it -- both share the word "scancel"."""
    if not dispatcher.log.exists():
        return []
    return [line for line in dispatcher.log.read_text().splitlines()
            if line.startswith("scancel")]


def test_array_children_collapse_to_one_parent_id(dispatcher, tmp_path):
    manifest = tmp_path / "variants.txt"
    manifest.write_text("trial-a\ntrial-b\ntrial-c\n")
    dispatcher("array", str(manifest), "--campaign", "sweep-1")

    result = dispatcher("cancel", "--campaign", "sweep-1")

    assert result.returncode == 0, result.stderr
    calls = _scancel_calls(dispatcher)
    assert calls == ["scancel 12345"]


def test_terminal_rows_are_skipped(dispatcher):
    dispatcher("run", "a", "--campaign", "c1", STUB_SBATCH="Submitted batch job 1")
    dispatcher("run", "b", "--campaign", "c1", STUB_SBATCH="Submitted batch job 2")
    dispatcher("status", "--campaign", "c1", STUB_SACCT="1|COMPLETED|cpu|00:00:21")

    result = dispatcher("cancel", "--campaign", "c1")

    assert result.returncode == 0, result.stderr
    calls = _scancel_calls(dispatcher)
    assert calls == ["scancel 2"]
    rows = {r["job_id"]: r["status"] for r in campaign.jobs(dispatcher.project, "c1")}
    assert rows["1"] == "COMPLETED"
    assert rows["2"] == "CANCELLED"


def test_empty_scope_exits_nonzero_and_does_not_call_scancel(dispatcher):
    result = dispatcher("cancel", "--campaign", "nothing-here")

    assert result.returncode != 0
    assert not dispatcher.log.exists(), "an empty scope must never touch the cluster"


def test_ledger_rows_for_cancelled_ids_become_cancelled(dispatcher):
    dispatcher("run", "smoke", "--campaign", "c1")

    result = dispatcher("cancel", "--campaign", "c1")

    assert result.returncode == 0, result.stderr
    rows = campaign.jobs(dispatcher.project, "c1")
    assert rows[0]["status"] == "CANCELLED"


def test_job_flag_pins_one_group(dispatcher, tmp_path):
    manifest = tmp_path / "variants.txt"
    manifest.write_text("trial-a\ntrial-b\n")
    dispatcher("array", str(manifest), "--campaign", "sweep-1",
               STUB_SBATCH="Submitted batch job 12345")
    dispatcher("run", "solo", "--campaign", "sweep-1",
               STUB_SBATCH="Submitted batch job 999")

    result = dispatcher("cancel", "--campaign", "sweep-1", "--job", "12345")

    assert result.returncode == 0, result.stderr
    calls = _scancel_calls(dispatcher)
    assert calls == ["scancel 12345"]
    rows = {r["job_id"]: r["status"] for r in campaign.jobs(dispatcher.project, "sweep-1")}
    assert rows["12345_0"] == "CANCELLED"
    assert rows["12345_1"] == "CANCELLED"
    assert rows["999"] == "PENDING"


def test_scancel_failure_leaves_the_ledger_untouched(dispatcher):
    dispatcher("run", "smoke", "--campaign", "c1")

    result = dispatcher("cancel", "--campaign", "c1", STUB_SCANCEL_RC="1")

    assert result.returncode != 0
    rows = campaign.jobs(dispatcher.project, "c1")
    assert rows[0]["status"] == "PENDING"
