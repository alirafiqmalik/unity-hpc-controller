#!/usr/bin/env python3
"""Model-check the campaign Worker pass (tests/formal/campaign_worker) with TLC.

Usage:
  python3 tests/formal/check_campaign_worker.py            # model, findings, and broken variants
  python3 tests/formal/check_campaign_worker.py --model    # the model only
  python3 tests/formal/check_campaign_worker.py --keep DIR # keep TLC output and specs in DIR

Every check must end as expected: the model passes, and each broken variant
or recorded finding breaks the rule named next to it. A broken variant that
passes means the model can no longer see that bug.

TLC comes from $TLA2TOOLS_JAR, else a pinned tla2tools.jar (v1.7.4, checked by
SHA-256) cached under $XDG_CACHE_HOME/unity-hpc. Java 11 or later comes from
$JAVA, else `java` on PATH. The first run downloads the jar.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent / "campaign_worker"
TLC_VERSION = "1.7.4"
TLC_URL = f"https://github.com/tlaplus/tlaplus/releases/download/v{TLC_VERSION}/tla2tools.jar"
TLC_SHA256 = "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
CAPACITY = ("CapacityHeld", "QosLimitHeld", "AccountLimitHeld")

# name, why it must fail, config changes, spec edits (old, new), rules it may break
CHECKS = [
    ("model", "the code's design", {}, [], ()),
    ("ad4db80-qos-rule",
     "finding at ad4db80: a task without qos counts under the candidate campaign's default QOS",
     {"QosRule": '"candidate-default"', "MaxActive": "3", "AccountJobLimit": "3"}, [], ("QosLimitHeld",)),
    ("ad4db80-account-rule",
     "finding at ad4db80: account job limits count only same-QOS tasks",
     {"AccountRule": '"same-qos"', "MaxActive": "3", "MaxGpus": "2", "QosJobLimit": "MCWideQosJobLimit"}, [],
     ("AccountLimitHeld",)),
    ("no-rebuild-after-error",
     "admission keeps its totals after record_submission raised",
     {}, [("    /\\ counted' = ActiveTasks\n    /\\ todo' = Tail(todo)", "    /\\ UNCHANGED counted\n    /\\ todo' = Tail(todo)")],
     CAPACITY),
    ("count-accepted-only",
     "an uncertain submission does not join the totals",
     {}, [("counted' = IF next \\in Active THEN", "counted' = IF next = \"live\" THEN")], CAPACITY),
    ("retry-uncertain-blindly",
     "reconcile sends an uncertain task without a visible job back to waiting",
     {}, [("THEN /\\ task[t].state = \"submitting\"\n              /\\ task' = [task EXCEPT ![t].state = \"uncertain\"]",
           "THEN /\\ task[t].state \\in {\"submitting\", \"uncertain\"}\n"
           "              /\\ task' = [task EXCEPT ![t].state = IF task[t].state = \"uncertain\" THEN \"waiting\" ELSE \"uncertain\"]")],
     ("SlurmWorkCounted",)),
    ("submit-before-intent",
     "sbatch runs before the journal records the attempt",
     {}, [("    /\\ task' = [task EXCEPT ![t] = [state |-> \"submitting\", attempt |-> @.attempt + 1, jobKnown |-> FALSE]]\n",
           "    /\\ UNCHANGED task\n"),
          ("NewJob(t) == [task |-> t, attempt |-> task[t].attempt, status", "NewJob(t) == [task |-> t, attempt |-> task[t].attempt + 1, status"),
          ("inflight \\cup {<<cand, task[cand].attempt>>}", "inflight \\cup {<<cand, task[cand].attempt + 1>>}"),
          ("task' = [task EXCEPT ![cand].state = next,", "task' = [task EXCEPT ![cand].attempt = @ + 1, ![cand].state = next,")],
     ("IntentBeforeSlurm", "SlurmWorkCounted")),
    ("cancel-without-lock",
     "an HTTP cancel runs while the Worker pass holds campaigns.lock()",
     {}, [("CancelBegin(c) ==\n    /\\ lock = \"free\"", "CancelBegin(c) ==\n    /\\ cancelOf = None"),
          ("    /\\ lock' = \"cancel\"\n", "    /\\ UNCHANGED lock\n"),
          ("CancelEnd ==\n    /\\ lock = \"cancel\"", "CancelEnd ==\n    /\\ cancelOf # None"),
          ("    /\\ lock' = \"free\"\n    /\\ cancelOf' = None\n    /\\ UNCHANGED <<inflight,", "    /\\ cancelOf' = None\n    /\\ UNCHANGED <<lock, inflight,"),
          ("Crash ==\n    /\\ lock # \"free\"", "Crash ==\n    /\\ (lock # \"free\" \\/ cancelOf # None)")],
     ("CancelFence",)),
    ("cancel-marks-active-done",
     "a cancel request records an active task cancelled before Slurm ends its job",
     {}, [("IF CampaignOf[t] = c /\\ task[t].state = \"waiting\"", "IF CampaignOf[t] = c /\\ task[t].state # \"done\"")],
     ("SlurmWorkCounted",)),
]


def tlc_jar():
    if os.environ.get("TLA2TOOLS_JAR"):
        return Path(os.environ["TLA2TOOLS_JAR"])
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "unity-hpc"
    jar = cache / f"tla2tools-{TLC_VERSION}.jar"
    if not jar.exists():
        cache.mkdir(parents=True, exist_ok=True)
        print(f"downloading TLC {TLC_VERSION} ...", flush=True)
        data = urllib.request.urlopen(TLC_URL, timeout=120).read()
        if hashlib.sha256(data).hexdigest() != TLC_SHA256:
            sys.exit("tla2tools.jar checksum mismatch; refusing to run it")
        partial = jar.with_suffix(".part")
        partial.write_bytes(data)
        partial.replace(jar)
    return jar


def edited(text, edits, name):
    for old, new in edits:
        if text.count(old) != 1:
            sys.exit(f"{name}: spec edit target occurs {text.count(old)} times, expected once:\n{old}")
        text = text.replace(old, new)
    return text


def configured(text, changes, name):
    for key, value in changes.items():
        pattern = re.compile(rf"^(\s+{key}\s*(?:=|<-)\s*).*$", re.M)
        if len(pattern.findall(text)) != 1:
            sys.exit(f"{name}: config has no single {key} line")
        text = pattern.sub(lambda m: m.group(1) + value, text)
    return text


def trace(output):
    """The counterexample as numbered steps: the action, then the variables that changed."""
    steps, previous = [], {}
    for number, action, body in re.findall(r"^State (\d+): <(.*?)>\n(.*?)(?=^\s*$)", output, re.M | re.S):
        values = dict(re.findall(r"^/\\ (\w+) = (.*?)(?=^/\\ |\Z)", body, re.M | re.S))
        values = {key: " ".join(value.split()) for key, value in values.items()}
        changed = {key: value for key, value in values.items() if previous.get(key) != value} if previous else {}
        name = action.split(" line ")[0]
        steps.append(f"  {number}. {name}" + "".join(f"\n       {key} = {value}" for key, value in changed.items()
                                                       if key in ("task", "campaign", "jobs", "inflight", "counted")))
        previous = values
    return "\n".join(steps)


def run(java, jar, work, name, changes, edits):
    directory = work / name
    directory.mkdir(parents=True)
    spec = edited((HERE / "CampaignWorker.tla").read_text(), edits, name)
    (directory / "CampaignWorker.tla").write_text(spec)
    shutil.copy(HERE / "MCCampaignWorker.tla", directory)
    (directory / "MC.cfg").write_text(configured((HERE / "MCCampaignWorker.cfg").read_text(), changes, name))
    command = [java, "-XX:+UseParallelGC", "-cp", str(jar), "tlc2.TLC", "-workers", "auto", "-cleanup",
               "-metadir", str(directory / "states"), "-config", "MC.cfg", "MCCampaignWorker.tla"]
    result = subprocess.run(command, cwd=directory, capture_output=True, text=True)
    output = result.stdout + result.stderr
    (directory / "tlc.out").write_text(output)
    broken = re.findall(r"(?:Invariant|Action property|property) (\w+) is violated", output)
    if "Temporal properties were violated" in output:
        broken.append("CancelFence")
    states = re.findall(r"([\d,]+) distinct states found", output)
    passed = "Model checking completed. No error has been found." in output
    if not passed and not broken:
        sys.exit(f"{name}: TLC did not finish:\n{output[-3000:]}")
    return passed, broken, states[-1] if states else "?", output


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", action="store_true", help="check the model only")
    parser.add_argument("--keep", type=Path, help="keep specs and TLC output in this directory")
    args = parser.parse_args()
    java = os.environ.get("JAVA") or shutil.which("java")
    if not java:
        sys.exit("Java 11 or later is required (set $JAVA or put java on PATH)")
    jar = tlc_jar()
    work = args.keep or Path(tempfile.mkdtemp(prefix="campaign-worker-tlc-"))
    if args.keep and work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    failures = 0
    for name, why, changes, edits, expected in CHECKS[:1] if args.model else CHECKS:
        passed, broken, states, output = run(java, jar, work, name, changes, edits)
        if not expected:
            ok = passed
            verdict = f"holds over {states} distinct states" if passed else f"BROKEN: {', '.join(broken)}"
        else:
            ok = bool(broken) and set(broken) <= set(expected)
            verdict = f"breaks {', '.join(broken)} as expected" if ok else (
                "PASSED, so the model no longer sees this bug" if passed else f"breaks {', '.join(broken)}, expected {', '.join(expected)}")
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {name}: {verdict}  [{why}]", flush=True)
        if broken and (not ok or os.environ.get("CAMPAIGN_WORKER_TRACES")):
            print(trace(output))
    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    else:
        print(f"specs and TLC output: {work}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
