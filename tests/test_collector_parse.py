import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "cluster-intel"))

import collector_parse as cp  # noqa: E402

TS = "2026-07-22T14:00:00Z"


def test_parse_partitions_extracts_cpu_and_gpu_types():
    text = "gpu|up|145|1676/1612/0/3288|gpu:a100:4\ncpu|up|300|5000/15000/0/20000|(null)\n"
    parts = cp.parse_partitions(text)
    assert parts["gpu"]["cpus_total"] == 3288
    assert parts["gpu"]["cpus_alloc"] == 1676
    assert parts["gpu"]["nodes_total"] == 145
    assert parts["gpu"]["gpu_types"] == ["a100"]
    assert parts["cpu"]["gpu_types"] == []


def test_parse_partitions_skips_malformed_row_keeps_good_ones():
    text = (
        "gpu|up|145|1676/1612/0/3288|gpu:a100:4\n"
        "broken|row\n"  # too few fields
        "cpu|up|not_a_number|5000/15000/0/20000|(null)\n"  # non-numeric nodes
    )
    parts = cp.parse_partitions(text)
    assert set(parts) == {"gpu", "cpu"}
    assert parts["gpu"]["cpus_total"] == 3288
    assert parts["cpu"]["nodes_total"] == 0  # degrades to 0, doesn't raise
    assert parts["cpu"]["cpus_total"] == 20000


def test_parse_pending_counts_by_partition():
    text = "gpu|Priority\ngpu|Resources\ncpu|Priority\n"
    assert cp.parse_pending(text) == {"gpu": 2, "cpu": 1}


def test_parse_gpu_types_is_lenient():
    text = ("GPU usage\n"
            "a100    144 / 157    80GB   cc 8.0\n"
            "l40s     10 / 40     48GB   cc 8.9\n"
            "garbage line with no numbers\n")
    recs = cp.parse_gpu_types(text)
    by_id = {r["resource_id"]: r for r in recs}
    assert by_id["a100"]["total"] == 157 and by_id["a100"]["alloc"] == 144
    assert by_id["a100"]["vram_gb"] == 80
    assert by_id["a100"]["compute_capability"] == 8.0
    assert "l40s" in by_id


def test_parse_nodes_extracts_idle_cpus_and_widened_fields():
    text = "gpu|gpu013|mix|48/16/0/64|515000|120000|gpu:a100:4|gpu:a100:3\n"
    nodes = cp.parse_nodes(text)
    n = nodes[0]
    assert n["resource_id"] == "gpu013"
    assert n["partition"] == "gpu"
    assert n["cpus_total"] == 64 and n["cpus_idle"] == 16
    assert n["state"] == "mix"
    assert n["mem_mb_total"] == 515000
    assert n["mem_mb_free"] == 120000
    assert n["gpu_types"] == ["a100"]
    assert n["gpus_total"] == 4
    assert n["gpus_idle"] == 1


def test_parse_nodes_skips_malformed_row_keeps_good_ones():
    text = (
        "gpu|gpu013|mix|48/16/0/64|515000|120000|gpu:a100:4|gpu:a100:3\n"
        "gpu|gpu014|idle\n"  # too few fields
        "cpu|cpu001|idle|0/64/0/64|not_a_number|32000|(null)|(null)\n"  # non-numeric mem
    )
    nodes = cp.parse_nodes(text)
    by_id = {n["resource_id"]: n for n in nodes}
    assert set(by_id) == {"gpu013", "cpu001"}
    assert by_id["gpu013"]["cpus_idle"] == 16
    assert by_id["cpu001"]["mem_mb_total"] == 0  # degrades to 0, doesn't raise
    assert by_id["cpu001"]["mem_mb_free"] == 32000


def test_parse_nodes_honest_none_for_missing_freemem_and_gresused():
    # collector.sh emits an empty field (not the total) when sinfo's
    # FreeMem is "N/A" or GresUsed is unparseable — honesty guard (§8).
    text = "gpu|gpu013|mix|48/16/0/64|515000||gpu:a100:4|\n"
    nodes = cp.parse_nodes(text)
    n = nodes[0]
    assert n["mem_mb_free"] is None
    assert n["gpus_idle"] is None
    assert n["mem_mb_total"] == 515000  # total is still known/real
    assert n["gpus_total"] == 4


