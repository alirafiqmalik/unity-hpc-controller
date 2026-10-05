"""Scorers: each turns (inputs, outputs, expectations) into one assessment.

An assessment is::

    {"value": True | False | number | str, "kind": "pass_fail" | "score" | "category",
     "rationale": str, "source": str}

Built in: `correctness` (expected answer appears in the response),
`exact_match`, `contains_all` (every listed fact appears), `regex_match`
(the expectation `pattern`), `json_valid`, `response_length`, and `judge`, an
LLM-as-a-judge scorer that asks the same endpoint the agent uses to grade with
a rubric. Add your own with `@scorer(...)`.

Expectation keys the built-ins read: `expected_response` or `expected_answer`,
`expected_facts` (list), `pattern`, `guidelines`.
"""
from __future__ import annotations

import json
import re
from typing import Callable

Assessment = dict
Scorer = Callable[..., Assessment]

_REGISTRY: dict[str, "Registered"] = {}


class Registered:
    def __init__(self, fn: Scorer, name: str, kind: str, source: str, needs_response: bool):
        self.fn, self.name, self.kind, self.source, self.needs_response = fn, name, kind, source, needs_response

    def __call__(self, **kwargs) -> Assessment:
        result = self.fn(**kwargs)
        result.setdefault("kind", self.kind)
        result.setdefault("source", self.source)
        result.setdefault("rationale", "")
        return result


def scorer(name: str, *, kind: str = "pass_fail", source: str = "code", needs_response: bool = True):
    def wrap(fn: Scorer) -> Registered:
        registered = Registered(fn, name, kind, source, needs_response)
        _REGISTRY[name] = registered
        return registered
    return wrap


def get(name: str) -> Registered:
    if name not in _REGISTRY:
        raise KeyError(f"unknown scorer {name!r}; known: {', '.join(sorted(_REGISTRY))}")
    return _REGISTRY[name]


def names() -> list[str]:
    return sorted(_REGISTRY)


def _expected(expectations: dict) -> str | None:
    for key in ("expected_response", "expected_answer", "answer"):
        if key in expectations and expectations[key] not in (None, ""):
            return str(expectations[key])
    return None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


@scorer("correctness")
def correctness(inputs, outputs, expectations, context) -> Assessment:
    expected = _expected(expectations)
    if expected is None:
        return {"value": None, "kind": "pass_fail", "rationale": "no expected answer on this record"}
    ok = _norm(expected) in _norm(outputs or "")
    return {"value": ok, "rationale": f"expected {expected!r} {'found' if ok else 'not found'} in the response"}


@scorer("exact_match")
def exact_match(inputs, outputs, expectations, context) -> Assessment:
    expected = _expected(expectations)
    if expected is None:
        return {"value": None, "rationale": "no expected answer on this record"}
    ok = _norm(expected) == _norm(outputs or "")
    return {"value": ok, "rationale": "normalised whitespace and case"}


@scorer("contains_all")
def contains_all(inputs, outputs, expectations, context) -> Assessment:
    facts = expectations.get("expected_facts") or expectations.get("must_mention") or []
    if not facts:
        return {"value": None, "rationale": "no expected_facts on this record"}
    text = _norm(outputs or "")
    missing = [fact for fact in facts if _norm(str(fact)) not in text]
    return {"value": not missing, "rationale": f"missing: {missing}" if missing else f"all {len(facts)} facts present"}


@scorer("regex_match")
def regex_match(inputs, outputs, expectations, context) -> Assessment:
    pattern = expectations.get("pattern")
    if not pattern:
        return {"value": None, "rationale": "no pattern on this record"}
    ok = re.search(str(pattern), outputs or "", re.S) is not None
    return {"value": ok, "rationale": f"pattern {pattern!r}"}


@scorer("json_valid")
def json_valid(inputs, outputs, expectations, context) -> Assessment:
    try:
        json.loads(outputs or "")
        return {"value": True, "rationale": "response parses as JSON"}
    except (TypeError, ValueError) as exc:
        return {"value": False, "rationale": f"not JSON: {exc}"}


@scorer("response_length", kind="score")
def response_length(inputs, outputs, expectations, context) -> Assessment:
    return {"value": len((outputs or "").split()), "rationale": "words in the response"}


@scorer("judge", source="llm-judge")
def judge(inputs, outputs, expectations, context) -> Assessment:
    """LLM-as-a-judge: grade the response against the expectations with a rubric."""
    if context.get("mock"):
        expected = _expected(expectations)
        ok = expected is not None and _norm(expected) in _norm(outputs or "")
        return {"value": ok, "rationale": "mock judge: substring check", "source": "mock-judge"}
    import agent
    guidelines = expectations.get("guidelines") or "The response must answer the question correctly and completely."
    rubric = (
        "You grade an AI response. Reply with one line: PASS or FAIL, then a short reason.\n\n"
        f"Guidelines: {guidelines}\n\nInputs: {json.dumps(inputs, sort_keys=True)}\n\n"
        f"Expectations: {json.dumps(expectations, sort_keys=True)}\n\nResponse: {outputs}"
    )
    answer = agent.chat([{"role": "user", "content": rubric}], {**context, "max_tokens": 200, "temperature": 0.0})
    verdict = ((answer.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    return {"value": verdict.strip().upper().startswith("PASS"), "rationale": verdict.strip()[:400], "source": f"llm-judge:{context.get('model')}"}


DEFAULT_SCORERS = ["correctness", "response_length"]
