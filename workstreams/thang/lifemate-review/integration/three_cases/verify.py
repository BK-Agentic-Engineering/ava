"""Verify the three portable reference cases. Run with Python 3.10+ and stdlib."""
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from verifiers import batch02, wave15, wave16

SAMPLES = ("TR15_PLANNING_TOMORROW", "B02_N_C", "TR16_APP_KEEP")
VERSION = "lifemate-harness-proposal-0.1"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(ref):
    target = (ROOT / ref["path"]).resolve()
    assert target.is_relative_to(ROOT), "Reference escapes package"
    data = read(target)
    pointer = ref["selector"]
    assert not pointer or pointer.startswith("/")
    for key in pointer.split("/")[1:]:
        key = key.replace("~1", "/").replace("~0", "~")
        data = data[int(key)] if isinstance(data, list) else data[key]
    return data


def check_refs(value):
    if isinstance(value, dict):
        if "path" in value and "selector" in value:
            resolve(value)
        for item in value.values():
            check_refs(item)
    elif isinstance(value, list):
        for item in value:
            check_refs(item)


def strip_history(turns):
    plain = deepcopy(turns)
    for turn in plain:
        if "tool_calls" in turn:
            calls, results = turn["tool_calls"], turn["tool_results"]
            assert len(calls) == len(results)
            for call, result in zip(calls, results):
                assert call["call_id"] == result["call_id"]
                assert result["result_id"] == call["call_id"] + "/result"
            turn["tool_calls"] = [{"name": c["name"], "arguments": c["arguments"]} for c in calls]
            turn["tool_results"] = [r["payload"] for r in results]
    return plain


def verify_case(sid, catalog):
    inp, out = (read(ROOT / f"{sid}.{suffix}.json") for suffix in ("input", "output"))
    check_refs(inp)
    check_refs(out)
    assert inp["contract_version"] == out["contract_version"] == VERSION
    assert inp["sample_id"] == out["sample_id"] == sid
    assert inp["run_id"] == out["run_id"] and inp["run_id"].startswith("prepared-")
    private, visible = inp["private_execution"], inp["agent_visible"]
    assert set(visible) == {"request", "context", "history", "tool_schema_refs"}
    scenario = resolve(private["scenario_ref"])
    assert scenario["scenario_id"] == sid and scenario["status"] == "spec_only"
    assert not scenario.get("exportable", False)
    assert scenario["oracle_draft"] == resolve(private["oracle_ref"])
    original = resolve(private["visible_source_ref"])
    assert visible["request"] == original["request"] == scenario["agent_visible"]["request"]
    assert visible["context"] == original["context"]
    assert strip_history(visible["history"]) == original["history"]
    assert private["current_time"] == visible["context"]["current_time"]
    assert private["timezone"] == visible["context"]["timezone"]
    assert private["tools"] == original["allowed_tools"]
    assert private["latest_turn_log"] == []
    assert private["runtime"] == {"release": "v3.2.0", "schema": "2.7.0", "split": "train"}
    names = [resolve(ref)["name"] for ref in visible["tool_schema_refs"]]
    kinds = {tool["name"]: tool["kind"] for app in catalog["apps"] for tool in app["tools"]}
    assert len(names) == len(set(names))
    assert set(names) == set(private["effective_tools"]) == set(private["tools"]) | {"sys.ask_missing_info"}
    if "installed_apps" in visible["context"]:
        context_tools = {name for app in visible["context"]["installed_apps"].values() for name in app["tools"]}
        assert context_tools | {"sys.ask_missing_info"} == set(names)
    reference = read(ROOT / "private" / f"{sid}.json")
    initial = resolve(private["initial_state_ref"])
    assert initial == reference["initial_state"]
    assert out["provenance"]["kind"] == "prepared_from_canonical_local_execution"
    assert out["final_text"] is None and out["availability"]["final_text"] == "not_captured"
    assert out["availability"]["model_run"] == "not_performed"
    assert out["availability"]["tokens_latency_timestamps"] == "not_captured"
    assert out["task_outcome"] == {"source_outcome": scenario["oracle_draft"]["outcome"], "status": "local_expected"}
    session = Session(sid, {**initial, "_meta": {"tools": private["tools"], "current_time": private["current_time"]}}, catalog)
    assert session.log == [] and session.get_state() == initial
    assert session.allowed == set(names)
    calls, ids = [], []
    for turn in visible["history"]:
        for c, r in zip(turn.get("tool_calls", []), turn.get("tool_results", [])):
            assert c["call_id"].startswith(inp["run_id"] + "/history/")
            ids.extend([c["call_id"], r["result_id"]])
    paired = out["execution"]
    assert len(paired["tool_calls"]) == len(paired["tool_results"])
    for c, r in zip(paired["tool_calls"], paired["tool_results"]):
        assert c["call_id"] == r["call_id"] and r["result_id"] == c["call_id"] + "/result"
        assert c["call_id"].startswith(inp["run_id"] + "/latest/")
        ids.extend([c["call_id"], r["result_id"]])
        result = session.call(c["name"], c["arguments"])
        assert result == r["payload"], (sid, c["call_id"], "Runtime result differs")
        calls.append({"name": c["name"], "arguments": c["arguments"], "result": result,
                      "state_after": session.get_state()})
    assert len(ids) == len(set(ids))
    assert session.log == [{k: c[k] for k in ("name", "arguments", "result")} for c in calls]
    final = session.get_state()
    assert final == resolve(out["private_final_state_ref"]) == reference["final_state"]
    canonical_calls = resolve(out["provenance"]["reference_trace_ref"])
    assert [{k: c[k] for k in ("name", "arguments", "result")} for c in calls] == [
        {k: c[k] for k in ("name", "arguments", "result")} for c in canonical_calls
    ]
    if sid == "TR15_PLANNING_TOMORROW":
        verdict = wave15.verify(scenario, original, reference["events"], initial, calls, final, reference["gold_actions"])
        assert final["reminders"] == initial["reminders"]
        assert calls[0]["arguments"]["start"] == "2027-09-18T08:20:00+07:00"
        assert out["termination"]["status"] == "completed"
    elif sid == "B02_N_C":
        verdict = batch02.verify(initial, scenario, calls, final, kinds, None, "Trao đổi mẫu gốm", ["Nộp phiếu giao hàng"])
        assert calls[-1]["result"]["waiting_for_user"] is True
        assert out["termination"]["status"] == "waiting_for_user" and final == initial
    else:
        verdict = wave16.verify(scenario["oracle_draft"], original["allowed_tools"], initial, calls)
        assert out["termination"]["status"] == "completed" and final == initial
        assert out["local_verification"]["answer_content"]["reason"] == "answer_optional"
    assert verdict == reference["canonical_local_verdict"] == out["local_verification"]["tool_state"]
    assert verdict["verdict"] == "pass"
    assert session.allowed == set(private["effective_tools"])
    print(f"{sid}: existing verifier pass; responses, final state and permissions match")


