from copy import deepcopy
from .history import successful

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
