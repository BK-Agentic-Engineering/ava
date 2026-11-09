"""Execute authored history, then replay a fresh latest turn with visible provenance."""
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

from replay_batch03 import ROOT
from replay_train_wave_01 import canonical
from replay_train_wave_08 import load_design, validate as validate_collection

DESIGN = ROOT / "data/synthetic/design/train_wave_13.yaml"
OUTPUT = ROOT / "artifacts/synthetic/train_wave_13_replay/replay.json"


def argument(value, events):
    if isinstance(value, str) and value.startswith("$"):
        parts = value[1:].split(".")
        result = events[parts[0]]["result"]
        for key in parts[1:]:
            result = result[key]
        return deepcopy(result)
    if isinstance(value, dict) and "observed" in value:
        records = events[value["observed"]]["result"][value["collection"]]
        hits = [r for r in records if all(r.get(k) == v for k, v in value["match"].items())]
        assert len(hits) == 1, value
        return deepcopy(hits[0][value["field"]])
    if isinstance(value, dict):
        return {key: argument(item, events) for key, item in value.items()}
    if isinstance(value, list):
        return [argument(item, events) for item in value]
    return value


def successful(event):
    return event["result"].get("ok") is True and event["result"].get("done") is not False


def execute_history(session, plan):
    turns, events, calls = [], {}, []
    assert session.log == []
    for turn in plan:
        turns.append({"role": "user", "audio_text": turn["user"]})
        paired_calls, results = [], []
        for command in turn["calls"]:
            args = argument(command["arguments"], events)
            before = session.get_state()
            result = session.call(command["name"], args)
            event = {"name": command["name"], "arguments": deepcopy(args), "result": deepcopy(result)}
            assert result.get("ok") is True, event
            if command.get("expect") == "noop":
                assert result.get("done") is False and session.get_state() == before
            else:
                assert successful(event), event
            events[command["tag"]] = {
                **event, "position": len(calls),
                "state_unchanged": session.get_state() == before,
            }
            paired_calls.append({"name": command["name"], "arguments": deepcopy(args)})
            results.append(deepcopy(result))
            calls.append(event)
        turns.append({"role": "assistant", "text": turn.get("assistant_text", ""),
                      "tool_calls": paired_calls, "tool_results": results})
    assert session.log == calls
    return turns, events, calls


def canonical_state(state):
    result = deepcopy(state)
    for collections in result.values():
        for key, values in collections.items():
            if isinstance(values, list) and all(isinstance(v, dict) and "id" in v for v in values):
                collections[key] = sorted(values, key=lambda v: v["id"])
    return result


def selected(scenario, events):
    oracle = scenario["oracle_draft"]
    event = events[oracle["target_event"]]
    if oracle.get("selection") not in {"last_attempt", "last_failed_transfer"}:
        assert successful(event)
    if oracle.get("selection") in {"last_created", "first_created"}:
        choices = [e for e in events.values() if e["name"] == "reminders.create" and successful(e)]
        chosen = choices[-1 if oracle["selection"] == "last_created" else 0]
        assert chosen == event
    if oracle.get("selection") in {"last_successful_start", "last_attempt", "last_successful_transfer"}:
        tool = "banking.transfer" if oracle["selection"] == "last_successful_transfer" else "appliances.start_cycle"
        choices = [e for e in events.values() if e["name"] == tool and
                   (oracle["selection"] == "last_attempt" or successful(e))]
        assert choices[-1] == event
    if oracle.get("selection") == "last_failed_transfer":
        choices = [e for e in events.values() if e["name"] == "banking.transfer" and not successful(e)]
        assert choices[-1] == event and event["result"].get("done") is False
    record = event["result"].get("item", event["result"].get("transaction", {}))
    if oracle.get("record_match"):
        records = event["result"][oracle.get("record_collection", "contacts")]
        record = next(r for r in records if all(r.get(k) == v for k, v in oracle["record_match"].items()))
    if oracle.get("selection") == "last_attempt":
        record = known_record(events, event["arguments"]["appliance_id"])
    assert all(record.get(k) == v for k, v in oracle.get("expected_identity", {}).items())
    return deepcopy(record)


