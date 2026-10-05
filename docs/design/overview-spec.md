# Project Overview specification

Version 1, 2026-10-03. Agent-selected refinements to the accepted Overview landing page and retained research question.
The [shared specification](remaining-workspace-spec.md) governs identities, navigation, state dimensions, action safety, and ownership.

## User goal and layout

Overview answers what the project asks, which work needs attention, and which evidence supports the next experiment.
Clicking a project opens this page. Home occupies the brand-header slot and returns to the global Projects list.
The other sidebar destinations remain Experiments, Runs, Results, Files, and Settings.
The primary action is New experiment. It opens workflow selection without creating or dispatching a runnable plan.

The first row contains the research question on the left and Needs attention on the right.
The question card shows human-authored question, working hypothesis, intended outcome measure, and linked baseline when one exists.
Empty fields show Add research question or Link evidence. Example text must never become saved project data.
An Edit action opens a small metadata form with Save and Cancel. This page does not autosave scientific conclusions.

The second row has three cards: Experiments, Runs, and Results.
Experiments counts drafts by readiness. Runs counts Active, Needs attention, and Uncertain executions, with child counts available on opening.
Active means at least one active stage. Needs attention means at least one blocked, rejected, or failed stage or unresolved management action.
Uncertain means at least one uncertain submission or management action. These counts can overlap and must not appear as a summed total.
Links use Runs' `state=active` or `attention=needs_attention|uncertain` predicates and preserve the project and collection scope.

Results counts current reports, incomplete datasets, and reports with newer inputs. It does not claim that terminal jobs produced complete results.
Each count opens the matching filtered page. Counts use one response snapshot, with individual observation times where sources differ.

The next row contains Continue research and Evidence and conclusions.
Continue research links the latest edited draft, recent execution, saved comparison, and report, grouped by collection.

Original corpus and TLAiBench have equal first-level headings. TLAiBench preserves the project's First numbers designation and limitations.
The default overview scope is all collections. Collection filters alter cards and recent work, but do not hide the project research question.
Campaign is an optional advanced filter. It never becomes the experiment identity.

Evidence and conclusions contains pinned report/comparison revisions and concise human-authored notes.
Each note names its evidence version, author attribution available to this controller, and saved time.
If the deployment only knows the local operator, do not imply verified multi-user attribution.

The activity list follows below: dispatch, stage pause, retrieval outcome, analysis revision, and connection maintenance.
Each activity opens its exact entity. Load the newest 20 entries and paginate older entries.

## Controls, priorities, and transitions

| Action | Availability and effect |
| --- | --- |
| Edit research question | Metadata store writable; Save checks `expected_version`, preserves note history, and changes no experiment snapshot |
| New experiment | Valid workflows or composition capability; otherwise opens connection guidance in Settings |
| Continue draft | Draft exists, including archived experiment history; opening does not restore or dispatch it |
| Open attention item | Exact execution, attempt, artifact, or connection ID resolves; stale links show history rather than guessing a replacement |
| Pin evidence | A stable report, comparison, artifact, or sample reference exists; record exact revision and selection |
| Save conclusion | Human supplies text and optional evidence; save versioned metadata without ranking or generated interpretation |
| Update pinned evidence | Explicitly select a newer revision; preserve the old pin in history and show the changed evidence |
| Refresh | Read current controller summaries; no execution, retrieval, or connection repair side effects |

Question editing states are Viewing, Editing, Saving, Saved, Unsaved, and Conflict.
A failed save retains the edit buffer. A conflict shows saved and edited text with Reload and Copy my text actions.

No automatic merge occurs. Save after reconciliation uses the new expected version.
Pinning does not copy a report into a mutable “latest” reference. Deleted or unavailable bytes keep an unresolved evidence marker.

Needs attention ranks uncertain action outcomes first, then execution failures and dependency blocks, then missing data and stale analysis.
Connection problems appear first when they prevent the next action. Show severity, cause, observation time, scope, and a direct action link.

Deduplicate repeated events by affected entity and cause. Acknowledging an item hides only that observation until its condition changes.
Acknowledgment does not clear a failure, release a dependency, dismiss a mandatory check, or authorize recovery.
The default list shows five items and a View all link into Runs or the appropriate page.

## Edge states

