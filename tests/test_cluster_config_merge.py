from lib import cluster_config as cc


def _gpu_config():
    return {
        "schema_version": 1,
        "cluster": "unity",
        "gpu_fleet": {
            "a100": {"vram_gb": [80, 40], "compute_capability": 8.0,
                     "total_accessible": 157, "observed_utc": "2026-07-20T10:00:00Z"}
        },
        "partitions": {
            "gpu": {"nodes": 145, "cpus_total": 3288, "gpus_total": 769,
                    "gpu_types": ["a100", "l40s"], "observed_utc": "2026-07-20T10:00:00Z"}
        },
    }


def test_unobserved_fields_survive():
    # esim-fv replays a CPU-only recon that never probed GPUs.
    obs = {"partitions": {"cpu": {"nodes": 300, "cpus_total": 20000,
                                  "observed_utc": "2026-07-22T14:00:00Z"}}}
    merged = cc.merge_config(_gpu_config(), obs)
    assert merged["gpu_fleet"]["a100"]["total_accessible"] == 157, \
        "absence is not evidence of absence — GPU fleet must be untouched"
    assert merged["partitions"]["cpu"]["nodes"] == 300


def test_capacity_takes_max_never_shrinks():
    # A partial GPU observation reporting a100=40 must not reduce 157.
    obs = {"gpu_fleet": {"a100": {"total_accessible": 40,
                                  "observed_utc": "2026-07-22T14:00:00Z"}}}
    merged = cc.merge_config(_gpu_config(), obs)
    assert merged["gpu_fleet"]["a100"]["total_accessible"] == 157


def test_sets_take_union():
    obs = {"partitions": {"gpu": {"gpu_types": ["l40s", "h100"],
                                  "observed_utc": "2026-07-22T14:00:00Z"}}}
    merged = cc.merge_config(_gpu_config(), obs)
    assert merged["partitions"]["gpu"]["gpu_types"] == ["a100", "h100", "l40s"]


def test_gpu_aliases_fold_at_the_config_merge_boundary():
    current = {"gpu_fleet": {"rtx_8000": {"total_accessible": 4,
                                              "observed_utc": "2026-07-20T00:00:00Z"}}}
    observation = {"gpu_fleet": {"rtx8000": {"total_accessible": 8,
                                                "observed_utc": "2026-07-21T00:00:00Z"}},
                   "partitions": {"gpu": {"gpu_types": ["rtx_8000", "titan-x"]}}}
    merged = cc.merge_config(current, observation)
    assert set(merged["gpu_fleet"]) == {"rtx8000"}
    assert merged["gpu_fleet"]["rtx8000"]["total_accessible"] == 8
    assert merged["gpu_fleet"]["rtx8000"]["source_resource_ids"] == ["rtx_8000"]
    assert merged["partitions"]["gpu"]["gpu_types"] == ["rtx8000", "titanx"]


def test_legacy_gpu_storage_sections_fold_order_independently():
    a = {"gpu_capacity": {"titan_x": 4}}
    b = {"gpu_types": {"titanx": {"total_accessible": 8}}}
    ab = cc.merge_config(cc.merge_config({}, a), b)
    ba = cc.merge_config(cc.merge_config({}, b), a)
    assert ab == ba
    assert ab["gpu_fleet"] == {
        "titanx": {"total_accessible": 8, "source_resource_ids": ["titan_x"]}}
    assert "gpu_capacity" not in ab and "gpu_types" not in ab


def test_point_in_time_newest_observed_wins():
    cur = {"fairshare": {"factor": 0.4, "observed_utc": "2026-07-20T10:00:00Z"}}
    newer = {"fairshare": {"factor": 0.9, "observed_utc": "2026-07-22T14:00:00Z"}}
    older = {"fairshare": {"factor": 0.1, "observed_utc": "2026-07-19T10:00:00Z"}}
    assert cc.merge_config(cur, newer)["fairshare"]["factor"] == 0.9
    assert cc.merge_config(cur, older)["fairshare"]["factor"] == 0.4


