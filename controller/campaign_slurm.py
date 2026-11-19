"""Slurm protocol for portable campaigns over Cluster access. No caller-side run.sh or registry.

Every remote command is bounded. Submission receipts are written under a
remote flock; a missing receipt after an SSH failure is an uncertain outcome.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shlex
from datetime import datetime, timedelta, timezone
from pathlib import Path

from controller import campaign_store as store, catalog, cluster_access, hardware_class
from controller.campaign_contract import CampaignError


MAIL_TYPES = "END,FAIL,TIME_LIMIT,REQUEUE"


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
        # Some Unity devices appear in GRES but are absent from the submit
        # plugin's typed-name allowlist. The validated exact feature, catalog
        # GPU type, and in-job device attestation retain the hardware lock.
        if resources.get("gpu_request_by_constraint"):
            headers["gres"] = f"gpu:{resources['gpu_count']}"
        else:
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
    lines.extend(["cd " + shlex.quote(base + "/source"), "mkdir -p " + shlex.quote(output), "python3 - " + shlex.quote(json.dumps(resources)) + " <<'HPC_PREFLIGHT'", hardware_class.ATTESTATION_PROGRAM, "HPC_PREFLIGHT"])
    if resources["gpu_count"] and settings.get("sample_gpu_metrics", True):
        metrics = output + "/" + hardware_class.gpu_samples(task["attempt"])
        hardware = output + "/" + hardware_class.hardware_evidence(task["attempt"])
        lines.extend(["HPC_GPU_IDS=$(python3 -c " + shlex.quote("import json,sys;print(','.join(g['uuid'] for g in json.load(open(sys.argv[1]))['gpus']))") + " " + shlex.quote(hardware) + ")",
                      "nvidia-smi --id=\"${HPC_GPU_IDS}\" --query-gpu=timestamp,index,uuid,utilization.gpu,memory.used,power.draw --format=csv --loop=30 >" + shlex.quote(metrics) + " 2>/dev/null &", "HPC_SAMPLE_PID=$!", "trap 'kill \"${HPC_SAMPLE_PID}\" 2>/dev/null || true' EXIT"])
    argv = [a.replace("{output_dir}", output).replace("{task_id}", task["task_id"]) for a in spec["argv"]]
    lines.append(shlex.join(argv))
    return "\n".join(lines) + "\n"


class SlurmAdapter:
    """The Slurm protocol over one Cluster access transport: stage, submit, observe, collect, cancel, probe."""

    def __init__(self, settings, transport=None):
        self.settings = settings
        self.transport = transport if transport is not None else cluster_access.Ssh(settings["ssh_host"], settings.get("ssh_identity", ""))

    def command(self, command, timeout=90, input=None):
        return self.transport.run("export PAGER=NONE TZ=UTC LC_ALL=C; " + command, timeout=timeout, input=input)

    def transfer(self, source, remote, pull=False, include=None):
        result = self.transport.transfer(source, remote, pull=pull, include=include or ())
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
        archive = store.root(campaign["id"]) / "bundle.tar.gz"
        with archive.open("rb") as stream:
            sha = hashlib.file_digest(stream, "sha256").hexdigest()
        quote = shlex.quote
        link, cached, source, marker = quote(base + "/source"), quote(cache), quote(cache_source), quote(cache + "/.controller-source-manifest-sha256")
        legacy_marker, manifest_word, sha_word = quote(base + "/source/.bundle-sha256"), quote(manifest_sha), quote(sha)
        # The cache is intact when each path has its type, is not a symlink, and the marker names the frozen manifest.
        checks = (("-d", cached), ("-d", source), ("-f", marker))
        intact = " && ".join(f"test {kind} {path} && ! test -L {path}" for kind, path in checks) + f" && test \"$(cat {marker})\" = {manifest_word}"
        damaged = " || ".join(f"! test {kind} {path} || test -L {path}" for kind, path in checks) + f" || test \"$(cat {marker})\" != {manifest_word}"
        publish = "\n".join(["HPC_SOURCE_LINK=" + quote(base + "/.source-link-") + "$$", "ln -s " + source + " \"${HPC_SOURCE_LINK}\"", "mv -T \"${HPC_SOURCE_LINK}\" " + link])
        ready = "\n".join([
            f"if test -e {link} || test -L {link}; then",
            f"  if test -L {link} && test \"$(readlink {link})\" = {source} && {intact}; then echo HPC_SOURCE_CACHE_HIT; exit 0; fi",
            f"  if ! test -L {link} && test -f {legacy_marker} && ! test -L {legacy_marker} && test \"$(cat {legacy_marker})\" = {sha_word}; then echo HPC_SOURCE_LEGACY_READY; exit 0; fi",
            "  echo 'existing campaign source differs from its frozen snapshot; preserved' >&2; exit 1",
            "fi",
            f"if test -e {cached} || test -L {cached}; then",
            f"  if {damaged}; then echo 'source cache marker differs from the frozen manifest; preserved' >&2; exit 1; fi",
            publish,
            "  echo HPC_SOURCE_CACHE_HIT; exit 0",
            "fi",
        ])
        locked = "exec 9>" + quote(cache_parent + "/locks/" + manifest_sha + ".lock") + "; flock 9;\n"
        directories = [base + "/" + name for name in ("jobs", "logs", "receipts", "outputs")]
        directories += [cache_parent, cache_parent + "/locks"]
        initial = "set -e; umask 077; mkdir -p " + " ".join(quote(path) for path in directories)
        result = self.command(initial + ";\n" + locked + ready + "\necho HPC_SOURCE_NEEDS_UPLOAD", timeout=600)
        if result.returncode:
            raise RuntimeError("remote source cache readiness failed: " + result.stderr[-1500:])
        lines = result.stdout.splitlines()
        if "HPC_SOURCE_NEEDS_UPLOAD" in lines:
            self.transfer(archive, base + "/bundle.tar.gz")
            extract = "\n".join([
                "set -e; umask 077; " + locked + ready,
                "cd " + quote(base), "printf '%s  bundle.tar.gz\\n' " + sha_word + " | sha256sum -c -",
                "HPC_STAGE_DIR=$(mktemp -d " + quote(cache_parent + "/.stage-" + manifest_sha + ".XXXXXX") + ")",
                "mkdir \"${HPC_STAGE_DIR}/source\"", "tar -xzf bundle.tar.gz -C \"${HPC_STAGE_DIR}/source\"",
                "printf '%s\\n' " + manifest_word + " >\"${HPC_STAGE_DIR}/.controller-source-manifest-sha256\"",
                "printf '%s\\n' " + sha_word + " >\"${HPC_STAGE_DIR}/.bundle-sha256\"",
                "chmod -R a-w \"${HPC_STAGE_DIR}\"", "mv \"${HPC_STAGE_DIR}\" " + cached,
                publish, "echo HPC_SOURCE_CACHE_CREATED",
            ])
            result = self.command(extract, timeout=600)
            if result.returncode:
                raise RuntimeError("remote bundle verification failed: " + result.stderr[-1500:])
            lines = result.stdout.splitlines()
            if not any(token in lines for token in ("HPC_SOURCE_CACHE_CREATED", "HPC_SOURCE_CACHE_HIT", "HPC_SOURCE_LEGACY_READY")):
                raise RuntimeError("remote source cache activation receipt missing")
        elif not any(token in lines for token in ("HPC_SOURCE_CACHE_HIT", "HPC_SOURCE_LEGACY_READY")):
            raise RuntimeError("remote source cache readiness receipt missing")
        legacy = "HPC_SOURCE_LEGACY_READY" in lines
        return {"source_manifest_sha256": manifest_sha, "cache_hit": "HPC_SOURCE_CACHE_HIT" in lines,
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
        includes = ["/" + hardware_class.EVIDENCE_DIR + "/", "/" + hardware_class.EVIDENCE_DIR + "/***"]
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
        return catalog.parse(result.stdout, self.settings["account"])
