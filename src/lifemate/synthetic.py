"""Text adapter for the synthetic handoff; reference files remain separate."""

import argparse
import copy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import shutil
import time

from .data import build_messages
from .config import Budget
from .sdk import create_env


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve(package, ref):
    path = (package / ref["path"]).resolve()
    if not path.is_relative_to(package.resolve()):
        raise ValueError("Reference phải nằm trong package.")
    value = read(path)
    for key in ref["selector"].split("/")[1:]:
        key = key.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def render_visible(visible, run_id):
    """Hàm chỉ nhận visible; không nhận fixture, oracle hay reference output."""
    history = copy.deepcopy(visible["history"])
    mapping = {}
    for i, turn in enumerate(history):
        if turn["role"] == "user":
            if "audio_text" in turn and "text" in turn and turn["audio_text"] != turn["text"]:
                raise ValueError("History có hai transcript khác nhau.")
            if "audio_text" not in turn:
                turn["audio_text"] = turn["text"]
        calls, results = turn.get("tool_calls", []), turn.get("tool_results", [])
        if len(calls) != len(results):
            raise ValueError("History handoff thiếu cặp call/result.")
        for n, (call, result) in enumerate(zip(calls, results)):
            if call["call_id"] != result["call_id"]:
                raise ValueError("History call/result không cùng ID.")
            mapping[call["call_id"]] = f"{run_id}/history/{i}/{n}"
        if "tool_calls" in turn:
            turn["tool_calls"] = [{"name": c["name"], "arguments": c["arguments"]} for c in calls]
        if "tool_results" in turn:
            turn["tool_results"] = [r["payload"] for r in results]
    item = {"context": visible["context"], "history": history,
            "audio_text": visible["request"]}
    messages = build_messages(item, None, "train", text=True)
    # Đồng bộ native message IDs với run thực, không dùng prepared-run IDs làm execution IDs.
    for message in messages:
        for call in message.get("tool_calls", []):
            call["id"] = run_id + "/" + call["id"].replace("_", "/")
        if message["role"] == "tool":
            message["tool_call_id"] = run_id + "/" + message["tool_call_id"].replace("_", "/")
    return messages, mapping


