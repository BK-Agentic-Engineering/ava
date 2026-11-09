"""Replay Wave 10 using the existing trace loop and local app effect checks."""
import os
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
import argparse
import re

from replay_batch03 import ROOT
from replay_train_wave_01 import canonical
from replay_train_wave_08 import row, run, verify as verify_trace

DESIGN = ROOT / "data/synthetic/design/train_wave_10.yaml"
OUTPUT = ROOT / "artifacts/synthetic/train_wave_10_replay/replay.json"


def verify(world, scenario, initial, calls, final, kinds, **options):
    # Explicitly passing the observed stored default is equivalent to omitting
    # mode. Keep this equivalence local to the two default-mode requests.
    if scenario["scenario_id"] in {"TR10_ROBOT_INHERIT", "TR10_ROBOT_RESTARTALL"}:
        calls = deepcopy(calls)
        observed_mode = None
        for call in calls:
            if (call["name"] == "robot_vacuum.get_status"
                    and call["name"] in scenario["agent_visible"]["allowed_tools"]
                    and call["result"].get("ok") is True
                    and call["result"].get("done") is not False):
                observed_mode = call["result"].get("mode")
            if (call["name"] == "robot_vacuum.start" and observed_mode is not None
                    and call["arguments"].get("mode") == observed_mode):
                call["arguments"].pop("mode")
    return verify_trace(world, scenario, initial, calls, final, kinds, **options)


def normalize(action):
    name, args = action
    if name in {"reminders.create", "alarm.create"} and args.get("repeat") is None:
        args = {**args, "repeat": "once"}
    if name == "appliances.start_cycle":
        args = {**args, "cycle": args["cycle"].lower(), "delay_minutes": args.get("delay_minutes") or 0}
    if name == "robot_vacuum.start" and "rooms" in args:
        args = dict(args)
        if args["rooms"] is None or args["rooms"] == []:
            args.pop("rooms")
        else:
            args["rooms"] = sorted(args["rooms"])
    if name == "alarm.update":
        optional = {"time", "label", "enabled"}
        args = {key: value for key, value in args.items() if key not in optional or value is not None}
    return canonical([name, args])


def effects(initial, final, actions):
    expected = deepcopy(initial)
    created = defaultdict(list)
    for name, args in actions:
        app, operation = name.split(".")
        state = expected[app]
        if app == "reminders":
            if operation == "create":
                created[app, "reminders"].append({**args, "repeat": args.get("repeat") or "once", "done": False})
            else:
                reminder = row(state["reminders"], args["reminder_id"])
                if operation == "complete":
                    reminder["done"] = True
                else:
                    state["reminders"].remove(reminder)
        elif app == "appliances":
            appliance = row(state["appliances"], args["appliance_id"])["state"]
            if operation == "stop":
                appliance.update(status="idle", cycle=None, delay_minutes=0)
            else:
                delay = args.get("delay_minutes") or 0
                appliance.update(status="scheduled" if delay else "running",
                                 cycle=args["cycle"].lower(), delay_minutes=delay)
        elif app == "door_lock":
            if operation == "set_lock":
                row(state["locks"], args["lock_id"])["locked"] = args["locked"]
            else:
                created[app, "guest_codes"].append({k: v for k, v in args.items() if v is not None})
        elif app == "home_security":
            state["mode"] = args["mode"]
        elif app == "smart_home":
            if operation == "scene_run":
                scene = row(state["scenes"], args["scene_id"])
                for change in scene["actions"]:
                    row(state["devices"], change["device_id"])["state"].update(change["state"])
                state["active_scene"] = scene["id"]
            else:
                device = row(state["devices"], args["device_id"])
                device["state"].update({k: v for k, v in args.items() if k != "device_id" and v is not None})
        elif app == "phone":
            created[app, "calls"].append({
                "contact_id": None, "phone_number": args["phone_number"], "status": "dialing",
            })
        elif app == "alarm":
            if operation == "create":
                created[app, "alarms"].append({**args, "repeat": args.get("repeat") or "once", "enabled": True})
            else:
                alarm = row(state["alarms"], args["alarm_id"])
                if operation == "delete":
                    state["alarms"].remove(alarm)
                else:
                    alarm.update({k: v for k, v in args.items() if k != "alarm_id" and v is not None})
        elif app == "robot_vacuum":
            if operation == "stop":
                state.update(status="docked", current_job=None)
            else:
                picked = args.get("rooms") or []
                state.update(status="cleaning", current_job={
                    "rooms": [room for room in state["rooms"] if not picked or room in picked],
                    "whole_house": not picked,
                    "mode": args.get("mode") or state["mode"],
                })
        else:
            raise AssertionError(f"Missing Wave 10 effect check for {name}")

    for (app, collection), payloads in created.items():
        previous = {record["id"] for record in initial[app][collection]}
        records = final[app][collection]
        if len({record["id"] for record in records}) != len(records):
            return False
        added = [record for record in records if record["id"] not in previous]
        actual = [{k: v for k, v in record.items() if k != "id"} for record in added]
        if app == "door_lock":
            for payload in actual:
                if not re.fullmatch(r"[0-9]{6}", payload.pop("code", "")):
                    return False
        if Counter(map(canonical, actual)) != Counter(map(canonical, payloads)):
            return False
        expected[app][collection].extend(added)
    return expected == final


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    arguments = parser.parse_args()
    run(arguments.archive, arguments.output, design_path=DESIGN, effects=effects, normalize_action=normalize,
        verifier=verify)
