#!/usr/bin/env python3
"""Schema adapter and Arrow cache for the llms-agents train lane.

``format=native`` writes each source line unchanged.
``format=sharegpt`` writes ShareGPT JSONL (or ChatML when style is chatml).
``format=preference`` writes prompt, chosen, rejected JSONL.

The workflow file names the adapter. This module does not read a project slug.
Tokenized text is stored once under ``$REMOTE_DIR/_cache/llms-agents/``.
Later nodes read that shard and do not convert the source again.

Secrets stay in ``unityHPC/.env``. This module refuses to copy that file
into the cache or the checkpoint directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import sys
import time
from pathlib import Path

# Arrow IPC stream pieces for one nullable Utf8 column named "text".
# The schema message is constant. The record-batch metadata is the same
# shape for every shard; only the length fields change. pyarrow.ipc.open_stream
# reads the result.
_SCHEMA_MSG = bytes.fromhex(
    "ffffffff700000001000000000000a000c000600050008000a000000000104000c00"
    "00000800080000000400080000000400000001000000140000001000140008000600"
    "07000c00000010001000000000000105100000001c00000004000000000000000400"
    "000074657874000000000400040004000000"
)
_RB_META = bytearray.fromhex(
    "14000000000000000c0016000600050008000c000c0000000003040018000000"
    "200000000000000000000a0018000c00040008000a0000004c00000010000000"
    "0200000000000000000000000300000000000000000000000000000000000000"
    "00000000000000000c0000000000000010000000000000000a00000000000000"
    "000000000100000002000000000000000000000000000000"
)


def _align8(n: int) -> int:
    return (n + 7) & ~7


def write_arrow_stream(path: Path, texts: list[str]) -> None:
    """Write an Arrow IPC stream with one Utf8 column named ``text``."""
    raw = [text.encode("utf-8") for text in texts]
    blob = b"".join(raw)
    offsets = [0]
    for item in raw:
        offsets.append(offsets[-1] + len(item))
    off_bytes = b"".join(struct.pack("<i", n) for n in offsets)
    off_len = len(off_bytes)
    data_off = _align8(off_len)
    data_len = len(blob)
    body = off_bytes + b"\x00" * (data_off - off_len)
    body += blob + b"\x00" * (_align8(data_len) - data_len)
    meta = bytearray(_RB_META)
    struct.pack_into("<q", meta, 32, len(body))
    struct.pack_into("<q", meta, 64, len(texts))
    struct.pack_into("<q", meta, 104, off_len)
    struct.pack_into("<q", meta, 112, data_off)
    struct.pack_into("<q", meta, 120, data_len)
    struct.pack_into("<q", meta, 136, len(texts))
    payload = bytearray(_SCHEMA_MSG)
    payload += b"\xff\xff\xff\xff"
    payload += struct.pack("<i", len(meta))
    payload += meta
    payload += body
    payload += b"\xff\xff\xff\xff\x00\x00\x00\x00"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def refuse_secret(path: Path) -> None:
    """Refuse a secrets file. The template never copies ``.env``."""
    if path.name == ".env" or path.name.endswith(".env"):
        raise ValueError(f"refusing to copy secrets file {path} into the cache or checkpoint")


DEFAULT_QA_SCHEMA = {
    "context_field": "theory",
    "questions_field": "questions",
    "question_key": "question",
    "answer_key": "answer",
    "rejected_field": "rejected",
    "style": "sharegpt",
}


def _lookup(obj: dict, field: str):
    cur = obj
    for part in field.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _qa_pairs(obj: dict, schema: dict) -> list[tuple[str, str, str]]:
    """Return (prompt, chosen, rejected) rows for one JSON object."""
    context = _lookup(obj, schema.get("context_field", "theory")) or ""
    rejected = _lookup(obj, schema.get("rejected_field", "rejected")) or ""
    questions = _lookup(obj, schema.get("questions_field", "questions"))
    qkey = schema.get("question_key", "question")
    akey = schema.get("answer_key", "answer")
    pairs: list[tuple[str, str, str]] = []
    if isinstance(questions, dict):
        for item in questions.values():
            if not isinstance(item, dict):
                continue
            question = str(item.get(qkey) or "")
            answer = str(item.get(akey) or "")
            prompt = f"{context}\n\n{question}".strip() if context else question
            pairs.append((prompt, answer, str(rejected or "")))
    elif isinstance(questions, list):
        for item in questions:
            if not isinstance(item, dict):
                continue
            question = str(item.get(qkey) or "")
            answer = str(item.get(akey) or "")
            prompt = f"{context}\n\n{question}".strip() if context else question
            pairs.append((prompt, answer, str(item.get("rejected") or rejected or "")))
    elif "prompt" in obj and "chosen" in obj:
        pairs.append((str(obj["prompt"]), str(obj["chosen"]), str(obj.get("rejected") or "")))
    elif context:
        pairs.append((str(context), "", str(rejected or "")))
    return pairs


def _sharegpt(prompt: str, answer: str, *, style: str) -> dict:
    if style == "chatml":
        return {
            "messages": [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": answer},
            ]
        }
    return {
        "conversations": [
            {"from": "human", "value": prompt},
            {"from": "gpt", "value": answer},
        ]
    }


def convert_line(
    line: str,
    fmt: str,
    *,
    adapter: str = "qa-object",
    schema: dict | None = None,
) -> str:
    """Convert one JSONL record. ``native`` returns the line unchanged."""
    text = line.rstrip("\n")
    if fmt in ("native", "identity", ""):
        return text
    if adapter in ("identity", "native"):
        return text
    if not text.strip():
        return text
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError("source line is not a JSON object") from None
    if not isinstance(obj, dict):
        raise ValueError("source line is not a JSON object")
    spec = dict(DEFAULT_QA_SCHEMA)
    if schema:
        spec.update(schema)
    if fmt == "sharegpt":
        rows = []
        for prompt, answer, _rejected in _qa_pairs(obj, spec):
            rows.append(json.dumps(_sharegpt(prompt, answer, style=spec.get("style") or "sharegpt"), ensure_ascii=False))
        return "\n".join(rows)
    if fmt == "preference":
        rows = []
        for prompt, chosen, rejected in _qa_pairs(obj, spec):
            rows.append(json.dumps(
                {"prompt": prompt, "chosen": chosen, "rejected": rejected},
                ensure_ascii=False,
            ))
        return "\n".join(rows)
    raise ValueError(f"unknown format {fmt!r}; expected native, sharegpt, or preference")


def cache_dir(remote_dir: Path | str, digest: str) -> Path:
    return Path(remote_dir) / "_cache" / "llms-agents" / digest


def prepare(
    source: Path,
    remote_dir: Path | str,
    *,
    fmt: str,
    adapter: str = "qa-object",
    schema: dict | None = None,
) -> Path:
    """Convert ``source`` and write the JSONL plus the Arrow shard once."""
    refuse_secret(source)
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()[:16]
    dest = cache_dir(remote_dir, f"{fmt}-{digest}")
    marker = dest / "READY"
    if marker.is_file() and (dest / "shard.jsonl").is_file() and (dest / "shard.arrow").is_file():
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    texts: list[str] = []
    lines_out: list[str] = []
    for line in raw.decode("utf-8").splitlines():
        converted = convert_line(line, fmt, adapter=adapter, schema=schema)
        if not converted:
            continue
        for row in converted.split("\n"):
            lines_out.append(row)
            if fmt == "native":
                texts.append(row)
            else:
                try:
                    obj = json.loads(row)
                except json.JSONDecodeError:
                    texts.append(row)
                else:
                    texts.append(json.dumps(obj, ensure_ascii=False, sort_keys=True))
    (dest / "shard.jsonl").write_text("".join(f"{row}\n" for row in lines_out), encoding="utf-8")
    write_arrow_stream(dest / "shard.arrow", texts)
    (dest / "manifest.json").write_text(json.dumps({
        "format": fmt,
        "adapter": adapter,
        "records": len(lines_out),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
    }, indent=2) + "\n", encoding="utf-8")
    marker.write_text("ok\n", encoding="utf-8")
    return dest


def _rank() -> int:
    for key in ("RANK", "SLURM_PROCID", "SLURM_NODEID"):
        raw = os.environ.get(key)
        if raw is not None and raw != "":
            return int(raw)
    return 0


def consolidate(dest: Path, shards: Path) -> None:
    """Rank 0 writes a Hugging Face directory. Other ranks wait, then return.

    A parameter-efficient run (a PEFT ``adapter_config.json``) is merged into
    the base weights. A full-weight shard directory is copied. ``.env`` is
    never copied.
    """
    dest = dest.resolve()
    shards = shards.resolve()
    ready = dest / "READY"
    rank = _rank()
    if rank != 0:
        for _ in range(600):
            if ready.is_file():
                return
            time.sleep(2)
        raise SystemExit(f"rank {rank} waited and {ready} was not written")

    dest.mkdir(parents=True, exist_ok=True)
    adapter = None
    for candidate in (shards, shards.parent):
        if (candidate / "adapter_config.json").is_file():
            adapter = candidate
            break
    if adapter is not None:
        from peft import AutoPeftModelForCausalLM
        from transformers import AutoTokenizer
        model = AutoPeftModelForCausalLM.from_pretrained(str(adapter))
        merged = model.merge_and_unload()
        merged.save_pretrained(dest)
        AutoTokenizer.from_pretrained(str(adapter)).save_pretrained(dest)
    elif shards.is_dir():
        for item in shards.iterdir():
            refuse_secret(item)
            target = dest / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".env"))
            else:
                shutil.copy2(item, target)
    ready.write_text("ok\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prep.py")
    sub = parser.add_subparsers(dest="cmd", required=True)

    convert = sub.add_parser("convert")
    convert.add_argument("--input", required=True, type=Path)
    convert.add_argument("--format", required=True, choices=("native", "sharegpt", "preference"))
    convert.add_argument("--adapter", default="qa-object")
    convert.add_argument("--schema", default="", help="JSON object of adapter fields")
    convert.add_argument("--remote-dir", required=True, type=Path)

    merge = sub.add_parser("consolidate")
    merge.add_argument("--dest", required=True, type=Path)
    merge.add_argument("--shards", required=True, type=Path)

    args = parser.parse_args(argv)
    if args.cmd == "convert":
        schema = json.loads(args.schema) if args.schema else None
        dest = prepare(
            args.input, args.remote_dir, fmt=args.format, adapter=args.adapter, schema=schema,
        )
        print(dest)
        return 0
    consolidate(args.dest, args.shards)
    print(args.dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