def known_record(events, identity):
    known = None
    for event in events.values():
        if not successful(event):
            continue
        item = event["result"].get("item")
        if item and item.get("id") == identity:
            known = item
        for value in event["result"].values():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and item.get("id") == identity:
                        known = item
    assert known is not None, identity
    return deepcopy(known)


def desired_reminder(scenario, source):
    result = {k: source[k] for k in ["content", "time", "repeat", "done"]}
    result["time"] = (datetime.fromisoformat(source["time"]) +
                      timedelta(minutes=scenario["oracle_draft"]["minutes"])).isoformat()
    return result


def has_source_evidence(scenario, initial, calls, events, visible):
    family = scenario.get("family", "reminders")
    knowledge = {}

    def retain(name, result):
        if not name.startswith(family + ".") or result.get("ok") is not True or result.get("done") is False:
            return
        def records(value):
            if isinstance(value, dict):
                if "id" in value:
                    knowledge[value["id"]] = value
                for item in value.values():
                    records(item)
            elif isinstance(value, list):
                for item in value:
                    records(item)
        records(result)

    for turn in visible["history"]:
        if turn["role"] == "assistant":
            for call, result in zip(turn["tool_calls"], turn["tool_results"]):
                retain(call["name"], result)
    read_tools = {"reminders.list", "appliances.list", "contacts.search",
                  "banking.get_balance", "banking.list_beneficiaries", "banking.list_transactions"}
    for call in calls:
        if call["name"] not in read_tools:
            break
        retain(call["name"], call["result"])
    oracle = scenario["oracle_draft"]
    if oracle["operation"] == "inspect":
        return True  # Factual response text is outside these tool-only verdicts.
    target = selected(scenario, events)
    if family == "contacts":
        if oracle["requires_history"]:
            return True  # The selected, exact historical event is checked separately.
        record = knowledge.get(target["id"], {})
        return all(record.get(key) == target[key] for key in oracle["value_fields"])
    if family == "banking":
        return all(args["from_account_id"] in knowledge and args["beneficiary_id"] in knowledge
                   for _, args in expected_family_writes(scenario, initial, events))
    collection = "reminders" if family == "reminders" else "appliances"
    if family == "appliances" and oracle["operation"] == "stop_both":
        targets = [r for r in initial[family][collection] if r["name"] in oracle["requested_names"]]
    else:
        targets = [r for r in initial[family][collection] if r["id"] == target["id"]]
    return all(knowledge.get(record["id"]) == record for record in targets)


def expected_family_writes(scenario, initial, events):
    oracle = scenario["oracle_draft"]
    family = scenario["family"]
    target = selected(scenario, events)
    operation = oracle["operation"]
    if operation == "inspect":
        return []
    if family == "appliances":
        identity = target["id"]
        stop = ("appliances.stop", {"appliance_id": identity})
        if operation == "stop":
            return [stop]
        if operation == "stop_both":
            identities = [r["id"] for r in events["inventory"]["result"]["appliances"]
                          if r["name"] in oracle["requested_names"]]
            return [("appliances.stop", {"appliance_id": item}) for item in identities]
        assert operation == "restart"
        current = next(r for r in initial["appliances"]["appliances"] if r["id"] == identity)
        prefix = [stop] if current["state"]["status"] in {"running", "scheduled"} else []
        return prefix + [("appliances.start_cycle", {"appliance_id": identity, "cycle": oracle["cycle"]})]
    if family == "contacts":
        fields = oracle["value_fields"]
        value = oracle.get("separator", "").join(str(target[field]) for field in fields)
        return [("notes.create", {"title": oracle["note_title"], "content": value})]
    assert family == "banking"
    original = events[oracle["target_event"]]["arguments"]
    args = deepcopy(original)
    if operation == "repeat_changed_note":
        args["note"] = oracle["note"]
    if operation == "repeat_changed_amount":
        args["amount"] = oracle["amount"]
    if operation == "repeat_changed_source":
        account = next(r for r in events["inventory"]["result"]["accounts"] if r["name"] == oracle["source_name"])
        args["from_account_id"] = account["id"]
    if operation == "repeat_changed_beneficiary":
        args["beneficiary_id"] = events[oracle["beneficiary_event"]]["arguments"]["beneficiary_id"]
    return [("banking.transfer", args)]


