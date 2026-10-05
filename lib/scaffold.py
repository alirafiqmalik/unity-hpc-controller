"""Typed scaffold generator for the unity-hpc plugin.

Renders unityHPC/{run.sh,job_template.sh,sync.sh,.env} from plugin-owned
templates. Stdlib only — no runtime dependencies beyond the standard library.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

#: Replaced with the generating plugin's version when a template is rendered.
VERSION_PLACEHOLDER = "@@UNITY_HPC_VERSION@@"

TYPES: tuple[str, ...] = ("cpu", "gpu", "ml", "multi-cpu", "multi-gpu")
SCAFFOLD_FILES: tuple[str, ...] = ("run.sh", "job_template.sh", "sync.sh", ".env")

#: Workflow applications. `machine-learning` is reserved and has no runner.
APPLICATIONS: tuple[str, ...] = ("llms-agents", "machine-learning")
RUNNABLE_APPLICATIONS: frozenset[str] = frozenset({"llms-agents"})

#: files taken from templates/scaffold/common/ rather than the per-type dir
_COMMON_FILES = frozenset({"run.sh", "sync.sh"})

#: `--type` name -> templates/scaffold/ subdirectory. multi-cpu and multi-gpu
#: are fan-out orchestration on the same resource template as cpu/gpu; there is
#: no templates/scaffold/multi-*/ directory (spec §9).
_RESOURCE_DIR = {
    "cpu": "cpu",
    "gpu": "gpu",
    "ml": "ml",
    "multi-cpu": "cpu",
    "multi-gpu": "gpu",
}

#: on-disk template name for the rendered target name
_TEMPLATE_NAME = {".env": "env.example"}

#: where a displaced hand-written file is preserved
BACKUP_DIRNAME = ".pre-redesign"

#: files that become user data once written, and are never replaced afterwards
_USER_OWNED = frozenset({".env", "sync.sh", "fetch.sh"})


def plugin_root() -> Path:
    """The plugin install root. Falls back to the repo when run from source."""
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if root:
        return Path(root).expanduser()
    return Path(__file__).resolve().parent.parent


def template_root() -> Path:
    return plugin_root() / "templates" / "scaffold"


def plugin_version() -> str:
    """The version of the plugin doing the generating."""
    try:
        manifest = plugin_root() / ".claude-plugin" / "plugin.json"
        return json.loads(manifest.read_text()).get("version") or "unknown"
    except (OSError, ValueError, AttributeError):
        return "unknown"


def render(content: str) -> str:
    """Stamp a template with the version that produced it.

    Scaffold files are copies living in the project, so a plugin upgrade never
    reaches them. The stamp is what lets unity_doctor notice."""
    return content.replace(VERSION_PLACEHOLDER, plugin_version())


@dataclass(frozen=True)
class Action:
    kind: str                      # "create" | "replace" | "skip"
    path: Path
    content: str
    displaced_to: Path | None = None


def _template_path(ptype: str, target_name: str) -> Path:
    source_name = _TEMPLATE_NAME.get(target_name, target_name)
    subdir = "common" if target_name in _COMMON_FILES else _RESOURCE_DIR[ptype]
    return template_root() / subdir / source_name


def application_dir(application: str) -> Path:
    """The template directory for one application id."""
    if application not in APPLICATIONS:
        raise ValueError(
            f"unknown application {application!r}; expected one of {', '.join(APPLICATIONS)}"
        )
    return template_root() / "applications" / application


def _plan_pairs(project_dir: Path, pairs: list[tuple[Path, Path]]) -> list[Action]:
    """Turn (source, dest) pairs into create/skip/replace actions."""
    dest_dir = project_dir / "unityHPC"
    actions: list[Action] = []
    for source, dest in pairs:
        content = render(source.read_text(encoding="utf-8"))
        if not dest.exists():
            actions.append(Action(kind="create", path=dest, content=content))
            continue
        if dest.name in _USER_OWNED or dest.read_bytes() == content.encode():
            actions.append(Action(kind="skip", path=dest, content=content))
            continue
        rel = dest.relative_to(dest_dir)
        actions.append(Action(
            kind="replace",
            path=dest,
            content=content,
            displaced_to=dest_dir / BACKUP_DIRNAME / rel,
        ))
    return actions


def plan_application(project_dir: Path, application: str) -> list[Action]:
    """Install one application plus the common submitter and sync script.

    ``machine-learning`` is reserved. It has a README and no runner, so this
    raises instead of writing a job script.
    """
    if application not in APPLICATIONS:
        raise ValueError(
            f"unknown application {application!r}; expected one of {', '.join(APPLICATIONS)}"
        )
    if application not in RUNNABLE_APPLICATIONS:
        raise ValueError(
            f"application {application!r} is reserved and has no runner"
        )
    root = application_dir(application)
    dest_dir = project_dir / "unityHPC"
    pairs: list[tuple[Path, Path]] = []
    for name in ("run.sh", "sync.sh"):
        pairs.append((template_root() / "common" / name, dest_dir / name))
    for source in sorted(p for p in root.rglob("*") if p.is_file()):
        if "__pycache__" in source.parts or source.suffix == ".pyc":
            continue
        rel = source.relative_to(root)
        if source.name == "env.example" and source.parent == root:
            dest = dest_dir / ".env"
        else:
            dest = dest_dir / rel
        pairs.append((source, dest))
    return _plan_pairs(project_dir, pairs)


def plan(project_dir: Path, ptype: str) -> list[Action]:
    """Compute the actions needed to bring project_dir/unityHPC/ to canonical form.

    Does not touch the filesystem beyond reading.

    - absent          -> create
    - byte-identical  -> skip
    - user-owned      -> skip (environment and transfer adapters stay project-owned)
    - differing       -> replace, displacing the original to .pre-redesign/
    """
    if ptype not in TYPES:
        raise ValueError(f"unknown project type {ptype!r}; expected one of {', '.join(TYPES)}")

    dest_dir = project_dir / "unityHPC"
    actions: list[Action] = []
    for target_name in SCAFFOLD_FILES:
        content = render(_template_path(ptype, target_name).read_text())
        dest = dest_dir / target_name

        if not dest.exists():
            actions.append(Action(kind="create", path=dest, content=content))
            continue
        if target_name in _USER_OWNED or dest.read_bytes() == content.encode():
            actions.append(Action(kind="skip", path=dest, content=content))
            continue
        actions.append(Action(
            kind="replace",
            path=dest,
            content=content,
            displaced_to=dest_dir / BACKUP_DIRNAME / target_name,
        ))
    return actions


def _is_generated(data: bytes) -> bool:
    """True if we wrote this file — it carries our version stamp.

    A generated file is reproducible from the plugin, so displacing it needs no
    backup. Anything else is the user's and must never be lost."""
    return b"UNITY_SCAFFOLD_VERSION=" in data


