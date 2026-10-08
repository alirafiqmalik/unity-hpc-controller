import fcntl
import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COLLECTOR = REPO_ROOT / "cluster-intel" / "collector.sh"


@pytest.fixture
def cid(tmp_path):
    d = tmp_path / "cluster-intel"
    (d / "telemetry").mkdir(parents=True)
    return d


def _stub_bin(tmp_path):
    """A bin dir whose SLURM commands print fixtures regardless of args."""
    b = tmp_path / "bin"
    b.mkdir()
    stubs = {
        "sinfo": '#!/usr/bin/env bash\n'
                 'if [[ "$*" == *"GresUsed"* ]]; then\n'
                 '  printf "%-24s%-20s%-10s%-24s%-12s%-12s%-60s%-60s\\n" \\\n'
                 '    "gpu013" "gpu" "mix" "48/16/0/64" "515000" "120000" "gpu:a100:4" "gpu:a100:3";\n'
                 'else echo "gpu|up|145|1676/1612/0/3288|gpu:a100:4"; fi\n',
        "squeue": '#!/usr/bin/env bash\necho "gpu|Priority"\n',
        "unity-slurm-gpu-usage": '#!/usr/bin/env bash\necho "a100 144 / 157 80GB cc 8.0"\n',
        "sacct": '#!/usr/bin/env bash\n'
                 'echo "62009039|acct|gpu|COMPLETED|2026-07-22T10:00:00|2026-07-22T10:05:00|'
                 '2026-07-22T10:45:50|00:40:50|cpu=8,mem=16384M,gres/gpu:a100=1|0:0|1002M"\n',
    }
    for name, body in stubs.items():
        p = b / name
        p.write_text(body)
        p.chmod(0o755)
    return b


def _env(cid, bin_dir):
    env = dict(os.environ)
    env["UNITY_CID"] = str(cid)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return env


def test_sample_writes_valid_jsonl(cid, tmp_path):
    bin_dir = _stub_bin(tmp_path)
    r = subprocess.run(["bash", str(COLLECTOR), "sample"],
                       capture_output=True, text=True, env=_env(cid, bin_dir))
    assert r.returncode == 0, r.stderr
    days = list((cid / "telemetry").glob("20*/resource_state.jsonl"))
    assert days, "sample must write a day-partitioned resource_state.jsonl"
    recs = [json.loads(l) for l in days[0].read_text().splitlines()]
    kinds = {rec["kind"] for rec in recs}
    assert {"partition", "gpu_type", "node"} <= kinds
    # task_runs promoted from sacct
    assert (days[0].parent / "task_runs.jsonl").exists()
    node = next(r for r in recs if r["kind"] == "node")
    # real FreeMem/GresUsed sourced, not duplicated from the totals (I1
    # honesty guard): mem_free != mem_total, gpus_idle != 0.
    assert node["mem_mb_free"] == 120000 and node["mem_mb_total"] == 515000
    assert node["gpus_idle"] == 1


