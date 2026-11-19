---
name: verify-campaign-worker
description: "Check a change to the campaign Worker pass, admission capacity, submission intent, reconciliation, or HTTP cancel against the TLA+ model in tests/formal/campaign_worker and the generated walks of the real code. Use when a change touches controller/campaigns.py tick, _intent, _reconcile, cancel, or lock; the capacity checks in admission; campaign_lifecycle.py observed, submitted, salvaged, admission, or cancel_request; or campaign_store.py record_intent, record_submission, tasks_in_states, or roll_up."
---

# Verify the campaign Worker

## The rule and the harm

**Rule.** Slurm never holds campaign work that the journal does not count, and admission never counts past the controller ceilings, a campaign's `max_concurrent`, or the known QOS and account job limits. After a cancel request is recorded, that campaign records no new submission intent.

**Harm when it breaks.** A task runs twice and wastes allocation, a job runs that no campaign tracks or cancels, or the controller submits past a Slurm limit and `sbatch` refuses the task, which ends it as `rejected` for good.

## The two checks

1. **TLA+ model** (`tests/formal/campaign_worker/CampaignWorker.tla`). TLC explores every order of the Worker pass, HTTP cancel, Slurm job ends, lost `sbatch` replies, journal write failures, and controller crashes for two campaigns and three tasks. It also runs broken variants of the model and the findings recorded below, and each of them must fail.
2. **Generated walks** (`tests/formal/test_campaign_worker_walks.py`). Random walks drive the real `campaigns.tick` and `campaigns.cancel` through a fake Slurm with the same faults, and check the same rules on the real journal after every step. The walks tie the model to the code. They do not cover concurrency: a walk runs cancel only between passes.

Run both:

```sh
python3 tests/formal/check_campaign_worker.py
python -m pytest -q tests/formal/test_campaign_worker_walks.py
```

The first command needs Java 11 or later. It downloads the pinned TLC (tla2tools.jar v1.7.4, SHA-256 checked) once to `$XDG_CACHE_HOME/unity-hpc`, or uses `$TLA2TOOLS_JAR`. It takes about one minute on 16 cores: the model has about 1.8 million distinct states. The walks take about six seconds. For a longer walk run, set `CAMPAIGN_WORKER_WALKS=300`.

Read every TLC result with the `/statechart` skill: it gives each rule that breaks as its shortest path in plain words, and a chart of the states when the check passes. `python3 tests/formal/check_campaign_worker.py --keep DIR` keeps each spec and its `tlc.out` for that, and `CAMPAIGN_WORKER_TRACES=1` prints the numbered steps of every counterexample.

## Does my change touch the verified code?

The model covers these code paths. If your diff changes one of them, or changes what it reads or writes, run both checks and compare the code with the action that stands for it.

| Model action | Code (as of the sync commit) |
| --- | --- |
| `PassStart` | `campaigns.tick`: `lock()`, `store.identities_excluding(lifecycle.CAMPAIGN_TERMINAL)` (newest first) |
| `ReconcileBegin`, `ReconcileEnd`, `ReconcileFails` | `campaigns.tick` reconcile loop: `store.worker_read(campaign_id, attempt_identities=True)`, `campaigns._reconcile` end (`lifecycle.cancel_request`), `store.roll_up`, `campaigns._campaign_failed` |
| `Observe` | `campaigns._reconcile`: `adapter.observe`, `lifecycle.observed`, `adapter.cancel` on `CANCEL_JOB` |
| `Resolve` | `campaigns._reconcile` SALVAGE and RETRIEVE: `lifecycle.salvaged`, `campaigns._collect`, `lifecycle.delivered`, `lifecycle.undelivered` |
| `AdmitStart` | `campaigns.tick`: `_ActiveTotals(store.tasks_in_states(lifecycle.ACTIVE))` |
| `AdmitBegin`, `AdmitCancelWaiting` | `campaigns.tick` admission: `store.worker_read(campaign_id)`, the skip of a finished campaign, `running`, `lifecycle.admission` |
| `Admissible`, `EffectiveQos`, `SameQos`, `AccountCount` | the capacity checks in `campaigns.tick` admission: `max_concurrent`, `max_active_tasks`, `max_active_gpus`, `_ActiveTotals.under` for QOS job limits, `_ActiveTotals.overall` for account job limits; `planner.qos_for` |
| `Intent` | `campaigns._intent`, `store.record_intent` |
| `Submit` | `SlurmAdapter.submit` in `controller/campaign_slurm.py`, `lifecycle.uncertain_receipt` |
| `RecordSubmission`, `RecordSubmissionFails` | `lifecycle.submitted`, `store.record_submission`, `_ActiveTotals.add(task, placement["qos"])`, and the rebuild of `_ActiveTotals` after an admission exception in `campaigns.tick` |
| `AdmitEnd`, `PassEnd` | `store.roll_up` after a campaign's admission; the end of `tick` |
| `CancelBegin`, `CancelEnd` | `campaigns.cancel`: `lifecycle.cancel_campaign`, `store.record_cancel_request`, `adapter.cancel`, `lifecycle.cancel_request` |
| `Crash` | the controller process ends; `campaigns.db` and Slurm stay |
| `QosRule`, `AccountRule` (`MCCampaignWorker.cfg`) | `"own-default"` and `"all-active"`: which active tasks admission counts against a QOS job limit and against the account job limits |

