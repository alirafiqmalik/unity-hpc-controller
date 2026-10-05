# Files specification

The [shared contract](remaining-workspace-spec.md) governs state mappings, identities, navigation, and action receipts across pages.

Version 1, 2026-10-03. Final design for implementation planning.
All choices labeled F below are agent-selected under the autonomous planning request.
The accepted [Experiments baseline](experiments-spec.md) supplies ownership, snapshot, and recovery requirements.
This specification requires no amendment to Q1–Q23.
The [capability review](../research/results-files-capabilities.md) records current limits, including the broad legacy corpus hook.

## Decisions and purpose

Files helps a human find source, inspect evidence, understand availability, and retrieve declared outputs.
It is a browser over project files and workspace artifacts, with explicit provenance and transfer scope.
It does not become a remote shell, source editor, or second synchronization system.

| Decision | Selected behavior | Rationale |
| --- | --- | --- |
| F1 | Read-only source and artifact browsing, with bounded previews and downloads | Scientific source stays project-owned. Existing editors already own source editing. |
| F2 | Distinguish controller-local, remote-known, both, unavailable, and unknown locations | The browser device is not necessarily the controller host. |
| F3 | Retrieval names exact artifacts and destinations before it starts | A narrow selection must not silently invoke a broad corpus pull. |
| F4 | Transfers preserve previous bytes and never delete source or remote artifacts | A failed or partial retrieval must not destroy evidence. |
| F5 | Executions stage immutable reviewed bundles, independently of general source synchronization | Pending work must retain its approved source. |
| F6 | General source push, bidirectional sync, inline editing, rename, and delete are deferred | These need separate conflict and ownership contracts. They are unnecessary for the research workflow. |
| F7 | Generated wrappers remain inspectable. Save as custom script links to the accepted Experiments action. | Handwritten source cannot become an editable form by inference. |

## Navigation and layout

The project sidebar retains Home at the brand-header position and all six project sections.
Files uses `/projects/:slug/files`, with URL state for root, relative path, artifact, execution, and preview selection.
A direct artifact link selects its immutable identity and version. It does not select the latest file with the same name.
Back navigation restores the prior table position and filter state.

The header contains Files, scope, and Refresh listing.
A narrow left pane contains roots and directories. A central list contains files. A large right pane contains the selected preview.
The preview stacks below the list on narrow screens.

Breadcrumbs name the project root and relative directory. The UI shows host names when a path belongs to another machine.

| Root or filter | Content | Boundary |
| --- | --- | --- |
| Project source | Attached directory and explicitly allowed source/input roots | Read-only. Secret-bearing paths stay excluded. |
| Execution bundles | Reviewed plans, frozen source, generated wrappers, and companion metadata | Immutable execution evidence. No edit controls. |
| Outputs | Declared output artifacts grouped by execution, variant, stage, and attempt | Includes remote-known metadata and local copies. |
| Scheduler logs | Declared logs with campaign, job, array child, stage, attempt, and Purpose | Log state does not establish scientific outcome. |
| Reports and plots | Analysis revision outputs | Links to Results preserve revision scope. |
| Transfers | Current and prior retrieval operations | Each transfer records exact scope and member outcomes. |

These roots are views over one registry, not duplicate copies or new project folders.
The tree starts shallow and loads each directory on demand.
The list shows name, kind, size or Unknown, modified time, availability, integrity, producing execution, and Purpose.
Filters include name, kind, execution, variant, stage, Purpose, location, and changed-since-index.
Search covers the selected indexed root and names its scope. It does not recursively scan arbitrary remote directories.

The details pane shows source/destination locations, observed times, digest, schema, completeness, ownership, and producer/consumer links.
Open in Results appears for supported evidence. Open in Runs appears for a producing stage or log.
Copy path names the host and does not imply that the browser can access that path.

Download copies an available artifact to the browser device through the controller.
Open in editor is optional host integration. Otherwise, Copy path supplies the handoff without claiming that an editor opened.

## Preview contract

