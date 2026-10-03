# Declared operation composition specification

Version 1, 2026-10-03. Final extension design for implementation planning.

## Authority and product decision

Dynamic composition extends Experiments after its accepted workflow delivery.
It does not replace predefined workflows, the accepted editor, Measurements, or the dedicated Dispatch review.
All decisions C1–C8 below are agent-selected. Q1–Q23 remain unchanged.
The extension uses [ADR 0008](../adr/0008-project-workspace-and-approved-executions.md) identities, storage, and dispatch boundaries.
The [capability report](../research/settings-composition-capabilities.md) records source evidence and implementation gaps.
The [shared contract](remaining-workspace-spec.md) governs state mappings, identities, navigation, and action receipts across pages.

| Decision | Selected behavior | Rationale |
| --- | --- | --- |
| C1 | Compose declared operations through structured stage cards | Humans need valid connections without shell or graph expertise |
| C2 | Keep a directed acyclic graph with typed artifact ports | The compiler can reject incompatible work before dispatch |
| C3 | Use the existing experiment, revision, plan, execution, variant, stage, and attempt identities | Composition must not create a second history system |
| C4 | Require explicit stage scope and bounded variant expansion | Shared work and independent variants must have clear resource costs |
| C5 | Metrics select declared fields, collectors, and supported aggregations | Scientific logic remains project-owned |
| C6 | Use existing completed artifacts only through checked identity bindings | A filename alone cannot establish scientific compatibility |
| C7 | Freeze the graph, definitions, and source in the reviewed plan | Runtime automation remains deterministic and auditable |
| C8 | Omit loops, runtime graph invention, and arbitrary expressions | Unbounded or implicit work exceeds the approved plan |

## Navigation, layout, and actions

New experiment retains Workflow as the default creation route.
When the connection advertises composition support, the dialog also offers Compose operations.
The latter creates a draft with an empty stage list and the same research-context fields.
Clone preserves the source graph revision and creates a separate editable experiment.
A workflow can expose Customize stages only when every selected stage has a composable declaration.
The resulting draft records its source workflow and the graph differences.

The editor uses the accepted stage-and-resource area with three parts:

- A searchable operation picker grouped by Collect, Transform, Analyze, Plot, and Check.
- Ordered stage cards with purpose, input bindings, output ports, scope, placement, resources, and dependency links.
- A dependency preview beside the cards, with exact variant and stage counts.

The diagram shows the same graph as the cards. Dragging lines is not required for any action.
A keyboard-accessible dependency list offers the same information.
Selecting a diagram node focuses its stage card.
The review remains a separate page, and Dispatch appears there only.

| Action | Behavior |
| --- | --- |
| Add operation | Add a stage with declared typed defaults and visible unbound required inputs |
| Connect input | Choose a compatible prior output or completed saved artifact. Show rejected choices and their reasons |
| Add prerequisites | Add explicitly selected declared prerequisite operations and show the expanded stage list |
| Use completed output | Bind an immutable artifact ID, digest, provenance, completeness evidence, and port mapping |
| Duplicate stage | Create a new stable node ID and isolated output identity. Preserve editable values |
| Remove stage | Show affected dependents and bindings. Require explicit removal or rebinding of each affected connection |
| Change scope | Preview changed stage count, sharing, inputs, resource totals, and output identities |
| Reorder cards | Change visual order only. Dependencies remain explicit |
| Measurements | Select declared fields, collectors, units, grouping, and supported aggregations |
| Check setup | Validate the graph and run declared bounded checks. No cluster submission |
| Review plan | Freeze the exact expansion and explain remaining blockers |
| Save as custom script | Use the accepted transition to project-owned source. Re-registration precedes later selection |

A missing operation remains as an unresolved stage with its former ID and recorded version.
The UI never substitutes an operation with a similar name.
Renaming a card changes its label, not its node ID or historical references.
Resources remain per stage. Independent variants can each contain a coordinated `multi-gpu` stage.
Controller-host analysis does not create a scheduler job ID.

## Operation and artifact contracts

These fields extend the connection schema. Engineering must select their concrete version before implementation consumes them.
The reader must reject required unsupported features instead of ignoring them.
A composition revision references exact operation versions and the connection digest.

