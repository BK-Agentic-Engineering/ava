"""Wave 12 local replay with explicit family effects and a current-alert check."""
import os
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

from replay_batch03 import ROOT
from replay_train_wave_01 import canonical
from replay_train_wave_08 import load_design, observe, row, run
from replay_train_wave_11 import normalize as previous_normalize, verify as verify_policy

DESIGN = ROOT / "data/synthetic/design/train_wave_12.yaml"
OUTPUT = ROOT / "artifacts/synthetic/train_wave_12_replay/replay.json"


def normalize(action):
    name, args = action
    if name == "shopping_list.add" and args.get("quantity") is None:
        args = {**args, "quantity": 1}
    if name == "banking.transfer":
        args = {**args, "note": args.get("note")}
    return previous_normalize((name, args))


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
        elif app == "notes":
            if operation == "create":
                created[app, "notes"].append({"title": "", **args})
            else:
                note = row(state["notes"], args["note_id"])
                note["content"] = note["content"] + "\n" + args["content"] if note["content"] else args["content"]
        elif app == "alarm":
            created[app, "alarms"].append({"repeat": "once", **args, "enabled": True})
        elif app == "shopping_list":
            if operation == "add":
                created[app, "items"].append({"quantity": 1, **args, "checked": False})
            else:
                item = row(state["items"], args["item_id"])
                if operation == "remove":
                    state["items"].remove(item)
                else:
                    item["checked"] = True
        elif app == "library":
            book = row(state["books"], args["book_id"])
            created[app, "reservations"].append({
                "book_id": book["id"], "status": "ready" if book["available"] else "waiting",
            })
            book["available"] = False
        elif app == "banking":
            account = row(state["accounts"], args["from_account_id"])
            account["balance"] -= args["amount"]
            created[app, "transactions"].append({
                "account_id": account["id"], "beneficiary_id": args["beneficiary_id"],
                "amount": -args["amount"], "note": args.get("note"),
            })
        elif app == "learning":
            course = row(state["courses"], args["course_id"])
            if operation == "enroll":
                course["enrolled"] = True
            elif operation == "schedule_lesson":
                created[app, "lessons"].append({**args, "status": "scheduled"})
            else:
                course["progress_minutes"] += args["minutes"]
                created[app, "progress"].append(args)
        elif app == "tv":
            if operation == "tune":
                state.update(channel=args["channel"], power="on")
            else:
                program = row(state["programs"], args["program_id"])
                created[app, "recordings"].append({
                    "program_id": program["id"], "channel": program["channel"],
                    "start": program["start"], "status": "scheduled",
                })
        elif app == "home_security":
            if operation == "arm":
                state["mode"] = args["mode"]
            else:
                row(state["alerts"], args["alert_id"])["acknowledged"] = True
        else:
            raise AssertionError(f"Missing Wave 12 effect check for {name}")
    for (app, collection), payloads in created.items():
        previous = {record["id"] for record in initial[app][collection]}
        records = final[app][collection]
        if len({record["id"] for record in records}) != len(records):
            return False
        added = [record for record in records if record["id"] not in previous]
        actual = [{k: v for k, v in record.items() if k != "id"} for record in added]
        if Counter(map(canonical, actual)) != Counter(map(canonical, payloads)):
            return False
        expected[app][collection].extend(added)
    return expected == final


def verify(world, scenario, initial, calls, final, kinds, **options):
    verdict = verify_policy(world, scenario, initial, calls, final, kinds, **options)
    if scenario["oracle_draft"].get("current_alert_before_arm"):
        observed, history = {}, []
        for call in calls:
            if call["name"] in scenario["agent_visible"]["allowed_tools"]:
                if kinds[call["name"]] == "read":
                    observe(world, call, observed, history)
                elif call["name"] == "home_security.arm" and "acknowledged" not in observed:
                    verdict["reasons"] = sorted(set(verdict["reasons"]) | {"current_alert_evidence"})
                    verdict["verdict"] = "reject"
    return verdict


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    run(args.archive, args.output, design_path=DESIGN, effects=effects,
        normalize_action=normalize, verifier=verify)
