--------------------------- MODULE CampaignWorker ---------------------------
(***************************************************************************)
(* The campaign Worker pass, HTTP cancel, Slurm, and process crashes.      *)
(*                                                                         *)
(* Rule: Slurm never holds campaign work that the journal does not count,  *)
(* and admission never counts past the controller ceilings, a campaign's   *)
(* max_concurrent, or the known QOS and account job limits.                *)
(*                                                                         *)
(* Each action names the code it stands for.  The journal (campaigns.db)   *)
(* and Slurm survive a crash; every other variable is process memory.      *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS
    Tasks,            \* task ids of all accepted campaigns
    Order,            \* campaign ids, newest first (store.identities_excluding: ORDER BY created_at DESC)
    CampaignOf,       \* task -> campaign
    Gpus,             \* task -> spec.resources.gpu_count
    NoQos,            \* spec.resources.qos is missing or ""
    DeclaredQos,      \* task -> spec.resources.qos, or NoQos
    DefaultQos,       \* campaign -> spec.backend.qos (frozen at acceptance)
    QosNames,
    QosJobLimit,      \* QOS -> MaxJobs/MaxSubmitJobs per user (placement qos_limits)
    AccountJobLimit,  \* MaxJobs/MaxSubmitJobs/GrpJobs/GrpSubmitJobs (placement account_limits)
    MaxActive,        \* backend setting max_active_tasks
    MaxGpus,          \* backend setting max_active_gpus
    MaxConcurrent,    \* campaign -> declaration max_concurrent
    MaxAttempts,      \* declaration max_attempts
    QosRule,          \* how admission picks the QOS of an active task that declares none
    AccountRule       \* which active tasks admission counts against the account job limits

None == "none"
Campaigns == {Order[i] : i \in 1..Len(Order)}

(* Task states (controller/campaign_lifecycle.py).  "live" stands for     *)
(* accepted and running; "done" for every terminal state.                 *)
Active == {"submitting", "uncertain", "live", "fetching", "cancelling"}
TaskStates == Active \cup {"waiting", "done"}

VARIABLES
    task,        \* journal tasks row: [state, attempt, jobKnown (job_id recorded)]
    campaign,    \* journal campaigns.state: "open" | "cancelling" | "done"
    jobs,        \* Slurm jobs: [task, attempt, status: "live" | "ok" | "infra" | "cancelled"]
    inflight,    \* <<task, attempt>> of sbatch calls whose reply was lost and that can still create a job
    lock,        \* campaigns.lock(): "free" | "worker" | "cancel"
    pc,          \* Worker: "idle" | "reconcile" | "admit" | "intent" | "submitted"
    todo,        \* campaigns left in this pass step, in order
    reconciled,  \* campaigns whose reconcile succeeded in this pass, in order
    cur,         \* campaign under reconcile or admission, or None
    snap,        \* campaign state from the admission re-read of cur
    cand,        \* task between its intent and its recorded outcome, or None
    counted,     \* pass-local active totals: the tasks they count
    running,     \* pass-local active task count of cur
    reply,       \* the submit reply: None | "accepted" | "lost" | "rejected"
    cancelOf     \* campaign whose HTTP cancel holds the lock, or None

vars == <<task, campaign, jobs, inflight, lock, pc, todo, reconciled, cur, snap, cand, counted, running, reply, cancelOf>>
memory == <<lock, pc, todo, reconciled, cur, snap, cand, counted, running, reply, cancelOf>>

-----------------------------------------------------------------------------
RECURSIVE SumOf(_, _)
SumOf(f, S) == IF S = {} THEN 0 ELSE LET x == CHOOSE x \in S : TRUE IN f[x] + SumOf(f, S \ {x})

ActiveTasks == {t \in Tasks : task[t].state \in Active}
TasksOf(c) == {t \in Tasks : CampaignOf[t] = c}

(* The QOS a job runs under: planner.select uses resources.qos, else the  *)
(* frozen backend qos of the task's own campaign.                         *)
EffectiveQos(t) == IF DeclaredQos[t] = NoQos THEN DefaultQos[CampaignOf[t]] ELSE DeclaredQos[t]

(* campaigns.tick admission: the QOS under which active task t counts     *)
(* while a task of candidate campaign c is admitted.                      *)
(*   "candidate-default": resources.qos, else the CANDIDATE campaign's    *)
(*                        backend qos (the code at ad4db80)               *)
(*   "own-default":       EffectiveQos(t), the QOS the job runs under     *)
CountedQos(t, c) ==
    IF QosRule = "candidate-default" /\ DeclaredQos[t] = NoQos THEN DefaultQos[c] ELSE EffectiveQos(t)
SameQos(c, q) == {t \in counted : CountedQos(t, c) = q}

(* The active tasks counted against the account job limits:               *)
(*   "same-qos":   the same-QOS tasks only (the code at ad4db80)          *)
(*   "all-active": every active task                                      *)
AccountCount(c, q) == IF AccountRule = "same-qos" THEN Cardinality(SameQos(c, q)) ELSE Cardinality(counted)

CurrentJob(t) == {j \in jobs : j.task = t /\ j.attempt = task[t].attempt}
HasJob(t) == CurrentJob(t) # {}
TheJob(t) == CHOOSE j \in CurrentJob(t) : TRUE

(* store.roll_up with lifecycle.campaign_state: terminal when every task  *)
(* is terminal, else unchanged.                                           *)
RolledUp(c, tasks) ==
    IF \A t \in TasksOf(c) : tasks[t].state = "done" THEN "done" ELSE campaign[c]

(* lifecycle.cancel_request: a waiting task of c is recorded cancelled.   *)
Fenced(c) == [t \in Tasks |-> IF CampaignOf[t] = c /\ task[t].state = "waiting"
                                 THEN [task[t] EXCEPT !.state = "done"] ELSE task[t]]

Unfinished == SelectSeq(Order, LAMBDA c : campaign[c] # "done")

Init ==
    /\ task = [t \in Tasks |-> [state |-> "waiting", attempt |-> 0, jobKnown |-> FALSE]]
    /\ campaign = [c \in Campaigns |-> "open"]
    /\ jobs = {}
    /\ inflight = {}
    /\ lock = "free"
    /\ pc = "idle"
    /\ todo = <<>>
    /\ reconciled = <<>>
    /\ cur = None
    /\ snap = None
    /\ cand = None
    /\ counted = {}
    /\ running = 0
    /\ reply = None
    /\ cancelOf = None

-----------------------------------------------------------------------------
(* tick: take campaigns.lock(), select the unfinished campaigns.          *)
PassStart ==
    /\ pc = "idle" /\ lock = "free" /\ Unfinished # <<>>
    /\ lock' = "worker"
    /\ pc' = "reconcile"
    /\ todo' = Unfinished
    /\ reconciled' = <<>>
    /\ UNCHANGED <<task, campaign, jobs, inflight, cur, snap, cand, counted, running, reply, cancelOf>>

(* tick: store.read the next campaign, then _reconcile it.                *)
ReconcileBegin ==
    /\ pc = "reconcile" /\ cur = None /\ todo # <<>>
    /\ cur' = Head(todo)
    /\ UNCHANGED <<task, campaign, jobs, inflight, lock, pc, todo, reconciled, snap, cand, counted, running, reply, cancelOf>>

(* _reconcile: adapter.observe by job name, then lifecycle.observed for   *)
(* one active task.  A live job of a cancelling campaign is scancelled    *)
(* (CANCEL_JOB) and the task records cancelling.                          *)
Observe(t) ==
    /\ pc = "reconcile" /\ cur = CampaignOf[t]
    /\ task[t].state \in Active
    /\ IF ~HasJob(t)
         THEN /\ task[t].state = "submitting"
              /\ task' = [task EXCEPT ![t].state = "uncertain"]
              /\ UNCHANGED jobs
         ELSE LET j == TheJob(t)
                  seen == IF j.status # "live" THEN "fetching"
                          ELSE IF campaign[cur] = "cancelling" THEN "cancelling" ELSE "live"
              IN /\ task[t] # [task[t] EXCEPT !.state = seen, !.jobKnown = TRUE]
                 /\ task' = [task EXCEPT ![t].state = seen, ![t].jobKnown = TRUE]
                 /\ jobs' = IF j.status = "live" /\ campaign[cur] = "cancelling"
                              THEN (jobs \ {j}) \cup {[j EXCEPT !.status = "cancelled"]}
                              ELSE jobs
    /\ UNCHANGED <<campaign, inflight, memory>>

(* _reconcile after a terminal observation: SALVAGE records cancelled or  *)
(* a bounded infrastructure retry (lifecycle.salvaged); RETRIEVE records  *)
(* delivered() or undelivered().  A transfer retry keeps fetching.        *)
Resolve(t) ==
    /\ pc = "reconcile" /\ cur = CampaignOf[t]
    /\ task[t].state = "fetching"
    /\ LET j == TheJob(t) IN
       task' = [task EXCEPT ![t].state =
                  IF j.status = "cancelled" \/ campaign[cur] = "cancelling" THEN "done"
                  ELSE IF j.status = "infra" /\ task[t].attempt < MaxAttempts THEN "waiting"
                  ELSE "done"]
    /\ UNCHANGED <<campaign, jobs, inflight, memory>>

(* _reconcile end (cancel_request for a cancelling campaign), roll_up,    *)
(* _resolved: the campaign joins the admission list.                      *)
ReconcileEnd ==
    /\ pc = "reconcile" /\ cur # None
    /\ LET next == IF campaign[cur] = "cancelling" THEN Fenced(cur) ELSE task
       IN /\ task' = next
          /\ campaign' = [campaign EXCEPT ![cur] = RolledUp(cur, next)]
    /\ todo' = Tail(todo)
    /\ reconciled' = Append(reconciled, cur)
    /\ cur' = None
    /\ UNCHANGED <<jobs, inflight, lock, pc, snap, cand, counted, running, reply, cancelOf>>

(* An exception in _reconcile: _campaign_failed, and the campaign is left *)
(* out of admission.  Writes made before it stay.                         *)
ReconcileFails ==
    /\ pc = "reconcile" /\ cur # None
    /\ todo' = Tail(todo)
    /\ cur' = None
    /\ UNCHANGED <<task, campaign, jobs, inflight, lock, pc, reconciled, snap, cand, counted, running, reply, cancelOf>>

(* Admission starts after every reconcile: store.tasks_in_states(ACTIVE)  *)
(* gives the pass-local totals once.                                      *)
AdmitStart ==
    /\ pc = "reconcile" /\ cur = None /\ todo = <<>>
    /\ pc' = "admit"
    /\ todo' = reconciled
    /\ counted' = ActiveTasks
    /\ UNCHANGED <<task, campaign, jobs, inflight, lock, reconciled, cur, snap, cand, running, reply, cancelOf>>

(* Admission re-reads the next campaign: it skips a terminal one, else it *)
(* counts the campaign's active tasks (running) and reads its state.      *)
AdmitBegin ==
    /\ pc = "admit" /\ cur = None /\ todo # <<>>
    /\ LET c == Head(todo) IN
       IF campaign[c] = "done"
         THEN /\ todo' = Tail(todo)
              /\ UNCHANGED <<cur, snap, running>>
         ELSE /\ cur' = c
              /\ snap' = campaign[c]
              /\ running' = Cardinality(ActiveTasks \cap TasksOf(c))
              /\ UNCHANGED todo
    /\ UNCHANGED <<task, campaign, jobs, inflight, lock, pc, reconciled, cand, counted, reply, cancelOf>>

(* lifecycle.admission in a cancelling campaign: a waiting task is        *)
(* recorded cancelled.                                                    *)
AdmitCancelWaiting(t) ==
    /\ pc = "admit" /\ cur = CampaignOf[t] /\ snap = "cancelling"
    /\ task[t].state = "waiting"
    /\ task' = [task EXCEPT ![t].state = "done"]
    /\ UNCHANGED <<campaign, jobs, inflight, memory>>

(* The capacity checks in tick, in code order, for candidate t.           *)
Admissible(t) ==
    LET q == EffectiveQos(t) IN
    /\ running < MaxConcurrent[cur]
    /\ Cardinality(counted) < MaxActive
    /\ SumOf(Gpus, counted) + Gpus[t] <= MaxGpus
    /\ Cardinality(SameQos(cur, q)) < QosJobLimit[q]
    /\ AccountCount(cur, q) < AccountJobLimit

(* _intent / store.record_intent: one transaction writes the attempt row, *)
(* the task's submitting state, and the submitting event.                 *)
Intent(t) ==
    /\ pc = "admit" /\ cur = CampaignOf[t] /\ snap = "open"
    /\ task[t].state = "waiting"
    /\ Admissible(t)
    /\ task' = [task EXCEPT ![t] = [state |-> "submitting", attempt |-> @.attempt + 1, jobKnown |-> FALSE]]
    /\ cand' = t
    /\ pc' = "intent"
    /\ UNCHANGED <<campaign, jobs, inflight, lock, todo, reconciled, cur, snap, counted, running, reply, cancelOf>>

NewJob(t) == [task |-> t, attempt |-> task[t].attempt, status |-> "live"]

(* SlurmAdapter.submit: one remote command writes the script and runs     *)
(* sbatch under the receipt flock.  A raised call or a missing receipt    *)
(* gives uncertain_receipt, and the remote sbatch can still create the    *)
(* job later.  Only an explicit refusal proves rejection.                 *)
Submit ==
    /\ pc = "intent"
    /\ \/ /\ jobs' = jobs \cup {NewJob(cand)} /\ reply' = "accepted" /\ UNCHANGED inflight
       \/ /\ jobs' = jobs \cup {NewJob(cand)} /\ reply' = "lost" /\ UNCHANGED inflight
       \/ /\ inflight' = inflight \cup {<<cand, task[cand].attempt>>} /\ reply' = "lost" /\ UNCHANGED jobs
       \/ /\ reply' = "rejected" /\ UNCHANGED <<jobs, inflight>>
    /\ pc' = "submitted"
    /\ UNCHANGED <<task, campaign, lock, todo, reconciled, cur, snap, cand, counted, running, cancelOf>>

(* lifecycle.submitted + store.record_submission; an active outcome joins *)
(* the pass-local totals and the campaign's running count.                *)
RecordSubmission ==
    /\ pc = "submitted"
    /\ LET next == CASE reply = "accepted" -> "live"
                     [] reply = "lost" -> "uncertain"
                     [] reply = "rejected" -> "done"
       IN /\ task' = [task EXCEPT ![cand].state = next, ![cand].jobKnown = (reply = "accepted")]
          /\ counted' = IF next \in Active THEN counted \cup {cand} ELSE counted
          /\ running' = IF next \in Active THEN running + 1 ELSE running
    /\ pc' = "admit"
    /\ cand' = None
    /\ reply' = None
    /\ UNCHANGED <<campaign, jobs, inflight, lock, todo, reconciled, cur, snap, cancelOf>>

(* store.record_submission raises after the intent committed: the task    *)
(* stays submitting, _campaign_failed, and the totals are rebuilt from    *)
(* the journal.                                                           *)
RecordSubmissionFails ==
    /\ pc = "submitted"
    /\ counted' = ActiveTasks
    /\ todo' = Tail(todo)
    /\ cur' = None
    /\ cand' = None
    /\ reply' = None
    /\ pc' = "admit"
    /\ UNCHANGED <<task, campaign, jobs, inflight, lock, reconciled, snap, running, cancelOf>>

(* End of one campaign's admission, also after a capacity break or a      *)
(* placement or staging failure: store.roll_up.                           *)
AdmitEnd ==
    /\ pc = "admit" /\ cur # None
    /\ campaign' = [campaign EXCEPT ![cur] = RolledUp(cur, task)]
    /\ todo' = Tail(todo)
    /\ cur' = None
    /\ UNCHANGED <<task, jobs, inflight, lock, pc, reconciled, snap, cand, counted, running, reply, cancelOf>>

PassEnd ==
    /\ pc = "admit" /\ cur = None /\ todo = <<>>
    /\ pc' = "idle"
    /\ lock' = "free"
    /\ reconciled' = <<>>
    /\ counted' = {}
    /\ snap' = None
    /\ running' = 0
    /\ UNCHANGED <<task, campaign, jobs, inflight, todo, cur, cand, reply, cancelOf>>

-----------------------------------------------------------------------------
(* campaigns.cancel holds campaigns.lock(): record cancelling, scancel    *)
(* the recorded job ids of active tasks, record waiting tasks cancelled,  *)
(* then store.roll_up.                                                    *)
CancelBegin(c) ==
    /\ lock = "free"
    /\ campaign[c] # "done"
    /\ lock' = "cancel"
    /\ campaign' = [campaign EXCEPT ![c] = "cancelling"]
    /\ cancelOf' = c
    /\ UNCHANGED <<task, jobs, inflight, pc, todo, reconciled, cur, snap, cand, counted, running, reply>>

CancelEnd ==
    /\ lock = "cancel"
    /\ LET known == {t \in TasksOf(cancelOf) : task[t].state \in Active /\ task[t].jobKnown}
           hit == {j \in jobs : j.status = "live" /\ j.task \in known /\ j.attempt = task[j.task].attempt}
           next == Fenced(cancelOf)
       IN /\ jobs' = (jobs \ hit) \cup {[j EXCEPT !.status = "cancelled"] : j \in hit}
          /\ task' = next
          /\ campaign' = [campaign EXCEPT ![cancelOf] = RolledUp(cancelOf, next)]
    /\ lock' = "free"
    /\ cancelOf' = None
    /\ UNCHANGED <<inflight, pc, todo, reconciled, cur, snap, cand, counted, running, reply>>

(* The controller process dies: the journal and Slurm stay; memory and    *)
(* the flock go.                                                          *)
Crash ==
    /\ lock # "free"
    /\ lock' = "free"
    /\ pc' = "idle"
    /\ todo' = <<>>
    /\ reconciled' = <<>>
    /\ cur' = None
    /\ snap' = None
    /\ cand' = None
    /\ counted' = {}
    /\ running' = 0
    /\ reply' = None
    /\ cancelOf' = None
    /\ UNCHANGED <<task, campaign, jobs, inflight>>

-----------------------------------------------------------------------------
(* Slurm: a job ends by itself; a lost sbatch reply can still create the  *)
(* job later, or never.                                                   *)
JobEnds(j) ==
    /\ j.status = "live"
    /\ \E end \in {"ok", "infra"} : jobs' = (jobs \ {j}) \cup {[j EXCEPT !.status = end]}
    /\ UNCHANGED <<task, campaign, inflight, memory>>

LateSbatch(p) ==
    /\ inflight' = inflight \ {p}
    /\ \/ jobs' = jobs \cup {[task |-> p[1], attempt |-> p[2], status |-> "live"]}
       \/ UNCHANGED jobs
    /\ UNCHANGED <<task, campaign, memory>>

Next ==
    \/ PassStart
    \/ ReconcileBegin
    \/ \E t \in Tasks : Observe(t)
    \/ \E t \in Tasks : Resolve(t)
    \/ ReconcileEnd
    \/ ReconcileFails
    \/ AdmitStart
    \/ AdmitBegin
    \/ \E t \in Tasks : AdmitCancelWaiting(t)
    \/ \E t \in Tasks : Intent(t)
    \/ Submit
    \/ RecordSubmission
    \/ RecordSubmissionFails
    \/ AdmitEnd
    \/ PassEnd
    \/ \E c \in Campaigns : CancelBegin(c)
    \/ CancelEnd
    \/ Crash
    \/ \E j \in jobs : JobEnds(j)
    \/ \E p \in inflight : LateSbatch(p)

(* Every campaign finished and Slurm idle: nothing more happens.          *)
Finished ==
    /\ Unfinished = <<>> /\ lock = "free" /\ inflight = {}
    /\ \A j \in jobs : j.status # "live"
    /\ UNCHANGED vars

Spec == Init /\ [][Next \/ Finished]_vars

-----------------------------------------------------------------------------
TypeOK ==
    /\ \A t \in Tasks : task[t].state \in TaskStates /\ task[t].attempt \in 0..MaxAttempts
    /\ \A c \in Campaigns : campaign[c] \in {"open", "cancelling", "done"}
    /\ pc \in {"idle", "reconcile", "admit", "intent", "submitted"}
    /\ lock \in {"free", "worker", "cancel"}

(* Every Slurm job, and every sbatch that can still create one, belongs   *)
(* to an attempt whose intent the journal recorded first.                 *)
IntentBeforeSlurm ==
    /\ \A j \in jobs : j.attempt <= task[j.task].attempt
    /\ \A p \in inflight : p[2] <= task[p[1]].attempt

(* A live Slurm job, or an sbatch that can still create one, is the       *)
(* current attempt of a task that the journal counts as active: no task   *)
(* runs twice, and no Slurm work escapes the totals.                      *)
SlurmWorkCounted ==
    /\ \A j \in jobs : j.status = "live" => task[j.task].state \in Active /\ task[j.task].attempt = j.attempt
    /\ \A p \in inflight : task[p[1]].state \in Active /\ task[p[1]].attempt = p[2]

(* The journal's active tasks stay within the controller ceilings and     *)
(* each campaign's max_concurrent.                                        *)
CapacityHeld ==
    /\ Cardinality(ActiveTasks) <= MaxActive
    /\ SumOf(Gpus, ActiveTasks) <= MaxGpus
    /\ \A c \in Campaigns : Cardinality(ActiveTasks \cap TasksOf(c)) <= MaxConcurrent[c]

(* ... within each QOS job limit, counted by the QOS each job runs under, *)
QosLimitHeld ==
    \A q \in QosNames : Cardinality({t \in ActiveTasks : EffectiveQos(t) = q}) <= QosJobLimit[q]

(* ... and within the account job limit, which covers every QOS.          *)
AccountLimitHeld ==
    Cardinality(ActiveTasks) <= AccountJobLimit

(* After a cancel request is recorded, no task of that campaign records a *)
(* new submission intent.                                                 *)
CancelFence ==
    [][\A t \in Tasks : task'[t].attempt > task[t].attempt => campaign[CampaignOf[t]] = "open"]_vars
=============================================================================