def check_all():
    catalog = read(ROOT / "catalog.json")
    assert catalog["schema_version"] == "2.7.0"
    tools = {t["name"]: t for app in catalog["apps"] for t in app["tools"]}
    assert tools == read(ROOT / "tool_schemas.json")
    runs = [read(ROOT / f"{sid}.input.json")["run_id"] for sid in SAMPLES]
    assert len(runs) == len(set(runs))
    for sid in SAMPLES:
        verify_case(sid, catalog)
    print("PASS: all three reference traces; Python stdlib only")


def main():
    import argparse
    import shutil
    import tempfile
    import zipfile
    parser = argparse.ArgumentParser(description="Verify authored references using your authorized external SDK.")
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    global ROOT, Session
    source = ROOT
    with tempfile.TemporaryDirectory(prefix="lifemate_three_cases_") as directory:
        ROOT = Path(directory)
        # Copy only our synthetic envelopes/private evidence; SDK stays temporary.
        for file in source.glob("*.json"):
            shutil.copyfile(file, ROOT / file.name)
        (ROOT / "private").mkdir()
        for file in (source / "private").glob("*.json"):
            shutil.copyfile(file, ROOT / "private" / file.name)
        provenance = read(source / "SOURCES.json")
        with zipfile.ZipFile(args.archive) as archive:
            assert "v3.2.0" in archive.read("train+public_test/VERSION").decode("utf8")
            for member in provenance["sdk_members"]:
                relative = member.removeprefix("train+public_test/train/")
                assert relative.startswith("zaic_tools/") and ".." not in Path(relative).parts
                destination = ROOT / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(member))
            full = json.loads(archive.read("train+public_test/train/train_tools_catalog.json"))
        assert full["schema_version"] == "2.7.0"
        names = {ref["selector"][1:] for sid in SAMPLES
                 for ref in read(source / f"{sid}.input.json")["agent_visible"]["tool_schema_refs"]}
        catalog = {**full, "apps": []}
        for app in full["apps"]:
            tools = [tool for tool in app["tools"] if tool["name"] in names]
            if tools: catalog["apps"].append({**app, "tools": tools})
        schemas = {tool["name"]: tool for app in catalog["apps"] for tool in app["tools"]}
        assert set(schemas) == names
        for filename, value in [("catalog.json", catalog), ("tool_schemas.json", schemas)]:
            (ROOT / filename).write_text(json.dumps(value, ensure_ascii=False), encoding="utf8")
        sys.path.insert(0, str(ROOT))
        from zaic_tools.executor import Session
        check_all()


if __name__ == "__main__":
    main()