def test_seff_efficiency_only_recorded_for_terminal_jobs(cid, tmp_path):
    bin_dir = _stub_bin(tmp_path)
    # Override the fixed single-job sacct stub with four jobs spanning a
    # non-terminal (RUNNING), a plain-terminal (COMPLETED), a
    # terminal-with-suffix (CANCELLED by <uid>), and an empty state, each
    # with seff output so the fix can't be confused with seff simply not
    # running.
    (bin_dir / "sacct").write_text(
        '#!/usr/bin/env bash\n'
        'echo "111|acct|gpu|RUNNING|2026-07-22T10:00:00|2026-07-22T10:05:00||'
        '00:05:00|cpu=8,mem=16384M|0:0|500M"\n'
        'echo "222|acct|gpu|COMPLETED|2026-07-22T10:00:00|2026-07-22T10:05:00|'
        '2026-07-22T10:45:50|00:40:50|cpu=8,mem=16384M|0:0|1002M"\n'
        'echo "333|acct|gpu|CANCELLED by 12345|2026-07-22T10:00:00|2026-07-22T10:05:00|'
        '2026-07-22T10:10:00|00:05:00|cpu=8,mem=16384M|0:15|300M"\n'
        'echo "444|acct|gpu||2026-07-22T10:00:00|2026-07-22T10:05:00||'
        '00:05:00|cpu=8,mem=16384M|0:0|500M"\n'
    )
    (bin_dir / "sacct").chmod(0o755)
    (bin_dir / "seff").write_text(
        '#!/usr/bin/env bash\n'
        'case "$1" in\n'
        '  111) echo "CPU Efficiency: 0.00% of 00:05:00 core-walltime"; '
        'echo "Memory Efficiency: 0.00% of 16.00GB";;\n'
        '  222) echo "CPU Efficiency: 55.00% of 00:40:50 core-walltime"; '
        'echo "Memory Efficiency: 12.00% of 16.00GB";;\n'
        '  333) echo "CPU Efficiency: 0.00% of 00:05:00 core-walltime"; '
        'echo "Memory Efficiency: 0.00% of 16.00GB";;\n'
        '  444) echo "CPU Efficiency: 0.00% of 00:05:00 core-walltime"; '
        'echo "Memory Efficiency: 0.00% of 16.00GB";;\n'
        'esac\n'
    )
    (bin_dir / "seff").chmod(0o755)
    r = subprocess.run(["bash", str(COLLECTOR), "sample"],
                       capture_output=True, text=True, env=_env(cid, bin_dir))
    assert r.returncode == 0, r.stderr
    days = list((cid / "telemetry").glob("20*/task_runs.jsonl"))
    assert days
    recs = {json.loads(l)["job_id"]: json.loads(l)["used"]
            for l in days[0].read_text().splitlines()}
    assert recs["111"]["cpu_eff_pct"] is None, \
        "RUNNING job must not report a measured efficiency"
    assert recs["111"]["mem_eff_pct"] is None
    assert recs["222"]["cpu_eff_pct"] == 55.0, \
        "COMPLETED job keeps its measured efficiency"
    assert recs["222"]["mem_eff_pct"] == 12.0
    assert recs["333"]["cpu_eff_pct"] == 0.0, \
        "a genuine 0.0 on a terminal (CANCELLED by <uid>) job is kept, not treated as missing"
    assert recs["333"]["mem_eff_pct"] == 0.0
    assert recs["444"]["cpu_eff_pct"] is None, \
        "an empty state must be treated as non-terminal, not crash the sample"
    assert recs["444"]["mem_eff_pct"] is None