def test_build_resource_state_excludes_unknown_gpu_alloc_from_partition_total():
    partitions_text = "gpu|up|2|1676/1612/0/3288|gpu:a100:4\n"
    nodes_text = (
        "gpu|gpu013|mix|48/16/0/64|515000|120000|gpu:a100:4|gpu:a100:3\n"
        "gpu|gpu014|alloc|64/0/0/64|515000||gpu:a100:4|\n"  # unknown mem/gres
    )
    recs = cp.build_resource_state(TS, partitions_text, "", "", nodes_text)
    part = next(r for r in recs if r["kind"] == "partition")
    assert part["gpus_total"] == 8
    # only gpu013 (idle=1, alloc=3) contributes; gpu014 is unknown, excluded
    # rather than counted as 0 alloc.
    assert part["gpus_alloc"] == 3
    node_recs = {r["resource_id"]: r for r in recs if r["kind"] == "node"}
    assert node_recs["gpu014"]["mem_mb_free"] is None
    assert node_recs["gpu014"]["gpus_idle"] is None


def test_diff_node_events_reports_transitions_only():
    prev = {"gpu013": "mix", "gpu014": "idle"}
    cur = {"gpu013": "drain", "gpu014": "idle"}
    events = cp.diff_node_events(prev, cur, TS)
    assert events == [{"ts": TS, "event": "node_state_change",
                       "resource_id": "gpu013", "from": "mix", "to": "drain"}]


def test_parse_task_runs_reads_alloctres_and_exit():
    text = ("62009039|pi_yourlab_umass_edu|gpu|COMPLETED|2026-07-22T10:00:00|"
            "2026-07-22T10:05:00|2026-07-22T10:45:50|00:40:50|"
            "cpu=8,mem=16384M,gres/gpu:a100=1|0:0|1002M|01:00:00\n")
    runs = cp.parse_task_runs(text)
    r = runs[0]
    assert r["job_id"] == "62009039"
    assert r["partition"] == "gpu" and r["gpu_type"] == "a100"
    assert r["req"] == {"cpus": 8, "mem_mb": 16384, "gpus": 1, "walltime_s": 3600}
    assert r["used"]["elapsed_s"] == 2450
    assert r["used"]["max_rss_mb"] == 1002
    assert r["state"] == "COMPLETED" and r["exit_code"] == 0


def test_parse_task_runs_normalizes_uid_suffixed_cancelled_state():
    # sacct emits `CANCELLED by <uid>` (the cancelling user's uid). Collapse
    # it to a bare `CANCELLED` so state aggregation is not fragmented into
    # hundreds of distinct per-uid states; the uid is another user's and is
    # dropped (privacy-correct). All other states pass through unchanged.
    text = (
        "111|acct|gpu|CANCELLED by 2974|2026-07-22T10:00:00|2026-07-22T10:05:00|"
        "2026-07-22T10:10:00|00:05:00|cpu=8|0:15|300M|01:00:00\n"
        "222|acct|gpu|CANCELLED|2026-07-22T10:00:00|2026-07-22T10:05:00|"
        "2026-07-22T10:10:00|00:05:00|cpu=8|0:15|300M|01:00:00\n"
        "333|acct|gpu|COMPLETED|2026-07-22T10:00:00|2026-07-22T10:05:00|"
        "2026-07-22T10:45:50|00:40:50|cpu=8|0:0|1002M|01:00:00\n"
    )
    states = {r["job_id"]: r["state"] for r in cp.parse_task_runs(text)}
    assert states == {"111": "CANCELLED", "222": "CANCELLED", "333": "COMPLETED"}


