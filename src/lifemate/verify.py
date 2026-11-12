"""Private verifier dispatch is declared by package/overlay, never agent policy."""

import importlib
import hashlib
import json
from pathlib import Path
import sys

from .data import read_jsonl
from .evaluate import score_calls
from .sdk import create_env, load_sdk
from .store import atomic_json


def pointer(value, path):
    if path and not path.startswith("/"):
        raise ValueError("Expected JSON Pointer")
    for key in path.split("/")[1:]:
        key = key.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def specification(case, package, overlay):
    if "verification" in case:
        return case["verification"]
    path = package / "verifiers.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["cases"].get(case["sample_id"])
    if overlay is not None:
        return json.loads(Path(overlay).read_text(encoding="utf-8"))["cases"].get(case["sample_id"])
    return None


def invoke_verifier(package, spec, context):
    if spec is None:
        return {"verdict": "unresolved", "reason": "no_verifier_declared"}
    loaded = sys.modules.get("verifiers")
    if loaded is not None and Path(loaded.__file__).resolve().parent != package / "verifiers":
        raise RuntimeError("Run each verifier package in a separate process")
    module, function = spec["callable"].split(":")
    if not module.startswith("verifiers.") or any(not p.isidentifier() for p in module.split(".")):
        raise ValueError("Verifier callable must be a module under the package's verifiers/")
    sys.path.insert(0, str(package))
    verify = getattr(importlib.import_module(module), function)
    arguments = []
    for arg in spec["arguments"]:
        if set(arg) == {"ref"}:
            arguments.append(pointer(context, arg["ref"]))
        elif set(arg) == {"literal"}:
            arguments.append(arg["literal"])
        else:
            raise ValueError("Verifier arguments must be explicit ref or literal")
    return verify(*arguments)


def evaluate_package(package, runtime_root, run_dir, cases, overlay=None):
    from .synthetic import resolve
    package, run_dir = Path(package).resolve(), Path(run_dir)
    catalog = json.loads((package / "catalog.json").read_text(encoding="utf-8"))
    tools = {t["name"]: t for app in catalog["apps"] for t in app["tools"]}
    predictions = {r["id"]: r for r in read_jsonl(run_dir / "submission.jsonl")}
    sdk = load_sdk(runtime_root, "train")
    reports = []
    for case in cases:
        sid = case["sample_id"]
        if sid not in predictions:
            continue
        private_ref = case["private_execution"]["initial_state_ref"]
        private = resolve(package, {"path": private_ref["path"], "selector": ""})
        pred = predictions[sid]
        env = create_env(runtime_root, "train", sid)
        calls, valid = [], []
        for call in pred["tool_calls"]:
            result = env.call(call["name"], call["arguments"])
            valid.append(bool(result.get("ok")))
            calls.append({**call, "result": result, "state_after": env.get_state()})
        final = env.get_state()
        spec = specification(case, package, overlay)
        try:
            verdict = invoke_verifier(package, spec, {
                "private": private, "execution": {"calls": calls, "final_state": final},
                "source": {"initial_state": resolve(package, private_ref),
                    "scenario": resolve(package, case["private_execution"]["scenario_ref"]),
                    "oracle": resolve(package, case["private_execution"]["oracle_ref"])},
                "catalog_kinds": {n: t["kind"] for n, t in tools.items()},
            })
        except Exception as exc:
            verdict = {"verdict": "unresolved", "error": f"{type(exc).__name__}: {exc}"}
        ref = resolve(package, case["reference_output_ref"]) if "reference_output_ref" in case else json.loads(
            (package / f"{sid}.output.json").read_text(encoding="utf-8"))
        gold = [{"name": c["name"], "arguments": c["arguments"]} for c in ref["execution"]["tool_calls"]]
        gold_hash = sdk.state_hash(resolve(package, ref["private_final_state_ref"]))
        submitted_metric = score_calls(pred["tool_calls"], gold, pred["state_hash"] == gold_hash, tools, valid)
        replay_metric = score_calls(pred["tool_calls"], gold, env.get_state_hash() == gold_hash, tools, valid)
        report = {"id": sid, "oracle": verdict, "local_btc_metric": submitted_metric,
            "replay_metric": replay_metric, "hash_reproduced": env.get_state_hash() == pred["state_hash"],
            "answer_content": "not_evaluated", "snapshot_source": "verifier_ordered_replay", "final_state": final}
        atomic_json(run_dir / "verification" / f"{sid}.json", report)
        reports.append({k: v for k, v in report.items() if k != "final_state"})
    atomic_json(run_dir / "metrics.json", {
        "scope": "executed_synthetic_cases", "evaluated_samples": len(reports),
        "selected_samples": len(cases), "complete_coverage": len(reports) == len(cases),
        "score_0_to_100": 100 * sum(r["local_btc_metric"]["score"] for r in reports) / len(reports) if reports and len(reports) == len(cases) else None,
        "replay_score_0_to_100": 100 * sum(r["replay_metric"]["score"] for r in reports) / len(reports) if reports and len(reports) == len(cases) else None,
        "official_evaluator_parity": "not_verified",
        "verifier_specifications": {c["sample_id"]: specification(c, package, overlay) for c in cases},
        "verifier_source_sha256": hashlib.sha256(b"".join(p.read_bytes()
            for p in sorted((package / "verifiers").glob("*.py")))).hexdigest(),
        "matching_assumptions": ["Exact argument key-set; optional defaults not expanded",
            "NFC lowercase whitespace multiset fuzzy F1 > 0.6; status does not alter score"],
        "details": reports})
    return reports

