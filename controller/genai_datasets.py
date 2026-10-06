"""Dataset viewer metadata from the records that are actually stored locally.

This module does not contact the Hub or invent train/validation partitions.
The same selection functions serve the viewer and evaluation launch controls.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re


def _object(value):
    return value if isinstance(value, dict) else {}


def _partition(record: dict, meta: dict) -> tuple[str, str]:
    tags, source = _object(record.get("tags")), _object(record.get("source"))
    origin = _object(meta.get("source"))
    subset = tags.get("subset") or tags.get("subsets") or tags.get("config") or source.get("config") or source.get("subset") or origin.get("config") or "default"
    split = tags.get("split") or source.get("split") or origin.get("split")
    if not split:
        stem = Path(str(source.get("path") or origin.get("path") or "")).stem
        # A file called meta-test is a real available partition, not a train/test
        # division of our own. Other names remain an unpartitioned local corpus.
        match = re.fullmatch(r"(?:meta-)?(?:train|test|validation|dev|valid)(?:[-_]\d+)?", stem, re.I)
        split = stem if match else "local"
    return str(subset), str(split)


def select_records(records: list[dict], meta: dict, subset: str = "", split: str = "") -> list[dict]:
    partitions = [_partition(record, meta) for record in records]
    if subset and subset not in {item[0] for item in partitions}:
        raise ValueError(f"Unknown dataset subset {subset!r}")
    selected = [(record, partition) for record, partition in zip(records, partitions) if not subset or partition[0] == subset]
    if split and split not in {partition[1] for _, partition in selected}:
        raise ValueError(f"Unknown dataset split {split!r} for subset {subset or 'all'!r}")
    return [record for record, partition in selected if not split or partition[1] == split]


def _type(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int64"
    if isinstance(value, float):
        return "float64"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        if value and all(isinstance(item, dict) and ("role" in item or "from" in item) and ("content" in item or "value" in item) for item in value):
            return "messages"
        return "list"
    if isinstance(value, dict):
        if value.get("_type") in ("Image", "Audio", "Video"):
            return str(value["_type"]).lower()
        if "sampling_rate" in value and ("array" in value or "path" in value or "src" in value):
            return "audio"
        if "src" in value and "width" in value and "height" in value:
            return "image"
        return "struct"
    return "string"


def _statistics(values: list, total: int, dtype: str) -> dict:
    stats = {"count": len(values), "missing": total - len(values), "histogram": [], "categories": []}
    measures = [len(value) for value in values] if dtype == "string" else [value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)] if dtype in ("int64", "float64") else []
    if measures:
        low, high = min(measures), max(measures)
        stats.update(min=low, max=high)
        histogram = [0] * 12
        for value in measures:
            index = min(11, int((value - low) / (high - low) * 12)) if high != low else 0
            histogram[index] += 1
        stats["histogram"] = histogram
    if dtype in ("string", "bool", "int64"):
        categories = Counter(str(value) for value in values)
        if len(categories) <= 20:
            stats["categories"] = [{"label": label, "count": count} for label, count in categories.most_common(8)]
    return stats


def viewer_metadata(records: list[dict], meta: dict, subset: str = "", split: str = "") -> dict:
    selected = select_records(records, meta, subset, split)
    partitions = Counter(_partition(record, meta) for record in records)
    subsets = [{"name": name, "rows": sum(count for (config, _), count in partitions.items() if config == name),
                "splits": [{"name": partition, "rows": count} for (config, partition), count in sorted(partitions.items()) if config == name]}
               for name in sorted({config for config, _ in partitions})]
    splits = Counter()
    for (config, partition), count in partitions.items():
        if not subset or config == subset:
            splits[partition] += count
    columns = []
    for group in ("inputs", "expectations", "tags"):
        keys = sorted({key for record in selected for key in _object(record.get(group))})
        for key in keys:
            values = [_object(record.get(group)).get(key) for record in selected if _object(record.get(group)).get(key) is not None]
            types = {_type(value) for value in values}
            dtype = next(iter(types)) if len(types) == 1 else "float64" if types == {"int64", "float64"} else "mixed" if types else "null"
            columns.append({"key": f"{group}.{key}", "label": key, "group": group, "type": dtype, "stats": _statistics(values, len(selected), dtype)})
    keys = {column["label"].lower() for column in columns}
    kind = "Preference pairs" if {"chosen", "rejected"} <= keys else "Conversation" if any(column["type"] == "messages" for column in columns) else "Code / formal specification" if keys & {"code", "puzzle", "solution", "spec", "problem"} else "Question answering" if keys & {"question", "answer", "expected_answer"} else "Text / tabular"
    return {"subsets": subsets, "splits": [{"name": name, "rows": count} for name, count in sorted(splits.items())],
            "selected_subset": subset, "selected_split": split, "rows": len(selected), "total_rows": len(records),
            "kind": kind, "columns": columns,
            "note": "Available subsets and splits come from the stored dataset. Local means no training split is declared."}
