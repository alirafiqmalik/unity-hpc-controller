# Remaining workspace design verification

Date: 2026-10-03. This record verifies planning artifacts, not application behavior or cluster capabilities.
The [specification index](remaining-workspace-spec.md) and [delivery plan](remaining-workspace-build-plan.md) contain the implementation handoff.

## Scope and preservation

This session created six area specifications, one shared specification, one consolidated plan, and three focused research reports.
It also added this verification record, ten board pages, and ten PNG exports.
New product choices carry agent-selected labels. No routine design question remains for the user.
Technical spikes specify a question, recommended approach, fallback, and completion gate.

No application code, setup skill, project configuration, or cluster state changed through this session's actions.
Other work continued in the shared checkout. Research reports identify source observations as working-tree evidence rather than released capabilities.
No commit, application test suite, scheduler command, migration, or connection probe ran for this planning work.

The accepted baseline documents remained byte-identical to the session's initial read:

| File | SHA-256 |
| --- | --- |
| `experiments-spec.md` | `797eefc8a90fd8edf6140abcfab49e43c4ce322b5b5a1c6e7ae0c08add4f33ae` |
| `experiments-build-plan.md` | `592cd102e984e16bb289f64201f1b737f2a511982ece903e3206bc06ba68d57f` |
| `project-workspace-plan.md` | `944a67dfe367d0d7b0e03e730568dcdcbb83b2c9e60afdabaa925498536032a3` |

Q1–Q23 and the accepted layout need no amendment for this package.
Earlier “later review” sections retain their historical meaning. The new specification index resolves that scope explicitly.

## Document checks

Cross-checks covered navigation, Home placement, collection names, source ownership, primitive/mode mapping, and exact execution identities.
They also covered purpose, state dimensions, completeness, immutable evidence, cancellation scope, action receipts, review invalidation, and delivery dependencies.

Two focused integration reviews found and resolved these issues:

- Overview counters now use explicit Runs predicates, with overlap visible.
- Analysis activity and report currency remain separate, so a failed new analysis does not hide an earlier report.
- A future schedule has no execution identity until dispatch. Its due check uses the accepted invalidation rules.
- Recovery uses fresh plan/variant/stage paths, with attempt lineage in metadata rather than an invented required path level.
- Legacy/import provenance can remain Unknown. The service cannot fabricate a producer attempt.
- Existing manifest research questions survive Overview metadata migration and later declaration reloads.

The local-link checker passed 97 links across the initial eleven specifications and research documents.
The final check passed 121 local links across twelve documents, including this record and all ten exported previews.
All eleven documents passed the descriptive Simple English lint threshold of one reported violation per 100 words.
Table content received a manual review because the linter excludes tables from much of its scoring.
Lint is a writing check, not proof of formal ASD-STE100 compliance.

## Board checks and export gallery

The session read the current board through the active tldraw hub.
Every save used its observed ETag in `If-Match`. No unconditional filesystem write replaced the board.
Readback checks preserved all 315 pre-existing records exactly, including manual positions, text, shapes, bindings, and page records.
Existing accepted Experiments pages and prior sketches remain intact.

The new pages contain 179 native geometry shapes, 12 native arrows, and 24 endpoint bindings.
All shape and binding references resolve. All IDs are unique, and every arrow has both endpoints bound.
No screenshot or bitmap replaces the editable wireframes.
Pages 10–19 provide the final remaining-page design. Earlier sketches remain reference material.

The local tldraw renderer exported all ten pages to PNG.
Visual inspection covered labels, wrapping, spacing, navigation, columns, and arrow paths.
The review corrected Runs view names, scheduling terminology, Files' three-pane layout, and delivery-phase labels.
It also corrected an empty-text serialization error and an arrow that crossed an unrelated delivery box.
Final exports render successfully. The source remains manually editable in the same board.

| Native page | PNG preview | Specification |
| --- | --- | --- |
| 10 Overview | [Overview](previews/project-workspace-10-overview-final-design.png) | [Overview](overview-spec.md) |
| 11 Runs | [Runs](previews/project-workspace-11-runs-final-design.png) | [Runs](runs-spec.md) |
| 12 Queue action review | [Queue actions](previews/project-workspace-12-queue-action-review-final-design.png) | [Runs](runs-spec.md) |
| 13 Results | [Results](previews/project-workspace-13-results-final-design.png) | [Results](results-spec.md) |
| 14 Samples and traces | [Samples](previews/project-workspace-14-samples-and-traces-final-design.png) | [Results](results-spec.md) |
| 15 Files | [Files](previews/project-workspace-15-files-final-design.png) | [Files](files-spec.md) |
| 16 Settings | [Settings](previews/project-workspace-16-settings-final-design.png) | [Settings](settings-spec.md) |
| 17 Dynamic composition | [Composition](previews/project-workspace-17-dynamic-composition-final-design.png) | [Composition](composition-spec.md) |
| 18 Function and ownership flow | [Function diagram](previews/project-workspace-18-function-and-ownership-flow-final-design.png) | [Shared contract](remaining-workspace-spec.md) |
| 19 Delivery dependencies | [Delivery diagram](previews/project-workspace-19-delivery-dependencies-final-design.png) | [Delivery plan](remaining-workspace-build-plan.md) |

Open [project-workspace.tldr](project-workspace.tldr) to edit the native records.
The PNGs show illustrative states and values. They do not report live cluster or project state.

## Material implementation dependencies

The completed Experiments implementation must supply the agreed IDs, immutable plans, durable continuation, scoped artifacts, and analysis lineage.
Scheduler adapters must prove exact task cancellation and safe state-dependent mutations under Unity's actual policy.
Project adapters must supply scoped retrieval, checked completeness, checkpoint compatibility, and selected-input analysis that preserves effective token-cap conditions.
Custom scientific plotting needs a declared project operation. Generic field plots do not substitute for missing scientific code.
Composition schema negotiation, bounded indexing, and multi-file maintenance need the documented technical gates before write controls activate.

The delivery plan provides fallbacks for each dependency. No unresolved ordinary product preference blocks implementation planning.
