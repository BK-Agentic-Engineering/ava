"""Evaluate scoped, authored Vietnamese factual-answer probes against canonical evidence."""
import json
import re
import unicodedata
from collections import Counter
from functools import cache

from replay_train_wave_08 import ROOT, load_design

SPEC = ROOT / "data/synthetic/factual_answer_pilot.yaml"


@cache
def canonical_sources(version):
    design = load_design(SPEC.parent / "design" / (version + ".yaml"))
    artifact = ROOT / "artifacts/synthetic" / (version + "_replay") / "replay.json"
    return {s["scenario_id"]: s for s in design["scenarios"]}, json.loads(artifact.read_text(encoding="utf-8"))


def at(value, path):
    for key in path:
        value = value[key]
    return value


def check_source(case):
    scenarios, artifact = canonical_sources(case["design"])
    sid = case["scenario_id"]
    scenario = scenarios[sid]
    assert case["split"] == "train" and scenario["status"] == "spec_only" and not scenario["exportable"]
    assert scenario["oracle_draft"]["outcome"] == "observe_no_write"
    visible = artifact.get("scenarios", {}).get(sid, {}).get(
        "agent_visible", artifact.get("agent_visible", {}).get(sid, scenario["agent_visible"]))
    assert visible["request"] == scenario["agent_visible"]["request"] == case["request"]
    row = next(r for r in artifact["replays"] if r["scenario_id"] == sid and r["trace_case"] == "standard"
               and r["verdict"]["verdict"] == "pass")
    source = case["evidence"]
    if source["kind"] == "latest":
        assert case["fresh"] is True
        call = row["calls"][source["call"]]
        name, result = call["name"], call["result"]
    else:
        assert source["kind"] == "history" and case["fresh"] is False
        turn = visible["history"][source["turn"]]
        assert turn["role"] == "assistant" and len(turn["tool_calls"]) == len(turn["tool_results"])
        name = turn["tool_calls"][source["call"]]["name"]
        result = turn["tool_results"][source["call"]]
    assert name == source["tool"] and name in visible["allowed_tools"]
    assert result["ok"] is True and result.get("done") is not False
    for claim in source["claims"]:
        assert at(result, claim["path"]) == claim["value"], (sid, claim)
    if "superseded_by" in source:
        later = source["superseded_by"]
        later_call = turn["tool_calls"][later["call"]]
        later_result = turn["tool_results"][later["call"]]
        assert later["call"] > source["call"] and later_call["name"] == later["tool"]
        assert later_result["ok"] is True and later_result.get("done") is not False
        assert later_result["item"]["id"] == result["contacts"][0]["id"]
        assert later_result["item"]["email"] == later["value"]
    if "complete_collection" in source:
        # Set claims are scoped to the full unfiltered returned collection.
        assert call["arguments"] == {}
        collection = source["complete_collection"]
        assert len(result[collection]) == source["collection_size"]


def normalize(text):
    return " ".join(unicodedata.normalize("NFC", text).casefold().split()).rstrip(".! ")


def grade(case, text):
    """Grade only recognized whole answers. Other formulations go to review."""
    if text is None or not text.strip():
        return ("fail", "missing_answer") if case["required"] else ("pass", "answer_optional")
    text = normalize(text)
    for reason, patterns in case["fail"].items():
        if any(re.fullmatch(pattern, text) for pattern in patterns):
            return "fail", reason
    if any(re.fullmatch(pattern, text) for pattern in case["pass"]):
        return "pass", "supported_facts"
    # The pilot's canonical paths contain no reminder creation.
    suffix = ". tôi đã tạo lời nhắc"
    if text.endswith(suffix) and any(re.fullmatch(pattern, text.removesuffix(suffix)) for pattern in case["pass"]):
        return "fail", "unsupported_action_claim"
    return "unresolved", "outside_scoped_rules"


def overall(trace_verdict, answer_verdict):
    if "fail" in (trace_verdict, answer_verdict):
        return "fail"
    if trace_verdict == answer_verdict == "pass":
        return "pass"
    return "unresolved"


def evaluate(spec=SPEC):
    design = load_design(spec)
    assert design["provenance"] == "authored_evaluation_probes"
    rows = []
    ids = set()
    for case in design["cases"]:
        sid = case["scenario_id"]
        assert sid not in ids
        ids.add(sid)
        check_source(case)
        probes = set()
        for probe in case["probes"]:
            assert probe["id"] not in probes
            probes.add(probe["id"])
            verdict, reason = grade(case, probe["text"])
            assert [verdict, reason] == probe["expect"], (sid, probe["id"], verdict, reason)
            rows.append({"scenario_id": sid, "probe_id": probe["id"], "trace_verdict": "pass",
                         "answer_verdict": verdict, "reason": reason, "overall": overall("pass", verdict)})
    return {"scenarios": len(ids), "verdict_counts": dict(Counter(r["answer_verdict"] for r in rows)), "probes": rows}


if __name__ == "__main__":
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
