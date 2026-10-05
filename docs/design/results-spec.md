# Results specification

Version 1, 2026-10-03. Final design for implementation planning.
All choices labeled R below are agent-selected under the autonomous planning request.
The accepted [Experiments baseline](experiments-spec.md) supplies Q1–Q23. This specification requires no amendment to those decisions.
The [capability review](../research/results-files-capabilities.md) distinguishes inspected implementation from required work.
The [shared contract](remaining-workspace-spec.md) governs common state mappings, identity, navigation, and action receipts.

## Decisions and purpose

Results answers three questions: what happened, which conditions differ, and what evidence supports a conclusion.
The page shows project-defined scientific meaning. The controller stores identities and coordinates declared operations.
Scientific collectors, analyses, and plotting code remain project-owned.

| Decision | Selected behavior | Rationale |
| --- | --- | --- |
| R1 | Reports is the default subview. Plots, Compare, and Samples & traces are peer subviews within Results. | A report supplies context before a user explores individual metrics. |
| R2 | Separate Original corpus and TLAiBench report families. Preserve TLAiBench's First numbers designation. | Their outcomes and benchmark claims differ. |
| R3 | Freeze every analysis revision's exact artifact inputs, definitions, parameters, and source. | New measurements cannot rewrite an earlier conclusion. |
| R4 | Keep scheduler state, artifact availability, completeness, provenance, and report currency independent. | Job completion alone does not establish usable evidence. |
| R5 | Compare explicit conditions with coverage and differences visible. Never deduplicate across variants or executions. | TLAiBench record identity omits the effective token cap. |
| R6 | Default aggregates exclude smoke tests and superseded research runs. | Test evidence and historical evidence remain inspectable without contaminating measurements. |
| R7 | Use only declared metrics and deterministic presentation. Do not infer scientific meaning or generate conclusions. | Humans interpret evidence. Project code defines measurement logic. |

## Navigation and layout

The project sidebar retains Home, Overview, Experiments, Runs, Results, Files, and Settings.
Home occupies the brand-header position and returns to `/jobs/project`.
Results uses `/projects/:slug/results` with shared URL keys for view, collection, execution, variant, stage, analysis, and sample.
Collection names the report family: Original corpus or TLAiBench. It is not a separate execution identity.
These names describe routing semantics. The implementation must use one shared serializer across the workspace.
Opening an artifact link preserves its exact execution and revision scope rather than selecting a newer report.

The header shows Results, the selected evidence scope, and New analysis.
Below it, a scope bar shows report family, experiment, executions, variants, stages, and Purpose.
Purpose defaults to Experiments. All includes explicit Smoke tests and historical Unclassified evidence.
Historical Unclassified data needs an explicit import selection before it enters a saved aggregate.

A coverage strip shows expected items, observed items, assessed items, exclusions, and the last indexed time.
It also names unknown counts. Unknown never appears as zero.

| Subview | Layout and controls | Main actions |
| --- | --- | --- |
| Reports | Revision list at left. Selected report and coverage summary in the main pane. Provenance drawer on the right. | Open report, download, inspect inputs, new analysis, copy evidence link |
| Plots | Declared metric selector and filters above plots. Definition, units, denominator, and input revision beside each plot. | Select plot form, filter, inspect sample cohort, save view, export supported artifact |
| Compare | Condition columns with one explicit baseline. Configuration differences and coverage precede metric deltas. | Select 2–4 conditions, change baseline, align samples, save comparison, export table |
| Samples & traces | Filtered sample table beside a details pane. TLAiBench adds parent chain and turn navigation. | Open source, inspect prompt/output/trace, compare aligned sample, copy sample link |

Internal subviews do not reintroduce horizontal project navigation.
On narrow screens, the scope bar wraps, the revision list collapses, and details follow the selected table row.
Keyboard controls reach filters, table selection, chart summaries, provenance, and downloads.
Every plot has a table alternative. Color alone never encodes outcome or completeness.

## Reports and analysis revisions

A report shows its title, authoring operation, analysis revision, input selection, creation time, and scientific limitations.
Its header names the experiment question when one exists. Human conclusions appear as separately attributed notes.
Notes reference exact report or sample identities and use an expected version for edits.
Notes are companion metadata. They never edit the project-generated report.

A revision selector lists prior revisions and their state. A failed new revision does not hide the last successful report.
The UI labels an older revision “Earlier inputs” when a newer compatible artifact set exists.
It does not call the immutable earlier revision incorrect or silently recalculate it.
A changed file at an indexed input path instead produces “Input changed” and requires a new artifact version.

New analysis follows this sequence:

1. Select saved artifacts and a declared analysis operation.
2. Select available metric definitions, parameters, and plot operations.
3. Check completeness, compatibility, source, and required fields.
4. Review exact inputs, resources, operations, outputs, and differences.
5. Dispatch the reviewed analysis plan.

