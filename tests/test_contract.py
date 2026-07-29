"""Skills may only promise what the plugin actually implements.

Every documented defect in the v0.6.0 field reports was one instance of the
same failure: a skill told the agent to run `run.sh fetch`, or to read a
"monitor PID", against a dispatcher that had neither. Nothing caught it because
prose and code were never checked against each other.

These tests are that check. They are deliberately structural — they will fail
the moment a skill references a subcommand, MCP tool, or file the plugin does
not provide, whichever side changes first.
"""

import re

import pytest
from pathlib import Path

from lib import campaign

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_SH = REPO_ROOT / "templates" / "scaffold" / "common" / "run.sh"
SERVER = REPO_ROOT / "mcp" / "hpc_server.py"
SKILLS = sorted((REPO_ROOT / "skills").glob("*/SKILL.md"))


def _dispatcher_subcommands() -> set[str]:
    """The subcommands run.sh's case statement actually handles."""
    text = RUN_SH.read_text()
    body = text.split("case \"${1:-}\" in", 1)[1]
    found = set()
    for line in body.splitlines():
        m = re.match(r"\s*([a-z|]+)\)", line)
        if m:
            found.update(m.group(1).split("|"))
    return found


def _registered_tools() -> set[str]:
    return set(re.findall(r'name="(unity_\w+)"', SERVER.read_text()))


def _dispatched_tools() -> set[str]:
    return set(re.findall(r'name == "(unity_\w+)"', SERVER.read_text()))


def test_skills_exist():
    assert SKILLS, "no skills found — the glob is wrong"


def test_every_run_sh_subcommand_a_skill_calls_exists():
    known = _dispatcher_subcommands()
    offenders = []
    for skill in SKILLS:
        for sub in re.findall(r"run\.sh\s+([a-z][a-z-]*)", skill.read_text()):
            if sub not in known:
                offenders.append(f"{skill.parent.name}: run.sh {sub}")
    assert not offenders, (
        f"skills call subcommands run.sh does not implement: {offenders}. "
        f"run.sh handles: {sorted(known)}"
    )


def test_every_mcp_tool_a_skill_calls_is_registered():
    known = _registered_tools()
    offenders = []
    for skill in SKILLS:
        for tool in re.findall(r"mcp__unity-hpc__(\w+)", skill.read_text()):
            if tool not in known:
                offenders.append(f"{skill.parent.name}: {tool}")
    assert not offenders, (
        f"skills call MCP tools that are not registered: {offenders}. "
        f"registered: {sorted(known)}"
    )


def test_every_registered_tool_is_dispatched():
    """A tool advertised in list_tools but missing from _dispatch answers
    'Unknown tool' at runtime — a silent contract break."""
    missing = _registered_tools() - _dispatched_tools()
    assert not missing, f"registered but never dispatched: {sorted(missing)}"


def test_no_skill_promises_a_background_monitor():
    """v0.6.0 has no monitor process: nothing auto-fetches, auto-requeues, or
    holds a PID. Skills that claim otherwise send agents chasing state that
    will never exist."""
    banned = ("monitor PID", "auto-fetch", "auto-requeue", "monitor log",
              "automatically requeue", "monitor will")
    offenders = []
    for skill in SKILLS:
        text = skill.read_text().lower()
        for phrase in banned:
            if phrase.lower() in text:
                offenders.append(f"{skill.parent.name}: {phrase!r}")
    assert not offenders, f"skills describe a monitor that does not exist: {offenders}"


def test_no_skill_references_the_retired_cluster_profile_file():
    """cluster-profile.md was retired by the v0.6.0 migration; the profile is
    now cluster-config.json, read through unity_cluster_profile."""
    offenders = [s.parent.name for s in SKILLS if "cluster-profile.md" in s.read_text()]
    assert not offenders, f"skills still point at cluster-profile.md: {offenders}"


# ─── dispatcher/library ledger contract ──────────────────────────────────────

def test_run_sh_embeds_the_canonical_schema_verbatim():
    """run.sh cannot import lib/campaign.py — it must survive a plugin upgrade
    that moves the plugin directory — so it inlines the schema. If the two ever
    drift, the dispatcher writes a table the readers cannot read."""
    assert campaign.SCHEMA in RUN_SH.read_text(), (
        "lib/campaign.py SCHEMA is not embedded verbatim in run.sh"
    )


def test_run_sh_knows_every_terminal_state():
    text = RUN_SH.read_text()
    missing = [s for s in campaign.TERMINAL if f'"{s}"' not in text]
    assert not missing, f"run.sh's TERMINAL set is missing: {sorted(missing)}"


