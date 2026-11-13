from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from agent import MAX_TOOL_TURNS, request_json, run_agent
from diagnostics import call_key, compact, failures, fingerprint


def score(rows: list[dict]) -> dict:
    predicted = sum(len(r["tool_calls"]) for r in rows)
    expected = sum(len(r["expected_calls"]) for r in rows)
    matches = sum(sum((Counter(map(call_key, r["tool_calls"])) &
                       Counter(map(call_key, r["expected_calls"]))).values()) for r in rows)
    precision = matches / predicted if predicted else float(expected == 0)
    recall = matches / expected if expected else float(predicted == 0)
    latencies = sorted(r["task_seconds"] for r in rows)
    return {"tasks": len(rows), "exact_call_precision": precision, "exact_call_recall": recall,
            "exact_call_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0,
            "exact_call_sequence_accuracy": statistics.mean(r["sequence_exact"] for r in rows),
            "raw_final_state_accuracy": statistics.mean(r["raw_state_exact"] for r in rows),
            "canonical_final_state_accuracy": statistics.mean(r["canonical_state_exact"] for r in rows),
            "terminations": dict(Counter(r["termination"] for r in rows)),
            "schema_rejections": sum(r["failures"]["schema_rejections"] for r in rows),
            "business_failures": sum(r["failures"]["business_failures"] for r in rows),
            "mean_task_seconds": statistics.mean(latencies),
            "p95_task_seconds": latencies[max(0, (95 * len(latencies) + 99) // 100 - 1)],
            "max_task_seconds": max(latencies), "predicted_calls": predicted, "expected_calls": expected}


def run_one(item: dict, *, data_root: Path, catalog: dict, base_url: str, timeout: float,
            trace_dir: Path, max_turns: int, temperature: float, research: bool, vocab_size: int | None,
            parallel_tool_calls: bool | None) -> dict:
    from zaic_tools import ToolEnv, state_hash
    env = ToolEnv("train", item["id"], root=data_root)
    initial = env.get_state()
    path = trace_dir / f"{item['id']}.jsonl"
    summary = run_agent(item, catalog, env, base_url=base_url, timeout=timeout, temperature=temperature,
                        trace_path=path, max_turns=max_turns, research=research, vocab_size=vocab_size,
                        parallel_tool_calls=parallel_tool_calls)
    final = env.get_state()
    changed = {app: state for app, state in final.items() if state != initial.get(app)}
    expected = item["label"].get("final_state") or {}
    expected_full = {**initial, **expected}
    calls = env.get_tool_calls()
    gold = item["label"].get("tool_calls") or []
    events = [json.loads(line) for line in path.read_text().splitlines()]
    results = [e["result"] for e in events if e["event"] == "result"]
    kinds = {t["name"]: t["kind"] for a in catalog["apps"] for t in a["tools"]}
    summary.update(tool_calls=calls, state_hash=env.get_state_hash(), expected_calls=gold,
                   sequence_exact=list(map(call_key, calls)) == list(map(call_key, gold)),
                   raw_state_exact=changed == expected,
                   canonical_state_exact=state_hash(final) == state_hash(expected_full),
                   failures=failures(calls, results, gold, kinds), trace=str(path))
    with path.open("a", encoding="utf-8") as stream:
        stream.write(compact({"event": "evaluation", "expected_calls": gold,
                              "raw_state_exact": summary["raw_state_exact"],
                              "canonical_state_exact": summary["canonical_state_exact"],
                              "failures": summary["failures"]}) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Text-only local benchmark; no official combined score.")
    parser.add_argument("--data-root", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--temperature", type=float, default=0)
    parser.add_argument("--timeout", type=float, default=1800, help="Per HTTP request, not a task deadline")
    parser.add_argument("--max-turns", type=int, default=MAX_TOOL_TURNS)
    parser.add_argument("--ids", type=Path, help="JSON array of fixed task IDs, in evaluation order")
    parser.add_argument("--research", action="store_true", help="Extra template/token requests and top-20 logprobs; not throughput mode")
    parser.add_argument("--parallel-tool-calls", action=argparse.BooleanOptionalAction, default=None,
                        help="Override the template default; use --no-parallel-tool-calls for one call per generation")
    parser.add_argument("--server-manifest", type=Path, required=True, help="Manifest written by serve.sh")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if min(args.limit, args.workers, args.max_turns, args.timeout) <= 0:
        parser.error("limit, workers, max-turns and timeout must be positive")
    data_root = args.data_root.resolve()
    split = data_root / "train"
    sys.path.insert(0, str(split))
    rows = [json.loads(line) for line in (split / "train.jsonl").read_text().splitlines() if line.strip()]
    if args.ids:
        by_id = {r["id"]: r for r in rows}
        ids = json.loads(args.ids.read_text())
        if not isinstance(ids, list) or len(ids) != len(set(ids)):
            parser.error("ids must be a JSON array without duplicates")
        rows = [by_id[id] for id in ids]
    rows = rows[:args.limit]
    if not rows:
        parser.error("No selected tasks")
    catalog = json.loads((split / "train_tools_catalog.json").read_text())
    models = request_json(args.base_url.rstrip("/") + "/models")["data"]
    props = request_json(args.base_url.removesuffix("/v1").rstrip("/") + "/props")
    manifest = json.loads(args.server_manifest.read_text())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output = (args.output_dir or Path(__file__).parent / "runs" / stamp).resolve()
    output.mkdir(parents=True, exist_ok=False)
    trace_dir = output / "traces"
    trace_dir.mkdir()
    identity = {"created_at": stamp, "task_ids": [r["id"] for r in rows], "temperature": args.temperature,
                "workers": args.workers, "research": args.research, "max_turns": args.max_turns,
                "parallel_tool_calls": args.parallel_tool_calls,
                "request_timeout_seconds": args.timeout, "endpoint": args.base_url,
                "server": manifest, "server_models": models, "server_props": props,
                "catalog_hash": fingerprint(catalog), "selected_inputs_hash": fingerprint(rows),
                "code_hashes": {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                                for name in ("agent.py", "benchmark.py", "diagnostics.py")}}
    (output / "run.json").write_text(json.dumps(identity, ensure_ascii=False, indent=2) + "\n")
    vocab_size = models[0].get("meta", {}).get("n_vocab") if models else None
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    results, errors = [], []
    with (output / "results.jsonl").open("x", encoding="utf-8", buffering=1) as journal, \
         (output / "submission.jsonl").open("x", encoding="utf-8", buffering=1) as submission, \
         concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_one, row, data_root=data_root, catalog=catalog,
                               base_url=args.base_url, timeout=args.timeout, trace_dir=trace_dir,
                               max_turns=args.max_turns, temperature=args.temperature, research=args.research,
                               vocab_size=vocab_size, parallel_tool_calls=args.parallel_tool_calls): row["id"]
                   for row in rows}
        for future in concurrent.futures.as_completed(futures):
            id = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                error = {"id": id, "error": f"{type(exc).__name__}: {exc}"}
                errors.append(error)
                journal.write(compact(error) + "\n")
                print(f"{id}: artifact/environment failure: {error['error']}", flush=True)
                continue
            results.append(result)
            journal.write(compact(result) + "\n")
            submission.write(compact({k: result[k] for k in ("id", "tool_calls", "state_hash")}) + "\n")
            print(f"{len(results) + len(errors)}/{len(rows)} {id}: {result['termination']}", flush=True)
    elapsed = time.perf_counter() - started
    report = score(results) if results else {}
    prompt_tokens = sum(r["prompt_tokens"] for r in results)
    report.update(selected_tasks=len(rows), artifact_errors=errors, wall_seconds=elapsed,
                  started_at=started_at, ended_at=datetime.now(timezone.utc).isoformat(),
                  tasks_per_second=len(results) / elapsed,
                  aggregate_completion_tokens_per_second=sum(r["completion_tokens"] for r in results) / elapsed,
                  prompt_cache_fraction=sum(r["cached_tokens"] for r in results) / prompt_tokens if prompt_tokens else None,
                  prompt_ms_sum=sum(r["prompt_ms"] for r in results), decode_ms_sum=sum(r["decode_ms"] for r in results),
                  metrics_note="Exact calls and raw/canonical state are separate diagnostics, not an official score. State agreement alone does not establish task correctness.")
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Artifacts: {output}")
    if errors or any(r["termination"] not in ("final_answer", "waiting_for_user") for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
