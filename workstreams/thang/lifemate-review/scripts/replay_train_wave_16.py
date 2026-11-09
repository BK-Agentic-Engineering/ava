"""Run Wave 16 recovery branches in the pinned local Executor."""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
from time import perf_counter
import zipfile

from audit_synthetic_coverage import components
from replay_train_wave_08 import load_design, validate
from replay_train_wave_13 import ROOT, execute_history, successful
from replay_train_wave_01 import canonical
from replay_train_wave_15 import ARCHIVE

DESIGN = ROOT / "data/synthetic/design/train_wave_16.yaml"
OUTPUT = ROOT / "artifacts/synthetic/train_wave_16_replay/replay.json"
READS = {"package_tracking.track": "shipments", "library.search": "books",
         "appliances.list": "appliances", "maps.search_place": "places"}


def expected_after(before, name, args, result):
    after = deepcopy(before)
    if name in READS or not successful({"result": result}):
        return after
    app = after[name.split(".")[0]]
    if name == "package_tracking.reschedule_delivery":
        row = next(r for r in app["shipments"] if r["tracking_id"] == args["tracking_id"])
        row["scheduled_time"] = args["time"]
    elif name == "library.reserve":
        row = next(r for r in app["books"] if r["id"] == args["book_id"])
        app["reservations"].append({"id": result["reservation"]["id"], "book_id": row["id"],
                                    "status": "ready" if row["available"] else "waiting"})
        row["available"] = False
    elif name in {"appliances.start_cycle", "appliances.stop"}:
        row = next(r for r in app["appliances"] if r["id"] == args["appliance_id"])
        row["state"] = ({"status": "idle", "cycle": None, "delay_minutes": 0}
                        if name.endswith(".stop") else
                        {"status": "scheduled" if args.get("delay_minutes") else "running",
                         "cycle": args["cycle"], "delay_minutes": args.get("delay_minutes", 0)})
    elif name == "maps.save_place":
        row = next((r for r in app["saved_places"] if r["place_id"] == args["place_id"]), None)
        if row is None:
            app["saved_places"].append({"id": result["id"], **args})
        else:
            row["label"] = args["label"]
    elif name == "reminders.create":
        app["reminders"].append({"id": result["id"], "repeat": "once", "done": False, **args})
    elif name == "tasks.add":
        app["tasks"].append({"id": result["id"], "due": "", "priority": "normal", "done": False, **args})
    else:
        raise AssertionError(name)
    return after


def verify(oracle, allowed, initial, calls):
    reasons, observed, sequence = set(), set(), []
    efficiency_notes = set()
    before = initial
    for c in calls:
        name, args, result, after = (c[k] for k in ("name", "arguments", "result", "state_after"))
        action = [name, args]
        if name not in allowed:
            reasons.add("permission")
        if result.get("ok") is not True:
            reasons.add("call_failure")
        elif name in READS:
            records = result.get(READS[name])
            if result.get("done") is False or not isinstance(records, list):
                reasons.add("unqualified_read")
                records = None
            for row in records or []:
                if name == oracle.get("reader"):
                    observed.add(row.get("id"))
                    if oracle.get("trigger_read") and all(
                        row.get(k) == v for k, v in oracle["trigger_read"].items()
                    ):
                        observed.add("trigger")
            for key, label in [("empty_query", "absence"), ("second_absence", "second_absence")]:
                query = oracle.get(key)
                if records is not None and query and name == query[0]:
                    if action == query and not records:
                        observed.add(label)
                    # These authored scopes use exact addresses and one query word.
                    if name == "maps.search_place" and args == {"query": query[1]["query"]}:
                        if all(r["address"] != query[1]["near"] for r in records):
                            observed.add(label)
                    if name == "package_tracking.track" and not args:
                        if all(r["tracking_id"] != query[1]["tracking_id"] for r in records):
                            observed.add(label)
        elif action == oracle.get("primary"):
            if oracle.get("ground_primary") and oracle["ground_primary"] not in observed:
                reasons.add("primary_grounding")
            if result.get("done") is False:
                sequence.append("noop")
                if result.get("message") != oracle.get("noop_message") or before != after:
                    reasons.add("unqualified_noop")
                else:
                    if "trigger" in observed and not oracle.get("require_attempt"):
                        efficiency_notes.add("redundant_attempt")
                    observed.add("attempt_trigger")
            else:
                sequence.append("primary")
        elif action == oracle.get("fallback") or action == oracle.get("followup"):
            token = "fallback" if action == oracle.get("fallback") else "followup"
            sequence.append(token)
            if result.get("done") is False and (
                not oracle.get("fallback_noop_message")
                or result.get("message") != oracle["fallback_noop_message"] or before != after
            ):
                reasons.add("unqualified_noop")
            if token == "fallback":
                qualifiers = {"attempt_trigger"}
                if not oracle.get("require_attempt"):
                    qualifiers.add("trigger")
                    if oracle.get("fallback_on_absence"):
                        qualifiers.add("absence")
                if not qualifiers & observed or "primary" in sequence[:-1]:
                    reasons.add("fallback_authorization")
            if oracle.get("ground_fallback") and oracle["ground_fallback"] not in observed:
                reasons.add("fallback_grounding")
        else:
            reasons.add("unauthorized_action")
        if name in READS or result.get("ok") is not True or result.get("done") is False:
            if before != after:
                reasons.add("state")
        elif action in [oracle.get("primary"), oracle.get("fallback"), oracle.get("followup")]:
            if expected_after(before, name, args, result) != after:
                reasons.add("state")
        before = after
    if sequence not in oracle["sequences"]:
        reasons.add("branch")
    if oracle.get("require_absence") and "absence" not in observed:
        reasons.add("absence_evidence")
    if oracle.get("second_absence") and not {"absence", "second_absence"} <= observed:
        reasons.add("second_absence_evidence")
    if oracle.get("require_trigger") and "trigger" not in observed:
        reasons.add("trigger_evidence")
    verdict = {"verdict": "reject" if reasons else "pass", "reasons": sorted(reasons), "sequence": sequence}
    if efficiency_notes:
        verdict["efficiency_notes"] = sorted(efficiency_notes)
    return verdict