def test_merge_is_order_independent():
    a = {"partitions": {"gpu": {"gpu_types": ["a100"], "nodes": 100,
                                "observed_utc": "2026-07-21T00:00:00Z"}}}
    b = {"partitions": {"gpu": {"gpu_types": ["l40s"], "nodes": 145,
                                "observed_utc": "2026-07-22T00:00:00Z"}}}
    base = {"schema_version": 1}
    ab = cc.merge_config(cc.merge_config(base, a), b)
    ba = cc.merge_config(cc.merge_config(base, b), a)
    assert ab == ba


def test_qos_list_unions_by_name():
    cur = {"account_limits": {"qos": [{"name": "short", "max_wall": "04:00:00"}]}}
    obs = {"account_limits": {"qos": [{"name": "long", "max_wall": "48:00:00"}]}}
    names = [q["name"] for q in cc.merge_config(cur, obs)["account_limits"]["qos"]]
    assert names == ["long", "short"]


def test_arguments_are_not_mutated():
    cur = _gpu_config()
    snapshot = {"a": cur["gpu_fleet"]["a100"]["total_accessible"]}
    cc.merge_config(cur, {"gpu_fleet": {"a100": {"total_accessible": 999,
                                                 "observed_utc": "2026-07-25T00:00:00Z"}}})
    assert cur["gpu_fleet"]["a100"]["total_accessible"] == snapshot["a"]


def test_merged_result_is_fully_isolated_from_observation():
    import copy

    # Every nested-mutable field below is chosen to route through one of the
    # deep-copied generic branches, not through _MAX_FIELDS / _union_list /
    # observed_utc handling (those already deep-copy or are immutable):
    #   - gpu_fleet.a100.extra    -> merge_resource's generic `else` branch
    #   - cluster_meta            -> merge_config's generic `elif v is not None`
    #   - account_limits.qos[].limits -> _union_by_name's named-record merge
    current = {"schema_version": 1, "cluster": "unity"}
    observation = {
        "gpu_fleet": {
            "a100": {
                "extra": {"note": "orig"},
                "observed_utc": "2026-07-22T14:00:00Z",
            }
        },
        "cluster_meta": {"note": "orig"},
        "account_limits": {
            "qos": [{"name": "short", "limits": {"note": "orig"}}],
        },
    }
    pristine_observation = copy.deepcopy(observation)
    pristine_current = copy.deepcopy(current)

    merged = cc.merge_config(current, observation)

    # Mutate the merged result's nested dicts/lists in place.
    merged["gpu_fleet"]["a100"]["extra"]["note"] = "MUTATED"
    merged["cluster_meta"]["note"] = "MUTATED"
    merged["account_limits"]["qos"][0]["limits"]["note"] = "MUTATED"

    # Without the copy.deepcopy fixes in merge_resource's else branch,
    # merge_config's generic elif branch, and _union_by_name's named-record
    # merge, each of these nested dicts would still be the SAME object as
    # the one inside `observation`, so mutating `merged` would mutate
    # `observation` too and this equality would fail.
    assert observation == pristine_observation, \
        "mutating the merged output must not affect the observation argument"
    assert current == pristine_current, \
        "mutating the merged output must not affect the current argument"


def test_account_limits_merge_is_order_independent():
    base = {"schema_version": 1}
    a = {"account_limits": {"max_jobs": 100, "observed_utc": "2026-07-20T10:00:00Z"}}
    b = {"account_limits": {"max_jobs": 250, "observed_utc": "2026-07-22T14:00:00Z"}}

    ab = cc.merge_config(cc.merge_config(base, a), b)
    ba = cc.merge_config(cc.merge_config(base, b), a)

    assert ab == ba
    assert ab["account_limits"]["max_jobs"] == 250
    assert ba["account_limits"]["max_jobs"] == 250