def test_parse_task_runs_skips_truncated_line_keeps_good_ones():
    text = (
        "62009039|pi_yourlab_umass_edu|gpu|COMPLETED|2026-07-22T10:00:00|"
        "2026-07-22T10:05:00|2026-07-22T10:45:50|00:40:50|"
        "cpu=8,mem=16384M,gres/gpu:a100=1|0:0|1002M|01:00:00\n"
        "62009040|pi_yourlab_umass_edu|gpu|RUNNING|2026-07-22T11:00:00\n"  # truncated
        "62009039.batch|pi_yourlab_umass_edu|gpu|COMPLETED|x|x|x|x|x|x|x|x\n"  # sub-step
    )
    runs = cp.parse_task_runs(text)
    assert len(runs) == 1
    assert runs[0]["job_id"] == "62009039"


def test_build_resource_state_stamps_ts_and_kind():
    recs = cp.build_resource_state(
        TS,
        "gpu|up|145|1676/1612/0/3288|gpu:a100:4\n",
        "gpu|Priority\n",
        "a100 144 / 157 80GB cc 8.0\n",
        "gpu|gpu013|mix|48/16/0/64|515000|120000|gpu:a100:4|gpu:a100:3\n")
    kinds = {r["kind"] for r in recs}
    assert kinds == {"partition", "gpu_type", "node"}
    assert all(r["ts"] == TS for r in recs)
    part = next(r for r in recs if r["kind"] == "partition")
    assert part["pending"] == 1


def test_build_resource_state_emits_node_state_tally_and_gpu_totals():
    partitions_text = "gpu|up|3|1676/1612/0/3288|gpu:a100:4\n"
    nodes_text = (
        "gpu|gpu013|mix|48/16/0/64|515000|120000|gpu:a100:4|gpu:a100:3\n"
        "gpu|gpu014|alloc|64/0/0/64|515000|10000|gpu:a100:4|gpu:a100:4\n"
        "gpu|gpu015|idle|0/64/0/64|515000|500000|gpu:a100:4|(null)\n"
        "gpu|gpu016|drain|0/64/0/64|515000|500000|(null)|(null)\n"
    )
    recs = cp.build_resource_state(TS, partitions_text, "", "", nodes_text)
    part = next(r for r in recs if r["kind"] == "partition" and r["resource_id"] == "gpu")
    assert part["node_states"] == {"mix": 1, "alloc": 1, "idle": 1, "drain": 1}
    assert part["gpus_total"] == 12  # 4 + 4 + 4 + 0
    assert part["gpus_alloc"] == 7  # 3 + 4 + 0 + 0

    node_recs = {r["resource_id"]: r for r in recs if r["kind"] == "node"}
    assert node_recs["gpu013"]["gpus_total"] == 4
    assert node_recs["gpu013"]["gpus_idle"] == 1
    assert node_recs["gpu013"]["mem_mb_free"] == 120000
    assert node_recs["gpu013"]["partition"] == "gpu"
    assert node_recs["gpu016"]["gpus_total"] == 0
    assert node_recs["gpu016"]["gpus_idle"] == 0


# --- real unity-slurm-gpu-usage layout + node-GRES fallback -------------------

# Verbatim shape of the deployed wrapper's stdout, captured live: ONE entry
# per line `type [bar]? alloc/total pending vram cc`, the `[####...]` bar
# OPTIONAL, plus pseudo-rows (`any`, `unknown`, the latter with no bar and a
# bare pending count instead of alloc/total), a header, a ruler, and a
# trailing prose line — see tests/fixtures/gpu_usage_wrapper.txt.
REAL_GPU_TEXT = (Path(__file__).resolve().parent / "fixtures" / "gpu_usage_wrapper.txt").read_text()

# 8-field per-node rows exactly as collector.sh's awk emits them.
REAL_NODES_TEXT = (
    "gpu|gpu001|mix|48/16/0/64|515000|120000|gpu:a100:4|gpu:a100:3\n"
    "gpu|gpu002|idle|0/64/0/64|515000|500000|gpu:a100:4|gpu:a100:0\n"
    "gpu|gpu003|mix|32/32/0/64|515000|200000|gpu:l40s:8|gpu:l40s:2\n"
    "cpu|cpu001|idle|0/64/0/64|515000|500000|(null)|(null)\n"
)