def run(archive, output, pilot=False):
    start = perf_counter()
    design = load_design(DESIGN)
    docs = [load_design(p) for p in sorted(DESIGN.parent.glob("*.yaml"))]
    inventory = validate(next(d for d in docs if d["version"] == "train_wave_14"), docs)
    inventory.pop("near_duplicate_review", None)
    worlds = {w["world_id"]: w for w in design["worlds"]}
    assert (design["split"], design["status"], design["exportable"]) == ("train", "spec_only", False)
    inventory["components"] = components({w["world_id"]: w for d in docs for w in d["worlds"]},
                                        {s["scenario_id"]: s for d in docs for s in d["scenarios"]})
    provenance = design["provenance"]
    apps = sorted({t.split(".")[0] for w in worlds.values() for t in w["relevant_tools"]} - {"sys"})
    paths = ["__init__.py", "executor.py", "validate.py", "utils.py", "apps/__init__.py",
             "apps/base.py", "apps/sys.py"] + [f"apps/{app}.py" for app in apps]
    members = [provenance["runtime_root"] + p for p in paths] + [provenance["catalog_member"]]
    output.parent.mkdir(parents=True, exist_ok=True)
    rows, records, outcomes = [], {}, Counter()
    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        root = Path(directory)
        with zipfile.ZipFile(archive) as source:
            for path, member in zip(paths, members):
                target = root / "zaic_tools" / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read(member))
            catalog = root / "catalog.json"
            catalog.write_bytes(source.read(members[-1]))
        spec = json.loads(catalog.read_text(encoding="utf-8"))
        assert spec["schema_version"] == provenance["schema"]
        assert "zaic_tools" not in sys.modules
        sys.path.insert(0, str(root))
        from zaic_tools.executor import Executor

        def executor(state, now, allowed):
            fixture = root / "synthetic.json"
            fixture.write_text(canonical({"wave16": {**state, "sys": {},
                                                     "_meta": {"tools": allowed, "current_time": now}}}),
                               encoding="utf-8")
            return Executor(str(fixture), str(catalog))

        for s in design["scenarios"]:
            if pilot and not s.get("pilot"):
                continue
            sid = s["scenario_id"]
            world = worlds[s["world_id"]]
            visible, oracle = deepcopy(s["agent_visible"]), s["oracle_draft"]
            context, allowed = visible["context"], visible["allowed_tools"]
            assert s["status"] == "spec_only" and s["exportable"] is False
            assert world["split"] == "train" and allowed == world["relevant_tools"]
            assert s["fixture_variant"] == "base" or s["fixture_variant"] in world["variants"]
            state = deepcopy(world["initial_state"])
            for app, patch in world["variants"].get(s["fixture_variant"], {}).items():
                state[app].update(deepcopy(patch))
            historical_calls = []
            for turn in s.get("historical_turns", []):
                assert datetime.fromisoformat(turn["current_time"]) < datetime.fromisoformat(context["current_time"])
                session = executor(state, turn["current_time"], allowed).open("wave16")
                turns, _, calls = execute_history(session, [turn])
                visible["history"].extend(turns)
                historical_calls.extend(calls)
                state = session.get_state()
            latest = executor(state, context["current_time"], allowed)
            initial = latest.open("wave16").get_state()
            records[sid] = {"agent_visible": visible, "post_history_state": initial,
                            "historical_calls": historical_calls}
            outcomes[oracle["outcome"]] += 1
            for case, trace in s["traces"].items():
                session = latest.open("wave16")
                assert session.log == [] and session.get_state() == initial
                assert session.allowed == set(allowed) | {"sys.ask_missing_info"}
                calls = []
                for name, args in trace["calls"]:
                    validation = session.validate(name, args)
                    result = session.call(name, args)
                    calls.append({"name": name, "arguments": deepcopy(args), "result": deepcopy(result),
                                  "state_after": session.get_state(), "validation": validation})
                assert [{k: c[k] for k in ("name", "arguments", "result")} for c in calls] == session.log
                verdict = verify(oracle, allowed, initial, calls)
                assert verdict["reasons"] == sorted(trace.get("reject", [])), (sid, case, verdict)
                if case == "standard":
                    assert verdict["verdict"] == "pass"
                rows.append({"scenario_id": sid, "trace_case": case, "evidence_kind": "actual_runtime_trace",
                             "calls": calls, "final_state": session.get_state(), "verdict": verdict})
            assert latest.open("wave16").get_state() == initial
    result = {"created_utc": datetime.now(timezone.utc).isoformat(),
              "replay_wall_seconds": perf_counter() - start,
              "declared_volatile_fields": ["created_utc", "replay_wall_seconds"],
              "inventory": inventory, "provenance": {**provenance, "archive": str(archive), "allowlisted_members": members},
              "scenarios": records, "replays": rows,
              "status": {"outcomes": outcomes, "historical_calls": sum(len(s["historical_calls"]) for s in records.values()),
                         "verdicts": Counter(r["verdict"]["verdict"] for r in rows),
                         "standard_sequences": Counter("+".join(r["verdict"]["sequence"]) or "no_write"
                                                       for r in rows if r["trace_case"] == "standard"),
                         "verifier_only_probes": 0, "execution_verified": 0, "exportable": False}}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(result["status"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--pilot", action="store_true")
    args = parser.parse_args()
    run(args.archive, args.output, args.pilot)