| State | Required behavior |
| --- | --- |
| New attachment | Research question remains editable; show Add question and New experiment or Configure connection; all counts are actual zeroes |
| Loading | Render card skeletons independently; do not show zero as a temporary count |
| Stale | Keep previous facts with observation times and stale badges; hide claims of current activity until refreshed |
| Unavailable | Show which source failed; keep notes and other loaded cards; provide Settings diagnostics |
| Partial success | A failed result summary leaves Runs and research text usable; never discard successful sections |
| Failure | Preserve entered text and prior saved state; show retry only for the failed metadata/read operation |
| Missing evidence | Keep pin identity and provenance; offer Files availability details; do not switch to a different report |
| No matching scope | Explain active filters and provide Clear filters; retain the project question |
| Archived experiment | History links remain readable; active counts exclude it only when their label says Active experiments |

Overview uses declared research progress when available. Otherwise it shows counts of known stages and completed artifacts.
It never synthesizes sample progress from elapsed walltime or GPU allocation.
Resource usage includes smoke tests and failed work. Scientific summaries exclude smoke tests by default.

## Proposed data contract

Add a read projection at `GET /api/v1/projects/{slug}/workspace/overview`.
Return `project`, `research_context`, `scope`, `counts`, `attention`, `continuations`, `pins`, `activity_cursor`, and per-section freshness/errors.
Every link includes stable entity IDs. Every count includes its predicate and observation time.
Bound this projection to indexed metadata. Do not scan corpora or call SSH while rendering it.

Use existing controller events and workspace records as sources. Create research metadata storage in the same workspace database.

Research context contains `version`, `question`, `hypothesis`, optional `outcome_metric_ref`, optional `baseline_ref`, and `updated_at`.
Until the first explicit metadata Save, read the existing connection's `research_question` as the question fallback.
Record the declaration digest and `origin=manifest` beside that fallback. A missing declaration cannot erase a previously observed question.
The first Save copies the displayed context into versioned workspace metadata and records its declaration origin.
Later declaration reloads preserve saved workspace text, including an intentionally cleared question. They show changed declared text as an optional adoption preview.

Notes contain `id`, `version`, plain text, evidence references, available author attribution, and timestamps.
Write endpoints require the shared expected-version contract. These are metadata writes, not source-file writes.
An experiment copies selected research context into its draft only through explicit human selection. Later Overview edits do not change that snapshot.

The required dependencies are project layout, experiment identity/readiness, durable execution projection, artifact index, and saved Results references.
The first Overview increment can show missing sections as Not available yet, with a precise capability reason.
Do not ship fabricated counts or substitute the fixed catalog for the saved experiment library.

## Automation limits and verification

Overview can aggregate observations and sort attention items deterministically.
It cannot select a hypothesis, infer causality, choose a winning model, submit recovery, retrieve artifacts, or rewrite conclusions.
Links lead to page-specific review flows for actions with runtime effects.

Acceptance scenarios:

1. A new attachment opens Overview with an editable empty question and truthful zero counts. Home returns to the prior Projects filter.
2. A failed smoke test appears under attention with Purpose intact. Its link opens only the affected execution and dependents.
3. Scheduler observations become stale while local notes remain available. Their independent timestamps remain visible.
4. Two editors save the same question revision. The second receives a conflict, keeps its text, and cannot overwrite silently.
5. Reanalysis creates a new report. An existing pin and conclusion still open the original revision until the human updates the pin.
6. A complete corpus behind a failed scheduler exit appears as a blocker and as available evidence, without automatic continuation.
7. Results indexing fails. The question, Runs cards, and successful section reads remain usable.
8. Keyboard and narrow-screen users can reach Home, all six sections, attention items, pins, and metadata save controls.
9. An existing manifest question survives upgrade. Declaration reload cannot overwrite a saved human revision or restore intentionally cleared text.

## Delivery and deferred features

Deliver the research question, layout, scoped links, and honest empty states with the accepted project layout.
Add operational summaries after the execution projection. Add pins, conclusions, and collection summaries after the Results index and comparison contracts.
Defer cross-project research summaries, collaborative rich-text editing, automatic conclusions, and free-form dashboard widgets.
No additional product interview is required. The projection must pass mixed-freshness and conflict fixtures before its action links activate.
