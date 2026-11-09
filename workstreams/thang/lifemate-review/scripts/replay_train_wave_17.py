"""Replay a relative calendar edit against the observed original interval."""
import os
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from replay_train_wave_08 import ROOT, gold_observations, matches, run, verify
from replay_train_wave_09 import effects, normalize

DESIGN = ROOT / "data/synthetic/design/train_wave_17.yaml"
OUTPUT = ROOT / "artifacts/synthetic/train_wave_17_replay/replay.json"


def calendar_verdict(world, scenario, initial, calls, final, kinds, **_):
    oracle = scenario["oracle_draft"]
    rule = oracle["time_rule"]
    target = gold_observations(world, initial)[rule["target"]]
    interval = {k: datetime.fromisoformat(target[k]) for k in ("start", "end")}
    delta = timedelta(minutes=rule["minutes"])
    if rule["mode"] == "shift":
        interval["start"] += delta
    else:
        assert rule["mode"] == "extend"
    interval["end"] += delta
    args = oracle["actions"][0][1]
    assert all(datetime.fromisoformat(args.get(k, target[k])) == v for k, v in interval.items())

    def equivalent(action):
        name, fields = action
        if name == "calendar.update_event" and fields.get("event_id") == target["id"]:
            fields = dict(fields)
            for key in ("start", "end"):
                if fields.get(key):
                    try:
                        instant = datetime.fromisoformat(fields[key])
                    except (ValueError, TypeError):
                        continue
                    if instant.tzinfo is not None:
                        fields[key] = (target[key] if instant == datetime.fromisoformat(target[key])
                                       else instant.astimezone(timezone.utc).isoformat())
            fields = {k: v for k, v in fields.items() if k not in target or v != target[k]}
        return normalize((name, fields))

    def calendar_effects(before, after, actions):
        # Preserve every other field and entity. Compare target timestamps as instants.
        after = deepcopy(after)
        record = next((r for r in after["calendar"]["events"] if r["id"] == target["id"]), None)
        if record is None:
            return False
        for key, expected in interval.items():
            try:
                if datetime.fromisoformat(record[key]) == expected:
                    record[key] = args.get(key, target[key])
            except (KeyError, TypeError, ValueError):
                return False
        return effects(before, after, actions)

    verdict = verify(world, scenario, initial, calls, final, kinds,
                     effects=calendar_effects, normalize_action=equivalent)
    required = {k: target[k] for k in ("id", "title", "location", "start", "end")}
    prefix = calls[:next((i for i, c in enumerate(calls) if kinds[c["name"]] != "read"), len(calls))]
    if not any(c["name"] == "calendar.list_events" and c["result"].get("ok") is True
               and any(matches(r, required) for r in c["result"].get("events", [])) for c in prefix):
        verdict["verdict"] = "reject"
        verdict["reasons"] = sorted(set(verdict["reasons"]) | {"source_interval"})
    return verdict


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    run(args.archive, args.output, design_path=DESIGN, verifier=calendar_verdict)
