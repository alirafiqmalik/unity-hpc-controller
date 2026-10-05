"""Read a project's declared experiments and launch only fixed catalog entries.

The catalog belongs to the attached project. It describes resource needs and
fixed launch arguments; HTTP callers cannot add shell arguments or overrides.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from controller import dispatch, events, registry

_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_MAX_BYTES = 1024 * 1024
_STATUSES = {"ready", "needs_input", "historical"}


class CatalogError(ValueError):
    """Malformed catalog or unsupported launch request."""


def _entries(project: dict) -> list[dict]:
    root = Path(project["path"]).resolve()
    path = (root / "unityHPC" / "experiments.json").resolve()
    if not path.is_relative_to(root):
        raise CatalogError("experiments.json must stay inside the project")
    if not path.is_file():
        return []
    if path.stat().st_size > _MAX_BYTES:
        raise CatalogError("experiments.json exceeds 1 MiB")
    try:
        data = json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"cannot read experiments.json: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise CatalogError("experiments.json requires schema_version 1")
    entries = data.get("experiments")
    if not isinstance(entries, list) or len(entries) > 500:
        raise CatalogError("experiments must be a list of at most 500 entries")
    ids: set[str] = set()
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not _ID.fullmatch(item["id"]):
            raise CatalogError("each experiment needs a URL-safe id")
        if item["id"] in ids:
            raise CatalogError(f"duplicate experiment id {item['id']!r}")
        ids.add(item["id"])
        if item.get("status", "historical") not in _STATUSES:
            raise CatalogError(f"invalid status for experiment {item['id']!r}")
        if any(key in item and not isinstance(item[key], str)
               for key in ("title", "description")):
            raise CatalogError(f"title and description must be text for {item['id']!r}")
        if not isinstance(item.get("resources", {}), dict):
            raise CatalogError(f"resources must be an object for {item['id']!r}")
        if "launch" in item and not isinstance(item["launch"], dict):
            raise CatalogError(f"launch must be an object for {item['id']!r}")
    return entries


def read(slug: str) -> dict:
    project = registry.get(slug)
    if project is None:
        raise CatalogError(f"unknown project {slug!r}")
    try:
        return {"experiments": _entries(project), "experiments_error": None}
    except CatalogError as exc:
        return {"experiments": [], "experiments_error": str(exc)}


def launch(slug: str, experiment_id: str, dry_run: bool = False) -> dict:
    project = registry.get(slug)
    if project is None:
        raise CatalogError(f"unknown project {slug!r}")
    entry = next((one for one in _entries(project) if one["id"] == experiment_id), None)
    if entry is None:
        raise CatalogError(f"unknown experiment {experiment_id!r}")
    status = entry.get("status", "historical")
    if status == "historical" or (status != "ready" and not dry_run):
        raise CatalogError(f"experiment {experiment_id!r} is {status}; live dispatch is unavailable")
    plan = entry.get("launch")
    if not isinstance(plan, dict):
        raise CatalogError(f"experiment {experiment_id!r} has no launch plan")
    kind = plan.get("kind")
    if kind == "run":
        exp = plan.get("exp")
        if not isinstance(exp, str):
            raise CatalogError("run launch requires exp")
        if "campaign" in plan and not isinstance(plan["campaign"], str):
            raise CatalogError("run launch campaign must be text")
        overrides = plan.get("overrides", {})
        if not isinstance(overrides, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                                   for k, v in overrides.items()):
            raise CatalogError("run launch overrides must map strings to strings")
        result = dispatch.run(slug, exp, campaign=plan.get("campaign"),
                              dry_run=dry_run, overrides=overrides)
    elif kind == "script":
        result = dispatch.catalog_script(
            project, path=plan.get("path"), args=plan.get("args", []),
            dry_run_arg=plan.get("dry_run_arg"), dry_run=dry_run,
        )
        events.record("dry-run" if dry_run else "dispatch",
                      f"{slug} experiment {experiment_id}" + (" (dry-run)" if dry_run else ""),
                      slug=slug, exp=experiment_id, ok=result["ok"])
    else:
        raise CatalogError(f"unsupported launch kind {kind!r}")
    return result