def test_parse_gpu_types_reads_the_real_wrapper_fixture():
    recs = cp.parse_gpu_types(REAL_GPU_TEXT)
    assert len(recs) >= 10, "must parse most of the real fleet, not fall back silently"
    by_id = {r["resource_id"]: r for r in recs}
    assert "any" not in by_id, "the 'any' aggregate row must be skipped"
    assert "unknown" not in by_id, "the 'unknown' aggregate row (no alloc/total) must be skipped"


def test_parse_gpu_types_reads_bar_prefixed_alloc_total_pending_vram_cc():
    by_id = {r["resource_id"]: r for r in cp.parse_gpu_types(REAL_GPU_TEXT)}
    h100 = by_id["h100"]
    assert h100["alloc"] == 8 and h100["total"] == 8
    assert h100["pending"] == 1
    assert h100["vram_gb"] == 80
    assert h100["compute_capability"] == 9.0


def test_parse_gpu_types_treats_zero_vram_and_cc_as_no_data():
    # A wrapper row with no real VRAM/CC reading prints bare 0s there; §8
    # honesty forbids recording that as a fabricated 0 GB / 0.0 CC.
    text = " widget       [##                ] 1/4          0         0         0       \n"
    by_id = {r["resource_id"]: r for r in cp.parse_gpu_types(text)}
    assert by_id["widget"]["alloc"] == 1 and by_id["widget"]["total"] == 4
    assert "vram_gb" not in by_id["widget"]
    assert "compute_capability" not in by_id["widget"]


def test_parse_gpu_types_merges_repeated_type_rows_without_fabricating():
    # Same type listed twice (Unity lists a100 at 40GB and 80GB): counts sum,
    # and the disagreeing vram column is OMITTED rather than guessed.
    text = (" a100         [####              ] 40/57         2         40        8.0     \n"
            " a100         [##########        ] 108/100       1         80        8.0     \n")
    by_id = {r["resource_id"]: r for r in cp.parse_gpu_types(text)}
    assert by_id["a100"]["alloc"] == 148 and by_id["a100"]["total"] == 157
    assert by_id["a100"]["pending"] == 3
    assert "vram_gb" not in by_id["a100"]
    assert by_id["a100"]["compute_capability"] == 8.0  # agrees, so kept


def test_gpu_types_from_nodes_aggregates_measured_gres():
    recs = cp.gpu_types_from_nodes(REAL_NODES_TEXT)
    by_id = {r["resource_id"]: r for r in recs}
    assert set(by_id) == {"a100", "l40s"}
    assert by_id["a100"]["total"] == 8 and by_id["a100"]["alloc"] == 3
    assert by_id["l40s"]["total"] == 8 and by_id["l40s"]["alloc"] == 2
    assert by_id["a100"]["kind"] == "gpu_type"
    assert by_id["a100"]["source"] == "node_gres"


def test_gpu_types_from_nodes_excludes_nodes_with_unmeasured_gres_alloc():
    # Node gpu002 has an EMPTY gres_alloc (collector.sh's honesty guard for an
    # unreadable GresUsed). It must contribute to neither alloc nor total,
    # rather than being counted as 0-allocated.
    text = ("gpu|gpu001|mix|48/16/0/64|515000|120000|gpu:a100:4|gpu:a100:3\n"
            "gpu|gpu002|mix|48/16/0/64|515000|120000|gpu:a100:4|\n")
    by_id = {r["resource_id"]: r for r in cp.gpu_types_from_nodes(text)}
    assert by_id["a100"]["total"] == 4 and by_id["a100"]["alloc"] == 3


def test_build_resource_state_emits_gpu_type_records_from_the_wrapper():
    recs = cp.build_resource_state(TS, "", "", REAL_GPU_TEXT, REAL_NODES_TEXT)
    gpus = {r["resource_id"] for r in recs if r["kind"] == "gpu_type"}
    assert "h100" in gpus and "a100" in gpus
    assert "any" not in gpus and "unknown" not in gpus
    assert len(gpus) >= 10


