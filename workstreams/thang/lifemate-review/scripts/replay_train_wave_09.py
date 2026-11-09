"""Replay Wave 09 with app-specific effect checks and the reviewed local trace loop."""
import os
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import argparse
import re

from replay_batch03 import ROOT
from replay_train_wave_01 import canonical
from replay_train_wave_08 import row, run

DESIGN = ROOT / "data/synthetic/design/train_wave_09.yaml"
OUTPUT = ROOT / "artifacts/synthetic/train_wave_09_replay/replay.json"


def event_payload(args):
    result = {key: value for key, value in args.items() if value is not None}
    if "end" not in result:
        result["end"] = (datetime.fromisoformat(args["start"]) + timedelta(hours=1)).isoformat()
    return result


def normalize(action):
    name, args = action
    if name == "calendar.create_event":
        args = event_payload(args)
    elif name == "calendar.update_event":
        optional_fields = {"title", "start", "end", "location"}
        args = {key: value for key, value in args.items() if key not in optional_fields or value is not None}
    elif name == "video_meeting.create":
        args = {**args, "attendees": sorted(args.get("attendees") or [])}
    elif name == "package_tracking.reschedule_delivery":
        args = {**args, "tracking_id": "".join(args["tracking_id"].split()).upper()}
    return canonical([name, args])


def effects(initial, final, actions):
    expected = deepcopy(initial)
    created = defaultdict(list)
    for name, args in actions:
        app, operation = name.split(".")
        state = expected[app]
        if app == "calendar":
            if operation == "create_event":
                created[app, "events"].append({**event_payload(args), "status": "confirmed"})
            else:
                event = row(state["events"], args["event_id"])
                if operation == "cancel_event":
                    event["status"] = "cancelled"
                else:
                    event.update({k: v for k, v in args.items() if k != "event_id" and v is not None})
        elif app == "video_meeting":
            if operation == "join":
                row(state["meetings"], args["meeting_id"])["status"] = "joined"
            else:
                created[app, "meetings"].append({
                    **args, "attendees": sorted(args.get("attendees") or []), "status": "scheduled",
                })
        elif app == "banking":
            account = row(state["accounts"], args["from_account_id"])
            account["balance"] -= args["amount"]
            created[app, "savings"].append({
                "account_id": account["id"], "amount": args["amount"],
                "term_months": args["term_months"], "status": "active",
            })
        elif app == "ewallet":
            state["balance"] -= args["amount"]
            created[app, "transactions"].append({
                **args, "amount": -args["amount"], "type": operation,
            })
        elif app == "news":
            if not any(entry["article_id"] == args["article_id"] for entry in state["saved"]):
                created[app, "saved"].append(args)
        elif app == "package_tracking":
            if operation == "schedule_pickup":
                created[app, "pickups"].append({**args, "status": "scheduled"})
            else:
                code = "".join(args["tracking_id"].split()).upper()
                shipment = next(r for r in state["shipments"] if r["tracking_id"] == code)
                shipment["scheduled_time"] = args["time"]
        elif app == "music":
            if operation == "play":
                if "track_id" in args:
                    track = row(state["tracks"], args["track_id"])
                    state["now_playing"] = {"track_id": track["id"], "title": track["title"], "status": "playing"}
                else:
                    playlist = row(state["playlists"], args["playlist_id"])
                    state["now_playing"] = {"playlist_id": playlist["id"], "name": playlist["name"], "status": "playing"}
            elif operation == "control":
                action = args["action"]
                if action == "volume":
                    state["volume"] = args["volume"]
                else:
                    state["now_playing"]["status"] = {"pause": "paused", "resume": "playing"}[action]
            else:
                playlist = row(state["playlists"], args["playlist_id"])
                if args["track_id"] not in playlist["track_ids"]:
                    playlist["track_ids"].append(args["track_id"])
        else:
            raise AssertionError(f"Missing Wave 09 effect check for {name}")

    for (app, collection), payloads in created.items():
        old = {r["id"] for r in initial[app][collection]}
        records = final[app][collection]
        if len({r["id"] for r in records}) != len(records):
            return False
        added = [r for r in records if r["id"] not in old]
        actual = [{k: v for k, v in record.items() if k != "id"} for record in added]
        if app == "video_meeting":
            for payload in actual:
                link = payload.pop("link", "")
                if not re.fullmatch(r"https://meet\.example\.test/[a-z]{3}-[a-z]{4}-[a-z]{3}", link):
                    return False
                payload["attendees"] = sorted(payload["attendees"])
        if Counter(map(canonical, actual)) != Counter(map(canonical, payloads)):
            return False
        expected[app][collection].extend(added)
    return expected == final


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    arguments = parser.parse_args()
    run(arguments.archive, arguments.output, design_path=DESIGN, effects=effects, normalize_action=normalize)
