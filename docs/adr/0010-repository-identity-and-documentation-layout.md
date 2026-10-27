# Separate repository identity from plugin identity

Accepted on 2026-10-26.

The repository is named `unity-hpc-controller` to describe its primary
responsibility under ADR 0009. The plugin install slug and MCP server name
remain `unity-hpc`; the marketplace remains `phd-agentic-tools`. Repository
URLs, marketplace entries, and issue routing follow the new repository name.

Runtime modules, operator commands, and plugin discovery directories retain
their paths. Existing deployed services may reference those paths directly.
The local checkout directory does not have to match the GitHub repository name.

Documentation is organized by purpose: `docs/guides/` for current instructions,
`docs/research/` for dated evidence, `docs/adr/` for decisions, `docs/agents/`
for contributor-agent conventions, and `docs/assets/` for editable diagrams.
`docs/README.md` is the navigation entry point. The canonical backend guide
stays at `docs/backend-campaigns.md`, preserving existing contract links.

Executable examples live in `examples/`, outside runtime implementation.
The README presents verified capabilities and links to source and deeper
reference material. Version numbers remain in the plugin manifests rather
than being copied into the README.

This changes presentation and distribution naming; it preserves ADR 0009's
ownership and campaign contract.
