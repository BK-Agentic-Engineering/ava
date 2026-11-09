"""Replay combined historical, current-context and competing-tool decisions offline."""
import os
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
from time import perf_counter
import zipfile
from zoneinfo import ZoneInfo

from replay_train_wave_01 import canonical
from replay_train_wave_08 import load_design, validate as validate_collection
from replay_train_wave_13 import ROOT, argument, execute_history, successful
from replay_train_wave_14 import COLLECTIONS, payload

DESIGN = ROOT / "data/synthetic/design/train_wave_15.yaml"
OUTPUT = ROOT / "artifacts/synthetic/train_wave_15_replay/replay.json"
ARCHIVE = Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip"))
READS = {"reminders.list", "calendar.list_events", "tasks.list", "package_tracking.track",
         "fitness.get_activity", "contacts.search", "contacts.get", "notes.list"}
CREATES = {**COLLECTIONS, "notes.create": "notes"}


def effect(name, args, now):
    if name == "notes.create":
        return {"title": "", **args}
    return payload(name, args, now)


def comparable(record):
    normalized = dict(record)
    for field in {"start", "end", "due", "time"} & record.keys():
        value = record[field]
        if value and "T" in value:
            timestamp = datetime.fromisoformat(value)
            if timestamp.tzinfo is not None:
                normalized[field] = timestamp.astimezone(timezone.utc).isoformat()
    return normalized


def verify(scenario, visible, events, initial, calls, final, actions):
    oracle = scenario["oracle_draft"]
    reasons = set()
    writes = [c for c in calls if c["name"] not in READS]
    if any(c["name"] not in visible["allowed_tools"] for c in calls):
        reasons.add("permission")
    if any(not successful(c) for c in calls):
        reasons.add("unsuccessful_call")
    now = visible["context"]["current_time"]

    def token(name, args):
        return canonical([name, comparable(effect(name, args, now)) if name in CREATES else args])

    if Counter(token(c["name"], c["arguments"]) for c in writes) != Counter(
        token(name, args) for name, args in actions
    ):
        reasons.add("authorized_actions")
    desired = deepcopy(initial)
    for name, args in actions:
        app = name.split(".")[0]
        collection = CREATES[name]
        old = {row["id"] for row in initial[app][collection]}
        record = effect(name, args, now)
        found = next((r for r in final[app][collection] if r["id"] not in old
                      and r not in desired[app][collection]
                      and comparable({k: v for k, v in r.items() if k != "id"}) == comparable(record)), None)
        if found is None:
            reasons.add("state")
        else:
            desired[app][collection].append(found)
    if desired != final:
        reasons.add("state")

    for tag in oracle.get("history_required", []):
        event = events[tag]
        if not successful(event) or not any(
            call == {"name": event["name"], "arguments": event["arguments"]} and result == event["result"]
            for turn in visible["history"] if turn["role"] == "assistant"
            for call, result in zip(turn["tool_calls"], turn["tool_results"])
        ):
            reasons.add("historical_grounding")
    for index in oracle.get("user_history_required", []):
        expected = {"role": "user", "audio_text": scenario["historical_turns"][index]["user"]}
        if visible["history"][2 * index:2 * index + 1] != [expected]:
            reasons.add("historical_grounding")

    if oracle.get("fresh_contact"):
        identity = argument(oracle["fresh_contact"], events)
        contact = next(r for r in initial["contacts"]["contacts"] if r["id"] == identity)
        consumers = {actions[c["action"]][0] for c in oracle["source_checks"] if c.get("current_contact")}
        prefix = calls[:next((i for i, c in enumerate(calls) if c["name"] in consumers), len(calls))]
        if not any(c["name"] in {"contacts.search", "contacts.get"} and successful(c)
                   and c["name"] in visible["allowed_tools"]
                   and any(r.get("id") == identity and "email" in r and r["email"] == contact["email"]
                           for r in c["result"].get("contacts", [])) for c in prefix):
            reasons.add("fresh_observation")

    return {"verdict": "reject" if reasons else "pass", "reasons": sorted(reasons),
            "official_call_matching": "not_evaluated"}


