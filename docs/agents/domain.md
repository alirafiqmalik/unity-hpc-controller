# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root: the glossary, with the retired terms to avoid.
- **`docs/adr/`**: read the ADRs that touch the area you're about to work in. ADR 0009 is the current contract. ADRs 0001, 0002, 0006, and 0008 carry a superseded marker; read them only for history. ADRs 0003 to 0007 still govern the telemetry archive.
- **`ARCHITECTURE.md`**: ownership, execution flow, data stores, and limits.

If a file does not exist, proceed silently. Do not suggest creating it upfront.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Record decisions as ADRs

New decisions go in `docs/adr/` as numbered files. Mark a superseded ADR with a one-line note under its title that links the replacement.

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0009 (headless campaigns) — but worth reopening because…_