The review uses the Experiments plan contract. Dispatch opens Runs filtered to the new execution.
The analysis revision links that execution to its source collection executions and earlier analysis revision.
It has no collection stage unless the human explicitly leaves this flow to create a collection plan.

Missing data offers “Create collection plan” with the missing requirements. It never starts collection automatically.
New analysis requires complete saved inputs, consistent with Q20.
An existing partial report remains readable with its partial label. Live previews are not saved analysis revisions.

Analysis states are `draft → checked → reviewed → queued → running → succeeded`.
Edits return checked or reviewed drafts to `draft`.
A rejected submission, failed operation, or invalid output produces `failed` with affected stages and evidence.
Cancellation produces `cancelled` after Runs checks process termination.

Accepted-but-uncertain submission keeps a distinct `uncertain` submission fact and blocks repeat submission until reconciliation.
These analysis labels summarize the linked execution. They do not replace its stage or attempt states.

| Condition | Available action | Unavailable action and explanation |
| --- | --- | --- |
| Complete, compatible, locally available inputs | Prepare and review analysis | None from input readiness alone |
| Complete remote-only inputs | Retrieve selected artifacts, then check | Dispatch until the required bytes and identities are available |
| Incomplete or incompatible inputs | Inspect gaps, open Runs recovery, create collection plan | New analysis with a false completeness claim |
| Analysis queued or running | Open Runs, inspect logs, cancel through Runs | Edit its frozen inputs or replace outputs |
| Analysis failed | Inspect partial outputs, prepare new reviewed attempt | Silent retry or overwrite of the last good report |
| Source changed since review | Recheck and review | Dispatch the stale review |
| Unsupported connection version | Read cached compatible exports | Start an unknown operation |

## Completeness, provenance, and outcome rules

Completeness comes from a declared check over the expected item set and observed artifact snapshot.
The check records its version, input digests, timestamp, expected count, observed count, missing identities, duplicates, and exclusions.
Resume invocation counters cannot replace this check.

Repeated rows within one attempt require a declared deterministic rule. Conflicting duplicates block complete status until the adapter resolves them.
Identical records in different variants remain separate observations.
Recovery can select prior complete items only through the approved recovery lineage. Results never silently unions attempts.

A scientifically negative model outcome can be a complete measurement.
Harness errors and dataset limitations remain separate counts, with declared inclusion rules for every denominator.
TLC phases retain applicability and skipped reasons. The UI never averages inapplicable phases as failures.
A complete corpus behind a nonzero scheduler exit stays available as evidence.
It links to the stranded-stage recovery action in Runs without releasing dependencies itself.

Every output retains project slug, experiment/revision, plan, execution, variant, stage, attempt, Purpose, and research-run identity where known.
Campaign, group, scheduler job, and array child remain separate linked fields.
Controller-host analyses have no invented scheduler job ID.
Historical imports use explicit import identities with nullable workspace lineage and provenance gaps.
The import cannot fabricate a source snapshot, model revision, dataset revision, or effective generation parameter.

Provenance includes dataset version and item selection, model revision, seed policy, effective token cap, context budget, evaluator version, and toolchain versions.
It also includes source digest, dirty-source snapshot, environment fingerprint, hardware observations, operation version, artifact digests, and parent links.
Unknown fields are visible. Source paths do not imply captured source bytes.
TLAiBench uses effective request settings for condition labels and shows record-identity settings separately.

## Plots and metric semantics

Initial plot forms are table, grouped bar, histogram, scatter, and line against an explicitly declared step or time field.
Each form consumes declared typed fields and metric definitions.
A custom scientific plot remains an output of a declared project operation.
No training-loss plot appears unless the project declares training-loss data.

TLAiBench presets cover outcome rate, outcome class by stage, applicable checker phases, trace length, truncation, and context exhaustion.
Original-corpus presets cover benchmark outcome, trace length, token limits, and available timing measurements.
These presets require adapter field mappings before activation. Their labels are not evidence that the current connection supports them.

Every metric definition contains its ID, version, source, type, unit, grouping dimensions, aggregation, denominator, exclusions, and missing-value policy.
Rates show numerator and denominator next to the value.
A zero denominator yields Not defined. Missing values never become zero or disappear without an exclusion count.
Precision follows the declared metric or a view setting. Export retains underlying values.

Throughput distinguishes generation timing from scheduler elapsed time.
A hardware allocation count never appears as measured GPU busy fraction.

View changes update filters and visual form only. Save view records those settings and exact analysis/input references as companion metadata.
If a view needs new derived values, New analysis creates a reviewed revision.
Initial delivery shows no automatic confidence interval or significance claim.
A later project-declared statistical operation must specify sampling unit, dependence, repetitions, exclusions, and method before such values appear.
Exports include definitions, input identities, filters, and coverage in a companion manifest.

