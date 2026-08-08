# Plan: move unity-hpc's `scripts/` to the plugin-root `bin/`

While a plugin is enabled, Claude Code adds its root-level `bin/` to the PATH of
the Bash tool. A move to `bin/` therefore makes `hpc-status`, `hpc-usage` and the
rest directly runnable. Today they need the full
`${CLAUDE_PLUGIN_ROOT}/scripts/hpc-status`.

Status: **planned, not applied.** It describes the tree at `0.10.0`.

---

## 1. Why this is mechanically safe

`bin/` and `scripts/` sit at **the same depth**. Both are one level below the
plugin root. Every self-relative resolver is therefore unchanged:

| Resolver | In `scripts/` | In `bin/` |
|---|---|---|
| `sys.path.insert(0, Path(__file__).resolve().parent.parent)` (`hpc-scaffold`, `hpc-config-write`, `hpc-retention-gate`, `hpc-usage`) | plugin root | plugin root |
| `PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"` (`hpc-dashboard`) | plugin root | plugin root |

This is a **rename, not a re-rooting.** That is exactly why you can do it without
touching any path logic inside the scripts.

All 13 scripts are already executable (`-rwxr-xr-x`), and each one carries a
shebang: `#!/usr/bin/env bash` or `python3`. They are therefore valid PATH entries
as they are. No permission work and no wrapper work is necessary.

## 2. The one real trap

`cluster-intel/sync-telemetry.sh:11` reaches across directories:

```bash
GATE="$HERE/../scripts/hpc-retention-gate"
```

A grep finds **only this one** internal cross-directory reference to a script. No
script calls a sibling script.

This line must change to `../bin/` in the same commit as the move, or telemetry
sync loses its retention gate. That script gates `--delete`, so a silent break here
risks a prune of telemetry days that were not fully summarised.

## 3. Complete change inventory

Everything that names `scripts/`, grouped by whether it must change.

**Must change — code and tests (8 sites):**

| File | Change |
|---|---|
| `cluster-intel/sync-telemetry.sh:11` | `../scripts/` → `../bin/` |
| `tests/test_cli.py:6` | `REPO_ROOT / "scripts"` → `"bin"` |
| `tests/test_end_to_end.py:6` | the same |
| `tests/test_cluster_config_write.py:14` | the same |
| `tests/test_retention.py:9` | the same |
| `tests/test_sync_telemetry.py:138` | `SCAN_DIRS` — `"scripts"` → `"bin"` |
| `tests/test_reader_cutover.py:114` | `scan_dirs` — `"scripts"` → `"bin"` |
| `tests/test_no_stale_references.py:4` | `SEARCHED` — `"scripts"` → `"bin"` |

**Must change — skills (2 invocations):**

| File | Change |
|---|---|
| `skills/setup/SKILL.md` | `${CLAUDE_PLUGIN_ROOT}/scripts/hpc-scaffold` → `/bin/` |
| `skills/recon/SKILL.md` | `${CLAUDE_PLUGIN_ROOT}/scripts/hpc-config-write` → `/bin/` |

**Prose mentions — update for accuracy (2 files):**
`skills/log-result/SKILL.md` and `README.md`.

**Already correct:** `tests/test_shipping_safety.py:19` holds
`CODE_DIRS = ("lib", "scripts", "mcp", "bin", "tests")`. It already scans both
directories, so the marketplace guard needs no edit, and it keeps covering the
scripts throughout the transition.

## 4. Decision: a skill keeps the explicit path

The tempting simplification is to let a skill call bare `hpc-scaffold`, and rely on
the injected PATH. **Do not — at least not in this change.**

- PATH injection applies to the Bash tool only while the plugin is *enabled*. A
  bare name depends on that in silence. An explicit path never does.
- The tests call these scripts by absolute path. A bare-name skill is therefore
  **untested**: it passes CI, and fails only at runtime.
- A `--plugin-dir` session, a disabled-plugin state, and a non-Bash caller all keep
  working with an explicit path.

So: move the files to `bin/`, and keep each skill on
`${CLAUDE_PLUGIN_ROOT}/bin/...`. The PATH convenience then becomes a **bonus for the
human at a terminal**, not a dependency of the plugin's own machinery. That is what
makes this change "nothing breaks" rather than "probably fine".

A later phase can switch the skills to bare names, *after* somebody checks that
injection works in practice. That phase must also add a guard test that asserts
each `bin/` entry is executable and carries a shebang.

## 5. Scope: move all 13, or split them?

**Recommended: move all 13, and delete `scripts/`.** That gives one location, no
per-script judgment call, and the `hpc-` prefix already namespaces them against a
PATH collision.

The alternative is `bin/` for user-facing commands and `scripts/` for internal
helpers, that is `hpc-scaffold`, `hpc-config-write` and `hpc-retention-gate`. It is
more principled in Unix terms, but it adds a second location and a "which one is
this?" decision for every future script. At 13 files, that cost is not worth it.

## 6. Staging

Two commits, each one green:

```
1. refactor(unity-hpc): move scripts/ to bin/ for PATH exposure
   git mv scripts bin  +  sync-telemetry.sh  +  8 test sites  +  2 skill invocations
2. docs(unity-hpc): update script paths for bin/
   prose mentions in README and the log-result skill
```

Commit 1 must be atomic. A split between the `git mv` and the `sync-telemetry.sh`
edit leaves a commit where telemetry sync is broken.

Raise `plugin.json` to **0.11.0** with commit 1. That is a minor bump: the
user-visible surface gains commands, and loses none.

Then follow `docs/marketplace.md`: run `claude plugin marketplace update`, run
`claude plugin update unity-hpc@phd-agentic-tools --scope local` in each of the two
projects, and restart.

## 7. Verification

```bash
pytest                                   # expect the suite to pass, unchanged
grep -rn 'scripts/hpc-' . --include='*.sh' --include='*.py' --include='*.md'
                                         # expect: no hits
ls -l bin | head       # all 13, still executable
claude plugin validate . --strict
```

Then, in a restarted session with the plugin enabled, check the payoff:

```bash
which hpc-status && hpc-status --help
```

If `which` finds nothing, the move is still correct, and every skill still works,
because the skills use explicit paths. Only the convenience is absent. That is the
designed failure mode: **the worst case is no benefit, not a broken plugin.**

## 8. Residual risks

| Risk | Assessment |
|---|---|
| A PATH collision with an existing `hpc-*` binary | Low — the prefix is distinctive. If it happens, the user's own PATH entry wins or loses by order. The skills are unaffected, because they use explicit paths. |
| All 13 become user-visible, including the internal helpers | Cosmetic. `hpc-retention-gate` on PATH is harmless. |
| An older Claude Code does not honor `bin/` | It degrades to "no PATH convenience". Explicit paths still work. |
| The telemetry retention gate is missed in silence | This is the real one. Two things reduce it: §2 is atomic with the move, and `test_sync_telemetry.py` covers the gate. |