def apply_family_effects(initial, writes, calls):
    expected = deepcopy(initial)
    for name, args in writes:
        if name == "appliances.stop":
            item = next(r for r in expected["appliances"]["appliances"] if r["id"] == args["appliance_id"])
            item["state"].update(status="idle", cycle=None, delay_minutes=0)
        elif name == "appliances.start_cycle":
            item = next(r for r in expected["appliances"]["appliances"] if r["id"] == args["appliance_id"])
            item["state"].update(status="running", cycle=args["cycle"], delay_minutes=0)
        elif name == "notes.create":
            creates = [c for c in calls if c["name"] == "notes.create"]
            if len(creates) != 1:
                return None
            expected["notes"]["notes"].append({"id": creates[0]["result"]["id"], **args})
        elif name == "banking.transfer":
            creates = [c for c in calls if c["name"] == name]
            if len(creates) != 1:
                return None
            transaction = creates[0]["result"].get("transaction", {})
            account = next(r for r in expected["banking"]["accounts"] if r["id"] == args["from_account_id"])
            account["balance"] -= args["amount"]
            expected["banking"]["transactions"].append({
                "id": transaction.get("id"), "account_id": args["from_account_id"],
                "beneficiary_id": args["beneficiary_id"], "amount": -args["amount"], "note": args.get("note"),
            })
    return expected


def verify_family(scenario, initial, calls, final, events, visible, reasons):
    writes = expected_family_writes(scenario, initial, events)
    actual = [c for c in calls if c["name"] in {
        "appliances.stop", "appliances.start_cycle", "notes.create", "contacts.update", "banking.transfer",
    }]
    tokens = [canonical((c["name"], c["arguments"])) for c in actual]
    expected = [canonical(action) for action in writes]
    if scenario["oracle_draft"].get("ordered"):
        if tokens != expected:
            reasons.add("authorized_order_or_writes")
    elif Counter(tokens) != Counter(expected):
        reasons.add("authorized_writes")
    if any(not successful(c) for c in actual):
        reasons.add("latest_write_failed")
    state = apply_family_effects(initial, writes, calls)
    if state is None or canonical_state(state) != canonical_state(final):
        reasons.add("state")
    return {"verdict": "reject" if reasons else "pass", "reasons": sorted(reasons),
            "official_call_matching": "not_evaluated"}


def fresh_evidence(scenario, initial, calls, events):
    family = scenario.get("family", "reminders")
    target = selected(scenario, events)
    if family == "banking":
        tool, collection, fields = "banking.get_balance", "accounts", ["balance"]
        identity = events[scenario["oracle_draft"]["target_event"]]["arguments"]["from_account_id"]
    else:
        tool, collection, fields = {
            "reminders": ("reminders.list", "reminders", ["time"]),
            "appliances": ("appliances.list", "appliances", ["state"]),
            "contacts": ("contacts.search", "contacts", ["email"]),
        }[family]
        identity = target["id"]
    expected = next(row for row in initial[family][collection] if row["id"] == identity)
    reads = {"reminders.list", "appliances.list", "contacts.search",
             "banking.get_balance", "banking.list_transactions", "banking.list_beneficiaries"}
    for call in calls:
        if call["name"] not in reads:
            break
        if (call["name"] == tool and call["name"] in scenario["agent_visible"]["allowed_tools"]
                and successful(call) and any(
                    row.get("id") == identity and all(field in row and row[field] == expected[field] for field in fields)
                    for row in call["result"].get(collection, [])
                )):
            return True
    return False


