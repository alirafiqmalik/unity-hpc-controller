# Contributing

Read [the glossary](CONTEXT.md), [architecture](ARCHITECTURE.md), and
[ADR 0009](docs/adr/0009-headless-campaign-controller.md) before changing behavior.
The [documentation index](docs/README.md) links setup, operations, and evidence.

## Development

Use Python 3.12, the version exercised by CI. The controller uses the standard
library; the test suite needs pytest. The optional MCP client uses the dependency
range in [mcp/requirements.txt](mcp/requirements.txt).

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install pytest
python -m pytest -q
scripts/release-check
```

The tests use local fixtures and simulated transport. Passing them does not
establish access to Unity or validate a live allocation. For changes to Slurm
behavior, describe any bounded live validation separately.

## Changes

Keep scientific logic in the project and cluster execution in the controller.
MCP and CLI tools call HTTP. Preserve the journal, campaign identity, and
hardware-class contract. Add an ADR for a new ownership or execution decision.

Use neutral placeholders in examples and docs. Keep local settings and raw
cluster evidence outside the repository. Update both plugin manifest versions
when shipped files change; `scripts/release-check` compares committed history
with `origin/main` by default.

Report bugs in this repository's GitHub Issues with a reproducible command,
expected and actual behavior, relevant versions, and sanitized diagnostics.
Include focused verification with a pull request. Avoid raw cluster records or
private account details. See [issue conventions](docs/agents/issue-tracker.md)
for the repository's tracking workflow.
