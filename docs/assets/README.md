# README diagrams

`campaign-flow.dot` is the editable Graphviz source for `campaign-flow.svg`.
It describes the boundaries implemented by the HTTP client, controller API,
planner, journal, worker, and Slurm transport. It is an architecture diagram,
not a measurement or a screenshot.

Regenerate from the repository root after changing those relationships:

```bash
dot -Tsvg docs/assets/campaign-flow.dot -o docs/assets/campaign-flow.svg
```

The README's Mermaid sequence adds the submission and result-retrieval order.
Keep both aligned with [architecture](../../ARCHITECTURE.md).
