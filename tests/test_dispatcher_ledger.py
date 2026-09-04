"""The dispatcher must record what it submits.

Before this, `run.sh run` submitted a job and told nobody: every management
tool (`unity_status`, `unity_jobs`, `unity_my_jobs`) reads the ledger, and the
ledger was never written. A project could not name the jobs it had launched.

These tests drive the real generated `run.sh` with a stub `ssh`/`rsync` on PATH.
"""

import subprocess

import pytest

from lib import campaign

STUB_SSH = r"""#!/usr/bin/env bash
# stub ssh: last argument is the remote command
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
    """A materialised project whose run.sh talks to stub ssh/rsync."""
    return make_dispatcher(
        {"ssh": STUB_SSH, "rsync": STUB_RSYNC},
        STUB_SBATCH="Submitted batch job 12345",
        STUB_SACCT="",
    )


def test_submitting_records_the_job_in_the_ledger(dispatcher):
    result = dispatcher("run", "smoke", "--campaign", "c1")
    assert result.returncode == 0, result.stderr

    rows = campaign.jobs(dispatcher.project, "c1")
    assert [r["job_id"] for r in rows] == ["12345"]
    assert rows[0]["exp"] == "smoke"
    assert rows[0]["status"] == "PENDING"
    assert rows[0]["partition"] == "cpu"
    assert rows[0]["submitted_utc"]


def test_submission_writes_provenance_manifest(dispatcher, tmp_path):
    payload = tmp_path / "provenance.json"
    result = dispatcher(
        "run", "smoke", "--campaign", "c1",
        STUB_PAYLOAD_LOG=payload,
        UNITY_CID="/work/tester/cluster-intel",
        PROJECT_NAME="trace-project",
        MODEL="model-a",
        DATASET="data-a",
        SEED="7",
        CONFIG_HASH="abc123",
    )
    assert result.returncode == 0, result.stderr
    text = payload.read_text()
    assert '"job_id": "12345"' in text
    assert '"experiment": "smoke"' in text
    assert '"campaign": "c1"' in text
    assert '"project": "trace-project"' in text
    assert '"model": "model-a"' in text


def test_dispatcher_bounds_each_ssh_call(dispatcher):
    result = dispatcher("run", "smoke", "--campaign", "c1",
                        UNITY_SSH_TIMEOUT="17")
    assert result.returncode == 0, result.stderr
    timeout_calls = [line for line in dispatcher.log.read_text().splitlines()
                     if line.startswith("timeout ")]
    assert timeout_calls
    assert all("--foreground 17 ssh" in line for line in timeout_calls)


def test_the_ledger_is_where_the_mcp_server_looks(dispatcher):
    dispatcher("run", "smoke", "--campaign", "c1")
    assert (dispatcher.project / ".unity_state" / "c1.db").exists()
    assert campaign.all_job_ids(dispatcher.project) == ["12345"]


def test_campaign_defaults_to_the_utc_day(dispatcher):
    from datetime import datetime, timezone
    dispatcher("run", "smoke")
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    assert campaign.latest_campaign(dispatcher.project) == today


def test_two_submissions_share_one_campaign(dispatcher):
    dispatcher("run", "a", "--campaign", "c1", STUB_SBATCH="Submitted batch job 1")
    dispatcher("run", "b", "--campaign", "c1", STUB_SBATCH="Submitted batch job 2")
    rows = campaign.jobs(dispatcher.project, "c1")
    assert [(r["job_id"], r["exp"]) for r in rows] == [("1", "a"), ("2", "b")]


def test_array_submission_uses_one_sbatch_and_records_tasks(dispatcher, tmp_path):
    manifest = tmp_path / "variants.txt"
    manifest.write_text("trial-a\ntrial-b\ntrial-c\n")
    payload = tmp_path / "payload.log"

    result = dispatcher("array", str(manifest), "--campaign", "sweep-1",
                        "--limit", "2", STUB_PAYLOAD_LOG=payload)

    assert result.returncode == 0, result.stderr
    rows = campaign.jobs(dispatcher.project, "sweep-1")
    assert [(r["job_id"], r["exp"]) for r in rows] == [
        ("12345_0", "trial-a"),
        ("12345_1", "trial-b"),
        ("12345_2", "trial-c"),
    ]
    assert len(dispatcher.sbatch_calls()) == 1
    assert "#SBATCH --array=0-2%2" in payload.read_text()


def test_array_ledger_exp_is_the_token_not_the_payload_tail(dispatcher, tmp_path):
    """A manifest line may be token<TAB>json; the ledger's exp column is the
    token alone, so a tab-delimited payload tail cannot desync cmd_jobs'
    job_id/exp/partition/status columns or cmd_fetch's filename stem."""
    manifest = tmp_path / "variants.txt"
    manifest.write_text('trial-a\t{"lr": 0.01}\ntrial-b\n')

    result = dispatcher("array", str(manifest), "--campaign", "sweep-1")

    assert result.returncode == 0, result.stderr
    rows = campaign.jobs(dispatcher.project, "sweep-1")
    assert [(r["job_id"], r["exp"]) for r in rows] == [
        ("12345_0", "trial-a"),
        ("12345_1", "trial-b"),
    ]


