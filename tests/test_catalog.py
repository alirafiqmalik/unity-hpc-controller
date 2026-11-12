"""Catalog survey, storage, freshness, schedule, and HTTP contract."""
import hashlib
import json
import stat
import subprocess
import time
from datetime import datetime, timezone

import pytest

from controller import campaigns, catalog
from controller.campaign_slurm import SlurmAdapter
from controller.http import Request, handle


SURVEY = (
    "NODES\n"
    "NodeName=gpu013 Arch=x86_64 CoresPerSocket=56 CPUAlloc=16 CPUTot=112 CPULoad=3.10 AvailableFeatures=a100-80g,sapphirerapids ActiveFeatures=a100-80g,sapphirerapids Gres=gpu:a100:8(S:0-1) NodeAddr=gpu013 NodeHostName=gpu013 OS=Linux RealMemory=2000000 AllocMem=262144 FreeMem=N/A Sockets=2 Boards=1 State=MIXED ThreadsPerCore=1 TmpDisk=0 Weight=1 Owner=N/A MCS_label=N/A Partitions=gpu,gpu-preempt CfgTRES=cpu=112,mem=2000000M,billing=112,gres/gpu=8 AllocTRES=cpu=16,mem=256G,gres/gpu=2\n"
    "NodeName=gpu042 CPUTot=64 ActiveFeatures=l40s,intel Gres=gpu:l40s:4(S:0),gpu:a16:2 RealMemory=515000 FreeMem=401234 State=IDLE Partitions=gpu-preempt AllocTRES=\n"
    "NodeName=cpu001 CPUTot=128 ActiveFeatures=amd,zen4 Gres=(null) RealMemory=1031000 FreeMem=900000 State=ALLOCATED+DRAIN Partitions=cpu,cpu-preempt AllocTRES=cpu=128\n"
    "PARTITIONS\n"
    "PartitionName=gpu AllowGroups=ALL AllowAccounts=pi_test,pi_other AllowQos=ALL DenyQos=short Default=NO QoS=N/A DefaultTime=01:00:00 MaxNodes=UNLIMITED MaxTime=2-00:00:00 PriorityJobFactor=1 PriorityTier=4 PreemptMode=OFF State=UP TotalCPUs=4480 TotalNodes=40\n"
    "PartitionName=gpu-preempt AllowGroups=ALL AllowAccounts=ALL DenyAccounts=pi_banned AllowQos=ALL MaxTime=UNLIMITED PreemptMode=REQUEUE State=UP\n"
    "PartitionName=cpu AllowGroups=research,admins AllowAccounts=ALL AllowQos=normal,long DenyQos=(null) MaxTime=14-00:00:00 PriorityTier=1 PreemptMode=OFF State=DOWN\n"
    "QOS\n"
    "normal||1000|2000|\n"
    "long|14-00:00:00|5|10|cpu=512,gres/gpu=8\n"
    "short|30|||\n"
    "broken|1\n"
    "ASSOCIATIONS\n"
    "pi_test|normal,long|100|200|cpu=1000|7-00:00:00\n"
    "pi_other|normal||||\n"
    "ACCOUNT_LIMITS\n"
    "pi_test||cpu=2000,gres/gpu=64|500|1000\n"
    "pi_test|someuser|cpu=10|1|1\n"
    "GROUPS\n"
    "users pi_test research\n"
    "FAIRSHARE\n"
    "pi_other|someuser|0.900000|0.100000\n"
    "pi_test|someuser|0.512345|0.012300\n"
)
EXPECTED = {
    "nodes": [
        {"name": "gpu013", "cpus": 112, "memory_mb": 2000000, "features": ["a100-80g", "sapphirerapids"], "partitions": ["gpu", "gpu-preempt"],
         "gpus": {"a100": 8}, "state": "MIXED", "alloc_tres": "cpu=16,mem=256G,gres/gpu=2", "free_memory_mb": None},
        {"name": "gpu042", "cpus": 64, "memory_mb": 515000, "features": ["l40s", "intel"], "partitions": ["gpu-preempt"],
         "gpus": {"l40s": 4, "a16": 2}, "state": "IDLE", "alloc_tres": "", "free_memory_mb": 401234},
        {"name": "cpu001", "cpus": 128, "memory_mb": 1031000, "features": ["amd", "zen4"], "partitions": ["cpu", "cpu-preempt"],
         "gpus": {}, "state": "ALLOCATED+DRAIN", "alloc_tres": "cpu=128", "free_memory_mb": 900000},
    ],
    "partitions": {
        "gpu": {"state": "UP", "max_walltime_seconds": 172800, "priority_tier": 4, "preempt_mode": "OFF", "allow_accounts": ["pi_test", "pi_other"],
                "deny_accounts": [], "allow_groups": ["ALL"], "allow_qos": ["ALL"], "deny_qos": ["short"]},
        "gpu-preempt": {"state": "UP", "max_walltime_seconds": None, "priority_tier": 0, "preempt_mode": "REQUEUE", "allow_accounts": ["ALL"],
                        "deny_accounts": ["pi_banned"], "allow_groups": ["ALL"], "allow_qos": ["ALL"], "deny_qos": []},
        "cpu": {"state": "DOWN", "max_walltime_seconds": 1209600, "priority_tier": 1, "preempt_mode": "OFF", "allow_accounts": ["ALL"],
                "deny_accounts": [], "allow_groups": ["research", "admins"], "allow_qos": ["normal", "long"], "deny_qos": []},
    },
    "qos": {
        "normal": {"max_walltime_seconds": None, "max_jobs": 1000, "max_submit_jobs": 2000, "max_tres_per_user": None},
        "long": {"max_walltime_seconds": 1209600, "max_jobs": 5, "max_submit_jobs": 10, "max_tres_per_user": "cpu=512,gres/gpu=8"},
        "short": {"max_walltime_seconds": 1800, "max_jobs": None, "max_submit_jobs": None, "max_tres_per_user": None},
    },
    "associations": {
        "pi_test": {"qos": ["normal", "long"], "max_jobs": 100, "max_submit_jobs": 200, "grp_tres": "cpu=1000", "max_walltime_seconds": 604800},
        "pi_other": {"qos": ["normal"], "max_jobs": None, "max_submit_jobs": None, "grp_tres": None, "max_walltime_seconds": None},
    },
    "groups": ["users", "pi_test", "research"],
    "account": {"name": "pi_test", "qos": ["normal", "long"], "max_jobs": 100, "max_submit_jobs": 200, "grp_tres": "cpu=2000,gres/gpu=64",
                "max_walltime_seconds": 604800, "grp_jobs": 500, "grp_submit_jobs": 1000},
    "source": "bounded SSH Slurm commands",
    "fairshare": {"factor": 0.512345, "effective_usage": 0.0123},
}
SURVEY_COMMAND = "export PAGER=NONE TZ=UTC LC_ALL=C; set -e; export PATH=/modules/user-resources/bin:$PATH; printf 'NODES\\n'; timeout 25 scontrol show node -o; printf 'PARTITIONS\\n'; timeout 20 scontrol show partition -o; printf 'QOS\\n'; timeout 20 sacctmgr -n -P show qos format=Name,MaxWall,MaxJobsPerUser,MaxSubmitJobsPerUser,MaxTRESPerUser; printf 'ASSOCIATIONS\\n'; timeout 20 sacctmgr -n -P show assoc where user=$(whoami) format=Account,QOS,MaxJobs,MaxSubmitJobs,GrpTRES,MaxWallDurationPerJob; printf 'ACCOUNT_LIMITS\\n'; timeout 20 sacctmgr -n -P show assoc where account=pi_test format=Account,User,GrpTRES,GrpJobs,GrpSubmitJobs; printf 'GROUPS\\n'; id -Gn; printf 'FAIRSHARE\\n'; timeout 15 sshare -U -n -P -o Account,User,FairShare,EffectvUsage"
# sha256 of SURVEY_COMMAND (the string value): e714a20759a1d5a07262aaddf8395936dc0ec89f398b336da1b5e45cd90ccbae
T0 = datetime(2026, 11, 12, tzinfo=timezone.utc).timestamp()


