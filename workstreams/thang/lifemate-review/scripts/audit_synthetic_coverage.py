"""Read-only counts from synthetic designs and their canonical replay evidence."""
import os
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import unicodedata
import zipfile

from replay_train_wave_08 import ROOT, load_design, validate

CATALOG = "train+public_test/train/train_tools_catalog.json"
WORDING_MARKERS = {
    "guard": r"\b(giữ nguyên|không (tạo|đổi|sửa|xóa|thêm)|đừng)\b",
    "reference": r"\b(vừa|lần trước|theo lịch|như cũ|đã chốt)\b",
    "correction": r"\b(à không|đổi ý|chứ không|thay vì|bỏ đề xuất)\b",
    "condition": r"\b(nếu|trừ khi|chỉ khi)\b",
    "copy": r"\b(nguyên văn|đúng chữ|tên chính xác)\b",
}


def components(worlds, scenarios):
    neighbors = {wid: set() for wid in worlds}
    for wid, world in worlds.items():
        ancestry = world.get("ancestry", {})
        parents = set(ancestry.get("parent_world_ids", []))
        parents.update(scenarios[sid]["world_id"] for sid in ancestry.get("parent_scenario_ids", []))
        for parent in parents:
            neighbors[wid].add(parent)
            neighbors[parent].add(wid)
    counts = Counter()
    while neighbors:
        start = next(iter(neighbors))
        pending = [start]
        split = worlds[start]["split"]
        while pending:
            current = pending.pop()
            if current in neighbors:
                assert worlds[current]["split"] == split
                pending.extend(neighbors.pop(current))
        counts[split] += 1
    return counts


def passed(row):
    verdict = row["verdict"]
    return verdict.get("verdict") == "pass" or verdict.get("passed") is True


def successful(call):
    result = call["result"]
    return result.get("ok") is True and result.get("done") is not False


