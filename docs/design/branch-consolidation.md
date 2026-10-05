# Branch consolidation

The comparison covers `feat/llms-agents-application`, its uncommitted iterations, and the main checkout’s latest edits.
The final tree combines the evaluation interface with the existing execution engine and research tools.

## Retained changes

| Source | Change | Reason |
| --- | --- | --- |
| Branch | Application metadata, selector, and scaffold command | Separates the application from its resource primitive |
| Branch | GenAI traces, sessions, datasets, evaluations, prompts, and agent versions | Gives LLM evaluation projects a useful interface over their evidence |
| Branch | Generic runner API and bounded execution views | Reuses checked plans and the durable execution engine |
| Branch | Dataset, predict function, and scorer scaffold | Implements the latest evaluation design with portable fixtures |
| Branch | Job Monitor selection, confirmation, and keyboard controls | Supports removal of unwanted monitor rows |
| Main | One prefilled setup screen | Follows the latest interface research and editor simplification |
| Main | Setup first, execution history afterward | Opens the useful project page for its current state |
| Main | Experiment drafts, composition, recovery, schedules, analysis, files, and settings | Preserves implemented execution and maintenance tools |
| Main | Design specifications, browser suites, and delivery evidence | Keeps the requirements and their acceptance evidence |

LLMs & Agents projects open on Traces.
Other projects open workflow setup before their first execution and execution history afterward.
Research tools remain accessible from project navigation.

## Superseded changes

The original branch commit supplied an Axolotl and TRL training scaffold.
The branch’s later evaluation design replaces that scaffold.
The final tree contains the evaluation scaffold.

The branch also deleted the research interface, specifications, and browser suites.
The consolidation retains them because the new execution view lacks their recovery and maintenance controls.

## Corrections

Evaluation setup now prepares a frozen plan and opens it for review.
Explicit approval starts that exact plan.
The review includes output declarations and check failures.
An invalid live declaration still permits access to execution history and frozen plans.

GenAI reads reject files that resolve outside the project.
Evaluation purpose comes from explicit metadata. Missing purpose stays unclassified.

Delete removes rows from Job Monitor and retains their ledger receipts.
Workers and management tools can still reconcile and manage those jobs.
The connect instructions expose the application scaffold and preserve existing attachment metadata.

## Validation

The production build, TypeScript check, and ESLint pass.
The focused API and scaffold suite passes all 84 tests.
The backend suite passes all 1,066 tests across the full run and corrected fixture checks.
All 39 browser checks pass across the suite runs and updated layout checks.
The production browser checks use isolated projects and prohibit cluster access.

A later dataset viewer and evaluation matrix iteration appeared during review.
It remains in the original worktree for continued development.
The reviewed integration uses the initial snapshot saved on October 5, 2026.
