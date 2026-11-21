"""The predict function: one call of your model or agent per dataset record.

`predict(inputs, context)` receives the record's `inputs` and returns a
prediction::

    {"response": str, "reasoning": str | None,
     "tokens": {"prompt": int, "completion": int, "total": int},
     "spans": [{"name": str, "type": "LLM" | "TOOL" | "RETRIEVER" | "SPAN",
                "duration_s": float, "inputs": ..., "outputs": ..., "tokens": {...}}]}

The default talks to an OpenAI-compatible endpoint — a vLLM server started on
the compute node, or any hosted API — named by `LLM_BASE_URL` and `LLM_API_KEY`.
Replace the body of `predict` with your agent: tool loops, retrievers,
multi-turn. Keep one span per step so the trace view shows the steps.

`mock_predict` runs without a model. The connection check and the smoke-test
workflow use it, so a project is checkable on the controller.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path

ENGINE = "openai-compatible"
ROOT = Path(__file__).resolve().parent.parent

SYSTEM_PROMPT_PATH = ROOT / "prompts" / "system.md"


def engine_version() -> str:
    return os.environ.get("LLM_ENGINE_VERSION") or "unknown"


def system_prompt() -> str:
    if SYSTEM_PROMPT_PATH.is_file():
        return SYSTEM_PROMPT_PATH.read_text().strip()
    return "You are a careful assistant. Answer the question directly."


def prompt_identity(context: dict) -> dict:
    """What the run manifest records about the prompt, so a change shows as a new version."""
    text = system_prompt()
    return {"prompt_version": "system.md", "prompt_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "path": str(SYSTEM_PROMPT_PATH.relative_to(ROOT)) if SYSTEM_PROMPT_PATH.is_file() else None}


def render_user_message(inputs: dict) -> str:
    """Turn a record's inputs into the user turn. Edit to match your dataset schema."""
    if "question" in inputs and "context" in inputs:
        return f"Context:\n{inputs['context']}\n\nQuestion: {inputs['question']}"
    if "question" in inputs:
        return str(inputs["question"])
    if "prompt" in inputs:
        return str(inputs["prompt"])
    return json.dumps(inputs, sort_keys=True)


def chat(messages: list[dict], context: dict) -> dict:
    """One chat completion against the OpenAI-compatible endpoint."""
    base = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/")
    body = {"model": context["model"], "messages": messages, "max_tokens": context.get("max_tokens", 1024),
            "temperature": context.get("temperature", 0.0), "seed": context.get("seed")}
    request = urllib.request.Request(
        f"{base}/chat/completions", data=json.dumps(body).encode(),
        headers={"content-type": "application/json", "authorization": f"Bearer {os.environ.get('LLM_API_KEY', 'none')}"},
    )
    with urllib.request.urlopen(request, timeout=float(os.environ.get("LLM_TIMEOUT_S", "600"))) as response:
        return json.loads(response.read())


def predict(inputs: dict, context: dict) -> dict:
    messages = [{"role": "system", "content": system_prompt()}, {"role": "user", "content": render_user_message(inputs)}]
    started = time.perf_counter()
    answer = chat(messages, context)
    duration = time.perf_counter() - started
    choice = (answer.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    usage = answer.get("usage") or {}
    tokens = {"prompt": usage.get("prompt_tokens", 0), "completion": usage.get("completion_tokens", 0),
              "total": usage.get("total_tokens", 0)}
    return {
        "response": message.get("content"),
        "reasoning": message.get("reasoning_content") or message.get("reasoning"),
        "tokens": tokens,
        "spans": [{"name": "chat.completions", "type": "LLM", "duration_s": round(duration, 6),
                   "inputs": messages, "outputs": message.get("content"), "tokens": tokens,
                   "status": choice.get("finish_reason")}],
    }


def mock_predict(inputs: dict, context: dict) -> dict:
    """A deterministic stand-in: echoes the expected shape without a model."""
    text = render_user_message(inputs)
    digest = hashlib.sha256(text.encode()).hexdigest()
    response = f"[mock answer {digest[:8]}] {text[:80]}"
    tokens = {"prompt": len(text.split()), "completion": len(response.split()), "total": len(text.split()) + len(response.split())}
    return {"response": response, "reasoning": "mock engine; no model was called", "tokens": tokens,
            "spans": [{"name": "mock.completion", "type": "LLM", "duration_s": 0.0, "inputs": text, "outputs": response, "tokens": tokens, "status": "stop"}]}