def report(archive):
    with zipfile.ZipFile(archive) as source:
        catalog = json.loads(source.read(CATALOG))
    assert catalog["schema_version"] == "2.7.0"
    tools = {t["name"]: (a["id"], a["group"], t["kind"]) for a in catalog["apps"] for t in a["tools"]}
    docs = [load_design(p) for p in sorted((ROOT / "data/synthetic/design").glob("*.yaml"))]
    inventory = validate(next(d for d in docs if d["version"] == "train_wave_14"), docs)
    inventory.pop("near_duplicate_review", None)  # This label describes the Wave 14 review.
    worlds = {w["world_id"]: w for d in docs for w in d["worlds"]}
    scenarios = {s["scenario_id"]: s for d in docs for s in d["scenarios"]}
    summary = defaultdict(Counter)
    requests = defaultdict(list)
    all_rows = []
    for doc in docs:
        artifact = ROOT / "artifacts/synthetic" / (doc["version"] + "_replay") / "replay.json"
        evidence = json.loads(artifact.read_text(encoding="utf-8"))
        all_rows.extend(evidence["replays"])
        by_id = defaultdict(list)
        for row in evidence["replays"]:
            by_id[row["scenario_id"]].append(row)
        assert set(by_id) == {s["scenario_id"] for s in doc["scenarios"]}
        for scenario in doc["scenarios"]:
            sid = scenario["scenario_id"]
            oracle = scenario["oracle_draft"]
            outcome = oracle["outcome"]
            # Prefer a passing standard. Early batches sometimes name it by action.
            accepted = [r for r in by_id[sid] if passed(r)
                        and not r.get("evidence_kind", "").startswith("verifier_only")]
            standard = next((r for r in accepted if r["trace_case"] == "standard"), None)
            if standard is None:
                summary["named_standard_fallback"][doc["version"]] += 1
                case = {"out_of_scope": "no_calls", "ask_missing": "direct_ask", "execute": "cancel"}[outcome]
                standard = next(r for r in accepted if r["trace_case"] == case)
            ref = standard.get("initial_fixture_ref", sid)
            views = evidence.get("agent_visible", {})
            visible = views.get(sid, views.get(ref, scenario["agent_visible"]))
            if "scenarios" in evidence:
                visible = evidence["scenarios"][sid]["agent_visible"]
            context, history = visible.get("context", {}), visible.get("history", [])
            allowed = visible["allowed_tools"]
            split = worlds[scenario["world_id"]]["split"]
            assert scenario["status"] == "spec_only" and not scenario.get("exportable", False)
            summary["outcomes"][split + "/" + outcome] += 1
            summary["allowlist_width"][len(allowed)] += 1
            summary["context_keys"].update(context.keys())
            summary["profile_keys"].update(context.get("user_profile", {}).keys())
            if history:
                summary["history_cases"][split] += 1
            prior = []
            for turn in history:
                if turn.get("role") != "assistant":
                    continue
                calls, results = turn.get("tool_calls", []), turn.get("tool_results", [])
                if calls or results:
                    prior.extend({**c, "result": r} for c, r in zip(calls, results, strict=True))
            if prior:
                summary["history_with_results"][split] += 1
                summary["historical_calls"][doc["version"]] += len(prior)
                summary["historical_noops"][doc["version"]] += sum(
                    c["result"].get("done") is False for c in prior
                )
            request = unicodedata.normalize("NFC", visible["request"]).casefold()
            summary["wording_markers"].update(k for k, pattern in WORDING_MARKERS.items() if re.search(pattern, request))
            requests[" ".join(re.findall(r"\w+", request))].append(sid)

            calls = standard["calls"]
            if "initial_state" in standard:
                initial = standard["initial_state"]
            elif "scenarios" in evidence:
                initial = evidence["scenarios"][sid]["post_history_state"]
            else:
                initial = evidence["fixtures"][ref]
            final = standard["final_state"]
            changed = {app for app in initial.keys() | final.keys()
                       if app != "_meta" and initial.get(app) != final.get(app)}
            summary["changed_apps"].update(changed)
            summary["changed_apps_by_count"][len(changed)] += 1
            if outcome != "execute":
                assert not changed, (sid, changed)
            if not changed and outcome == "execute":
                summary["execute_without_state_delta"][sid] += 1
            names = {c["name"] for c in calls if successful(c)}
            assert names <= set(allowed) | {"sys.ask_missing_info"}, sid
            for name in set(allowed):
                summary["allowed_tools"][name] += 1
            for name in names:
                summary["accepted_tools"][name] += 1
            writes = [c for c in calls if tools[c["name"]][2] == "write" and successful(c)]
            summary["successful_writes_by_count"][len(writes)] += 1
            summary["accepted_write_tools"].update({c["name"] for c in writes})
            summary["accepted_domains"].update({tools[n][1] for n in names if tools[n][2] != "meta"})
            summary["accepted_write_apps"].update({tools[c["name"]][0] for c in writes})
            if any(tools[n][2] == "read" for n in names):
                summary["read_present_by_outcome"][outcome] += 1
            if not calls:
                summary["empty_log_by_outcome"][outcome] += 1
            summary["authored_ordered_flag"][outcome] += bool(oracle.get("ordered"))
    summary["components"] = components(worlds, scenarios)
    summary["replay_rows"]["total"] = len(all_rows)
    summary["replay_rows"]["pass"] = sum(map(passed, all_rows))
    summary["replay_rows"]["marked_verifier_only"] = sum(
        row.get("evidence_kind", "").startswith("verifier_only") for row in all_rows
    )
    summary["mail_hold"]["cases"] = sum(s["lineage_id"] == "TRAIN_MAIL_DISPOSITION_01" for s in scenarios.values())
    repeated = [ids for ids in requests.values() if len(ids) > 1]
    summary["normalized_request_groups"]["repeated"] = len(repeated)
    summary["normalized_request_groups"]["cases_in_repeated_groups"] = sum(map(len, repeated))
    summary["normalized_request_groups"]["cross_split"] = sum(
        len({worlds[scenarios[sid]["world_id"]]["split"] for sid in ids}) > 1 for ids in repeated
    )
    summary["catalog"]["tools"] = len(tools)
    summary["catalog"]["allowed_unique"] = len(summary["allowed_tools"])
    summary["catalog"]["successful_standard_unique"] = len(summary["accepted_tools"])
    summary["catalog"]["successful_write_standard_unique"] = len(summary["accepted_write_tools"])
    return {"inventory": inventory, **summary}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    args = parser.parse_args()
    print(json.dumps(report(args.archive), ensure_ascii=False, indent=2))