## Comparisons

A condition is an explicit execution, variant, stage, and artifact selection, or a compatible analysis output from that selection.
The UI allows 2–4 conditions initially. Larger selections open a table without a multi-column sample inspector.
No condition becomes the baseline until the human selects it. A saved comparison retains that selection.

| Compatibility | Treatment |
| --- | --- |
| Same metric definition, unit, evaluator, dataset revision, and selection policy | Show deltas with paired coverage and unmatched items |
| Different model, effective cap, seed, context budget, or hardware | Show as intentional condition differences. Preserve these dimensions in all labels and exports. |
| Different dataset revision, evaluator, denominator, or metric definition | Show side-by-side descriptive values. Disable aggregate deltas until a declared compatibility mapping exists. |
| Missing provenance | Show Unknown compatibility. Permit inspection with a visible warning. Do not claim a controlled comparison. |
| Partial evidence | Exclude from default complete comparison. Explicit exploratory selection shows coverage and excludes incomplete data from saved analysis inputs. |
| Smoke-test evidence | Keep a separate Purpose filter. Do not mix it into research aggregates. |

The default sample join uses dataset identity/revision, item identity, stage, and declared sample index or seed policy.
Model and token cap identify conditions and do not belong in the cross-condition join key.
Execution and variant identity remain on each joined observation.
For TLAiBench, the adapter includes puzzle, sample index, stage, and parent context where required.
Ambiguous many-to-many matches block paired deltas until the human selects an attempt or a declared repeat aggregation.
The UI never pairs rows by file order or assumes equal record IDs across different models.

The comparison first shows configuration differences and counts for matched, left-only, right-only, excluded, and unknown records.
A user can select all available evidence or the intersection. The selected policy remains visible and enters exports.
Default aggregate values use each condition's declared denominator. Paired deltas use the displayed matched subset only.
Changing to intersection never silently changes the meaning of a published report.

## Samples and traces

The table includes dataset item, model, variant, stage, sample/seed, outcome, completeness, trace length, truncation, and source identity.
Filters cover outcomes, harness errors, dataset limitations, capped turns, recovered traces, missing fields, and superseded research runs.
Opening a sample shows raw prompt, formatted prompt when recorded, emitted output, extracted trace, answer, reference, and evaluation evidence.
TLAiBench adds turn index, tool directives, tool results, checker phases, candidate specification, parent record, and artifact truncation indicators.

Observable reasoning trace means emitted model text. It does not claim access to internal reasoning.
“Not recorded,” “Recorded empty,” “Truncated,” and “Unavailable file” are different states.
A prompt digest cannot substitute for prompt text.

Large traces use bounded pages with explicit offsets. Search reports whether it covers the loaded page or the complete indexed sample.
The inspector shows literal model/tool text safely and never executes embedded code, scripts, links, or tool directives.
A missing parent shows its known identity and location, plus retrieval availability. It never substitutes another variant's parent.

## Data and service contracts

The API belongs under `/api/v1/projects/{slug}/workspace`, as ADR 0008 specifies.
The following resources extend that family. Exact HTTP naming is an engineering contract, not proof of implementation.

| Resource | Required fields and behavior |
| --- | --- |
| Result set | Stable ID, project, family, selected artifact IDs/versions, selection policy, coverage, provenance status, index version, observed time |
| Artifact reference | Artifact ID, content version/digest, producing identities, Purpose, schema/version, declared kind, availability, completeness evidence, locations |
| Analysis revision | Stable ID, predecessor ID, selected inputs, metric versions, parameters, operation/source snapshot, reviewed plan, linked execution, output artifact IDs |
| Metric value | Definition ID/version, dimensions, value or missing reason, unit, numerator/denominator, exclusion counts, source cohort |
| Sample | Stable adapter sample key, scoped record identity, artifact digest and record locator, dataset/item/seed, condition, parent links, recorded-field flags |
| Comparison | Stable ID/version, condition references, baseline, join policy, compatibility result, cohort counts, filters, selected metrics |
| Evidence note | Stable ID/version, human text, author/time, exact evidence references, optimistic concurrency token |
| Query response | Pagination cursor, selection fingerprint, index version, total or unknown count, completeness and freshness, structured errors |

Results and Files share the artifact registry, transfer records, content checks, and location terminology.
Heavy indexing uses bounded controller work or a declared compute stage. It never runs scientific compute on a login node.
A query cannot dispatch, fetch, analyze, rewrite source, mutate a manifest, or repair a dataset.

Read-side cache indexing parses already available artifacts only. Approved analysis and retrieval follow their declared execution scope.
No workflow LLM selects metrics, changes exclusions, interprets failures, or writes conclusions.

## Loading and failure behavior