One model step is one journal transaction or one Slurm call in the code. If your change splits a transaction in two, or moves a Slurm call before a journal write, the model must split or move the step too.

**Sync commit:** `4ba63339d4de0aeff1549beab0dbb1fbfc54aef8`. At this commit the model, the walks, and the code agree, and both checks end as expected.

To see whether covered code changed since then:

```sh
git log --oneline 4ba63339d4de0aeff1549beab0dbb1fbfc54aef8..HEAD -- controller/campaigns.py controller/campaign_lifecycle.py controller/campaign_store.py controller/campaign_slurm.py
```

Move the sync commit forward only after you read the covered code at the new commit, confirm that each row above still describes it, and both checks end as expected.

## Reading a result

- `ok model: holds over N distinct states`, every other line `ok ... breaks X as expected`, and the walks pass: the change keeps the rule within the bounds below.
- `FAIL model: BROKEN: <rule>`: get the path with `/statechart` or `CAMPAIGN_WORKER_TRACES=1`. Replay it on the real code as a test, one step per action, with the fake Slurm in `tests/formal/test_campaign_worker_walks.py`. If the real code does it, it is a bug in the code: report it with the path in the code's words, and do not weaken the rule or the model. If the real code cannot take one of the steps, the model is wrong: fix the action so that it matches the code, and say which step the code cannot take.
- `FAIL <variant>: PASSED, so the model no longer sees this bug`: the model lost the power to catch that bug. Find the edit that hid it before you trust a pass.
- `<variant>: spec edit target occurs 0 times`: you edited the model text that a broken variant rewrites. Update that variant's edit in `CHECKS` in `tests/formal/check_campaign_worker.py` so that it still breaks the same step.
- A walk fails: the message gives the seed, the broken rule, and the steps. Rerun it with `CAMPAIGN_WORKER_SEED=<seed> python -m pytest -q tests/formal/test_campaign_worker_walks.py`. The walk runs the real code, so a failing walk is a code bug unless the fake Slurm in the test does something real Slurm cannot.

## When the change is intended

If you change the design on purpose, for example a new task state, a new capacity limit, or a shorter lock, change the model in the same commit:

1. Edit the action in `CampaignWorker.tla` that stands for the changed code, and the table above.
2. If the change adds a rule, add it as an invariant and add a broken variant to `CHECKS` that shows it can fail.
3. Run both checks. Every broken variant must still fail.
4. Update the walks if the change adds a fault or a Slurm behavior that the fake Slurm does not have.
5. Move the sync commit only after both checks end as expected on the new code.

Never delete a broken variant to get a green run.

## Bounds and assumptions

- Two campaigns (newest first, as `ORDER BY created_at DESC`), three tasks, two attempts, two QOS names, one GPU per GPU task. The controller ceilings stay fixed during a run; lowering a ceiling can leave more active tasks than the new ceiling, by design.
- Slurm observation by job name is exact when it succeeds. A failed observation fails the campaign's reconcile. A lost `sbatch` reply can still create the job later.
- Campaign acceptance, catalog refresh, staging details, dependencies, budgets (`max_new_tasks_per_pass`, `admission_budget_seconds`), TRES ceilings, and result delivery details are left out. Staging and placement failures act like the end of a campaign's admission.
- The rule counts only this controller's tasks. Jobs that the same account runs outside the controller also use the Slurm limits, and the controller cannot see them.
- An `uncertain` task whose job never reaches Slurm stays active, and its campaign never finishes, also after a cancel. The model shows this as a cycle; it is the documented fence ("never resubmitted blindly"), not a rule break.

## Findings

Both findings were found by the model and replayed on the real code by the walks at `ad4db80`. Commit `4ba6333` fixes both:

1. **QOS job limit counted under the wrong QOS.** Admission counted an active task without `resources.qos` under the candidate campaign's frozen `qos`, not the QOS the task runs under. Path: campaign `c2` (frozen qos `long`) submits task `c`; campaign `c1` (frozen qos `normal`) then admits task `b`, which declares `long`; admission counts `c` as `normal`, sees no `long` job, and submits `b` past the `long` limit of one.
2. **Account job limits counted only same-QOS tasks.** The association limits (`max_jobs`, `max_submit_jobs`, `grp_jobs`, `grp_submit_jobs`) cover every QOS, but admission compared them with the same-QOS count. Path: `c2` submits `c` (`long`); `c1` submits `a` (`normal`) and `b` (`long`); each check sees at most one job of its QOS, and the account ends with three jobs against a limit of two.

The broken variants `ad4db80-qos-rule` and `ad4db80-account-rule` in `tests/formal/check_campaign_worker.py` keep these paths as checks.
