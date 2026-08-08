# Open follow-ups

This file lists known work that was deferred on purpose. Each entry names the
trigger that makes it live, so it surfaces at the right moment. Nobody has to
rediscover it.

When the work lands, delete its entry. This file holds open items only, not
history.

Moved here from the phd-agentic-tools marketplace when unity-hpc became a
standalone repository. Last reviewed 2026-08-08, against plugin version 0.11.0.

---

## Known gaps

| Gap | Detail | Cost of leaving it |
|---|---|---|
| **The dispatcher makes six untimed SSH calls.** | `templates/scaffold/common/run.sh` calls `ssh` at six sites with no `timeout`. The MCP server, `collector.sh` and `hpc-tmux` all wrap theirs. | A wedged login node hangs `run.sh` with no ceiling. This breaks the design rule in `ARCHITECTURE.md` §10. |
| **`agents/` sits outside every structural guard.** | `CODE_DIRS` in `tests/test_shipping_safety.py` covers `lib`, `scripts`, `mcp`, `bin` and `tests`. `SKILLS` in `test_contract.py` globs `skills/*/SKILL.md` only. | Two faults reached users through `agents/`: the author's real cluster paths, and instructions to write a retired file. Both were corrected on 2026-07-30, and nothing stops a third. |
| **No guard catches a new unquoted `ssh` interpolation.** | `hpc-tmux` was hardened by hand, and `tests/test_tmux.py` covers that one script. | A fourteenth script that interpolates a user value into an `ssh` remote-command string reproduces the fixed defect, and the suite stays green. A scanning guard is this repo's usual answer to "never again". |
| **The dashboard reads an archived snapshot.** | The historical panels in `cluster-intel/dashboard/` still read `$UNITY_HPC_DATA/archive/`. The live pipeline writes `summaries.db`. | Those panels show data that no longer updates. The dashboard README states this. |
| **`REPO_ROOT` is a misnomer in 20 test modules.** | Each module redeclares `REPO_ROOT = Path(__file__).resolve().parent.parent`. In the standalone repository the name is accurate again, but a shared `tests/paths.py` exporting `PLUGIN_ROOT` is still the cleaner shape. | Only a naming fault, with no behavior change. Do it on its own, because folding it into another change makes that diff unreviewable. |

## Planned, not started

| Item | Where |
|---|---|
| Move `scripts/` to the plugin-root `bin/`, so Claude Code puts the commands on PATH | `docs/bin-migration-plan.md` — a complete plan, with the change inventory, the one real trap, and the staging |
| Optional in-job `nvidia-smi` sampling, emitted into `task_runs` | It would recover part of the blind spot in `docs/design-decisions.md` §4, at the cost of touching the job template. Deferred, and not blocking |

## Release trap worth remembering

An install copies the working tree, not `git archive`. On the 0.10.0 release, 864K
of the 1.2M `tests/` directory was `__pycache__`. Clearing the caches before a
release cut the payload from **3.6M to 752K**.

Clear `__pycache__` before every release.
`tests/test_shipping_safety.py::test_release_tree_has_no_tracked_cache_files`
guards the tracked side of this.
