# A declared CPU result

This example uses Python's standard library and requests one CPU, 1 GiB of
memory, and five minutes. It writes `{"count": 5, "sum": 28}` to the required
`result.json` file inside `HPC_OUTPUT_DIR`.

From the repository root, with a configured controller and fresh catalog:

```bash
scripts/hpc-campaign plan examples/cpu-result/campaign.json
scripts/hpc-campaign submit examples/cpu-result/campaign.json
scripts/hpc-campaign watch cpu-result-example
scripts/hpc-campaign results cpu-result-example
```

`bundle.path` is resolved on the controller machine, relative to its working
directory when it is not absolute. Start the controller from the repository
root for this example. For a controller elsewhere, set an absolute bundle path
on that machine. The HTTP client does not upload a local directory.

The catalog selects a compatible CPU partition from backend policy. Adjust
that policy for your account before submitting. Repeating the same declaration
reuses its campaign identity; use a new `campaign_id` for a separate campaign.

To check the scientific command locally without a cluster:

```bash
example_output=$(mktemp -d)
HPC_OUTPUT_DIR="$example_output" python3 examples/cpu-result/task.py
cat "$example_output/result.json"
```

See [backend operations](../../docs/backend-campaigns.md) for result cursors,
artifact retrieval, dependencies, and GPU declarations.
