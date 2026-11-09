from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from .canonical import canonical
from .history import argument, successful
from .payloads import payload, COLLECTIONS

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