def audit_sources(oracle, context, events, initial, actions):
    for check in oracle.get("source_checks", []):
        actual = actions[check["action"]][1][check["field"]]
        if "history" in check:
            expected = argument(check["history"], events)
        if "profile" in check:
            expected = context["user_profile"][check["profile"]]
        if check.get("runtime_now"):
            expected = context["current_time"]
        if "days" in check:
            local = datetime.fromisoformat(context["current_time"]).astimezone(ZoneInfo(context["timezone"]))
            day = local.date() + timedelta(days=check["days"])
            expected = day.isoformat()
            if "clock" in check:
                clock = datetime.fromisoformat(argument(check["clock"], events)).timetz().replace(tzinfo=None)
                expected = datetime.combine(day, clock, local.tzinfo).isoformat()
        if "current_contact" in check:
            identity = argument(oracle["fresh_contact"], events)
            expected = next(r["email"] for r in initial["contacts"]["contacts"] if r["id"] == identity)
        if "add" in check:
            expected += check["add"]
        if "template" in check:
            expected = check["template"].format(expected)
        assert actual == expected, (check, actual, expected)


def run(archive, output, *, group=None):
    start = perf_counter()
    design = load_design(DESIGN)
    docs = [load_design(p) for p in sorted(DESIGN.parent.glob("*.yaml"))]
    inventory = validate_collection(next(d for d in docs if d["version"] == "train_wave_14"), docs)
    assert (design["split"], design["status"], design["exportable"]) == ("train", "spec_only", False)
    worlds = {w["world_id"]: w for w in design["worlds"]}
    scenarios = {s["scenario_id"]: s for s in design["scenarios"]}
    for world in worlds.values():
        assert scenarios[world["design_base"]]["world_id"] == world["world_id"]
        assert world["origin"] == "train_derivative" and world["ancestry"]["parent_scenario_ids"]
    provenance = design["provenance"]
    tools = {name for w in worlds.values() for name in w["relevant_tools"]}
    apps = sorted({name.split(".")[0] for name in tools} - {"sys"})
    paths = ["__init__.py", "executor.py", "validate.py", "utils.py", "apps/__init__.py",
             "apps/base.py", "apps/sys.py"] + [f"apps/{app}.py" for app in apps]
    members = [provenance["runtime_root"] + path for path in paths] + [provenance["catalog_member"]]
    output.parent.mkdir(parents=True, exist_ok=True)
    evidence, rows = {}, []
    with tempfile.TemporaryDirectory(prefix="wave15_", dir=output.parent) as directory:
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
            fixture.write_text(canonical({"wave15": {**state, "sys": {},
                                                     "_meta": {"tools": allowed, "current_time": now}}}),
                               encoding="utf-8")
            return Executor(str(fixture), str(catalog))

        for sid, scenario in scenarios.items():
            world = worlds[scenario["world_id"]]
            if group and world["family"] != group:
                continue
            visible = deepcopy(scenario["agent_visible"])
            context = visible["context"]
            oracle = scenario["oracle_draft"]
            allowed = visible["allowed_tools"]
            assert allowed == world["relevant_tools"] and world["split"] == "train"
            assert scenario["status"] == "spec_only" and scenario["exportable"] is False
            assert visible["history"] == []
            state = deepcopy(world["initial_state"])
            assert not any(r["id"] in canonical(visible) for app in state.values()
                           for records in app.values() if isinstance(records, list)
                           for r in records if isinstance(r, dict) and "id" in r)
            pre = deepcopy(state)
            history, events, historical_calls, turn_times = [], {}, [], []
            for turn in scenario["historical_turns"]:
                now = turn["current_time"]
                assert datetime.fromisoformat(now) <= datetime.fromisoformat(context["current_time"])
                assert not turn_times or datetime.fromisoformat(now) >= datetime.fromisoformat(turn_times[-1])
                turn_times.append(now)
                session = executor(state, now, allowed).open("wave15")
                # Wave 13 helper executes one turn; resolve any prior-turn references first.
                commands = [{**c, "arguments": argument(c["arguments"], events)} for c in turn["calls"]]
                assert len({c["tag"] for c in commands}) == len(commands)
                assert all(c["tag"] not in events for c in commands)
                turns, observed, calls = execute_history(session, [{**turn, "calls": commands}])
                history.extend(turns)
                historical_calls.extend(calls)
                events.update(observed)
                state = session.get_state()
            visible["history"] = history
            assert set(visible) == {"request", "context", "history", "allowed_tools"}
            assert [{"name": call["name"], "arguments": call["arguments"], "result": result}
                    for turn in history if turn["role"] == "assistant"
                    for call, result in zip(turn["tool_calls"], turn["tool_results"])] == historical_calls
            latest = executor(state, context["current_time"], allowed)
            initial = latest.open("wave15").get_state()
            actions = argument(oracle["actions"], events)
            audit_sources(oracle, context, events, initial, actions)
            evidence[sid] = {"agent_visible": visible, "pre_history_state": pre, "post_history_state": initial,
                             "historical_calls": historical_calls, "historical_current_times": turn_times,
                             "gold_actions": actions}
            for case, trace in {"standard": {"calls": oracle.get("reads", []) + oracle["actions"]},
                                **oracle["variants"]}.items():
                session = latest.open("wave15")
                assert session.log == [] and session.get_state() == initial
                assert session.allowed == set(allowed) | {"sys.ask_missing_info"}
                calls = []
                for name, args in argument(trace["calls"], events):
                    result = session.call(name, args)
                    calls.append({"name": name, "arguments": deepcopy(args), "result": deepcopy(result)})
                assert calls == session.log
                assert all(successful(c) and c["name"] in allowed for c in calls), (sid, case, calls)
                final = session.get_state()
                verdict = verify(scenario, visible, events, initial, calls, final, actions)
                assert verdict["reasons"] == trace.get("reasons", []), (sid, case, verdict)
                if case == "wrong_tool":
                    assert calls[-1]["name"] not in {a[0] for a in actions} and final != initial
                rows.append({"scenario_id": sid, "trace_case": case, "evidence_kind": "actual_runtime_trace",
                             "calls": calls, "final_state": final, "verdict": verdict})
            assert latest.open("wave15").get_state() == initial

    for sid, record in evidence.items():
        pair = scenarios[sid].get("contrast")
        if not pair:
            continue
        other = evidence[pair["with"]]
        assert record["gold_actions"] != other["gold_actions"]
        a, b = record["agent_visible"], other["agent_visible"]
        assert {key for key in a if a[key] != b[key]} == {pair["changes"]}, sid
        if pair["changes"] != "history":
            assert record["post_history_state"] == other["post_history_state"]
        if pair["changes"] == "context":
            def leaves(context):
                return {**{k: v for k, v in context.items() if k != "user_profile"},
                        **{f"user_profile.{k}": v for k, v in context.get("user_profile", {}).items()}}
            left, right = leaves(a["context"]), leaves(b["context"])
            assert sum(left.get(k) != right.get(k) for k in left.keys() | right.keys()) == 1
    result = {"created_utc": datetime.now(timezone.utc).isoformat(), "replay_wall_seconds": perf_counter() - start,
              "declared_volatile_fields": ["created_utc", "replay_wall_seconds"],
              "inventory": inventory, "provenance": {**provenance, "archive": str(archive), "python": sys.version,
                                                     "allowlisted_members": members},
              "scenarios": evidence, "replays": rows,
              "status": {"standards": len(evidence), "historical_calls": sum(len(e["historical_calls"]) for e in evidence.values()),
                         "historical_noops": sum(not successful(c) for e in evidence.values() for c in e["historical_calls"]),
                         "outcomes": dict(Counter(scenarios[sid]["oracle_draft"]["outcome"] for sid in evidence)),
                         "verdicts": dict(Counter(r["verdict"]["verdict"] for r in rows)),
                         "verifier_only_probes": 0, "execution_verified": 0, "exportable": False}}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(result["status"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--group", choices=["planning", "pickup", "fitness", "contact"])
    args = parser.parse_args()
    run(args.archive, args.output, group=args.group)