def test_seff_enrichment_has_a_bounded_terminal_job_budget(cid, tmp_path):
    bin_dir = _stub_bin(tmp_path)
    calls = tmp_path / "seff-calls"
    (bin_dir / "sacct").write_text(
        "#!/usr/bin/env bash\n"
        "for i in $(seq 1 14); do\n"
        "  state=COMPLETED; [ \"$i\" -eq 14 ] && state=RUNNING\n"
        "  printf '10%02d|alice|acct|gpu|%s|2026-07-22T10:00:00|"
        "2026-07-22T10:05:00|2026-07-22T10:45:50|00:40:50|"
        "cpu=8|0:0|100M|01:00:00\\n' \"$i\" \"$state\"\n"
        "done\n"
    )
    (bin_dir / "sacct").chmod(0o755)
    (bin_dir / "seff").write_text(
        '#!/usr/bin/env bash\n'
        'echo "$1" >> "$SEFF_CALLS"\n'
        'echo "CPU Efficiency: 55.00%"\n'
    )
    (bin_dir / "seff").chmod(0o755)
    env = _env(cid, bin_dir)
    env["SEFF_CALLS"] = str(calls)
    result = subprocess.run(["bash", str(COLLECTOR), "sample"],
                            capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    queried = calls.read_text().splitlines()
    assert len(queried) <= 12
    assert "1014" not in queried, "running jobs have no final efficiency"
    assert "1013" in queried, "the newest terminal job gets the budget"


def test_once_exits_cleanly_when_lock_held(cid, tmp_path):
    bin_dir = _stub_bin(tmp_path)
    lock_path = cid / "collector.lock"
    lock = open(lock_path, "w")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    try:
        r = subprocess.run(["bash", str(COLLECTOR), "once"],
                           capture_output=True, text=True, env=_env(cid, bin_dir))
        assert r.returncode == 0
        assert "already running" in (r.stdout + r.stderr).lower()
        assert not list((cid / "telemetry").glob("20*/resource_state.jsonl")), \
            "the singleton must not write while another holds the lock (I1)"
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def test_once_writes_when_lock_free(cid, tmp_path):
    bin_dir = _stub_bin(tmp_path)
    r = subprocess.run(["bash", str(COLLECTOR), "once"],
                       capture_output=True, text=True, env=_env(cid, bin_dir))
    assert r.returncode == 0, r.stderr
    assert list((cid / "telemetry").glob("20*/resource_state.jsonl"))


def test_prune_removes_days_older_than_retention(cid, tmp_path):
    tel = cid / "telemetry"
    (tel / "2020-01-01").mkdir()
    today = subprocess.run(["date", "-u", "+%F"], capture_output=True, text=True).stdout.strip()
    (tel / today).mkdir(exist_ok=True)
    env = dict(os.environ, UNITY_CID=str(cid), UNITY_COLLECTOR_RETENTION_DAYS="35")
    r = subprocess.run(["bash", str(COLLECTOR), "prune"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert not (tel / "2020-01-01").exists(), "an aged-out day must be pruned"
    assert (tel / today).exists(), "today's day must survive"


def _days_ago(n):
    return subprocess.run(["date", "-u", "-d", f"{n} days ago", "+%F"],
                          capture_output=True, text=True).stdout.strip()


def test_prune_boundary_at_retention_days(cid):
    # Guards the `<` (not `<=`) cutoff comparison: a day-dir exactly
    # RETENTION_DAYS old is the cutoff itself and must survive; only
    # strictly-older dirs are pruned.
    tel = cid / "telemetry"
    retention = 35
    d34, d35, d36 = _days_ago(34), _days_ago(35), _days_ago(36)
    for d in (d34, d35, d36):
        (tel / d).mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, UNITY_CID=str(cid),
              UNITY_COLLECTOR_RETENTION_DAYS=str(retention))
    r = subprocess.run(["bash", str(COLLECTOR), "prune"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert (tel / d34).exists(), "34-days-old must survive"
    assert (tel / d35).exists(), "exactly-35-days-old (the cutoff) must survive"
    assert not (tel / d36).exists(), "36-days-old must be pruned"


def _date(*args):
    return subprocess.run(["date", "-u", *args],
                          capture_output=True, text=True).stdout.strip()


def test_window_first_run_defaults_to_now_minus_20min(cid, tmp_path):
    # No last_sample_utc state file -> the safe first-run default window.
    r = subprocess.run(["bash", str(COLLECTOR), "window"],
                       capture_output=True, text=True, env=_env(cid, _stub_bin(tmp_path)))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "now-20minutes"


def test_window_uses_high_water_mark_with_5min_overlap(cid, tmp_path):
    # A recent high-water mark -> -S is that mark minus a 5-minute overlap.
    hwm = _date("-d", "10 minutes ago", "+%Y-%m-%dT%H:%M:%SZ")
    (cid / "last_sample_utc").write_text(hwm + "\n")
    expected = _date("-d", f"{hwm} - 5 minutes", "+%Y-%m-%dT%H:%M:%S")
    r = subprocess.run(["bash", str(COLLECTOR), "window"],
                       capture_output=True, text=True, env=_env(cid, _stub_bin(tmp_path)))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == expected


def test_window_clamps_to_7_days_when_mark_is_ancient(cid, tmp_path):
    # A high-water mark older than 7 days must clamp -S to now-7days (an
    # unbounded sacct pull on a shared login node is unacceptable) and warn.
    (cid / "last_sample_utc").write_text(
        _date("-d", "30 days ago", "+%Y-%m-%dT%H:%M:%SZ") + "\n")
    floor_day = _date("-d", "7 days ago", "+%Y-%m-%d")
    r = subprocess.run(["bash", str(COLLECTOR), "window"],
                       capture_output=True, text=True, env=_env(cid, _stub_bin(tmp_path)))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().startswith(floor_day), "must clamp to now-7days"
    assert "clamp" in r.stderr.lower() or "7d" in r.stderr.lower(), \
        "an ancient mark must emit a warning to stderr"


def test_sample_records_high_water_mark_after_success(cid, tmp_path):
    bin_dir = _stub_bin(tmp_path)
    r = subprocess.run(["bash", str(COLLECTOR), "sample"],
                       capture_output=True, text=True, env=_env(cid, bin_dir))
    assert r.returncode == 0, r.stderr
    state = cid / "last_sample_utc"
    assert state.exists(), "a successful sample must persist the high-water mark"
    import re as _re
    assert _re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", state.read_text().strip())


def test_collector_no_longer_hardcodes_fixed_20min_sacct_window():
    text = COLLECTOR.read_text()
    # The sacct pull must use the computed window variable, not a frozen
    # -S now-20minutes that loses every job started+ended during downtime.
    assert "-S now-20minutes -E now -X -P" not in text
    assert "last_sample_utc" in text


def test_catchup_buckets_jobs_into_their_submit_day_dir(cid, tmp_path):
    # rollup stamps day_utc from the day-DIRECTORY a task_runs.jsonl lives in,
    # not from record timestamps, so catchup must file each re-observed job
    # under its own submit-derived day (2026-07-22 here) rather than today.
    bin_dir = _stub_bin(tmp_path)
    r = subprocess.run(["bash", str(COLLECTOR), "catchup", "2026-07-20T00:00:00"],
                       capture_output=True, text=True, env=_env(cid, bin_dir))
    assert r.returncode == 0, r.stderr
    submit_day = cid / "telemetry" / "2026-07-22" / "task_runs.jsonl"
    assert submit_day.exists(), "catchup must file a job under its submit-derived day"
    rec = json.loads(submit_day.read_text().splitlines()[0])
    assert rec["job_id"] == "62009039"
    today = subprocess.run(["date", "-u", "+%F"], capture_output=True, text=True).stdout.strip()
    assert not (cid / "telemetry" / today / "task_runs.jsonl").exists(), \
        "a historical job must not be misfiled under today's day-dir"


def test_catchup_does_not_touch_high_water_mark(cid, tmp_path):
    bin_dir = _stub_bin(tmp_path)
    (cid / "last_sample_utc").write_text("2026-07-24T02:00:00Z\n")
    r = subprocess.run(["bash", str(COLLECTOR), "catchup", "now-3days"],
                       capture_output=True, text=True, env=_env(cid, bin_dir))
    assert r.returncode == 0, r.stderr
    assert (cid / "last_sample_utc").read_text().strip() == "2026-07-24T02:00:00Z", \
        "catchup must not advance the sampler's high-water mark"


def test_catchup_requires_a_start_argument(cid, tmp_path):
    r = subprocess.run(["bash", str(COLLECTOR), "catchup"],
                       capture_output=True, text=True, env=_env(cid, _stub_bin(tmp_path)))
    assert r.returncode != 0
    assert "usage" in (r.stdout + r.stderr).lower()


def test_catchup_exits_cleanly_when_lock_held(cid, tmp_path):
    bin_dir = _stub_bin(tmp_path)
    lock = open(cid / "collector.lock", "w")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    try:
        r = subprocess.run(["bash", str(COLLECTOR), "catchup", "now-1days"],
                           capture_output=True, text=True, env=_env(cid, bin_dir))
        assert r.returncode == 0
        assert "already running" in (r.stdout + r.stderr).lower()
        assert not list((cid / "telemetry").glob("20*/task_runs.jsonl")), \
            "catchup must not write while another holds the lock (I1)"
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def test_collector_dispatches_catchup_via_parser():
    text = COLLECTOR.read_text()
    assert "catchup)" in text
    assert "collector_parse.py" in text


def test_collector_has_path_and_pager_fix():
    text = COLLECTOR.read_text()
    assert "/modules/user-resources/bin" in text
    assert "PAGER=NONE" in text


def test_collector_wraps_commands_in_timeout_and_nice():
    text = COLLECTOR.read_text()
    assert "timeout" in text
    assert "nice" in text


def test_collector_is_singleton_guarded():
    # The in-script guarantee is flock alone; see
    # test_once_exits_cleanly_when_lock_held / test_once_writes_when_lock_free
    # for the behavioral proof. `tmux has-session` opens the controller's
    # cluster session. It is not a second writer.
    text = COLLECTOR.read_text()
    assert "flock" in text
    assert "collector.lock" in text
    # The session open lives with the schedule, not in the connect skill.
    # flock inside collector.sh is still what stops two samples writing at once.
    session_text = (REPO_ROOT / "controller" / "cluster_session.py").read_text()
    assert "tmux has-session" in session_text


def test_collector_sources_real_freemem_and_gresused_for_nodes():
    text = COLLECTOR.read_text()
    assert "FreeMem" in text
    assert "GresUsed" in text
    # the old fabrication (mem_free := mem_total, gres_alloc := gres_total)
    # must be gone
    assert '$4 "|" $4' not in text
    assert '$5 "|" $5' not in text


def test_collector_prunes_at_35_days_by_default():
    text = COLLECTOR.read_text()
    assert "UNITY_COLLECTOR_RETENTION_DAYS" in text
    assert "35" in text


def test_collector_writes_cluster_telemetry_path_and_pipes_through_parser():
    text = COLLECTOR.read_text()
    assert "telemetry" in text
    assert "collector_parse.py" in text


def test_collector_dispatches_all_four_modes():
    text = COLLECTOR.read_text()
    for mode in ("loop", "once", "sample", "prune"):
        assert mode in text


def test_no_personal_ids_in_collector():
    # Tokens are split so this guard file itself doesn't trip the repo-wide
    # author-identifier scan (tests/test_no_personal_ids.py) on its own
    # banned-token list.
    text = COLLECTOR.read_text()
    banned = ("pi_taqi" + "_umass_edu", "ahmal" + "ik", "autores" + "earch")
    for token in banned:
        assert token not in text


def test_real_gpu_usage_layout_survives_the_pending_enrichment(cid, tmp_path):
    """The real wrapper reports pending PER GPU TYPE itself. squeue-derived
    enrichment must fill that gap, never overwrite the authoritative reading —
    and both entries on a wrapper line must reach the store."""
    bin_dir = _stub_bin(tmp_path)
    (bin_dir / "unity-slurm-gpu-usage").write_text(
        '#!/usr/bin/env bash\n'
        'echo " h100         [##################] 8/8          1         80        9.0     "\n'
        'echo " a100         [###############   ] 148/157       12        80        8.0     "\n'
        'echo "18 nodes are inacessible and are not counted in the above numbers."\n')
    (bin_dir / "unity-slurm-gpu-usage").chmod(0o755)
    # squeue reports one pending a100 job; a100 already has an authoritative 12.
    (bin_dir / "squeue").write_text(
        '#!/usr/bin/env bash\necho "gpu|Priority|gpu:a100:1"\n')
    (bin_dir / "squeue").chmod(0o755)

    r = subprocess.run(["bash", str(COLLECTOR), "sample"],
                       capture_output=True, text=True, env=_env(cid, bin_dir))
    assert r.returncode == 0, r.stderr
    day = next(iter((cid / "telemetry").glob("20*/resource_state.jsonl")))
    gpus = {rec["resource_id"]: rec
            for rec in (json.loads(l) for l in day.read_text().splitlines())
            if rec["kind"] == "gpu_type"}
    assert set(gpus) == {"h100", "a100"}
    assert gpus["a100"]["alloc"] == 148 and gpus["a100"]["total"] == 157
    assert gpus["a100"]["pending"] == 12, "wrapper's own pending must not be clobbered"
    assert gpus["a100"]["vram_gb"] == 80
    assert gpus["h100"]["compute_capability"] == 9.0


def test_gpu_types_emitted_from_node_gres_when_the_wrapper_is_silent(cid, tmp_path):
    """Deployed failure mode: unity-slurm-gpu-usage produced nothing, so the
    day's resource_state.jsonl held zero gpu_type records."""
    bin_dir = _stub_bin(tmp_path)
    (bin_dir / "unity-slurm-gpu-usage").write_text('#!/usr/bin/env bash\nexit 1\n')
    (bin_dir / "unity-slurm-gpu-usage").chmod(0o755)

    r = subprocess.run(["bash", str(COLLECTOR), "sample"],
                       capture_output=True, text=True, env=_env(cid, bin_dir))
    assert r.returncode == 0, r.stderr
    day = next(iter((cid / "telemetry").glob("20*/resource_state.jsonl")))
    gpus = [rec for rec in (json.loads(l) for l in day.read_text().splitlines())
            if rec["kind"] == "gpu_type"]
    assert [g["resource_id"] for g in gpus] == ["a100"]
    assert gpus[0]["alloc"] == 3 and gpus[0]["total"] == 4
    assert gpus[0]["source"] == "node_gres"


def _failing_sacct(bin_dir):
    """Overwrite the sacct stub with one that fails like a throttled slurmdbd."""
    p = bin_dir / "sacct"
    p.write_text('#!/usr/bin/env bash\n'
                 'echo "sacct: error: slurm_persist_conn_open: Connection refused" >&2\n'
                 'exit 1\n')
    p.chmod(0o755)


def test_sample_keeps_high_water_mark_when_sacct_fails(cid, tmp_path):
    # A transient slurmdbd failure must NOT advance the mark: advancing it
    # would permanently skip this window's jobs (they'd fall outside every
    # future window). The failed window is retried next cycle instead.
    bin_dir = _stub_bin(tmp_path)
    r = subprocess.run(["bash", str(COLLECTOR), "sample"],
                       capture_output=True, text=True, env=_env(cid, bin_dir))
    assert r.returncode == 0, r.stderr
    mark = (cid / "last_sample_utc").read_text().strip()
    assert mark  # good sample advanced the mark

    _failing_sacct(bin_dir)
    r2 = subprocess.run(["bash", str(COLLECTOR), "sample"],
                        capture_output=True, text=True, env=_env(cid, bin_dir))
    assert r2.returncode == 0, r2.stderr          # sample survives the outage
    assert "sacct failed" in r2.stderr            # ...but says so loudly
    assert (cid / "last_sample_utc").read_text().strip() == mark, \
        "a failed sacct must not advance the high-water mark"


def test_catchup_fails_loudly_when_sacct_fails(cid, tmp_path):
    # A catchup that swallows a sacct failure reports "healed" with zero
    # records -- the exact silent loss this guard exists to prevent.
    bin_dir = _stub_bin(tmp_path)
    _failing_sacct(bin_dir)
    r = subprocess.run(["bash", str(COLLECTOR), "catchup", "2026-07-01T00:00:00"],
                       capture_output=True, text=True, env=_env(cid, bin_dir))
    assert r.returncode == 3, f"rc={r.returncode}; stderr={r.stderr}"
    assert "sacct failed" in r.stderr
    assert not list((cid / "telemetry").glob("20*/task_runs.jsonl")), \
        "a failed catchup must write nothing"