def latest_family(session, scenario, events, case, call, calls):
    oracle = scenario["oracle_draft"]
    family = scenario["family"]
    initial = session.get_state()
    target = selected(scenario, events)
    if case == "omitted":
        return calls
    if case not in {"history_only", "late_read"} and (case == "fresh_lookup" or oracle.get("fresh_required")):
        if family == "appliances":
            call("appliances.list", {"type": "dryer"} if case == "unrelated_read" else {})
        elif family == "contacts":
            query = {"empty_read": "Không Có Liên Hệ 13", "unrelated_read": "Lê An Vân"}.get(case, target["name"])
            call("contacts.search", {} if case == "broad_read" else {"query": query})
        else:
            call("banking.get_balance", {})
            if not oracle.get("requires_history"):
                call("banking.list_beneficiaries", {})
    if case == "replay_action":
        event = events[oracle["replay_event"]]
        call(event["name"], event["arguments"])
    writes = expected_family_writes(scenario, initial, events)
    if case == "other":
        if family == "appliances":
            identity = oracle["other_name"]
            # The competing ID comes from the real historical list.
            item = next(r for r in events["inventory"]["result"]["appliances"] if r["name"] == identity)
            writes = [("appliances.stop", {"appliance_id": item["id"]})]
        elif family == "contacts":
            other = events[oracle["wrong_event"]]["result"]
            other = other["item"] if "item" in other else next(
                r for r in other["contacts"] if r["name"] == oracle.get("wrong_name", target["name"])
            )
            value = oracle.get("separator", "").join(str(other[f]) for f in oracle["value_fields"])
            writes = [("notes.create", {"title": oracle.get("note_title", "Không được ghi"), "content": value})]
        else:
            args = deepcopy(events[oracle["target_event"]]["arguments"])
            # Real beneficiary from the earlier successful list, different from the selected transfer.
            beneficiary = next(r for r in events["beneficiaries"]["result"]["beneficiaries"]
                               if r["id"] != args["beneficiary_id"])
            args["beneficiary_id"] = beneficiary["id"]
            args["amount"] = 50000
            writes = [("banking.transfer", args)]
    for name, args in writes:
        call(name, args)
    if case == "late_read":
        call("contacts.search", {"query": target["name"]})
    return calls


def verify(scenario, initial, calls, final, events, visible):
    oracle = scenario["oracle_draft"]
    target = selected(scenario, events)
    reasons = set()
    if any(c["name"] not in scenario["agent_visible"]["allowed_tools"] for c in calls):
        reasons.add("permission")
    if not has_source_evidence(scenario, initial, calls, events, visible):
        reasons.add("source_grounding")
    if oracle.get("fresh_required") and not fresh_evidence(scenario, initial, calls, events):
        reasons.add("fresh_observation")
    if oracle.get("requires_history"):
        historical = [(c, r) for turn in visible["history"] if turn["role"] == "assistant"
                      for c, r in zip(turn["tool_calls"], turn["tool_results"])]
        event = events[oracle["target_event"]]
        if not any(c == {k: event[k] for k in ["name", "arguments"]} and r == event["result"]
                   for c, r in historical):
            reasons.add("historical_grounding")
    family = scenario.get("family", "reminders")
    if family != "reminders":
        return verify_family(scenario, initial, calls, final, events, visible, reasons)
    expected = deepcopy(initial)
    writes = [c for c in calls if c["name"] != "reminders.list"]
    operation = oracle["operation"]
    identity = target["id"]
    source = next(r for r in initial["reminders"]["reminders"] if r["id"] == identity)
    if operation == "move":
        payload = desired_reminder(scenario, source)
        creates = [c for c in writes if c["name"] == "reminders.create"]
        deletes = [c for c in writes if c["name"] == "reminders.delete"]
        completes = [c for c in writes if c["name"] == "reminders.complete"]
        if len(creates) != 1 or len(deletes) != 1 or len(completes) != int(source["done"]):
            reasons.add("authorized_writes")
        else:
            made = creates[0]["result"].get("item", {})
            args = creates[0]["arguments"]
            if args != {k: payload[k] for k in ["content", "time", "repeat"]}:
                reasons.add("replacement_fields")
            if deletes[0]["arguments"] != {"reminder_id": identity}:
                reasons.add("target")
            if completes and completes[0]["arguments"] != {"reminder_id": made.get("id")}:
                reasons.add("completion_state")
            expected["reminders"]["reminders"] = [
                r for r in expected["reminders"]["reminders"] if r["id"] != identity
            ] + [{**payload, "id": made.get("id")}]
    elif operation == "delete":
        if [c["name"] for c in writes] != ["reminders.delete"] or writes[0]["arguments"] != {"reminder_id": identity}:
            reasons.add("target")
        expected["reminders"]["reminders"] = [r for r in expected["reminders"]["reminders"] if r["id"] != identity]
    elif operation == "complete":
        if len(writes) != 1 or writes[0]["name"] != "reminders.complete" or writes[0]["arguments"] != {"reminder_id": identity}:
            reasons.add("target")
        next(r for r in expected["reminders"]["reminders"] if r["id"] == identity)["done"] = True
    else:
        assert operation == "inspect"
        if writes:
            reasons.add("authorized_writes")
    if any(not successful(c) for c in writes):
        reasons.add("latest_write_failed")
    if canonical_state(expected) != canonical_state(final):
        reasons.add("state")
    return {"verdict": "reject" if reasons else "pass", "reasons": sorted(reasons),
            "official_call_matching": "not_evaluated"}