| Contract | Required fields and constraints |
| --- | --- |
| Operation | Stable ID/version, category, title, argument-vector bindings, source closure, working directory, environment fingerprint, allowed locations |
| Parameter | Stable key, primitive type, unit, bounds, choices, default, required flag, variant eligibility, literal argument binding |
| Input port | Stable port ID, schema ID/version, cardinality, units/dimensions where relevant, purpose restrictions, completeness requirement, compatibility fields |
| Output port | Stable port ID, schema ID/version, scoped path template, cardinality, expected content, completion validator, retrieval rule |
| Side effects | Read roots, exclusive write roots, output ownership, idempotence declaration, timeout, and process/resource limits |
| Node | Stable node ID, operation version, parameter bindings, purpose, scope, resource request, declared prerequisites |
| Edge | Source node/output or saved artifact ID, target node/input, variant matching rule, required completion evidence |
| Graph revision | Experiment/revision ID, source workflow reference, nodes, edges, selected measurements, exclusions, defaults digest |
| Expansion | Concrete node/variant IDs, dependency IDs, input identities, generated argv, resources, output paths, cardinality counts |
| Measurement | Definition ID/version, field or collector, unit, grouping keys, denominator, exclusions, missing policy, supported aggregation |

An output port can connect only when the input contract accepts its schema and required provenance fields.
The project must declare version compatibility explicitly. Matching file extensions or column names do not establish compatibility.
No implicit unit conversion, dataset join, schema upgrade, or scientific transform occurs.
A declared conversion operation can supply the conversion as a visible stage.

Optional inputs require an explicit absent binding when the operation supports absence.
Cardinality mismatches block the connection instead of choosing an arbitrary first artifact.

An artifact binding preserves project slug, experiment, revision, plan, execution, variant, stage, attempt, artifact version, and purpose when known.
It also records dataset identity, sample identity policy, model/evaluator versions, parent artifact links, and completeness evidence as required by that port.

Legacy unknown values remain Unknown. Strict ports reject an incomplete provenance contract.
Smoke-test outputs cannot satisfy a full measurement input.
An artifact outside the attached project requires an explicit registered import with immutable identity and ownership before selection.
The first delivery supports same-project artifacts only.


## Stage scope and deterministic expansion

Supported scopes are `per_variant`, `shared`, and `reduce_selected`.
The form initially uses `per_variant`.
Shared prerequisites run once for the plan only when their parameters and bound inputs are identical across dependent variants.
Variant-dependent parameters on a shared node are invalid. The UI offers a scope change instead of silently duplicating it.

A `per_variant` edge binds within the same variant by default.
A `shared` output can feed explicitly listed compatible variant nodes.
A `reduce_selected` node receives the exact reviewed set of selected output artifacts through a declared many-input port.
The adapter owns record alignment and scientific statistics.
Arbitrary cross-variant joins remain unsupported in the first delivery.

All combinations and Explicit combinations retain their accepted meanings.
The compiler expands the finite parameter list before any dispatch.
It checks cycles, unbound inputs, duplicate destinations, incompatible resources, source closure, and artifact completeness requirements.
The plan includes excluded variants and the reason for each exclusion.
An invalid variant blocks review readiness until the human fixes or explicitly excludes it.

Initial agent-selected guardrails are 1000 included variants, 5000 expanded stages, and 100 incoming artifacts per port.
A project can declare tighter limits. Raising controller limits requires an explicit operator change and another review.
The compiler computes cardinalities before large expansion and rejects over-budget plans without truncation.
Choice readers remain bounded and cannot expand the graph at runtime.

Stage IDs are unique within the graph revision. Concrete stage identities also carry their variant or shared scope.
Outputs use the baseline plan/variant/stage namespace under `.unity-workspace/outputs/`.
The compiler reserves a shared-stage scope token that cannot collide with a user variant ID.

Recovery creates another reviewed plan with attempt lineage. It never writes into an active prior attempt's output destination.
One plan still creates at most one execution.

Variant concurrency limits active variant chains. Coordinated rank counts describe one stage allocation.
Shared stages use their own explicit resource request and appear in the reviewed resource count.
The review states whether a resource count is a maximum, an allocation request, or an unavailable estimate.
Neither stage count nor summed walltime claims a completion or queue-start prediction.

## Measurement composition

