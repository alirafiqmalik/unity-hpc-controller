"""SSH adapter for portable campaigns. No caller-side run.sh or registry.

Every remote command is bounded. Submission receipts are written under a
remote flock; a missing receipt after an SSH failure is an uncertain outcome.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shlex
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from controller import campaign_store as store
from controller.cluster_session import _agent_env, ssh_argv
from controller.campaign_contract import CampaignError


MAIL_TYPES = "END,FAIL,TIME_LIMIT,REQUEUE"


PREFLIGHT = r'''
import csv,json,os,subprocess,sys
from pathlib import Path
r=json.loads(sys.argv[1]); out=Path(os.environ['HPC_OUTPUT_DIR']);out.mkdir(parents=True,exist_ok=True)
metadata={'task_id':os.environ['HPC_TASK_ID'],'attempt':int(os.environ['HPC_ATTEMPT']),'job_id':os.environ.get('SLURM_JOB_ID'),'node':os.environ.get('SLURMD_NODENAME'),'requested':r,'gpus':[],'verified':False}
try:
    if r['gpu_count']:
        p=subprocess.run(['nvidia-smi','--query-gpu=index,uuid,name,memory.total,driver_version','--format=csv,noheader,nounits'],capture_output=True,text=True,check=True,timeout=15)
        rows=list(csv.reader(p.stdout.splitlines(),skipinitialspace=True))
        # Device cgroups may expose an already restricted list. Slurm GPU ids
        # are global; CUDA ordinals can be remapped inside that list.
        if len(rows)!=r['gpu_count']:
            visible=os.environ.get('SLURM_STEP_GPUS') or os.environ.get('SLURM_JOB_GPUS') or os.environ.get('CUDA_VISIBLE_DEVICES','')
            ids=[]
            for item in visible.split(','):
                if '-' in item and all(x.isdigit() for x in item.split('-')):
                    a,b=map(int,item.split('-'));ids.extend(str(x) for x in range(a,b+1))
                else: ids.append(item)
            rows=[x for x in rows if x[0].strip() in ids or x[1].strip() in ids]
        if len(rows)!=r['gpu_count']: raise ValueError('visible GPU count differs from declared GPU count')
        for x in rows:
            gpu={'uuid':x[1].strip(),'name':x[2].strip(),'memory_mb':int(float(x[3])),'driver_version':x[4].strip()}
            if gpu['name']!=r['expected_gpu_name']: raise ValueError('GPU model mismatch: '+gpu['name'])
            if abs(gpu['memory_mb']-r['expected_gpu_memory_mb'])>r['gpu_memory_tolerance_mb']: raise ValueError('GPU memory mismatch')
            if r.get('expected_gpu_uuid') and gpu['uuid']!=r['expected_gpu_uuid']: raise ValueError('physical GPU UUID mismatch')
            metadata['gpus'].append(gpu)
    metadata['verified']=True
except Exception as exc:
    metadata['error']=str(exc)
finally:
    dest=out/'.controller';dest.mkdir(exist_ok=True)
    (dest/('hardware-'+os.environ['HPC_ATTEMPT']+'.json')).write_text(json.dumps(metadata,sort_keys=True))
if not metadata['verified']: sys.exit(86)
'''


def remote_root(settings, campaign):
    return settings["remote_root"].rstrip("/") + "/campaigns/" + campaign["id"]


def output_dir(settings, campaign, task):
    return remote_root(settings, campaign) + "/outputs/" + task["task_id"]


def script(settings, campaign, task, placement):
    spec, resources = task["spec"], task["spec"]["resources"]
    base = remote_root(settings, campaign)
    output = output_dir(settings, campaign, task)
    headers = {"job-name": task["job_name"], "account": settings["account"], "partition": ",".join(placement["selected_partitions"]),
               "time": f"{resources['walltime_seconds'] // 86400}-{resources['walltime_seconds'] // 3600 % 24:02}:{resources['walltime_seconds'] // 60 % 60:02}:{resources['walltime_seconds'] % 60:02}", "nodes": "1", "cpus-per-task": str(resources["cpus"]),
               "mem": str(resources["memory_mb"]) + "M", "output": base + "/logs/" + task["job_name"] + ".out", "error": base + "/logs/" + task["job_name"] + ".err",
               "qos": placement["qos"], "no-requeue": None}
    if settings.get("mail_user"):
        headers["mail-user"] = settings["mail_user"]
        headers["mail-type"] = MAIL_TYPES
    if resources["gpu_count"]:
        headers["gres"] = f"gpu:{resources['gpu_type']}:{resources['gpu_count']}"
    if resources.get("constraint"):
        headers["constraint"] = resources["constraint"]
    if resources.get("nodelist"):
        headers["nodelist"] = resources["nodelist"]
    lines = ["#!/usr/bin/env bash", *(f"#SBATCH --{k}" + (f"={v}" if v is not None else "") for k, v in headers.items()), "set -euo pipefail", "umask 077"]
    env = {**spec["env"], "HPC_TASK_ID": task["task_id"], "HPC_OUTPUT_DIR": output, "HPC_ATTEMPT": str(task["attempt"]),
           "HPC_CAMPAIGN_ID": campaign["id"], "HPC_HARDWARE_PROFILE_ID": spec.get("model_class", "cpu"),
           "HPC_EXPECT_GPU_NAME": resources.get("expected_gpu_name", ""), "HPC_EXPECT_GPU_MEMORY_MB": str(resources.get("expected_gpu_memory_mb", ""))}
    lines.extend(f"export {key}={shlex.quote(value)}" for key, value in env.items())
    lines.extend(["cd " + shlex.quote(base + "/source"), "mkdir -p " + shlex.quote(output), "python3 - " + shlex.quote(json.dumps(resources)) + " <<'HPC_PREFLIGHT'", PREFLIGHT.strip(), "HPC_PREFLIGHT"])
    if resources["gpu_count"] and settings.get("sample_gpu_metrics", True):
        metrics = output + "/.controller/gpu-samples-" + str(task["attempt"]) + ".csv"
        hardware = output + "/.controller/hardware-" + str(task["attempt"]) + ".json"
        lines.extend(["HPC_GPU_IDS=$(python3 -c " + shlex.quote("import json,sys;print(','.join(g['uuid'] for g in json.load(open(sys.argv[1]))['gpus']))") + " " + shlex.quote(hardware) + ")",
                      "nvidia-smi --id=\"${HPC_GPU_IDS}\" --query-gpu=timestamp,index,uuid,utilization.gpu,memory.used,power.draw --format=csv --loop=30 >" + shlex.quote(metrics) + " 2>/dev/null &", "HPC_SAMPLE_PID=$!", "trap 'kill \"${HPC_SAMPLE_PID}\" 2>/dev/null || true' EXIT"])
    argv = [a.replace("{output_dir}", output).replace("{task_id}", task["task_id"]) for a in spec["argv"]]
    lines.append(shlex.join(argv))
    return "\n".join(lines) + "\n"


class SlurmAdapter:
    def __init__(self, settings):
        self.settings = settings
        self.host = settings["ssh_host"]
        self.ssh = ssh_argv(self.host, settings.get("ssh_identity", ""))
        self.ssh[1:1] = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2"]
        self.env = _agent_env(self.host)

    def command(self, command, timeout=90, input=None):
        return subprocess.run([*self.ssh, "export PAGER=NONE TZ=UTC LC_ALL=C; " + command], input=input, capture_output=True, text=True, timeout=timeout, env=self.env)

    def transfer(self, source, remote, pull=False, include=None):
        remote_spec = self.host + ":" + remote
        endpoints = [remote_spec, str(source)] if pull else [str(source), remote_spec]
        filters = []
        if include:
            for pattern in include:
                filters.extend(["--include", pattern])
            filters.extend(["--exclude", "*"])
        result = subprocess.run(["rsync", "-a", "--safe-links", "--protect-args", *filters, "-e", shlex.join(self.ssh[:-1]), *endpoints], capture_output=True, text=True, timeout=300, env=self.env)
        if result.returncode:
            raise RuntimeError("artifact transfer failed: " + result.stderr[-1500:])

    def stage(self, campaign):
        base = remote_root(self.settings, campaign)
        manifest_sha = campaign.get("spec", {}).get("bundle_manifest", {}).get("sha256", "")
        if not re.fullmatch(r"[a-f0-9]{64}", manifest_sha):
            raise RuntimeError("source cache requires the frozen bundle manifest digest")
        cache_parent = self.settings["remote_root"].rstrip("/") + "/source-cache"
        cache = cache_parent + "/" + manifest_sha
        cache_source = cache + "/source"
        marker = cache + "/.controller-source-manifest-sha256"
        archive = store.root(campaign["id"]) / "bundle.tar.gz"
        digest = hashlib.sha256()
        with archive.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
        sha = digest.hexdigest()
        quote = shlex.quote
        publish = "\n".join([
            "HPC_SOURCE_LINK=" + quote(base + "/.source-link-") + "$$",
            "ln -s " + quote(cache_source) + " \"${HPC_SOURCE_LINK}\"",
            "mv -T \"${HPC_SOURCE_LINK}\" " + quote(base + "/source"),
        ])
        ready = "\n".join([
            "if test -e " + quote(base + "/source") + " || test -L " + quote(base + "/source") + "; then",
            "  if test -L " + quote(base + "/source") + " && test \"$(readlink " + quote(base + "/source") + ")\" = " + quote(cache_source)
            + " && test -d " + quote(cache) + " && ! test -L " + quote(cache)
            + " && test -d " + quote(cache_source) + " && ! test -L " + quote(cache_source)
            + " && test -f " + quote(marker) + " && ! test -L " + quote(marker)
            + " && test \"$(cat " + quote(marker) + ")\" = " + quote(manifest_sha) + "; then echo HPC_SOURCE_CACHE_HIT; exit 0; fi",
            "  if ! test -L " + quote(base + "/source") + " && test -f " + quote(base + "/source/.bundle-sha256")
            + " && ! test -L " + quote(base + "/source/.bundle-sha256")
            + " && test \"$(cat " + quote(base + "/source/.bundle-sha256") + ")\" = " + quote(sha)
            + "; then echo HPC_SOURCE_LEGACY_READY; exit 0; fi",
            "  echo 'existing campaign source differs from its frozen snapshot; preserved' >&2; exit 1",
            "fi",
            "if test -e " + quote(cache) + " || test -L " + quote(cache) + "; then",
            "  if ! test -d " + quote(cache) + " || test -L " + quote(cache)
            + " || ! test -d " + quote(cache_source) + " || test -L " + quote(cache_source)
            + " || ! test -f " + quote(marker) + " || test -L " + quote(marker)
            + " || test \"$(cat " + quote(marker) + ")\" != " + quote(manifest_sha)
            + "; then echo 'source cache marker differs from the frozen manifest; preserved' >&2; exit 1; fi",
            publish,
            "  echo HPC_SOURCE_CACHE_HIT; exit 0",
            "fi",
        ])
        locked = "exec 9>" + quote(cache_parent + "/locks/" + manifest_sha + ".lock") + "; flock 9;\n"
        directories = [base + "/" + name for name in ("jobs", "logs", "receipts", "outputs")]
        directories += [cache_parent, cache_parent + "/locks"]
        initial = "set -e; umask 077; mkdir -p " + " ".join(quote(path) for path in directories)
        result = self.command(initial + ";\n" + locked + ready + "\necho HPC_SOURCE_NEEDS_UPLOAD")
        if result.returncode:
            raise RuntimeError("remote source cache readiness failed: " + result.stderr[-1500:])
        if "HPC_SOURCE_NEEDS_UPLOAD" not in result.stdout.splitlines():
            if not any(token in result.stdout.splitlines() for token in ("HPC_SOURCE_CACHE_HIT", "HPC_SOURCE_LEGACY_READY")):
                raise RuntimeError("remote source cache readiness receipt missing")
            legacy = "HPC_SOURCE_LEGACY_READY" in result.stdout.splitlines()
            return {"source_manifest_sha256": manifest_sha, "cache_hit": "HPC_SOURCE_CACHE_HIT" in result.stdout.splitlines(),
                    "legacy_source": legacy, "cache_path": None if legacy else cache,
                    "source_path": base + "/source" if legacy else cache_source}
        self.transfer(archive, base + "/bundle.tar.gz")
        extract = "\n".join([
            "set -e; umask 077; " + locked + ready,
            "cd " + quote(base), "printf '%s  bundle.tar.gz\\n' " + quote(sha) + " | sha256sum -c -",
            "HPC_STAGE_DIR=$(mktemp -d " + quote(cache_parent + "/.stage-" + manifest_sha + ".XXXXXX") + ")",
            "mkdir \"${HPC_STAGE_DIR}/source\"", "tar -xzf bundle.tar.gz -C \"${HPC_STAGE_DIR}/source\"",
            "printf '%s\\n' " + quote(manifest_sha) + " >\"${HPC_STAGE_DIR}/.controller-source-manifest-sha256\"",
            "printf '%s\\n' " + quote(sha) + " >\"${HPC_STAGE_DIR}/.bundle-sha256\"",
            "chmod -R a-w \"${HPC_STAGE_DIR}\"", "mv \"${HPC_STAGE_DIR}\" " + quote(cache),
            publish, "echo HPC_SOURCE_CACHE_CREATED",
        ])
        result = self.command(extract)
        if result.returncode:
            raise RuntimeError("remote bundle verification failed: " + result.stderr[-1500:])
        if not any(token in result.stdout.splitlines() for token in ("HPC_SOURCE_CACHE_CREATED", "HPC_SOURCE_CACHE_HIT", "HPC_SOURCE_LEGACY_READY")):
            raise RuntimeError("remote source cache activation receipt missing")
        legacy = "HPC_SOURCE_LEGACY_READY" in result.stdout.splitlines()
        return {"source_manifest_sha256": manifest_sha, "cache_hit": "HPC_SOURCE_CACHE_HIT" in result.stdout.splitlines(),
                "legacy_source": legacy, "cache_path": None if legacy else cache,
                "source_path": base + "/source" if legacy else cache_source}

    def submit(self, campaign, task, placement):
        base = remote_root(self.settings, campaign)
        path = base + "/jobs/" + task["job_name"] + ".sh"
        result = self.command("umask 077; cat > " + shlex.quote(path), input=script(self.settings, campaign, task, placement))
        if result.returncode:
            return {"outcome": "rejected", "error": "job script staging failed: " + result.stderr[-1500:]}
        receipt = base + "/receipts/" + task["job_name"]
        code = "\n".join(["set -u", "exec 9>" + shlex.quote(receipt + ".lock"), "flock 9", "if test -s " + shlex.quote(receipt) + "; then cat " + shlex.quote(receipt) + "; exit 0; fi",
                           "sbatch --parsable " + shlex.quote(path) + " >" + shlex.quote(receipt + ".tmp"), "HPC_RC=$?", "if test \"$HPC_RC\" -ne 0; then echo HPC_SUBMISSION_REJECTED >&2; exit \"$HPC_RC\"; fi",
                           "mv " + shlex.quote(receipt + ".tmp") + " " + shlex.quote(receipt), "cat " + shlex.quote(receipt)])
        result = self.command("bash -c " + shlex.quote(code))
        match = re.fullmatch(r"\s*(\d+)(?:;[A-Za-z0-9_.-]+)?\s*", result.stdout)
        if result.returncode == 0 and match:
            return {"outcome": "accepted", "job_id": match[1]}
        # Only an explicit remote refusal proves that no job was accepted.
        return {"outcome": "rejected" if "HPC_SUBMISSION_REJECTED" in result.stderr else "uncertain", "error": result.stderr[-1500:] or "submission receipt missing"}

    def observe(self, campaign, tasks):
        names = ",".join(t["job_name"] for t in tasks)
        created = datetime.fromisoformat(campaign["created_at"].replace("Z", "+00:00"))
        start = (created.astimezone(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
        command = "set -e; printf 'QUEUE\\n'; timeout 20 squeue -h --name=" + shlex.quote(names) + " -o '%i|%j|%T|%R|%N|%S'; printf 'ACCOUNTING\\n'; timeout 30 sacct -u $(whoami) --name=" + shlex.quote(names) + " -S " + shlex.quote(start) + " -E now -P -n -o JobIDRaw,JobName%100,State,ExitCode,NodeList,ElapsedRaw,Submit,Start,End,AllocTRES,MaxRSS,TotalCPU,TRESUsageInMax"
        result = self.command(command, timeout=70)
        if result.returncode:
            raise RuntimeError("scheduler observation failed: " + result.stderr[-1500:])
        queue, accounting, section = {}, {}, ""
        for line in result.stdout.splitlines():
            if line in ("QUEUE", "ACCOUNTING"):
                section = line
                continue
            row = line.split("|")
            if len(row) < 5 or "." in row[0]:
                continue
            identity, name, state = (x.strip() for x in row[:3])
            if not identity.isdigit() or not state or section not in ("QUEUE", "ACCOUNTING"):
                continue
            observation = {"job_id": identity, "job_name": name, "state": state.split()[0].rstrip("+"), "node_list": row[4].strip(), "source": section}
            if section == "QUEUE":
                observation["pending_reason"] = row[3].strip() if observation["state"] == "PENDING" else None
                estimate = row[5].strip() if len(row) >= 6 else ""
                try:
                    datetime.fromisoformat(estimate)
                except ValueError:
                    estimate = None
                observation["estimated_start"] = estimate if observation["state"] == "PENDING" else None
                observation["estimated_start_source"] = "Slurm backfill hint; can change" if observation["estimated_start"] else None
            elif len(row) >= 13:
                observation.update(exit_code=row[3].strip(), elapsed_seconds=int(row[5] or 0), submit=row[6], start=row[7], end=row[8], alloc_tres=row[9], max_rss=row[10] or None, total_cpu=row[11] or None, tres_usage_in_max=row[12] or None)
            existing = queue.get(name) or accounting.get(name)
            if existing and existing["job_id"] != identity:
                raise RuntimeError("multiple scheduler jobs match one submission intent")
            (queue if section == "QUEUE" else accounting)[name] = observation
        values = {}
        for name in accounting.keys() | queue.keys():
            record = dict(accounting.get(name, {}))
            if name in queue:
                # Accounting can lag a live allocation or become terminal while
                # epilog still runs. Queue state owns progression until the job
                # disappears, while accounting continues to supply its details.
                if name in accounting:
                    record["accounting_state"] = accounting[name]["state"]
                    record["accounting_node_list"] = accounting[name]["node_list"]
                record.update(queue[name])
            record["sources"] = [source for source, rows in (("QUEUE", queue), ("ACCOUNTING", accounting)) if name in rows]
            record["observed_at"] = store.now()
            values[name] = record
        return values

    def collect(self, campaign, task):
        local = store.root(campaign["id"]) / "results" / task["task_id"]
        local.mkdir(parents=True, exist_ok=True)
        includes = ["/.controller/", "/.controller/***"]
        for output in task["spec"]["outputs"]:
            path = Path(output)
            for parent in reversed(path.parents):
                if str(parent) != ".":
                    includes.append("/" + str(parent) + "/")
            escaped = re.sub(r"([*?\[\]\\])", r"\\\1", output)
            includes.append("/" + escaped)
        self.transfer(local, output_dir(self.settings, campaign, task) + "/", pull=True, include=includes)
        base = remote_root(self.settings, campaign)
        for suffix in ("out", "err"):
            try:
                self.transfer(local / (task["job_name"] + "." + suffix), base + "/logs/" + task["job_name"] + "." + suffix, pull=True)
            except RuntimeError:
                pass
        return local

    def cancel(self, job_ids):
        if not all(str(x).isdigit() for x in job_ids):
            raise CampaignError("invalid scheduler identity")
        if job_ids:
            result = self.command("timeout 20 scancel " + " ".join(job_ids), timeout=30)
            if result.returncode:
                raise RuntimeError(result.stderr[-1500:])

    def probe(self):
        command = "set -e; export PATH=/modules/user-resources/bin:$PATH; printf 'NODES\\n'; timeout 25 scontrol show node -o; printf 'PARTITIONS\\n'; timeout 20 scontrol show partition -o; printf 'QOS\\n'; timeout 20 sacctmgr -n -P show qos format=Name,MaxWall,MaxJobsPerUser,MaxSubmitJobsPerUser,MaxTRESPerUser; printf 'ASSOCIATIONS\\n'; timeout 20 sacctmgr -n -P show assoc where user=$(whoami) format=Account,QOS,MaxJobs,MaxSubmitJobs,GrpTRES,MaxWallDurationPerJob; printf 'ACCOUNT_LIMITS\\n'; timeout 20 sacctmgr -n -P show assoc where account=" + shlex.quote(self.settings["account"]) + " format=Account,User,GrpTRES,GrpJobs,GrpSubmitJobs; printf 'GROUPS\\n'; id -Gn; printf 'FAIRSHARE\\n'; timeout 15 sshare -U -n -P -o Account,User,FairShare,EffectvUsage"
        result = self.command(command, timeout=150)
        if result.returncode:
            raise RuntimeError("backend probe failed: " + result.stderr[-1500:])
        return parse_probe(result.stdout, self.settings["account"])


def parse_probe(text, account):
    from controller.campaign_planner import seconds
    value = {"observed_at": store.now(), "nodes": [], "partitions": {}, "qos": {}, "associations": {}, "groups": [], "account": {"name": account}, "source": "bounded SSH Slurm commands"}
    section = ""
    for line in text.splitlines():
        if line in ("NODES", "PARTITIONS", "QOS", "ASSOCIATIONS", "ACCOUNT_LIMITS", "GROUPS", "FAIRSHARE"):
            section = line
            continue
        fields = dict(re.findall(r"(?:^|\s)([A-Za-z][A-Za-z0-9_]*)=([^\s]*)", line))
        if section == "NODES" and "NodeName" in fields:
            gpus = {name: int(count) for name, count in re.findall(r"gpu:([^:,()]+):(\d+)", fields.get("Gres", ""))}
            value["nodes"].append({"name": fields["NodeName"], "cpus": int(fields.get("CPUTot", 0)), "memory_mb": int(fields.get("RealMemory", 0)), "features": fields.get("ActiveFeatures", "").split(","), "partitions": fields.get("Partitions", "").split(","), "gpus": gpus, "state": fields.get("State"), "alloc_tres": fields.get("AllocTRES"), "free_memory_mb": int(fields["FreeMem"]) if fields.get("FreeMem", "").isdigit() else None})
        elif section == "PARTITIONS" and "PartitionName" in fields:
            value["partitions"][fields["PartitionName"]] = {"state": fields.get("State"), "max_walltime_seconds": seconds(fields.get("MaxTime")), "priority_tier": int(fields.get("PriorityTier", 0)), "preempt_mode": fields.get("PreemptMode", "OFF"), **{key: fields.get(source, "").split(",") if fields.get(source) not in (None, "(null)", "") else [] for key, source in (("allow_accounts", "AllowAccounts"), ("deny_accounts", "DenyAccounts"), ("allow_groups", "AllowGroups"), ("allow_qos", "AllowQos"), ("deny_qos", "DenyQos"))}}
        elif section == "QOS":
            row = line.split("|")
            if len(row) >= 5:
                value["qos"][row[0]] = {"max_walltime_seconds": seconds(row[1]), "max_jobs": int(row[2]) if row[2].isdigit() else None, "max_submit_jobs": int(row[3]) if row[3].isdigit() else None, "max_tres_per_user": row[4] or None}
        elif section == "ASSOCIATIONS":
            row = line.split("|")
            if len(row) >= 6:
                value["associations"][row[0]] = {"qos": row[1].split(","), "max_jobs": int(row[2]) if row[2].isdigit() else None, "max_submit_jobs": int(row[3]) if row[3].isdigit() else None, "grp_tres": row[4] or None, "max_walltime_seconds": seconds(row[5])}
                if row[0] == account:
                    value["account"].update(value["associations"][row[0]])
        elif section == "ACCOUNT_LIMITS":
            row = line.split("|")
            if len(row) >= 5 and row[0] == account and not row[1]:
                value["account"].update(grp_tres=row[2] or None, grp_jobs=int(row[3]) if row[3].isdigit() else None, grp_submit_jobs=int(row[4]) if row[4].isdigit() else None)
        elif section == "GROUPS":
            value["groups"] = line.split()
        elif section == "FAIRSHARE":
            row = line.split("|")
            if len(row) >= 4 and row[0] == account:
                value["fairshare"] = {"factor": float(row[2]) if row[2] else None, "effective_usage": float(row[3]) if row[3] else None}
    return value