def test_build_resource_state_falls_back_to_node_gres_when_wrapper_is_silent():
    # The deployed failure mode: unity-slurm-gpu-usage yielded nothing, so the
    # day's resource_state.jsonl had ZERO gpu_type records even though 813 node
    # records carried fully measured per-type GRES.
    recs = cp.build_resource_state(TS, "", "", "", REAL_NODES_TEXT)
    gpus = {r["resource_id"]: r for r in recs if r["kind"] == "gpu_type"}
    assert gpus, "node GRES must back-fill gpu_type when the wrapper is silent"
    assert set(gpus) == {"a100", "l40s"}
    assert gpus["a100"]["alloc"] == 3 and gpus["a100"]["total"] == 8
    assert all(r["ts"] == TS for r in gpus.values())


def test_build_resource_state_emits_no_gpu_types_when_no_source_yields_any():
    recs = cp.build_resource_state(TS, "", "", "", "cpu|cpu001|idle|0/64/0/64|515000|500000|(null)|(null)\n")
    assert not [r for r in recs if r["kind"] == "gpu_type"]


# ─── hardware is a device, never a queue ─────────────────────────────────────

def test_a_known_gpu_type_is_the_hardware():
    from collector_parse import derive_hardware
    assert derive_hardware("A100", {"gpus": 1}) == "a100"


def test_a_gpu_job_with_no_recorded_type_is_explicit_not_a_partition():
    """`hardware` used to fall back to the partition string, so `gpu-preempt`
    (a queue) sat in the same column as `a100` (a device) and got ranked
    against it."""
    from collector_parse import derive_hardware, GPU_UNSPECIFIED
    assert derive_hardware(None, {"gpus": 2}) == GPU_UNSPECIFIED
    assert GPU_UNSPECIFIED not in ("gpu", "gpu-preempt")


def test_a_job_with_no_gpu_is_cpu():
    from collector_parse import derive_hardware
    assert derive_hardware(None, {"cpus": 8}) == "cpu"
    assert derive_hardware(None, {"cpus": 8, "gpus": 0}) == "cpu"
    assert derive_hardware(None, None) == "cpu"


def test_hardware_never_takes_a_partition_name(): 
    """Regression: no input may make derive_hardware return a queue name."""
    from collector_parse import derive_hardware
    for part in ("gpu", "gpu-preempt", "gpu,gpu-preempt", "cpu-preempt",
                 "superpod-a100", "uri-gpu"):
        # the partition is not even an argument any more — it cannot leak in
        assert derive_hardware(None, {"gpus": 1}) != part
        assert derive_hardware(None, {}) != part or part == "cpu"


def test_parse_task_runs_keeps_partition_and_gpu_type_separate():
    from collector_parse import parse_task_runs, derive_hardware
    row = ("61|acct|gpu,gpu-preempt|COMPLETED|2026-07-01T00:00:00|"
           "2026-07-01T00:00:10|2026-07-01T00:01:00|00:00:50|"
           "billing=1,cpu=4,gres/gpu:a100=2,mem=8G|0:0|1024K|01:00:00|")
    t = parse_task_runs(row)[0]
    assert t["partition"] == "gpu,gpu-preempt"
    assert t["gpu_type"] == "a100"
    assert derive_hardware(t["gpu_type"], t["req"]) == "a100"


def test_untyped_gres_still_counts_as_a_gpu_job():
    from collector_parse import parse_task_runs, derive_hardware, GPU_UNSPECIFIED
    row = ("62|acct|gpu-preempt|COMPLETED|2026-07-01T00:00:00|"
           "2026-07-01T00:00:10|2026-07-01T00:01:00|00:00:50|"
           "billing=1,cpu=4,gres/gpu=1,mem=8G|0:0|1024K|01:00:00|")
    t = parse_task_runs(row)[0]
    assert t["gpu_type"] is None and t["req"].get("gpus") == 1
    assert derive_hardware(t["gpu_type"], t["req"]) == GPU_UNSPECIFIED