def test_sync_excludes_the_ledger():
    """The ledger is local bookkeeping; pushing it to the cluster would let a
    second machine's rsync clobber it."""
    sync = (REPO_ROOT / "templates" / "scaffold" / "common" / "sync.sh").read_text()
    assert "--exclude '.unity_state/'" in sync


# ─── the core must stay domain-agnostic ──────────────────────────────────────

#: Metric names belonging to one project's workflow, not to SLURM or to this
#: plugin. Two field reports hit these: a CPU project shown ML-training columns
#: it never printed.
_DOMAIN_METRICS = ("val_bpb", "mfu_percent", "peak_vram_mb", "training_seconds",
                   "total_tokens_M", "num_params_M", "memory_gb")

#: Where a domain metric may legitimately appear as an example.
_EXAMPLE_FILES = {"lib/metrics.py", "skills/setup/SKILL.md", "skills/fetch/SKILL.md",
                  "skills/log-result/SKILL.md", "README.md"}


def _core_files():
    for top in ("mcp", "lib"):
        for path in (REPO_ROOT / top).rglob("*.py"):
            if "__pycache__" not in path.parts:
                yield path


def test_no_domain_metric_is_hardcoded_in_the_core():
    """A project declares its metrics in unityHPC/metrics.json. The plugin core
    must not know any metric by name — that is what made results wrong for
    every non-ML project."""
    offenders = []
    for path in _core_files():
        rel = str(path.relative_to(REPO_ROOT))
        if rel in _EXAMPLE_FILES:
            continue
        text = path.read_text(errors="replace")
        for metric in _DOMAIN_METRICS:
            if metric in text:
                offenders.append(f"{rel}: {metric}")
    assert not offenders, (
        f"domain metrics hardcoded in the plugin core: {offenders}. "
        f"Projects declare metrics in unityHPC/metrics.json instead."
    )


def test_metric_examples_are_confined_to_documentation():
    """lib/metrics.py may show an example in its docstring, but must not branch
    on one."""
    source = (REPO_ROOT / "lib" / "metrics.py").read_text()
    body = source.split('"""', 2)[-1]
    offenders = [m for m in _DOMAIN_METRICS if m in body]
    assert not offenders, f"lib/metrics.py acts on specific metrics: {offenders}"


def test_doctor_is_reachable_from_a_skill():
    """A staleness detector nobody is told to run does not help anyone."""
    mentions = [s.parent.name for s in SKILLS if "unity_doctor" in s.read_text()]
    assert mentions, "no skill tells the agent to run unity_doctor"


@pytest.mark.parametrize("ptype", ["cpu", "gpu", "ml"])
def test_every_job_template_honours_the_variables_render_exports(ptype):
    """run.sh exports MODULES and VENV_PATH for every project type. A template
    that ignores one leaves the variable documented, exported, and inert -- the
    cpu template silently dropped MODULES."""
    body = (REPO_ROOT / "templates" / "scaffold" / ptype / "job_template.sh").read_text()
    assert "module load" in body, f"{ptype} ignores MODULES"
    assert "VENV_PATH" in body, f"{ptype} ignores VENV_PATH"


@pytest.mark.parametrize("ptype", ["cpu", "gpu", "ml"])
def test_documented_env_keys_are_actually_consumed(ptype):
    """Anything env.example advertises must be read by run.sh or the template."""
    import re
    env = (REPO_ROOT / "templates" / "scaffold" / ptype / "env.example").read_text()
    body = (REPO_ROOT / "templates" / "scaffold" / ptype / "job_template.sh").read_text()
    runner = RUN_SH.read_text()
    declared = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", env, re.M))
    ignored = {k for k in declared if k not in body and k not in runner}
    assert not ignored, f"{ptype}/env.example advertises unused keys: {sorted(ignored)}"


def test_everything_render_bakes_in_can_be_overridden():
    """A variable render() writes into the job script but the override list
    omits cannot be set for a single run. MODULES was in exactly that state: a
    caller passing MODULES=gcc silently got .env's empty value, which is
    indistinguishable from a broken module system on the node."""
    import re
    text = RUN_SH.read_text()
    exported = set(re.findall(r"printf 'export ([A-Z_]+)=%q", text))
    block = text.split("UNITY_OVERRIDABLE=", 1)[1].split('"', 2)[1]
    overridable = set(block.split())
    # EXP is the subcommand argument, not an .env setting
    missing = exported - overridable - {"EXP"}
    assert not missing, f"exported into the job but not overridable: {sorted(missing)}"