| Kind | Initial preview | Limits and fallback |
| --- | --- | --- |
| Plain text, source, logs | Escaped text with line numbers, line range, search scope, and wrap control | Initial 256 KiB or 2,000 lines, whichever comes first. More loads explicit bounded pages. |
| JSON | Raw text plus a collapsible tree when parsing succeeds | A parse error preserves raw preview and the error offset. No source repair. |
| JSONL | Records with their line/byte locators and schema status | Initial 100 records within the byte cap. A truncated final line stays incomplete. |
| CSV/TSV | Table with header, row count or Unknown, and source preview | Initial 100 rows within the byte cap. No automatic type coercion that changes values. |
| Markdown report | Safe rendered text with raw-source option | No script execution or automatic remote embeds. |
| Raster plot/image | Image and metadata | Decoding uses bounded dimensions and bytes. Unsupported files use Download. |
| SVG, HTML, notebooks | Escaped source by default | Rich preview requires a sandboxed renderer with no script or network access. |
| PDF | Download initially | Optional isolated preview only after the renderer capability passes its gate. |
| Binary, archive, model weights | Metadata, size, digest, availability | No implicit extraction, execution, or full-file read. |

Limits are initial implementation defaults, not scientific constraints.
The service enforces them even when the client requests larger responses.
Truncation labels show loaded bytes/records and offer the next bounded range or Download.
A preview reads a stable content version or returns a changed-file conflict.
It never splices bytes from two versions into one apparent document.

Remote-known files require explicit retrieval before content preview.
A metadata refresh can query an approved output root through a bounded read-only adapter.
It cannot crawl a home directory, run a scientific operation, or transfer a corpus as a side effect.
Follow live log content belongs to Runs. Files opens a bounded snapshot with a link to the Runs log viewer.

## Artifact availability and completeness

Location, transfer, integrity, completeness, and freshness are independent fields.
Files shares their meanings with Results and Runs.

| Axis | States | Meaning |
| --- | --- | --- |
| Availability | `local`, `remote`, `both`, `unavailable`, `unknown` | Known locations for the selected content version |
| Transfer | `idle`, `queued`, `running`, `succeeded`, `partial`, `failed`, `cancelled`, `uncertain` | Outcome of the selected retrieval operation |
| Integrity | `unchecked`, `checked`, `mismatch`, `changed` | Byte-level identity compared with the declared artifact version |
| Completeness | `unknown`, `partial`, `complete`, `invalid` | Project-declared artifact or corpus check result |
| Freshness | observed timestamp plus `current`, `stale`, or `unknown` | Currency of location/index observations, not scientific validity |

A successful transfer can contain an incomplete corpus.
A complete remote corpus can remain unavailable locally.
A stale remote observation cannot establish that a file still exists.
For append-only live output, each preview/index snapshot records its observed size and digest or declared generation token.
Only the declared completion check promotes that output to complete.

## Retrieval and action availability

Retrieve opens a scope review with artifact count, known byte total, unknown sizes, source host/root, destination, conflicts, and adapter name.
The review shows whether it retrieves selected artifacts, a selected execution, a campaign, or the entire declared corpus.
Every root and member is within the approved project's allowlist.
The review records its selection fingerprint and freshness.
A changed member set or destination conflict invalidates the review before transfer.

| Condition | Action | Effect |
| --- | --- | --- |
| Checked local copy | Preview, download, open evidence | No transfer |
| Remote-known artifact with scoped adapter | Retrieve | Create a persistent transfer with exact selected members |
| Remote-known artifact with only legacy hook | Review full corpus retrieval | Explicitly show the hook's entire declared scope. Never label it selected-file retrieval. |
| Local version differs from remote candidate | Inspect differences and retrieve as a new version | Preserve both copies and their provenance |
| Local destination contains unrelated bytes | Choose an isolated destination or cancel | Never overwrite project-owned source or inputs |
| Active transfer | Inspect members, cancel transfer | Stop transfer processes. Preserve checked members and quarantine partial bytes. |
| Partial or failed transfer | Retry failed members after review | Keep successful members. Do not restart a broad hook under a narrow label. |
| Unsupported transfer adapter | Copy known path, inspect metadata | Explain the capability gap. No raw shell fallback. |
| Uncertain interrupted transfer | Reconcile destination and partial files | Block duplicate transfer until the service determines safe remaining scope |
| Missing file | Refresh metadata, inspect producer in Runs | No automatic recollection or retry of scientific work |

The existing hook supports a full corpus pull with backups.
During compatibility delivery, only the full-scope action can invoke that hook.
It remains separate from the accepted execution continuation, which requires declared scoped output retrieval.
If the hook cannot provide trustworthy per-file progress, the UI shows phase and elapsed time without a fabricated percentage.

Transfers follow `queued → running → succeeded | partial | failed | cancelled`.
A controller interruption produces `uncertain` until reconciliation checks destination versions and the adapter's outcome.
Retry creates a new transfer identity linked to the prior transfer and its remaining scope.
Transfer cancellation does not cancel scheduler jobs, analysis stages, experiments, or unrelated transfers.