class Recorder:
    def __init__(self, stdout, returncode=0):
        self.stdout, self.returncode, self.calls = stdout, returncode, []

    def run(self, command, *, timeout, input=None):
        self.calls.append((command, timeout, input))
        return subprocess.CompletedProcess([], self.returncode, self.stdout, "boom" if self.returncode else "")

    def run_script(self, *args, **kwargs):
        raise AssertionError("unexpected script")

    def transfer(self, *args, **kwargs):
        raise AssertionError("unexpected transfer")


@pytest.mark.parametrize("key", ["nodes", "partitions", "qos", "associations", "account", "groups", "fairshare"])
def test_parse_survey_sections(key):
    assert catalog.parse(SURVEY, "pi_test")[key] == EXPECTED[key]


def test_parse_stamps_observation_time():
    before = time.time()
    value = catalog.parse(SURVEY, "pi_test")
    after = time.time()
    assert set(value) == set(EXPECTED) | {"observed_at"}
    assert value["source"] == EXPECTED["source"]
    stamp = datetime.fromisoformat(value["observed_at"])
    assert stamp.tzinfo is not None
    assert before - 1 <= stamp.timestamp() <= after + 1


@pytest.mark.parametrize("offset,expected_age,expected", [(3600, 3600.0, True), (3601, 3601.0, False), (-60, 0, True)])
def test_age_and_freshness_take_wall_time(offset, expected_age, expected):
    value = {"observed_at": "2026-11-12T00:00:00+00:00"}
    assert catalog.age(value, T0 + offset) == expected_age
    assert catalog.is_fresh(value, 3600, T0 + offset) is expected