def test_the_rendered_array_script_is_valid_bash(dispatcher, tmp_path):
    """A released array script escaped its manifest lookup with backslashes that
    bash's printf does not interpret, so every task died on line 14 with a
    syntax error while sbatch reported success and the ledger recorded a healthy
    campaign. No test that only matched strings could see it. Parse the script."""
    manifest = tmp_path / "variants.txt"
    manifest.write_text("trial-a\ntrial-b\n")
    payload = tmp_path / "payload.log"

    dispatcher("array", str(manifest), "--campaign", "sweep-1",
               STUB_PAYLOAD_LOG=payload)
    script = payload.read_text()

    check = subprocess.run(["bash", "-n"], input=script, capture_output=True, text=True)
    assert check.returncode == 0, f"rendered array script does not parse:\n{check.stderr}"
    assert "export EXP=\"$(sed -n " in script, script


def test_a_plain_job_script_is_valid_bash(dispatcher, tmp_path):
    payload = tmp_path / "payload.log"
    dispatcher("run", "smoke", "--campaign", "c1", STUB_PAYLOAD_LOG=payload)
    check = subprocess.run(["bash", "-n"], input=payload.read_text(),
                           capture_output=True, text=True)
    assert check.returncode == 0, check.stderr


def _break_job_template(dispatcher):
    """Corrupt the one part of the script that reaches the cluster verbatim.

    JOB_COMMAND cannot be used for this: render() emits it with printf %q, so
    even an unbalanced quote there produces valid bash. job_template.sh is
    cat'ed in unchanged, which is what makes it the honest test subject -- and
    it is a file users do hand-edit."""
    template = dispatcher.project / "unityHPC" / "job_template.sh"
    template.write_text(template.read_text() + '\nif [ -z "$EXP" ]\n')


def test_a_script_that_does_not_parse_is_never_submitted(dispatcher, tmp_path):
    """The syntax check is the guard that turns a silent 100% failure into an
    immediate, actionable error."""
    manifest = tmp_path / "variants.txt"
    manifest.write_text("trial-a\n")
    _break_job_template(dispatcher)

    result = dispatcher("array", str(manifest), "--campaign", "sweep-1")
    assert result.returncode == 2, result.stdout
    assert "not valid bash" in result.stderr
    assert "Nothing was submitted" in result.stderr
    # The check runs before the first SSH call, so nothing reached the cluster
    # at all -- not even the mkdir that would normally create the stub log.
    assert not dispatcher.log.exists(), dispatcher.log.read_text()
    assert campaign.jobs(dispatcher.project, "sweep-1") == []