def latest(session, scenario, events, case):
    target = selected(scenario, events)
    calls = []

    def call(name, args):
        result = session.call(name, args)
        assert result.get("ok") is True, result
        calls.append({"name": name, "arguments": deepcopy(args), "result": deepcopy(result)})
        return result

    if scenario.get("family", "reminders") != "reminders":
        return latest_family(session, scenario, events, case, call, calls)
    source = known_record(events, target["id"])
    if case == "omitted":
        return calls
    if case != "history_only" and (case in {"fresh_lookup", "first_row", "last_row", "largest_id"} or scenario["oracle_draft"].get("fresh_required")):
        rows = call("reminders.list", {"date": "2027-07-14"} if case == "empty_read" else {})["reminders"]
        if case == "first_row":
            source = rows[0]
        elif case == "last_row":
            source = rows[-1]
        elif case == "largest_id":
            source = max(rows, key=lambda r: r["id"])
        elif case != "empty_read":
            source = next(r for r in rows if r["id"] == target["id"])
    if case == "other":
        source = events[scenario["oracle_draft"]["other_event"]]["result"]["item"]
    if case == "replay_creations":
        for event in events.values():
            if event["name"] == "reminders.create":
                call(event["name"], event["arguments"])
    operation = scenario["oracle_draft"]["operation"]
    if operation == "move":
        payload = desired_reminder(scenario, source)
        if case != "create_first":
            call("reminders.delete", {"reminder_id": source["id"]})
        result = call("reminders.create", {k: payload[k] for k in ["content", "time", "repeat"]})
        if case == "create_first":
            call("reminders.delete", {"reminder_id": source["id"]})
        if payload["done"]:
            call("reminders.complete", {"reminder_id": result["id"]})
    elif operation == "delete":
        call("reminders.delete", {"reminder_id": source["id"]})
    elif operation == "complete":
        call("reminders.complete", {"reminder_id": source["id"]})
    elif operation == "inspect" and case == "other":
        call("reminders.complete", {"reminder_id": source["id"]})
    return calls


