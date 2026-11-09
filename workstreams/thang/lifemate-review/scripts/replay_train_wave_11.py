"""Local Wave 11 replay with explicit clarification and capability policy."""
import os
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

from replay_batch03 import ROOT
from replay_train_wave_01 import canonical
from replay_train_wave_08 import load_design, row, run, verify as verify_trace

DESIGN = ROOT / "data/synthetic/design/train_wave_11.yaml"
OUTPUT = ROOT / "artifacts/synthetic/train_wave_11_replay/replay.json"


def normalize(action):
    name, args = action
    args = dict(args)
    if name == "sys.ask_missing_info":
        args["params"] = sorted(args["params"])
    if name == "calendar.create_event" and args.get("end") is None:
        args["end"] = (datetime.fromisoformat(args["start"]) + timedelta(hours=1)).isoformat()
    if name == "tasks.add":
        for key, default in {"due": "", "priority": "normal"}.items():
            if args.get(key) is None:
                args[key] = default
    if name == "alarm.create" and args.get("repeat") is None:
        args["repeat"] = "once"
    if name == "home_automation.create_rule":
        args["time"] = args["time"][:5]
        if args.get("title") is None:
            args["title"] = ""
    return canonical([name, args])


def effects(initial, final, actions):
    expected = deepcopy(initial)
    created = defaultdict(list)
    for name, args in actions:
        app, operation = name.split(".")
        state = expected[app]
        if app == "sys":
            continue
        if app == "package_tracking":
            created[app, "pickups"].append({**args, "status": "scheduled"})
        elif app == "banking":
            account = row(state["accounts"], args["from_account_id"])
            account["balance"] -= args["amount"]
            created[app, "savings"].append({
                "account_id": account["id"], "amount": args["amount"],
                "term_months": args["term_months"], "status": "active",
            })
        elif app == "calendar":
            payload = {**args, "status": "confirmed"}
            payload.setdefault("end", (datetime.fromisoformat(args["start"]) + timedelta(hours=1)).isoformat())
            created[app, "events"].append(payload)
        elif app == "tasks":
            created[app, "tasks"].append({"due": "", "priority": "normal", **args, "done": False})
        elif app == "household_chores":
            row(state["chores"], args["chore_id"])["assignee"] = args["assignee"]
        elif app == "music":
            if operation == "play":
                if "track_id" in args:
                    track = row(state["tracks"], args["track_id"])
                    state["now_playing"] = {"track_id": track["id"], "title": track["title"], "status": "playing"}
                else:
                    playlist = row(state["playlists"], args["playlist_id"])
                    state["now_playing"] = {"playlist_id": playlist["id"], "name": playlist["name"], "status": "playing"}
            elif operation == "control":
                state["volume"] = args["volume"]
            else:
                playlist = row(state["playlists"], args["playlist_id"])
                if args["track_id"] not in playlist["track_ids"]:
                    playlist["track_ids"].append(args["track_id"])
        elif app == "alarm":
            if operation == "create":
                created[app, "alarms"].append({"repeat": "once", **args, "enabled": True})
            else:
                alarm = row(state["alarms"], args["alarm_id"])
                if operation == "delete":
                    state["alarms"].remove(alarm)
                else:
                    alarm.update({k: v for k, v in args.items() if k != "alarm_id" and v is not None})
        elif app == "home_automation":
            if operation == "delete_rule":
                state["rules"].remove(row(state["rules"], args["rule_id"]))
            else:
                created[app, "rules"].append({"title": "", **args, "time": args["time"][:5], "enabled": True})
        else:
            raise AssertionError(f"Missing Wave 11 effect check for {name}")
    for (app, collection), payloads in created.items():
        before = {record["id"] for record in initial[app][collection]}
        records = final[app][collection]
        if len({record["id"] for record in records}) != len(records):
            return False
        added = [record for record in records if record["id"] not in before]
        actual = [{k: v for k, v in record.items() if k != "id"} for record in added]
        if Counter(map(canonical, actual)) != Counter(map(canonical, payloads)):
            return False
        expected[app][collection].extend(added)
    return expected == final


def verify(world, scenario, initial, calls, final, kinds, **options):
    verdict = verify_trace(world, scenario, initial, calls, final, kinds, **options)
    if scenario["oracle_draft"]["outcome"] == "out_of_scope" and calls:
        verdict["reasons"] = sorted(set(verdict["reasons"]) | {"authorized_actions"})
        verdict["verdict"] = "reject"
    return verdict


def audit_contrasts():
    design = load_design(DESIGN)
    scenarios = {s["scenario_id"]: s for s in design["scenarios"]}
    for scenario in scenarios.values():
        contrast = scenario.get("contrast", {})
        if contrast.get("changes") not in {"history_only", "permissions_only"}:
            continue
        other = scenarios[contrast["with"]]
        assert (scenario["world_id"], scenario["fixture_variant"]) == (other["world_id"], other["fixture_variant"])
        key = "history" if contrast["changes"] == "history_only" else "allowed_tools"
        left, right = deepcopy(scenario["agent_visible"]), deepcopy(other["agent_visible"])
        assert left.pop(key) != right.pop(key)
        assert left == right


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    arguments = parser.parse_args()
    audit_contrasts()
    run(arguments.archive, arguments.output, design_path=DESIGN, effects=effects,
        normalize_action=normalize, verifier=verify)