The transfer service writes temporary files outside final artifact paths.
It checks the declared size/digest policy, then promotes complete files atomically within the destination filesystem.
Previous content remains available as a version or backup.
No retrieval uses deletion to mirror a remote tree.
A download from the controller to the browser is a separate operation from retrieval from the cluster.
Its failure does not change artifact availability on the controller host.

Approved execution continuation can retrieve the exact outputs already present in its reviewed plan.
A visit to Files, Refresh, or Preview cannot authorize a new transfer.
Failures pause dependent analysis for human review. They do not cause unlimited automatic transfer retries.
An adapter can resume bytes only within the same approved transfer and bounded policy. It cannot broaden scope.

## Editing and synchronization boundaries

Project-owned scientific source, runners, tests, analyses, plots, input datasets, and connection declarations have no inline Save button here.
The human edits them through an external editor and source-control workflow.
Refresh listing updates observations. Reload connection in Settings checks updated declarations.
Source changes invalidate undispatched reviews when they affect the declared snapshot.
Already dispatched work continues from its frozen bundle.

Files treats generated wrappers as read-only evidence.
Save as custom script opens the accepted Experiments conversion flow, which creates a new project-owned entrypoint without replacing the wrapper.
The Files page does not infer parameters or a workflow graph from arbitrary shell text.

There is no Push project or Sync all action in this delivery.
Approved cluster execution uploads only its immutable bundle through the controller.
Existing legacy synchronization remains a separately documented project capability in Settings.
A legacy sync cannot run automatically when the user previews files or dispatches a workspace plan.
No UI action overwrites custom `sync.sh`, `fetch.sh`, environment files, or connection declarations as repair.

No rename or deletion applies to project files, remote files, output artifacts, or history.
Archive in Experiments preserves all files.
Workspace retention remains explicit future work. An archived experiment does not authorize artifact deletion.

## Data contracts and resource scope

The service belongs under `/api/v1/projects/{slug}/workspace`.
The selected API names must match the shared artifact contract from [Results](results-spec.md).

| Resource | Required fields |
| --- | --- |
| Browse root | Stable ID, project slug, kind, ownership, host, canonical allowed path, visible/excluded patterns, supported actions |
| File entry | Root ID, relative path, file/directory/symlink kind, size, observed modified time, content version/token, observation timestamp |
| Artifact | Stable artifact ID, schema/version, producing identities, Purpose, input/output role, version/digest, declared paths, completeness evidence |
| Location | Artifact version, controller/cluster host identity, relative path under approved root, availability, observed time, size/digest if known |
| Preview | Version token, byte/line/record range, encoding, MIME, truncated flag, next cursor, structured error |
| Transfer | Stable ID, prior transfer ID, actor, approval time, exact scope, adapter/version, source/destination, member states, bytes known/transferred, errors |
| Conflict | Expected and observed versions, affected member, preserved locations, permitted recovery actions |
| Audit event | Action, actor, project, artifact/transfer IDs, timestamp, scope, outcome, secret-free explanation |

Project slug and root ID constrain every request. A browser-supplied absolute path never defines authorization.
Canonical resolution rejects traversal, disallowed symlink escapes, device files, sockets, and paths outside the allowed roots.
Symbolic links show their target classification. A link does not expand the root's permissions.
External input roots require explicit connection declarations and read-only access.

The default browser excludes environment secrets, private keys, controller credentials, and version-control internals.
A guessed URL cannot bypass those exclusions.

Downloads preserve content bytes and meaningful filenames without exposing arbitrary server paths.
Preview and indexing budgets include maximum bytes, records, walltime, and concurrent requests.
Scientific analysis does not run on a login node as part of retrieval or preview.
The controller remains the cluster access owner. UI actions never issue SSH or scheduler commands directly.

## Loading and failure behavior

