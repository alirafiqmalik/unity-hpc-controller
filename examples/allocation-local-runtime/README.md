# An allocation-local runtime

This example stages a large pinned runtime (a Lean toolchain and a source tree)
on the local disk of a compute node, inside a campaign task.
The controller does not import or run it. A project copies these files into its
own bundle, pins them, and calls them from its task command.

- `node_runtime.py` checks the node's local disk, verifies both archives,
  extracts them into a private directory, checks every file, and writes the
  staging evidence to `HPC_OUTPUT_DIR`. `--cleanup-root` removes only a
  directory that this allocation owns.
- `runtime_integrity.py` verifies a tree against its frozen file manifest.

The procedure and its rules are in
[backend operations](../../docs/backend-campaigns.md).