@pytest.mark.parametrize("value", [{}, {"observed_at": ""}, {"observed_at": "yesterday"},
                                    {"observed_at": None}, {"observed_at": 12345},
                                    {"observed_at": "2026-11-12T00:00:00"}])
def test_missing_or_malformed_observation_time_is_stale(value):
    assert catalog.age(value, T0) is None
    assert catalog.is_fresh(value, 3600, T0) is False


def test_missing_file_reads_as_absent(tmp_data_dir):
    assert catalog.load() == {}
    assert not catalog.is_fresh(catalog.load(), 86400, time.time())


@pytest.mark.parametrize("kind", ["json", "encoding", "directory"])
def test_unreadable_file_reads_as_absent(tmp_data_dir, kind):
    catalog.path().parent.mkdir(parents=True, exist_ok=True)
    if kind == "json":
        catalog.path().write_text("{not json")
    elif kind == "encoding":
        catalog.path().write_bytes(b"\xff\xfe")
    else:
        catalog.path().mkdir()
    assert catalog.load() == {}
    assert not catalog.is_fresh(catalog.load(), 86400, time.time())


def test_stored_file_is_read_without_rewrite(tmp_data_dir):
    value = {**EXPECTED, "observed_at": "2026-11-12T00:00:00+00:00"}
    campaigns._write_json(tmp_data_dir / "controller/backend-catalog.json", value)
    before, mtime = catalog.path().read_bytes(), catalog.path().stat().st_mtime_ns
    assert catalog.load() == value
    assert catalog.is_fresh(catalog.load(), 3600, T0 + 10)
    assert catalog.path().read_bytes() == before
    assert catalog.path().stat().st_mtime_ns == mtime


def test_refresh_runs_the_unchanged_survey_and_stores_atomically(tmp_data_dir):
    rec = Recorder(SURVEY)
    adapter = SlurmAdapter({"ssh_host": "alias-x", "account": "pi_test"}, transport=rec)
    value = catalog.refresh(adapter)
    assert hashlib.sha256(SURVEY_COMMAND.encode()).hexdigest() == "e714a20759a1d5a07262aaddf8395936dc0ec89f398b336da1b5e45cd90ccbae"
    assert rec.calls == [(SURVEY_COMMAND, 150, None)]
    assert {k: v for k, v in value.items() if k != "observed_at"} == EXPECTED
    assert catalog.path().read_text() == json.dumps(value, indent=2, sort_keys=True) + "\n"
    assert stat.S_IMODE(catalog.path().stat().st_mode) == 0o600
    assert list(catalog.path().parent.glob("*.tmp")) == []
    assert catalog.load() == value


def test_failed_survey_keeps_the_stored_catalog(tmp_data_dir):
    value = {**EXPECTED, "observed_at": "2026-11-12T00:00:00+00:00"}
    campaigns._write_json(tmp_data_dir / "controller/backend-catalog.json", value)
    before = catalog.path().read_bytes()
    adapter = SlurmAdapter({"ssh_host": "alias-x", "account": "pi_test"}, transport=Recorder("", returncode=1))
    with pytest.raises(RuntimeError, match="backend probe failed"):
        catalog.refresh(adapter)
    assert catalog.path().read_bytes() == before


def test_refresh_schedule_uses_monotonic_time():
    schedule = catalog.RefreshSchedule(100.0)
    assert schedule.claim(99.0) is False
    assert schedule.claim(100.0) is True
    assert schedule.claim(999.0) is False
    assert schedule.claim(1000.0) is True
    assert schedule.claim(1000.0) is False
    assert catalog.REFRESH_SECONDS == 900


def test_backend_route_answers_settings_and_stored_catalog(tmp_data_dir):
    campaigns.configure({"account": "pi_test", "remote_root": "/work/pi_test/controller"})
    response = handle(Request("GET", "/api/v1/backend"))
    body = json.loads(response.body)
    assert response.status == 200
    assert set(body) == {"settings", "catalog"}
    assert body["catalog"] == {}
    value = {**EXPECTED, "observed_at": "2026-11-12T00:00:00+00:00"}
    campaigns._write_json(tmp_data_dir / "controller/backend-catalog.json", value)
    response = handle(Request("GET", "/api/v1/backend"))
    assert response.status == 200
    assert json.loads(response.body)["catalog"] == value


def test_probe_route_answers_the_refreshed_catalog(tmp_data_dir, monkeypatch):
    monkeypatch.delenv("UNITY_ACCOUNT", raising=False)
    campaigns.configure({"account": "pi_test", "remote_root": "/work/pi_test/controller"})
    monkeypatch.setattr(campaigns, "slurm_adapter", lambda campaign=None, live=None: SlurmAdapter(live, transport=Recorder(SURVEY)))
    response = handle(Request("POST", "/api/v1/backend/probe"))
    body = json.loads(response.body)
    assert response.status == 200
    assert set(body) == {"catalog"}
    assert {k: v for k, v in body["catalog"].items() if k != "observed_at"} == EXPECTED
    assert catalog.load() == body["catalog"]
