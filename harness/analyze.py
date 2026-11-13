"""Offline analysis of legacy snapshot traces and current event journals."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

from diagnostics import call_key, call_structure, failures, fingerprint


def load_trace(path: Path) -> dict:
    if path.suffix == ".json":
        trace = json.loads(path.read_text())
        turns = [{"message": t["response"]["choices"][0]["message"],
                  "finish_reason": t["response"]["choices"][0].get("finish_reason"),
                  "usage": t["response"].get("usage", {}), "timings": t["response"].get("timings", {}),
                  "elapsed_seconds": t["elapsed_seconds"], "results": t["tool_results"]} for t in trace["turns"]]
        return {"id": trace["id"], "calls": trace["tool_calls"], "expected": trace["expected_calls"],
                "turns": turns, "raw_state_exact": trace["final_state_exact"],
                "canonical_state_exact": None, "legacy_states": (trace["predicted_state_changes"], trace["expected_final_state"]),
                "termination": "final_answer" if turns[-1]["finish_reason"] == "stop" else "unknown_legacy",
                "schemas": [fingerprint(t["request"]["tools"]) for t in trace["turns"]], "prefix": []}
    events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    turns = []
    for event in events:
        if event["event"] == "assistant":
            turns.append({**event, "results": []})
        elif event["event"] == "result" and turns:
            turns[-1]["results"].append(event["result"])
    evaluation = next((e for e in events if e["event"] == "evaluation"), {})
    end = next((e for e in events if e["event"] == "end"), {})
    return {"id": events[0]["id"], "calls": [{"name": e["name"], "arguments": e["arguments"]} for e in events if e["event"] == "call"],
            "expected": evaluation.get("expected_calls", []), "turns": turns,
            "raw_state_exact": evaluation.get("raw_state_exact"),
            "canonical_state_exact": evaluation.get("canonical_state_exact"),
            "termination": end.get("termination", "interrupted"),
            "schemas": [events[0]["schema_hash"]] + [e["schema_hash"] for e in events if e["event"] == "prefix"],
            "prefix": [e for e in events if e["event"] == "prefix" and "prefix_stability" in e]}


def analyze(run: Path, data_root: Path) -> dict:
    sys.path.insert(0, str(data_root / "train"))
    from zaic_tools import state_hash
    catalog = json.loads((data_root / "train/train_tools_catalog.json").read_text())
    kinds = {t["name"]: t["kind"] for a in catalog["apps"] for t in a["tools"]}
    traces = [load_trace(p) for p in sorted((run / "traces").iterdir()) if p.suffix in (".json", ".jsonl")]
    tasks = []
    for trace in traces:
        turns = trace["turns"]
        results = [r for t in turns for r in t["results"]]
        categories = failures(trace["calls"], results, trace["expected"], kinds)
        calls = trace["calls"]
        gold = trace["expected"]
        if "legacy_states" in trace:
            # Changed-state diagnostic only; historical traces lack the full initial state.
            trace["canonical_state_exact"] = state_hash(trace["legacy_states"][0]) == state_hash(trace["legacy_states"][1])
        tasks.append({"id": trace["id"], "termination": trace["termination"], **categories,
                      "sequence_exact": list(map(call_key, calls)) == list(map(call_key, gold)),
                      "raw_state_exact": trace["raw_state_exact"], "canonical_state_exact": trace["canonical_state_exact"],
                      "predicted_calls": len(calls), "expected_calls": len(gold), "turns": len(turns),
                      "inference_seconds": sum(t["elapsed_seconds"] for t in turns),
                      "schema_drift": len(set(trace["schemas"])) - 1,
                      "schema_signature": trace["schemas"][0],
                      "structural_signature": fingerprint(call_structure(calls)),
                      "call_signature": fingerprint(calls),
                      "prefix_violations": sum(not p["prefix_invariant"] for p in trace["prefix"]),
                      "business_messages": [r.get("message") for r in results if r.get("done") is False]})
    turns = [t for tr in traces for t in tr["turns"]]
    generated = sum(t["usage"].get("completion_tokens", 0) for t in turns)
    final_tokens = sum(tr["turns"][-1]["usage"].get("completion_tokens", 0) for tr in traces
                       if tr["turns"] and not tr["turns"][-1]["message"].get("tool_calls"))
    def count(field):
        return sum(t[field] for t in tasks if t[field] is not None)
    structures = Counter(t["structural_signature"] for t in tasks)
    prefix = [p for tr in traces for p in tr["prefix"]]
    uncertainties = [t["uncertainty"] for t in turns if t.get("uncertainty", {}).get("available")]
    return {"run": str(run), "tasks": len(tasks),
            "summary": {"sequence_exact": count("sequence_exact"), "raw_state_exact": count("raw_state_exact"),
                        "canonical_state_exact": count("canonical_state_exact"),
                        "schema_rejections": count("schema_rejections"), "business_failures": count("business_failures"),
                        "schema_drift_tasks": sum(t["schema_drift"] > 0 for t in tasks),
                        "repeated_write_tasks": sum(t["repeated_calls_by_kind"].get("write", 0) > 0 for t in tasks),
                        "no_call_with_gold_tasks": sum(t["predicted_calls"] == 0 and t["expected_calls"] > 0 for t in tasks),
                        "terminations": dict(Counter(t["termination"] for t in tasks)),
                        "mean_inference_seconds": statistics.mean(t["inference_seconds"] for t in tasks) if tasks else None,
                        "completion_tokens": generated, "terminal_generation_fraction": final_tokens / generated if generated else None,
                        "prompt_ms_sum": sum(t["timings"].get("prompt_ms", 0) for t in turns),
                        "decode_ms_sum": sum(t["timings"].get("predicted_ms", 0) for t in turns),
                        "distinct_structures": len(structures),
                        "prefix_samples": len(prefix),
                        "prefix_violation_rate": sum(not p["prefix_invariant"] for p in prefix) / len(prefix) if prefix else None,
                        "uncertainty_measured_tokens": sum(u["tokens"] for u in uncertainties),
                        "mean_entropy_lower_nats": sum(u["mean_entropy_lower_nats"] * u["tokens"] for u in uncertainties) / sum(u["tokens"] for u in uncertainties) if uncertainties else None},
            "interpretation": "Heuristics identify symptoms, not semantic root causes. Legacy canonical scores compare changed states only; new scores compare full states. Structural diversity across different tasks is not instability.",
            "task_details": tasks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--compare", type=Path, help="Paired run with the same task IDs")
    parser.add_argument("--task", help="Print one readable trajectory, including reasoning")
    parser.add_argument("--data-root", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    parser.add_argument("--output", type=Path, help="Write full JSON analysis; otherwise print summary")
    parser.add_argument("--gpu-csv", type=Path, help="serve.sh telemetry; filter to benchmark timestamps before interpretation")
    args = parser.parse_args()
    if args.task:
        paths = [args.run / "traces" / (args.task + ext) for ext in (".jsonl", ".json")]
        trace = load_trace(next(p for p in paths if p.exists()))
        print(f"{trace['id']} — {trace['termination']}")
        print("EXPECTED", json.dumps(trace["expected"], ensure_ascii=False))
        for i, turn in enumerate(trace["turns"]):
            print(f"\n--- Step {i}: {turn['finish_reason']} ({turn['elapsed_seconds']:.2f}s) ---")
            print(json.dumps(turn["message"], ensure_ascii=False, indent=2))
            for result in turn["results"]:
                print("RESULT", json.dumps(result, ensure_ascii=False))
        return
    report = analyze(args.run, args.data_root.resolve())
    if args.compare:
        other = analyze(args.compare, args.data_root.resolve())
        left = {t["id"]: t for t in report["task_details"]}
        right = {t["id"]: t for t in other["task_details"]}
        if left.keys() != right.keys():
            parser.error("Paired comparison requires identical task IDs")
        report["paired_comparison"] = {
            "other_run": str(args.compare), "tasks": len(left),
            "call_change_rate": sum(left[id]["call_signature"] != right[id]["call_signature"] for id in left) / len(left),
            "structural_change_rate": sum(left[id]["structural_signature"] != right[id]["structural_signature"] for id in left) / len(left),
            "schema_change_rate": sum(left[id]["schema_signature"] != right[id]["schema_signature"] for id in left) / len(left),
            "changed_ids": [id for id in left if left[id]["call_signature"] != right[id]["call_signature"]]}
    if args.gpu_csv:
        with args.gpu_csv.open() as stream:
            samples = list(csv.DictReader(stream, skipinitialspace=True))
        utilization = [float(row["utilization.gpu [%]"].split()[0]) for row in samples
                       if row["utilization.gpu [%]"].split()[0] != "[N/A]"]
        report["gpu"] = {"samples": len(utilization),
                         "mean_utilization_percent": statistics.mean(utilization) if utilization else None,
                         "utilization_stddev": statistics.pstdev(utilization) if utilization else None,
                         "below_50_percent_fraction": sum(u < 50 for u in utilization) / len(utilization) if utilization else None}
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "task_details"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