Measurements starts with the source workflow preset, or an empty explicit selection for an operation-only draft.
The picker distinguishes fields already emitted, derived measurements over saved fields, and measurements requiring new collection.
Each row shows definition, source port/field, unit, grouping keys, sample coverage, and supported aggregations.
A rate also shows its denominator and exclusion policy.

Generic aggregation supports count, sum, minimum, maximum, and arithmetic mean only when the declaration permits them.
A ratio requires declared numerator and denominator fields with compatible scope.
Quantiles, uncertainty intervals, paired tests, and dependence-aware estimates require a declared project analysis operation or definition.
The UI does not infer statistical independence from row count.

Metric selection never invents a new scientific formula.
A missing metric offers the declaration path and required contract fields, not an expression editor.
A collector version is immutable within a plan and records any extra runtime, storage, or instrumentation requirements.
Selecting a costly collector adds visible stages only after explicit selection and another review.
The UI does not hide those stages under a display preference.

A new analysis revision over saved artifacts uses the same composition contracts with collection operations disabled by default.
If a requested measurement needs missing inputs, Results links an explicit new collection draft.
Changing a measurement does not silently rerun model generation.
The analysis revision retains exact input selection, parameters, operation versions, and new output identities.
Earlier reports remain available. A plot revision references its metric definition and analysis revision.

For TLAiBench, adapters retain token-cap conditions before deduplication.
They preserve stage-parent links and complete-corpus evidence independently of scheduler state.
The source project owns its outcome classifications and checker semantics.
The generic harness remains metric-agnostic.

## States and action availability

Draft readiness is `unchecked | checking | blocked | ready` and remains separate from autosave and execution state.
Autosave retains Saving, Saved, and Unsaved, with expected-version conflicts.
Every graph, input, metric, source, or resource edit returns readiness to Unchecked.
A saved plan records the exact graph digest and declaration/source digests.
Changed digest inputs invalidate undispatched review. Approved executions retain their frozen graph.

At runtime, nodes wait for declared prerequisites, become ready, start, and reach a terminal outcome.
The baseline execution contract owns exact runtime state names and uncertain submission handling.
A valid negative scientific outcome can satisfy a successful operation's completion contract.
A script or infrastructure failure pauses affected branches. Unrelated approved branches can continue.
A complete corpus behind a failed job remains evidence for explicit recovery, never automatic dependency release.

| Condition | Required behavior |
| --- | --- |
| Empty operation library | Explain that project declarations are required. Keep predefined workflows and history if supported |
| Empty graph | Show Add operation and existing workflow options. Disable Review and Dispatch |
| Loading choices | Preserve chosen IDs and expose loading state. Do not replace selections with new defaults |
| Missing operation version | Preserve the draft and show a blocked stage with a declaration-maintenance link |
| Stale declaration or input | Invalidate review and show exact changed references |
| Choice-reader failure | Show the failed reader and last observation. A stale choice cannot silently pass a new plan check |
| Invalid connection | Keep historical executions and saved draft content visible. Disable new planning |
| Partial check success | Retain successful checks and identify blocked nodes. Do not drop failed variants |
| Partial dispatch | Show accepted, waiting, rejected, and uncertain portions in Runs, filtered to the execution |
| Retrieval or analysis failure | Preserve completed producers and artifacts. Pause only affected analysis branches |
| Cancelled producer | Mark required descendants blocked or cancelled according to the reviewed Runs cancellation scope |
| Save conflict | Preserve both graph versions. Offer reload or an explicit copied revision, never silent graph merge |

Removal of a metric or output after dispatch affects a new revision only.
A missing required output fails completeness even when the scheduler reports success.
An optional missing output stays visible as absent and cannot satisfy a required downstream input.

## Automatic-action limits

The compiler validates declarations, expands finite variants, serializes literal arguments, and generates wrappers.
The controller advances only the approved graph and its declared retrieval/check/analysis sequence.
It does not discover arbitrary scripts, evaluate free-form shell, infer prerequisites, or generate scientific source.
It does not choose hypotheses, optimize scientific parameters, invent missing measurements, or use a runtime orchestration LLM.

