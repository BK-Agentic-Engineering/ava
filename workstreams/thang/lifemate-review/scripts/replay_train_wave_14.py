"""Context and competing-tool replay using the local Executor."""
import os
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from replay_batch03 import ROOT
from replay_train_wave_01 import canonical
from replay_train_wave_08 import load_design, run, verify as verify_trace

DESIGN = ROOT / "data/synthetic/design/train_wave_14.yaml"
OUTPUT = ROOT / "artifacts/synthetic/train_wave_14_replay/replay.json"


def payload(name, args, current_time=None):
    args = {key: value for key, value in args.items() if value is not None}
    if name == "calendar.create_event":
        args.setdefault("end", (datetime.fromisoformat(args["start"]) + timedelta(hours=1)).isoformat())
        return {**args, "status": "confirmed"}
    if name == "reminders.create":
        return {"repeat": "once", **args, "done": False}
    if name == "alarm.create":
        return {"repeat": "once", **args, "enabled": True}
    if name == "tasks.add":
        return {"priority": "normal", "due": "", **args, "done": False}
    if name == "package_tracking.schedule_pickup":
        return {**args, "status": "scheduled"}
    if name == "fitness.log_workout":
        return {"time": current_time, **args}
    raise AssertionError(name)


COLLECTIONS = {
    "calendar.create_event": "events", "reminders.create": "reminders", "alarm.create": "alarms",
    "tasks.add": "tasks", "package_tracking.schedule_pickup": "pickups", "fitness.log_workout": "workouts",
}


def verify(world, scenario, initial, calls, final, kinds, **_):
    now = scenario["agent_visible"]["context"]["current_time"]

    def normalize(action):
        name, args = action
        return canonical([name, payload(name, args, now) if name in COLLECTIONS else args])

    def effects(before, after, actions):
        expected = deepcopy(before)
        created = defaultdict(list)
        for name, args in actions:
            app = name.split(".")[0]
            if name == "fitness.set_goal":
                expected[app]["goal_steps"] = args["steps"]
            elif name == "sys.ask_missing_info":
                continue
            else:
                created[app, COLLECTIONS[name]].append(payload(name, args, now))
        for (app, collection), desired in created.items():
            old = {r["id"] for r in before[app][collection]}
            rows = after[app][collection]
            added = [r for r in rows if r["id"] not in old]
            if len({r["id"] for r in rows}) != len(rows) or Counter(
                canonical({k: v for k, v in r.items() if k != "id"}) for r in added
            ) != Counter(map(canonical, desired)):
                return False
            expected[app][collection].extend(added)
        return expected == after

    return verify_trace(world, scenario, initial, calls, final, kinds,
                        effects=effects, normalize_action=normalize)


def audit_context(design):
    scenarios = {s["scenario_id"]: s for s in design["scenarios"]}
    for s in scenarios.values():
        visible, oracle = s["agent_visible"], s["oracle_draft"]
        context = visible["context"]
        for source in oracle.get("context_checks", []):
            index, argument = source["action"], source["argument"]
            if "days" in source:
                local = datetime.fromisoformat(context["current_time"]).astimezone(ZoneInfo(context["timezone"]))
                date = local.date() + timedelta(days=source["days"])
                expected = date.isoformat()
                if "clock" in source:
                    expected = datetime.combine(date, datetime.strptime(source["clock"], "%H:%M").time(),
                                                local.tzinfo).isoformat()
            elif source.get("profile"):
                expected = context["user_profile"][source["profile"]]
            else:
                assert source["runtime_now"]
                expected = context["current_time"]
            name, args = oracle["actions"][index]
            assert payload(name, args, context["current_time"]).get(argument) == expected
        if "forecast_city" in oracle:
            city = context["user_profile"]["city"]
            world = next(w for w in design["worlds"] if w["world_id"] == s["world_id"])
            local = datetime.fromisoformat(context["current_time"]).astimezone(ZoneInfo(context["timezone"]))
            tomorrow = (local.date() + timedelta(days=1)).isoformat()
            witnesses = [world["witnesses"][alias][1]
                         for clause in oracle["decision_evidence"] for alias in clause
                         if not alias.startswith("@")]
            assert witnesses and all(witness["date"] == tomorrow for witness in witnesses)
            assert all(world["witnesses"][alias][1]["location"] == city
                       for clause in oracle["decision_evidence"] for alias in clause
                       if not alias.startswith("@") and alias != "fallback")
            assert oracle["forecast_city"] == city
        if s.get("contrast", {}).get("changes") == "context_only":
            other = scenarios[s["contrast"]["with"]]
            assert (s["world_id"], s["fixture_variant"]) == (other["world_id"], other["fixture_variant"])
            counterpart = other["agent_visible"]
            assert {k: v for k, v in visible.items() if k != "context"} == {
                k: v for k, v in counterpart.items() if k != "context"
            }
            assert sum(context.get(k) != counterpart["context"].get(k)
                       for k in context.keys() | counterpart["context"].keys()) == 1
            profile = context.get("user_profile", {})
            other_profile = counterpart["context"].get("user_profile", {})
            if profile != other_profile:
                assert sum(profile.get(k) != other_profile.get(k)
                           for k in profile.keys() | other_profile.keys()) == 1
            def gold(scenario):
                oracle = scenario["oracle_draft"]
                time = scenario["agent_visible"]["context"]["current_time"]
                return oracle["outcome"], [payload(n, a, time) if n in COLLECTIONS else a
                                            for n, a in oracle["actions"]]
            assert gold(s) != gold(other)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    audit_context(load_design(DESIGN))
    run(args.archive, args.output, design_path=DESIGN, verifier=verify)
