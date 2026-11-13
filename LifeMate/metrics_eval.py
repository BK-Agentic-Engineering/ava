"""Score LifeMate train traces, including paired DDR."""

import argparse
import copy
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "train+public_test"
sys.path.insert(0, str(DATA / "train"))
from zaic_tools import ToolEnv, canon, catalog_tools, state_hash


ASK_TOOL = "sys.ask_missing_info"
NORMAL_STOP = "model kết thúc mà không gọi thêm tool"
MISSING = object()


def signature(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write("\n")
    temporary.replace(path)


def records_by_id(items):
    if not all(isinstance(item, dict) and isinstance(item.get("id"), (str, int)) for item in items):
        return None
    index = {"id=" + signature(item["id"]): item for item in items}
    return index if len(index) == len(items) else None


def state_delta(before, after, path=()):
    """Compare canonical state at field paths and identify list records by ID."""
    if isinstance(before, list) and isinstance(after, list):
        left, right = records_by_id(before), records_by_id(after)
        if left is not None and right is not None:
            before, after = left, right
    if isinstance(before, dict) and isinstance(after, dict):
        delta = {}
        for key in sorted(before.keys() | after.keys()):
            delta.update(state_delta(before.get(key, MISSING), after.get(key, MISSING), path + (key,)))
        return delta
    old = None if before is MISSING else signature(before)
    new = None if after is MISSING else signature(after)
    return {path: new} if old != new else {}


def requires_state_change(sample, initial):
    gold = {**initial, **sample["label"]["final_state"]}
    return bool(state_delta(canon(initial), canon(gold)))


def call_records(turn, specs):
    if "calls" in turn:
        return turn["calls"]
    return [{"call": call, "result": result, "kind": specs.get(call["name"], {}).get("kind")}
            for call, result in zip(turn["tool_calls"], turn["tool_results"], strict=True)]


def trace_states(sample_id, result, turns):
    calls = [call for turn in turns for call in turn if not call.get("blocked")]
    if "initial_state" in result and all("state_changes" in call for call in calls):
        initial = result["initial_state"]
        final = copy.deepcopy(initial)
        for call in calls:
            for app, change in call["state_changes"].items():
                if change["after"] is None:
                    final.pop(app, None)
                else:
                    final[app] = change["after"]
    else:
        env = ToolEnv("train", sample_id, root=DATA)
        initial = env.get_state()
        for call in result["submission"]["tool_calls"]:
            env.call(call["name"], call["arguments"])
        final = env.get_state()
    if state_hash(final) != result["submission"]["state_hash"]:
        raise ValueError(f"{sample_id}: state dựng lại khác state hash trong submission")
    return initial, final


def failure_type(record, specs):
    if record.get("blocked"):
        return None
    call = record["call"]
    result = record["result"]
    if result.get("ok") is False:
        return "rejected"
    if result.get("done") is False:
        return "not_done"
    spec = specs.get(call["name"], {})
    returns = spec.get("returns", "")
    if (spec.get("kind") != "read" or result.get("ok") is not True
            or not returns.endswith("[]") or result.get(returns[:-2]) != []):
        return None
    params = spec["parameters"]
    required = set(params.get("required", []))
    alternatives = {name for group in params.get("x-one-of", []) for name in group}
    if any(name in params["properties"] and name not in required | alternatives and value not in (None, "", [], {})
           for name, value in call["arguments"].items()):
        return "empty_read"
    return None


def successful_call(record, specs):
    result = record["result"]
    if record.get("blocked") or result.get("ok") is not True or result.get("done") is False:
        return False
    spec = specs.get(record["call"]["name"], {})
    if spec.get("kind") != "read":
        return True
    returns = spec.get("returns", "")
    if returns.endswith("[]"):
        return bool(result.get(returns[:-2]))
    return any(value not in (None, "", [], {}) for key, value in result.items()
               if key not in {"ok", "done", "error", "message"})


def recovery_events(turns, specs):
    """Count a corrected call or a schema-linked lookup on the next turn."""
    events = []
    for index, current in enumerate(turns):
        following = turns[index + 1] if index + 1 < len(turns) else []
        for failed in current:
            trigger = failure_type(failed, specs)
            if trigger is None:
                continue
            call = failed["call"]
            name = call["name"]
            props = specs.get(name, {}).get("parameters", {}).get("properties", {})
            sources = {source for prop in props.values() if prop.get("x-ref")
                       for source in re.findall(r"\b\w+\.\w+\b", prop.get("description", "").partition("lấy từ ")[2])
                       if specs.get(source, {}).get("kind") == "read"}
            same_failed_call = any(signature(record["call"]) == signature(call) for record in following)
            recovered = not same_failed_call and any(
                record["call"]["name"] in {name, *sources}
                and record["call"]["name"] != ASK_TOOL
                and successful_call(record, specs) for record in following
            )
            events.append({"turn": index + 1, "call": call, "trigger": trigger, "recovered": recovered})
    return events


def clarification(call):
    args = call["arguments"]
    return ("missing_info", args["tool_name"], tuple(sorted(set(args["params"]))))


def boundary_counts(label, result, turns):
    gold_calls = label["tool_calls"]
    expected = {clarification(call) for call in gold_calls if call["name"] == ASK_TOOL}
    if not gold_calls:
        expected.add(("abstention",))
    attempts = [record for turn in turns for record in turn]
    predicted = {clarification(record["call"]) for record in attempts
                 if record["call"]["name"] == ASK_TOOL and not record.get("blocked")
                 and record["result"].get("waiting_for_user") is True}
    if not attempts and not result["submission"]["tool_calls"] and result["stop_reason"] == NORMAL_STOP:
        predicted.add(("abstention",))
    return {"tp": len(expected & predicted), "fp": len(predicted - expected), "fn": len(expected - predicted)}


def score_sample(sample, result, specs):
    turns = [call_records(turn, specs) for turn in result["trace"]]
    initial, final = trace_states(sample["id"], result, turns)
    gold = {**initial, **sample["label"]["final_state"]}
    start = canon(initial)
    expected = state_delta(start, canon(gold))
    observed = state_delta(start, canon(final))
    matched = sum(key in observed and observed[key] == value for key, value in expected.items())
    unintended = len(observed) - matched
    return {
        "sample_id": sample["id"],
        "SSR": matched / len(expected) if expected else float(not observed),
        "USMR": int(unintended > 0),
        "USMR_key": ratio(unintended, len(observed)) or 0.0,
        "state_delta": {"expected": len(expected), "observed": len(observed), "matched": matched, "unintended": unintended},
        "state_hash_matches": result["submission"]["state_hash"] == state_hash(gold),
        "recovery_events": recovery_events(turns, specs),
        "boundary": boundary_counts(sample["label"], result, turns),
        "stop_reason": result["stop_reason"],
    }


def score_ddr(records, targets):
    """Paired final-state accuracy on samples with a nonempty gold state diff."""
    eligible = [row for row in records if row["state_delta"]["expected"]]
    pairs = [(row, targets[row["sample_id"]]) for row in eligible if row["sample_id"] in targets]
    n = len(pairs)
    full = ratio(sum(row["state_hash_matches"] for row, _ in pairs), n)
    target = ratio(sum(row["state_hash_matches"] for _, row in pairs), n)
    if not eligible:
        status = "no_state_changing_samples"
    elif n != len(eligible):
        status = "missing_target_traces"
    elif target == 0:
        status = "zero_target_accuracy"
    else:
        status = "ok"
    return {"value": 1 - full / target if status == "ok" else None, "status": status,
            "accuracy_basis": "final_state_hash_match_on_state_changing_samples",
            "eligible_samples": len(eligible), "paired_samples": n, "full_accuracy": full, "target_accuracy": target}


def score_runs(samples, catalog, full, target=None):
    specs = catalog_tools(catalog)
    records = [score_sample(samples[sid], trace, specs) for sid, trace in full.items()]
    targets = {}
    for sid, trace in (target or {}).items():
        if sid not in full:
            continue
        for key in ("input_source", "request_text", "history", "self_heal", "precision"):
            if key in full[sid] and key in trace and full[sid][key] != trace[key]:
                raise ValueError(f"{sid}: trace full và target khác {key}")
        targets[sid] = score_sample(samples[sid], trace, specs)
    events = [event for row in records for event in row["recovery_events"]]
    recovered = sum(event["recovered"] for event in events)
    boundary = {key: sum(row["boundary"][key] for row in records) for key in ("tp", "fp", "fn")}
    tp, fp, fn = (boundary[key] for key in ("tp", "fp", "fn"))
    ddr = score_ddr(records, targets)
    return {
        "sample_count": len(records),
        "metrics": {
            "SSR": ratio(sum(row["SSR"] for row in records), len(records)),
            "USMR": ratio(sum(row["USMR"] for row in records), len(records)),
            "SHR": ratio(recovered, len(events)),
            "missing_info_abstention_f1": ratio(2 * tp, 2 * tp + fp + fn),
            "DDR": ddr["value"],
        },
        "SHR_details": {"recovered": recovered, "events": len(events)},
        "boundary_details": {**boundary, "precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn)},
        "DDR_details": ddr,
        "samples": records,
    }


class MetricModels:
    def __init__(self, runtime):
        self.runtime = runtime
        self.source = runtime.source
        self.context_tokens = runtime.context_tokens
        self.target_names = None

    def transcribe(self, item):
        return self.runtime.transcribe(item)

    def generate(self, messages, tools, max_tokens):
        if self.target_names is not None:
            tools = [tool for tool in tools if tool["function"]["name"] in self.target_names]
        return self.runtime.generate(messages, tools, max_tokens)


def load_traces(path, variant="full"):
    if not path.is_dir():
        raise ValueError(f"Không tìm thấy thư mục trace {path}")
    files = sorted(path.glob(f"train_*_{variant}.json"))
    if not files:
        files = sorted(file for file in path.glob("train_*.json")
                       if not file.stem.endswith(("_full", "_target", "_reverse")))
    traces = {}
    for file in files:
        trace = read_json(file)
        traces[trace["submission"]["id"]] = trace
    if not traces and variant == "full":
        raise ValueError(f"Không tìm thấy trace trong {path}")
    return traces


def collect_runs(args, samples, catalog, out_dir):
    import sandbox_baseline as sandbox

    selected = [sample for sid, sample in samples.items() if not args.ids or sid in args.ids]
    if args.ids and set(args.ids) - samples.keys():
        raise ValueError(f"Không tìm thấy mẫu {sorted(set(args.ids) - samples.keys())}")
    if args.limit is not None:
        selected = selected[:args.limit]
    prompt = args.prompt.read_text(encoding="utf-8-sig") if args.prompt else None
    full_dir = out_dir / "full"
    full_dir.mkdir(parents=True, exist_ok=False)
    target_dir = out_dir / "target"
    if args.ddr:
        target_dir.mkdir()
    write_json(out_dir / "config.json", {"sample_ids": [sample["id"] for sample in selected],
                                        "input_source": args.input, "system_prompt": prompt, "self_heal": args.self_heal,
                                        "max_turns": args.max_turns, "max_tokens": args.max_tokens,
                                        "ddr": args.ddr})
    transcripts = sandbox.prepare_transcripts(selected, out_dir) if args.input == "asr" else None
    runtime = sandbox.Models(args.input, transcripts)
    models = MetricModels(runtime)
    full, target = {}, {}
    options = {"max_turns": args.max_turns, "max_tokens": args.max_tokens,
               "system_prompt": prompt, "self_heal": args.self_heal}
    try:
        for sample in selected:
            sid = sample["id"]
            print(f"{sid} | full", flush=True)
            models.target_names = None
            result = sandbox.run_sample(sample, catalog, models, **options)
            full[sid] = result
            write_json(full_dir / f"{sid}.json", result)
            if args.ddr and requires_state_change(sample, result["initial_state"]):
                print(f"{sid} | target", flush=True)
                models.target_names = {call["name"] for call in sample["label"]["tool_calls"]}
                target[sid] = sandbox.run_sample(sample, catalog, models, **options)
                write_json(target_dir / f"{sid}.json", target[sid])
    finally:
        runtime.close()
    return full, target


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    score = commands.add_parser("score", help="Chấm các trace đã lưu trên tập train")
    score.add_argument("run_dir", type=Path)
    score.add_argument("--target-dir", type=Path, help="Trace oracle tương ứng cho DDR")
    run = commands.add_parser("run", help="Tạo trace mới rồi chấm điểm")
    selection = run.add_mutually_exclusive_group(required=True)
    selection.add_argument("--ids", nargs="+")
    selection.add_argument("--limit", type=int)
    selection.add_argument("--all", action="store_true")
    run.add_argument("--input", choices=("asr", "reference"), required=True)
    run.add_argument("--prompt", type=Path)
    run.add_argument("--max-turns", type=int)
    run.add_argument("--max-tokens", type=int)
    run.add_argument("--self-heal", action="store_true")
    run.add_argument("--ddr", action="store_true", help="Chạy thêm điều kiện chỉ cấp schema tool từ nhãn")
    run.add_argument("--out-dir", type=Path)
    args = parser.parse_args()
    if args.command == "run" and any(value is not None and value <= 0 for value in (args.limit, args.max_turns, args.max_tokens)):
        parser.error("--limit, --max-turns và --max-tokens phải lớn hơn 0")
    train = DATA / "train"
    with (train / "train.jsonl").open(encoding="utf-8") as file:
        samples = {sample["id"]: sample for line in file if line.strip() and (sample := json.loads(line))}
    catalog = read_json(train / "train_tools_catalog.json")
    if args.command == "run":
        out_dir = args.out_dir or ROOT / "metric_runs" / datetime.now().strftime("run_%Y%m%d_%H%M%S_%f")
        full, target = collect_runs(args, samples, catalog, out_dir)
    else:
        out_dir = args.run_dir
        full_dir = out_dir / "full" if (out_dir / "full").is_dir() else out_dir
        target_dir = args.target_dir or (out_dir / "target" if (out_dir / "target").is_dir() else None)
        full = load_traces(full_dir)
        target = load_traces(target_dir, "target") if target_dir else {}
    summary = score_runs(samples, catalog, full, target)
    write_json(out_dir / "metrics_summary.json", summary)
    print(json.dumps(summary["metrics"], ensure_ascii=False, indent=2), flush=True)
    print(out_dir / "metrics_summary.json")


if __name__ == "__main__":
    main()