Runtime output cannot add stages, alter resources, increase variant limits, or release a failed prerequisite.
Automatic retries, checkpoint migration, resource changes, and collection beyond the reviewed scope remain disabled.
Project code can contain its own algorithmic loops, but the operation declaration must expose bounded resources and completion conditions.
The workflow engine treats those internals as project-owned behavior, not editable scheduler graph instructions.

Local operations require bounded process groups, declared working directories, and write scopes.
Two stages cannot append to the same mutable summary target concurrently.
The preferred contract gives each attempt isolated outputs and adds an explicit merge or report stage.
A project adapter can instead declare an exclusive write lock with a checked scope.
The first delivery rejects an undeclared shared write target.

## Acceptance and verification scenarios

1. A researcher composes GPU collection, CPU validation, and CPU analysis through typed ports without a predefined workflow.
2. Two models and two token caps produce four variants and preserve both cap conditions through result analysis.
3. A shared fixture check appears once, while a variant-dependent input prevents accidental shared execution.
4. A cyclic graph, missing port, unsupported version, and incompatible unit each produce a specific blocking error before dispatch.
5. A smoke-test artifact cannot replace the full parent corpus of a TLAiBench stage.
6. A many-input analysis consumes exactly the reviewed artifact set and exposes unmatched or incomplete inputs.
7. A graph over the configured expansion limit fails without partial submission or silent truncation.
8. Arguments containing spaces and shell metacharacters retain literal values in inspectable generated wrappers.
9. Selecting a derived metric over saved fields creates an analysis revision without collection. A new collector requires explicit added stages.
10. A removed operation preserves a saved draft and historical execution, with its original operation reference visible.
11. A controller restart resumes an approved graph without duplicate stages, overwritten outputs, or new scientific choices.
12. Parallel analysis attempts cannot corrupt a shared summary file because isolated outputs or declared exclusive scope control writes.
13. A failed prerequisite pauses only its dependents, while a valid negative measurement continues through approved analysis.
14. Every graph action works through keyboard-accessible cards and preserves the same dependency representation as the diagram.

Verification uses fixture operations, temporary output trees, synthetic artifacts, and a stub dispatcher.
The final integration gate reuses the accepted two-model/two-cap experiment and includes a composed equivalent.
It compares identities, effective resources, inputs, and output provenance between those plans.

## Delivery and technical gates

| Phase | Dependency | Deliverable and exit gate |
| --- | --- | --- |
| C-A | Accepted Experiments phases 0–3 and Settings capability contract | Versioned typed ports, operation registry, scope rules, graph validation, finite expansion fixtures |
| C-B | C-A | Stage cards, compatible artifact picker, graph preview, Measurements bindings, unchanged accepted workflow behavior |
| C-C | Accepted durable execution and artifact phases | Composed dispatch, recovery lineage, restart safety, bounded local work, isolated result outputs |
| C-D | Results analysis revisions and comparison identity | Selected-artifact reducers, collector selection, complete provenance, cap-preserving integration example |

Spike C-T1 asks how the first manifest version gains typed ports without silent interpretation changes.
The recommended approach introduces an explicit required feature version and a strict composition validator.
The fallback keeps predefined workflows available and marks composition unsupported until a versioned adapter exists.
Completion requires fixtures for old declarations and unsupported required features. Baseline workflow plans must retain identical meaning.

Spike C-T2 asks how existing project analysis scripts consume selected artifacts without scanning unrelated corpora.
The recommended approach passes an immutable artifact manifest to a project-owned adapter and writes a separate analysis output tree.
The fallback builds a checked temporary input view containing only selected immutable artifacts.
Completion requires both token-cap conditions, parent links, and exclusions to survive deduplication without shared-file races.

Spike C-T3 asks how execution limits and write scopes apply to controller-host operations across restarts.
The recommended approach uses durable leases, process-group deadlines, and declared exclusive resources.
The fallback serializes controller-host stages per project with strict deadlines.
Completion requires crash, timeout, and simultaneous-writer fixtures without duplicate scientific work or corrupted outputs.

Deferred features are free-form graph drawing, runtime branches, cycles, condition-driven experiment search, arbitrary metric expressions, and cross-project joins.
The first delivery omits template publishing through the UI. Cloning already supports reuse without writing project workflow source.
No amendment to Q1–Q23 is required. This extension starts only after their predefined-workflow scope is complete.