def _free_backup_slot(preferred: Path) -> Path:
    """A backup path that does not already hold something else.

    `.pre-redesign/` was a single slot: a second upgrade overwrote the first
    backup, so two upgrades in a row could destroy a hand-written file the
    mechanism had promised to preserve. Backups are now append-only."""
    if not preferred.exists():
        return preferred
    for n in range(1, 1000):
        candidate = preferred.with_name(f"{preferred.name}.{n}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"no free backup slot beside {preferred}")


def apply(actions: list[Action]) -> list[str]:
    """Perform the planned actions. Returns report lines naming every change."""
    report: list[str] = []
    for action in actions:
        if action.kind == "skip":
            report.append(f"  skip     unityHPC/{action.path.name} (unchanged)")
            continue

        action.path.parent.mkdir(parents=True, exist_ok=True)
        if action.kind == "replace" and action.displaced_to is not None:
            original = action.path.read_bytes()
            if _is_generated(original):
                report.append(
                    f"  upgraded unityHPC/{action.path.name} "
                    f"(previous copy was generated; no backup needed)"
                )
            else:
                target = _free_backup_slot(action.displaced_to)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(original)
                report.append(
                    f"  moved    unityHPC/{action.path.name} -> "
                    f"unityHPC/{BACKUP_DIRNAME}/{target.name}"
                )
        action.path.write_text(action.content)
        verb = "created" if action.kind == "create" else "replaced"
        report.append(f"  {verb:<8} unityHPC/{action.path.name}")
        if action.path.suffix == ".sh":
            action.path.chmod(0o755)
    return report