def prepare_runtime(package, run_dir, cases):
    """Materialize fixture ngoài model; inference sau đó chỉ dùng API ToolEnv."""
    root = run_dir / "runtime"
    split = root / "train"
    split.mkdir(parents=True)
    shutil.copytree(package / "zaic_tools", split / "zaic_tools",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(package / "catalog.json", split / "train_tools_catalog.json")
    for case in cases:
        private = case["private_execution"]
        initial = resolve(package, private["initial_state_ref"])
        entry = {**initial, "_meta": {"tools": private["tools"],
                                      "current_time": private["current_time"]}}
        save(split / "train_environment" / case["sample_id"] / "state.json", entry)
    return root


def case_tools(case, package):
    specs = [resolve(package, ref) for ref in case["agent_visible"]["tool_schema_refs"]]
    names = [t["name"] for t in specs]
    allowed = set(case["private_execution"]["tools"]) | {"sys.ask_missing_info"}
    if len(names) != len(set(names)) or set(names) != allowed:
        raise ValueError("Schema và quyền runtime không khớp.")
    installed = case["agent_visible"]["context"].get("installed_apps")
    if installed is not None:
        context_names = {name for app in installed.values() for name in app["tools"]}
        if context_names | {"sys.ask_missing_info"} != allowed:
            raise ValueError("installed_apps và quyền runtime không khớp.")
    catalog = read(package / "catalog.json")
    canonical = {t["name"]: t for app in catalog["apps"] for t in app["tools"]}
    if any(canonical.get(t["name"]) != t for t in specs):
        raise ValueError("Schema được resolve khác catalog runtime.")
    return [{"type": "function", "function": {k: t[k] for k in
             ("name", "description", "parameters")}} for t in specs]



DEFAULT_VERIFIERS = Path(__file__).resolve().parents[2] / "configs/handoff_v01_verifiers.json"


def prepare_case(case, package, runtime_root, run_id=None):
    from .sdk import environment_ref
    messages, mapping = render_visible(case["agent_visible"], run_id or case["sample_id"])
    manifest = read(package / "SOURCES.json") if (package / "SOURCES.json").exists() else {}
    metadata = case.get("source_metadata", manifest.get("cases", {}).get(case["sample_id"], {}))
    return {"id": case["sample_id"], "messages": messages, "tools": case_tools(case, package),
            "environment": environment_ref(runtime_root, "train", case["sample_id"]),
            "source": {"kind": "synthetic", "contract": case["contract_version"],
                       "metadata": metadata, "history_id_map": mapping,
                       "reference_run_id": case["run_id"],
                       "verification": case.get("verification")}}


def export_case(record, run_dir):
    run_id = record["run_id"]
    calls, results = [], []
    for pair in record["calls"]:
        calls.append({"call_id": pair["call_id"], **pair["call"]})
        results.append({"result_id": pair["call_id"] + "/result", "call_id": pair["call_id"],
                        "payload": pair["result"]})
    kind = record["backend"].get("kind", "unknown")
    output = {"contract_version": record["source"].get("contract"), "sample_id": record["id"],
        "run_id": run_id, "execution": {"tool_calls": calls, "tool_results": results},
        "final_text": record["final_text"],
        "termination": {"status": record["status"], "reason": record["reason"], "origin": "session_runner"},
        "provenance": {"kind": "actual_model_execution" if kind == "local_llm" else "scripted_backend_execution",
            "reference_run_id": record["source"].get("reference_run_id"),
            "source_metadata": record["source"].get("metadata", {}),
            "trace_call_id_map": {p["call_id"]: p["call_id"] for p in record["calls"]}},
        "availability": {"backend_kind": kind, "model_run": "performed" if kind == "local_llm" else "not_performed",
            "final_text": "captured" if record["final_text"] is not None else "not_emitted"},
        "private_final_state_ref": {"path": f"verification/{record['id']}.json", "selector": "/final_state"}}
    save(Path(run_dir) / "model_outputs" / f"{record['id']}.output.json", output)
    return output


def execute_case(case, package, runtime_root, run_dir, model, *, backend_kind="local_llm",
                 seconds=Budget().seconds, resume=False):
    from .agent import run_session, summary
    from .batch import session_trace, implementation_id
    from .store import SessionStore
    began = time.monotonic()
    prepared = prepare_case(case, package, runtime_root, f"{Path(run_dir).name}/{case['sample_id']}")
    prepared["timings"] = {"preparation_seconds": time.monotonic() - began}
    prepared["run_id"] = f"{Path(run_dir).name}/{case['sample_id']}"
    trace = session_trace(run_dir, case["sample_id"])
    try:
        record = run_session(prepared, model,
            lambda: create_env(runtime_root, "train", case["sample_id"]), trace,
            store=SessionStore(Path(run_dir) / "sessions" / case["sample_id"]),
            budget=Budget(seconds=seconds), backend_identity={**model.identity,
                "kind": backend_kind, "implementation": implementation_id()},
            resume=resume)
    finally:
        trace.close()
    export_case(record, run_dir)
    return record["submission"], summary(record)


def evaluate_cases(package, runtime_root, run_dir, cases, overlay=DEFAULT_VERIFIERS):
    from .verify import evaluate_package
    return evaluate_package(package, runtime_root, run_dir, cases, overlay)


def main():
    from .batch import run_batch, export_results, is_complete
    from .store import fingerprint
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--verifiers", type=Path, default=DEFAULT_VERIFIERS,
                        help="Explicit compatibility overlay; package verifiers.json/per-input declaration takes priority")
    parser.add_argument("--seconds", type=float, default=Budget().seconds)
    parser.add_argument("--context-tokens", type=int, default=Budget().context_tokens)
    parser.add_argument("--output-tokens", type=int, default=Budget().output_tokens)
    args = parser.parse_args()
    if args.resume and args.output is None:
        parser.error("--resume requires --output")
    package = args.package.resolve()
    root = Path(__file__).resolve().parents[2]
    cases = [read(p) for p in sorted(package.glob("*.input.json"))]
    stamp = datetime.now(timezone(timedelta(hours=7))).strftime("%Y%m%d_%H%M%S")
    folder = (args.output or root / "runs" / f"thang_text_{stamp}").resolve()
    runtime = folder / "runtime"
    if not args.resume:
        if folder.exists():
            raise FileExistsError("Choose a new run directory")
        prepare_runtime(package, folder, cases)
    from .llm import LocalLLM
    model = LocalLLM(root / "models/llm/lfm3-1.7b")
    source = {"kind": "synthetic", "mode": "synthetic_text", "split": "synthetic_package",
        "split_samples": len(cases), "package": str(package),
        "package_sha256": fingerprint({str(p.relative_to(package)): p.read_bytes().hex()
            for p in sorted(package.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}),
        "verifier_overlay": read(args.verifiers) if args.verifiers else None}
    records = run_batch(cases,
        lambda case: prepare_case(case, package, runtime, f"{folder.name}/{case['sample_id']}"),
        model, folder, backend_identity=model.identity,
        budget=Budget(args.seconds, args.context_tokens, args.output_tokens), resume=args.resume, source=source)
    for record in export_results(folder, [c["sample_id"] for c in cases]):
        export_case(record, folder)
    if is_complete(records, len(cases)):
        evaluate_cases(package, runtime, folder, cases, args.verifiers)
    print("RUN", folder)


if __name__ == "__main__":
    main()
