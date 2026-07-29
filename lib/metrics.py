"""Optional, per-project metric declaration.

The plugin serves every kind of SLURM job, so it must not know what a "good"
result looks like. But a project that *does* have a headline metric should not
have to re-explain it every time.

The resolution is a small file a project owns, `unityHPC/metrics.json`:

    {
      "primary": "val_bpb",
      "goal": "min",
      "report": ["val_bpb", "peak_vram_mb", "mfu_percent"],
      "labels": {"peak_vram_mb": "vram_mb"}
    }

Every field is optional and the file itself is optional. With no file, results
stay exactly as they are for a CPU simulation or a one-off script: whatever the
job printed, no ranking, no assumed columns. Nothing in the plugin core names a
domain metric.

Stdlib only; every load is fail-safe.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

FILENAME = "metrics.json"
GOALS = ("min", "max")


@dataclass(frozen=True)
class MetricSpec:
    """What a project has declared about its own numbers."""
    primary: str | None = None
    goal: str = "min"
    report: tuple[str, ...] = ()
    labels: dict[str, str] = field(default_factory=dict)

    def label(self, key: str) -> str:
        return self.labels.get(key, key)

    def is_better(self, candidate: float, incumbent: float) -> bool:
        return candidate < incumbent if self.goal == "min" else candidate > incumbent


def path(project_dir: Path) -> Path:
    return Path(project_dir) / "unityHPC" / FILENAME


def load(project_dir: Path) -> MetricSpec | None:
    """The project's declaration, or None if it has not made one."""
    spec, _ = load_with_error(project_dir)
    return spec


def load_with_error(project_dir: Path) -> tuple[MetricSpec | None, str | None]:
    """As `load`, plus a human-readable reason when a present file is unusable.

    A malformed declaration must never break results reporting — the job output
    is still real data. It degrades to the generic view and says why."""
    p = path(project_dir)
    if not p.exists():
        return None, None
    try:
        raw = json.loads(p.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        return None, f"{FILENAME} could not be read ({exc}); reporting all metrics."
    if not isinstance(raw, dict):
        return None, f"{FILENAME} must contain a JSON object; reporting all metrics."

    primary = raw.get("primary")
    if primary is not None and not isinstance(primary, str):
        return None, f"{FILENAME}: 'primary' must be a string; reporting all metrics."

    goal = raw.get("goal", "min")
    if goal not in GOALS:
        return None, (f"{FILENAME}: 'goal' must be one of {', '.join(GOALS)}; "
                      f"reporting all metrics.")

    report = raw.get("report", [])
    if not isinstance(report, list) or any(not isinstance(k, str) for k in report):
        return None, f"{FILENAME}: 'report' must be a list of strings; reporting all metrics."

    labels = raw.get("labels", {})
    if not isinstance(labels, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in labels.items()):
        labels = {}

    # A declared primary is implicitly reported, so a project cannot rank on a
    # column it never shows.
    ordered = list(dict.fromkeys(([primary] if primary else []) + list(report)))
    return MetricSpec(primary=primary, goal=goal, report=tuple(ordered),
                      labels=labels), None


def order_keys(spec: MetricSpec | None, discovered: list[str]) -> list[str]:
    """Declared keys first (in declared order), then anything else the jobs printed.

    Extra keys are appended rather than hidden: they are real output, and
    silently dropping them is how a report starts lying about what ran."""
    if spec is None or not spec.report:
        return list(discovered)
    present = [k for k in spec.report if k in discovered]
    return present + [k for k in discovered if k not in spec.report]


def missing_keys(spec: MetricSpec | None, discovered: list[str]) -> list[str]:
    """Declared keys no job actually printed — usually a failed or partial run."""
    if spec is None:
        return []
    return [k for k in spec.report if k not in discovered]


def best(spec: MetricSpec | None, rows: dict[str, dict]) -> tuple[str, float] | None:
    """(job, value) for the best primary metric, or None if not rankable."""
    if spec is None or not spec.primary:
        return None
    scored = [(name, m[spec.primary]) for name, m in sorted(rows.items())
              if isinstance(m.get(spec.primary), (int, float))]
    if not scored:
        return None
    winner = scored[0]
    for candidate in scored[1:]:
        if spec.is_better(candidate[1], winner[1]):
            winner = candidate
    return winner