def run(archive, output):
    start = perf_counter()
    design = load_design(DESIGN)
    docs = [load_design(p) for p in sorted(DESIGN.parent.glob("*.yaml"))]
    inventory = validate_collection(next(d for d in docs if d["version"] == "train_wave_12"), docs)
    inventory["near_duplicate_review"] = "Wave13 handoff audits executed-history controls, source provenance and inherited train ancestry."
    worlds = {w["world_id"]: w for w in design["worlds"]}
    for scenario in design["scenarios"]:
        assert scenario["status"] == "spec_only" and scenario["exportable"] is False
        assert scenario["agent_visible"]["allowed_tools"] == worlds[scenario["world_id"]]["relevant_tools"]
    provenance = design["provenance"]
    apps = sorted({tool.split(".")[0] for w in worlds.values() for tool in w["relevant_tools"]} - {"sys"})
    files = ["__init__.py", "executor.py", "validate.py", "utils.py",
             "apps/__init__.py", "apps/base.py", "apps/sys.py"] + [f"apps/{app}.py" for app in apps]
    rows, histories, pre, post, visible = [], {}, {}, {}, {}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wave13_", dir=output.parent) as directory:
        root = Path(directory)
        with zipfile.ZipFile(archive) as source:
            for name in files:
                path = root / "zaic_tools" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(source.read(provenance["runtime_root"] + name))
            catalog = root / "catalog.json"
            catalog.write_bytes(source.read(provenance["catalog_member"]))
        assert json.loads(catalog.read_text(encoding="utf-8"))["schema_version"] == provenance["schema"]
        assert "zaic_tools" not in sys.modules
        sys.path.insert(0, str(root))
        from zaic_tools.executor import Executor

        for scenario in design["scenarios"]:
            sid = scenario["scenario_id"]
            state = deepcopy(worlds[scenario["world_id"]]["initial_state"])
            for app, collections in worlds[scenario["world_id"]]["variants"].get(scenario["fixture_variant"], {}).items():
                for collection, patches in collections.items():
                    for identity, fields in patches.items():
                        next(r for r in state[app][collection] if r["id"] == identity).update(deepcopy(fields))
            state["sys"] = {}
            state["_meta"] = {"tools": scenario["agent_visible"]["allowed_tools"],
                              "current_time": scenario["agent_visible"]["context"]["current_time"]}
            pre[sid] = state
        path = root / "pre.json"
        path.write_text(canonical(pre), encoding="utf-8")
        before = Executor(str(path), str(catalog))
        for scenario in design["scenarios"]:
            sid = scenario["scenario_id"]
            session = before.open(sid)
            assert session.allowed == set(scenario["agent_visible"]["allowed_tools"]) | {"sys.ask_missing_info"}
            turns, events, calls = execute_history(session, scenario["historical_turns"])
            frozen = scenario["agent_visible"]["history"]
            assert not frozen or frozen == turns, (sid, "frozen history differs from actual execution")
            state = session.get_state()
            assert before.open(sid).get_state() == {k: v for k, v in pre[sid].items() if k != "_meta"}
            visible[sid] = {**scenario["agent_visible"], "history": turns}
            histories[sid] = {"turns": turns, "events": events, "calls": calls,
                              "post_state": deepcopy(state)}
            post[sid] = {**state, "_meta": deepcopy(pre[sid]["_meta"])}
            reverse = deepcopy(post[sid])
            for app in reverse.values():
                if isinstance(app, dict):
                    for values in app.values():
                        if isinstance(values, list):
                            values.reverse()
            post[sid + "/reversed"] = reverse
            selected(scenario, events)
        path = root / "post.json"
        path.write_text(canonical(post), encoding="utf-8")
        after = Executor(str(path), str(catalog))
        for scenario in design["scenarios"]:
            sid = scenario["scenario_id"]
            events = histories[sid]["events"]
            cases = ["standard", "fresh_lookup", "create_first", "other", "replay_creations",
                     "first_row", "last_row", "largest_id"]
            if scenario.get("family", "reminders") != "reminders":
                cases = ["standard", "fresh_lookup", "other", "replay_action"]
            elif scenario["oracle_draft"]["operation"] == "inspect":
                cases = ["standard", "fresh_lookup", "other", "replay_creations"]
            elif scenario["oracle_draft"]["operation"] != "move":
                cases.remove("create_first")
            if scenario["oracle_draft"]["operation"] != "inspect":
                cases.append("omitted")
            if scenario["oracle_draft"].get("fresh_required"):
                cases.append("history_only")
            if sid == "TR13_CONTACT_CURRENT_CHECK":
                cases += ["empty_read", "unrelated_read", "broad_read", "late_read"]
            if sid == "TR13_APP_READ":
                cases.append("unrelated_read")
            if sid == "TR13_REM_READ":
                cases.append("empty_read")
            for ordering in ["original", "reversed"]:
                for case in cases:
                    session = after.open(sid + ("/reversed" if ordering == "reversed" else ""))
                    initial = session.get_state()
                    assert session.log == []
                    assert session.allowed == set(scenario["agent_visible"]["allowed_tools"]) | {"sys.ask_missing_info"}
                    assert canonical_state(initial) == canonical_state(histories[sid]["post_state"])
                    if ordering == "original":
                        assert initial == histories[sid]["post_state"]
                    calls = latest(session, scenario, events, case)
                    final = session.get_state()
                    verdict = verify(scenario, initial, calls, final, events, visible[sid])
                    required = "reject" if case in {"other", "replay_creations", "largest_id", "replay_action",
                                                  "omitted", "history_only", "empty_read", "unrelated_read", "late_read"} else "pass"
                    if case in {"first_row", "last_row"}:
                        records = calls[0]["result"]["reminders"]
                        chosen = records[0 if case == "first_row" else -1]["id"]
                        required = "pass" if chosen == selected(scenario, events)["id"] else "reject"
                    assert verdict["verdict"] == required, (sid, case, verdict)
                    if case == "other":
                        assert all(successful(c) for c in calls), (sid, "wrong-target control must execute")
                    if required == "reject":
                        intended_reasons = {
                            "other": {"state", "target", "authorized_writes", "authorized_order_or_writes", "replacement_fields"},
                            "replay_creations": {"authorized_writes", "target"},
                            "replay_action": {"authorized_writes", "authorized_order_or_writes"},
                            "omitted": {"authorized_writes", "authorized_order_or_writes", "target"},
                            "history_only": {"fresh_observation"},
                            "empty_read": {"fresh_observation"},
                            "unrelated_read": {"fresh_observation"},
                            "late_read": {"fresh_observation"},
                            "first_row": {"state", "target", "replacement_fields"},
                            "last_row": {"state", "target", "replacement_fields"},
                            "largest_id": {"state", "target", "replacement_fields"},
                        }[case]
                        assert intended_reasons.intersection(verdict["reasons"]), (sid, case, verdict)
                    assert session.log == calls
                    assert after.open(sid + ("/reversed" if ordering == "reversed" else "")).get_state() == initial
                    rows.append({"scenario_id": sid, "trace_case": case, "ordering": ordering,
                                 "evidence_kind": "actual_runtime_trace", "calls": calls,
                                 "expected_verdict": required,
                                 "initial_state": initial, "final_state": final, "verdict": verdict})
    result = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "replay_wall_seconds": perf_counter() - start,
        "declared_volatile_fields": ["created_utc", "replay_wall_seconds"],
        "inventory": inventory, "provenance": {**provenance, "archive": str(archive), "python": sys.version,
            "allowlisted_members": [provenance["runtime_root"] + name for name in files] + [provenance["catalog_member"]]},
        "agent_visible": visible, "pre_history_fixtures": pre, "histories": histories,
        "replays": rows,
        "status": {"scenarios": len(design["scenarios"]),
                   "historical_calls": sum(len(h["calls"]) for h in histories.values()),
                   "historical_noops": sum(not successful(c) for h in histories.values() for c in h["calls"]),
                   "assistant_tool_history_scenarios": len(visible),
                   "history_dependent_latest_actions": sum(s["oracle_draft"]["requires_history"] and
                       s["oracle_draft"]["operation"] != "inspect" for s in design["scenarios"]),
                   "fresh_observation_required": sum(bool(s["oracle_draft"].get("fresh_required"))
                       for s in design["scenarios"]),
                   "verifier_only_probes": 0,
                   "latest_paths": len(rows),
                   "verdicts": dict(Counter(r["verdict"]["verdict"] for r in rows)),
                   "outcomes": dict(Counter(s["oracle_draft"]["outcome"] for s in design["scenarios"])),
                   "exportable": False, "execution_verified": 0},
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["status"]), f"replay seconds: {result['replay_wall_seconds']:.3f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    run(args.archive, args.output)