def test_a_plain_job_that_does_not_parse_is_never_submitted(dispatcher):
    _break_job_template(dispatcher)
    result = dispatcher("run", "smoke", "--campaign", "c1")
    assert result.returncode == 2, result.stdout
    assert "not valid bash" in result.stderr
    assert campaign.jobs(dispatcher.project, "c1") == []


def test_the_syntax_check_can_be_bypassed(dispatcher, tmp_path):
    """The local bash and the cluster's bash can differ, so the check must not
    be the only opinion that counts."""
    manifest = tmp_path / "variants.txt"
    manifest.write_text("trial-a\n")
    _break_job_template(dispatcher)

    result = dispatcher("array", str(manifest), "--campaign", "sweep-2",
                        UNITY_SKIP_SYNTAX_CHECK="1")
    assert result.returncode == 0, result.stderr
    assert len(campaign.jobs(dispatcher.project, "sweep-2")) == 1


def test_array_status_and_fetch_use_array_log_names(dispatcher, tmp_path):
    manifest = tmp_path / "variants.txt"
    manifest.write_text("trial-a\ntrial-b\n")
    dispatcher("array", str(manifest), "--campaign", "sweep-1")

    result = dispatcher(
        "status", "--campaign", "sweep-1",
        STUB_SACCT=("12345_0|COMPLETED|cpu|00:00:21\n"
                    "12345_1|FAILED|cpu|00:00:22"),
    )
    assert result.returncode == 0, result.stderr
    assert {r["status"] for r in campaign.jobs(dispatcher.project, "sweep-1")} == {
        "COMPLETED", "FAILED"
    }

    result = dispatcher("fetch", "--campaign", "sweep-1")
    assert result.returncode == 0, result.stderr
    rsync_calls = [line for line in dispatcher.log.read_text().splitlines()
                   if "--include" in line]
    assert "--include=sweep-1-12345_0.out" in rsync_calls[-1]


def test_unparseable_sbatch_reply_warns_and_records_nothing(dispatcher):
    result = dispatcher("run", "smoke", "--campaign", "c1",
                        STUB_SBATCH="sbatch: error: Batch job submission failed")
    assert "WARNING" in result.stderr
    assert campaign.jobs(dispatcher.project, "c1") == []


