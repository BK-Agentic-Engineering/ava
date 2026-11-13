"""Passive diagnostics; no model calls or third-party dependencies."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from typing import Any


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def call_key(call: dict) -> str:
    return fingerprint({"name": call["name"], "arguments": call.get("arguments") or {}})


def shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: shape(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return {"array_items": sorted({compact(shape(item)) for item in value})}
    return "null" if value is None else "boolean" if isinstance(value, bool) else "integer" if isinstance(value, int) else "number" if isinstance(value, float) else "string"


def call_structure(calls: list[dict]) -> list:
    return [{"name": c["name"], "arguments": shape(c.get("arguments") or {})} for c in calls]


def prefix_stats(previous: list[int], current: list[int]) -> dict:
    common = 0
    for left, right in zip(previous, current):
        if left != right:
            break
        common += 1
    return {"previous_tokens": len(previous), "current_tokens": len(current),
            "common_prefix_tokens": common,
            "prefix_stability": common / len(previous) if previous else 1.0,
            "prefix_invariant": common == len(previous)}


def uncertainty(choice: dict, vocab_size: int | None) -> dict:
    """Top-k entropy bounds, not full-vocabulary entropy or calibrated confidence."""
    logprobs = choice.get("logprobs") or {}
    entries = logprobs.get("content", []) if isinstance(logprobs, dict) else logprobs
    rows = []
    for position, entry in enumerate(entries):
        top = entry.get("top_logprobs") or []
        if not top:
            continue
        probabilities = [math.exp(t["logprob"]) for t in top]
        mass = min(1.0, sum(probabilities))
        residual = max(0.0, 1.0 - mass)
        lower = -sum(p * math.log(p) for p in probabilities if p > 0)
        if residual:
            lower -= residual * math.log(residual)
        upper = None
        if vocab_size and vocab_size > len(top):
            upper = lower + (residual * math.log(vocab_size - len(top)) if residual else 0.0)
        ranked = sorted((t["logprob"] for t in top), reverse=True)
        selected = entry.get("logprob")
        rows.append({"position": position, "token": entry.get("token"), "top_k_mass": mass,
                     "entropy_lower_nats": lower, "entropy_upper_nats": upper,
                     "top_two_logprob_margin": ranked[0] - ranked[1] if len(ranked) > 1 else None,
                     "selected_surprisal_nats": -selected if selected is not None else None})
    if not rows:
        return {"tokens": 0, "available": False}
    def mean(key):
        values = [r[key] for r in rows if r[key] is not None]
        return sum(values) / len(values) if values else None
    return {"available": True, "tokens": len(rows),
            "mean_top_k_mass": mean("top_k_mass"),
            "mean_entropy_lower_nats": mean("entropy_lower_nats"),
            "mean_entropy_upper_nats": mean("entropy_upper_nats"),
            "mean_selected_surprisal_nats": mean("selected_surprisal_nats"),
            "low_margin_fraction": sum(r["top_two_logprob_margin"] is not None and
                                       r["top_two_logprob_margin"] < 1.0 for r in rows) / len(rows),
            "highest_uncertainty": sorted(rows, key=lambda r: r["entropy_lower_nats"], reverse=True)[:5]}


def failures(calls: list[dict], results: list[dict], expected: list[dict], kinds: dict[str, str]) -> dict:
    predicted = Counter(map(call_key, calls))
    gold = Counter(map(call_key, expected))
    names = Counter(c["name"] for c in calls)
    gold_names = Counter(c["name"] for c in expected)
    repeated = Counter()
    seen = set()
    for call in calls:
        key = call_key(call)
        if key in seen:
            repeated[kinds.get(call["name"], "unknown")] += 1
        seen.add(key)
    return {"schema_rejections": sum(r.get("ok") is False for r in results),
            "business_failures": sum(r.get("done") is False for r in results),
            "extra_exact_calls": sum((predicted - gold).values()),
            "missing_exact_calls": sum((gold - predicted).values()),
            "extra_tool_names": sum((names - gold_names).values()),
            "missing_tool_names": sum((gold_names - names).values()),
            "repeated_calls_by_kind": dict(repeated),
            "argument_or_order_mismatch": names == gold_names and list(map(call_key, calls)) != list(map(call_key, expected))}