| Condition | Required behavior |
| --- | --- |
| Empty directory | Show its root and path. Preserve navigation and explain that the directory contains no visible files. |
| Empty Outputs | Link to Experiments and explain that declared outputs appear after execution or explicit import indexing. |
| Loading directory | Show placeholders only in that directory. Keep the rest of the tree and selected preview usable. |
| Stale listing | Keep rows with observation time. Refresh does not erase previously known artifact identities. |
| Controller unavailable | Keep cached metadata with a stale banner. Disable retrieval and new content reads. |
| Remote unavailable | Keep local copies usable. Show remote error and last observation separately. |
| Preview unsupported | Show metadata and Download when available. Do not call the artifact corrupt. |
| Preview failure | Show affected version and error. Keep other files usable and offer bounded retry. |
| Partial transfer | Show successful, failed, and unfinished members with distinct actions. Preserve completed copies. |
| Digest mismatch | Quarantine new bytes, retain prior copy, and mark the candidate invalid for analysis. |
| Access denied or excluded path | Show a specific unavailable reason without exposing secret contents. |
| Disk full | Stop affected writes, preserve partial and prior files, and show required versus known available space. |
| Concurrent file change | Return a conflict and restart preview on explicit refresh. Do not merge versions. |

A global Refresh does not make every row Loading when only one directory needs an update.
Failures retain the selected path and filters so that recovery does not require finding the artifact again.

## Acceptance and verification scenarios

1. A Results artifact link opens the exact file version and preserves execution, variant, stage, attempt, and Purpose.
2. A browser on another machine distinguishes controller-local availability from a completed browser download.
3. Selecting one remote artifact cannot invoke the broad legacy corpus hook without a review of that full scope.
4. A partial transfer preserves checked files, quarantines incomplete bytes, and retries only reviewed remaining members through a capable adapter.
5. A changed local destination never loses its prior bytes during retrieval.
6. Transfer cancellation leaves scheduler jobs and unrelated transfers unchanged.
7. An interrupted transfer reconciles existing bytes before any retry and never reports complete from an exit code alone.
8. A successful retrieval of incomplete JSONL remains Partial in Results and Files until its declared completeness check passes.
9. Source edits after review invalidate the next dispatch review while queued executions keep their frozen source.
10. A symlink escape, traversal path, secret file, and oversized preview cannot bypass server-side root and budget controls.
11. JSON parse failure leaves the raw bounded preview available without attempting a repair.
12. Model output that contains HTML or tool directives displays as evidence and executes nothing.
13. An unavailable remote location does not disable the checked local copy or erase its provenance.
14. Large text and JSONL remain navigable through bounded pages and accurately labeled search scope.
15. Archive and report supersession preserve file paths, downloads, and evidence links.

Verification uses temporary project roots, fake remote adapters, interrupted transfers, digest conflicts, and browser preview fixtures.
The implementation gate needs no cluster-state mutation.

## Delivery phases and technical gates

| Phase | Deliverable | Dependency and exit gate |
| --- | --- | --- |
| F0 | Artifact roots, location/version records, exclusions, preview budgets | Experiments ownership and identity contract. Traversal and mixed-version previews fail closed. |
| F1 | Read-only tree, bounded previews, local downloads, producer links | Shared artifact index. Empty, stale, unavailable, and unsupported states remain distinct. |
| F2 | Reviewed scoped retrieval, persistent transfers, conflicts, cancellation | Declared output adapter plus controller continuation. Partial and interrupted transfer scenarios pass. |
| F3 | Legacy broad-fetch compatibility and provenance import | Explicit scope preview and import identity. Historical source gaps remain unknown. |
| F4 | Performance and accessibility checks, optional safe rich preview | Representative large files and hostile-content fixtures. Budgets hold across API and browser. |

Deferred features include inline editing, code push, bidirectional synchronization, remote shell access, artifact deletion, automatic retention, and archive extraction.

| Spike | Recommended approach | Fallback | Completion gate |
| --- | --- | --- | --- |
| Can the current project hook retrieve one execution? | Add a project-owned adapter that accepts an explicit manifest of relative output paths. | Retain a clearly labeled full corpus retrieval action. Disable narrow retrieval for that adapter. | Fake-remote fixtures prove that selecting one execution transfers no unrelated corpus member. |
| How does retrieval protect changing outputs? | Snapshot final outputs or use producer completion markers plus digest/size checks before promotion. | Keep live output partial and offer bounded snapshot reads only. | A writer that appends during transfer cannot produce a falsely complete artifact. |
| How does the service preserve conflicting copies? | Versioned artifact destinations with atomic promotion and recorded source digests. | Isolated transfer directory requiring explicit import after checks. | Existing project files remain byte-identical through success, failure, cancellation, and restart. |
| Which rich previews can run safely? | Existing isolated viewers with no script or network privileges and explicit format support. | Escaped source or Download. | Hostile HTML/SVG/PDF fixtures cannot execute scripts, access project files, or request remote content. |