def test_dry_run_submits_nothing_and_records_nothing(dispatcher):
    result = dispatcher("run", "smoke", "--campaign", "c1", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "[dry-run]" in result.stdout
    assert campaign.jobs(dispatcher.project, "c1") == []
    assert not dispatcher.log.exists(), "dry-run must not touch the cluster"


def test_extra_sbatch_args_survive_campaign_parsing(dispatcher):
    dispatcher("run", "smoke", "--campaign", "c1", "--qos=short")
    submit = dispatcher.sbatch_calls()
    assert submit and "--qos=short" in submit[0]


def test_status_folds_live_sacct_into_the_ledger(dispatcher):
    dispatcher("run", "smoke", "--campaign", "c1")
    result = dispatcher("status", "--campaign", "c1",
                        STUB_SACCT="12345|COMPLETED|cpu|00:00:21")
    assert result.returncode == 0, result.stderr
    assert campaign.jobs(dispatcher.project, "c1")[0]["status"] == "COMPLETED"


def test_status_never_regresses_a_terminal_state(dispatcher):
    dispatcher("run", "smoke", "--campaign", "c1")
    dispatcher("status", "--campaign", "c1", STUB_SACCT="12345|COMPLETED|cpu|00:00:21")
    dispatcher("status", "--campaign", "c1", STUB_SACCT="12345|RUNNING|cpu|00:00:30")
    assert campaign.jobs(dispatcher.project, "c1")[0]["status"] == "COMPLETED"


def test_status_on_an_empty_campaign_is_graceful(dispatcher):
    result = dispatcher("status", "--campaign", "nothing-here")
    assert result.returncode == 0
    assert "No jobs recorded" in result.stdout


def test_jobs_reads_the_ledger_without_touching_the_cluster(dispatcher):
    dispatcher("run", "smoke", "--campaign", "c1")
    dispatcher.log.unlink()
    result = dispatcher("jobs", "--campaign", "c1")
    assert "12345" in result.stdout and "smoke" in result.stdout
    assert not dispatcher.log.exists(), "jobs must be a purely local read"


def test_fetch_pulls_only_this_campaign_s_output(dispatcher):
    dispatcher("run", "smoke", "--campaign", "c1")
    result = dispatcher("fetch", "--campaign", "c1")
    assert result.returncode == 0, result.stderr
    rsync_calls = [l for l in dispatcher.log.read_text().splitlines() if "--include" in l]
    assert rsync_calls, "fetch must invoke rsync"
    assert "--include=smoke-12345.out" in rsync_calls[0]
    assert "--include=smoke-12345.err" in rsync_calls[0]
    assert "--exclude=*" in rsync_calls[0]
    assert (dispatcher.project / "_results" / "c1").is_dir()


def test_fetch_is_the_subcommand_the_fetch_skill_calls(dispatcher):
    """The fetch skill ran `run.sh fetch` against a dispatcher that had no such
    subcommand, and got a usage error."""
    result = dispatcher("fetch", "--campaign", "c1")
    assert result.returncode == 0
    assert "usage:" not in result.stderr


def test_logs_tails_the_newest_job(dispatcher):
    dispatcher("run", "a", "--campaign", "c1", STUB_SBATCH="Submitted batch job 1")
    dispatcher("run", "b", "--campaign", "c1", STUB_SBATCH="Submitted batch job 2")
    result = dispatcher("logs", "--campaign", "c1", "-n", "5")
    assert result.returncode == 0, result.stderr
    assert "b-2.out" in result.stdout
    assert "log line one" in result.stdout


def test_unknown_subcommand_still_reports_usage(dispatcher):
    result = dispatcher("nonsense")
    assert result.returncode == 2
    assert "usage:" in result.stderr


def test_concurrent_submissions_all_land_in_the_ledger(dispatcher):
    """Several jobs submitted at once must not lose or corrupt rows — the whole
    point of the ledger is that a project can name everything it launched."""
    import concurrent.futures

    def submit(i):
        return dispatcher("run", f"job{i}", "--campaign", "race",
                          STUB_SBATCH=f"Submitted batch job {100 + i}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(submit, range(8)))

    assert all(r.returncode == 0 for r in results), \
        [r.stderr for r in results if r.returncode]
    rows = campaign.jobs(dispatcher.project, "race")
    assert {r["job_id"] for r in rows} == {str(100 + i) for i in range(8)}


def test_two_projects_keep_separate_ledgers(tmp_path, materialise, monkeypatch):
    """Projects share the telemetry store but never a ledger, so concurrent use
    cannot cross-contaminate."""
    from lib import campaign as c
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    c.record(a, "same-name", "1", "job", "cpu")
    c.record(b, "same-name", "2", "job", "cpu")
    assert c.all_job_ids(a) == ["1"]
    assert c.all_job_ids(b) == ["2"]


def test_run_refuses_an_unsafe_experiment_name(dispatcher):
    """exp reaches a remote shell command; it must never carry metacharacters."""
    result = dispatcher("run", "evil; echo INJECTED", "--campaign", "c1")
    assert result.returncode == 2
    assert "invalid experiment name" in result.stderr
    assert not dispatcher.log.exists(), "an unsafe name still reached the cluster"


def test_run_refuses_an_unsafe_campaign_name(dispatcher):
    """campaign becomes a local file path: '../..' must not escape .unity_state."""
    result = dispatcher("run", "ok", "--campaign", "../../escape")
    assert result.returncode == 2
    assert "invalid campaign name" in result.stderr


def test_run_still_refuses_a_missing_experiment_name(dispatcher):
    result = dispatcher("run", "--campaign", "c1")
    assert result.returncode == 2