| Condition | Required presentation and next action |
| --- | --- |
| No results | Explain that no indexed artifacts match the scope. Offer Experiments or Files import inspection. |
| No filter matches | Preserve filters and offer Clear filters. Do not imply that the project has no evidence. |
| Loading | Show scoped skeletons. Retain old data with a loading label until the new query completes. |
| Stale index or disconnected controller | Keep the last snapshot and its timestamp. Disable mutations that need fresh checks. Offer Refresh. |
| Remote-only artifact | Show metadata, known size, last observation, and Retrieve. Do not present an empty report. |
| Unsupported schema | Keep file/provenance links and the schema error. Disable derived views for affected artifacts. |
| Partial retrieval or analysis | Show successful artifacts and failed members separately. Keep prior reports accessible. |
| Malformed record | Name artifact and record locator. Quarantine it from aggregation with an exclusion count. |
| Missing report output | Show the linked analysis execution and expected artifact. Do not invent a report from logs. |
| Changed or missing input bytes | Preserve history. Mark the exact affected input unavailable or changed and block new use until checked. |

A superseded report remains reachable by URL. An unavailable input does not delete its derived report or erase the provenance gap.

## Acceptance and verification scenarios

1. Two models and two effective caps produce four visible conditions after analysis, even when TLAiBench record IDs collide across caps.
2. A resumed corpus with zero invocation `done` count can become complete only through its declared expected-item check.
3. A failed scheduler exit plus a complete corpus shows both facts and links to manual Runs recovery without releasing children.
4. A metric change over complete saved artifacts creates a new analysis revision and leaves generation untouched.
5. A missing collector field blocks that analysis and identifies the collection requirement before any dispatch.
6. A failed analysis preserves its partial outputs and the prior successful report with exact source links.
7. A comparison with different evaluator versions shows values and differences but no unsupported paired delta.
8. Missing, unmatched, and excluded samples remain counted. Zero is never the default for missing measurement data.
9. A TLAiBench sample opens its actual parent, turn, phase applicability, effective cap, and recovered-trace marker.
10. A historical `nogit` source and unversioned dataset display unknown provenance and cannot claim reproducibility.
11. A smoke-test artifact appears under Smoke tests and in resource accounting, but never in default research aggregates.
12. Exports reproduce the displayed cohort, metric definitions, and analysis revision from their companion manifest.
13. Browser closure and controller restart preserve an approved analysis execution without duplicate generation or report overwrite.
14. Concurrent evidence-note edits return a conflict and retain both the saved version and the user's unsaved text.

Verification uses fixture artifacts, fake transfers, declared mock analyses, and browser navigation checks.
A live cluster run is unnecessary for these Results guarantees.

## Delivery phases and technical gates

| Phase | Deliverable | Dependency and exit gate |
| --- | --- | --- |
| R0 | Shared result/artifact contracts and adapter fixtures | Experiments identity and snapshot contract. Four variants survive indexing with separate provenance. |
| R1 | Reports, availability, coverage, file links, revision history | Experiments artifact phase plus Files bounded previews. Scheduler, transfer, completeness, and currency remain separate. |
| R2 | Reviewed analysis revisions and isolated exports | Durable execution coordinator and declared project operations. New analysis never changes old outputs or reruns collection. |
| R3 | Samples, traces, declared plots, comparisons, saved views | Versioned query index and sample mappings. Mismatch and partial-evidence scenarios pass. |
| R4 | Human evidence notes, export manifests, scale checks | Stable references and conflict tokens. Saved links survive archive and later analysis. |

Deferred features include arbitrary metric expressions, hidden-state instrumentation, automatic significance claims, cross-project comparisons, production tracing, and automatic research conclusions.

| Spike | Recommended approach | Fallback | Completion gate |
| --- | --- | --- | --- |
| How can existing reports preserve variant identity? | Project adapter reads explicit artifact lists and partitions deduplication by execution/variant/stage. | Run existing report separately per selected condition, then join typed summaries without rescanning a combined root. | Both caps and repeats survive fixtures. Parent links and duplicate counts remain exact. |
| How can large JSONL support sample queries? | Versioned SQLite index with byte locators and artifact digests. Parse bounded batches off request threads. | Paginated file inspection and exported project tables. Disable full-corpus search until indexed. | Interrupted indexing resumes safely. Changed inputs invalidate locators. Queries never mix index generations. |
| How are legacy inputs frozen for reanalysis? | Capture a content-addressed local copy or project-provided immutable version before review. | Block reanalysis of mutable paths while retaining preview/download. | Modifying the original after review cannot change an approved analysis input. |
| Which project plotting entrypoints exist? | Add a project-owned adapter with fixture-backed plot outputs during implementation. | Fixed UI chart forms over declared fields and report tables. | The connection advertises only working plots with units, source cohorts, and downloadable outputs. |
