"""Replay the hand-authored Wave 08 contrasts in the local release Executor."""
from __future__ import annotations
import os

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
from time import perf_counter
import zipfile

import yaml

from replay_batch03 import ROOT, StrictLoader
from replay_train_wave_01 import canonical
from replay_train_wave_07 import validate as validate_previous


DESIGN = ROOT / "data/synthetic/design/train_wave_08.yaml"
OUTPUT = ROOT / "artifacts/synthetic/train_wave_08_replay/replay.json"
VOLATILE = ["created_utc", "replay_wall_seconds"]


def load_design(path):
    return yaml.load(path.read_text(encoding="utf-8"), Loader=StrictLoader)


def fixture(world, scenario):
    state = deepcopy(world["initial_state"])
    for app, collections in world["variants"].get(scenario["fixture_variant"], {}).items():
        for collection, records in collections.items():
            if app == "robot_vacuum" and collection == "current_job" and records is None:
                state[app][collection] = None
                continue
            if isinstance(state[app][collection], dict):
                state[app][collection].update(records)
                continue
            if not isinstance(records, dict):
                assert type(records) is type(state[app][collection])
                state[app][collection] = records
                continue
            for identity, changes in records.items():
                row(state[app][collection], identity).update(changes)
    state.setdefault("notes", {"notes": [{"id": "w8_guard", "title": "Riêng tư", "content": "Giữ nguyên."}]})
    state["sys"] = {}
    state["_meta"] = {
        "tools": scenario["agent_visible"]["allowed_tools"],
        "current_time": scenario["agent_visible"]["context"]["current_time"],
    }
    return state


def row(records, identity):
    return next(r for r in records if r["id"] == identity)


def matches(record, fields):
    if not isinstance(fields, dict):
        return record == fields
    return isinstance(record, dict) and all(
        key in record and matches(record[key], value) for key, value in fields.items()
    )


def bind(world, reader, records, observed, complete):
    for alias, (source, fields, *ranking) in world["witnesses"].items():
        if source == reader:
            needed = references(("", fields))
            if not needed <= observed.keys() or (ranking and not complete):
                continue
            _, criteria = resolve(("", fields), observed)
            hits = [record for record in records if matches(record, criteria)]
            if ranking and hits:
                field, direction, *tie_break = ranking[0]
                def rank(record):
                    return tuple(record[key] for key in [field, *tie_break])
                best = {"min": min, "max": max}[direction](map(rank, hits))
                hits = [r for r in hits if rank(r) == best]
            if len(hits) == 1:
                observed[alias] = hits[0]


def response_records(collection, value):
    if collection in {"balance", "battery", "status", "mode"}:
        return [{"id": collection, "value": value}]
    return value


def observe(world, call, observed, history):
    result = call["result"]
    if result.get("ok") is not True or result.get("done") is False:
        return
    history.append(call)
    # Replace older observations of the same query, while retaining the
    # relative order of different queries that can jointly bind an identity.
    recent = {canonical([c["name"], c["arguments"]]): i for i, c in enumerate(history)}
    observed.clear()
    for reader, (tool, collection, *queries) in world["readers"].items():
        records, complete = {}, False
        for index, item in enumerate(history):
            if item["name"] != tool or recent[canonical([tool, item["arguments"]])] != index:
                continue
            response = item["result"]
            if collection not in response:
                continue
            covers_scope = item["arguments"] in queries
            if tool == "podcast_radio.search" and collection == "episodes":
                # A hit on the named show returns every episode of that show.
                covers_scope |= reader in observed and observed[reader] in response.get("shows", [])
            if covers_scope:
                records.clear()
                complete = True
            records.update((record["id"], record) for record in response_records(collection, response[collection]))
        bind(world, reader, list(records.values()), observed, complete)
        if complete:
            observed["@" + reader] = True


def gold_observations(world, state):
    """Resolve authored natural selectors against the private fixture for gold only."""
    observed = {}
    for reader, (tool, collection, *_) in world["readers"].items():
        app = tool.split(".")[0]
        records = response_records(collection, state[app][collection])
        if tool == "flights.my_bookings":
            fields = ("origin", "destination", "date", "depart", "arrive", "airline")
            records = [
                {**b, "flight": {k: f[k] for k in fields if k in f}}
                for b in records for f in [row(state["flights"]["flights"], b["flight_id"])]
            ]
        bind(world, reader, records, observed, True)
        observed["@" + reader] = True
    return observed


def references(action):
    def aliases(value):
        if isinstance(value, str) and value.startswith("$"):
            yield value[1:].split(".")[0]
        elif isinstance(value, list):
            for item in value:
                yield from aliases(item)
    return {alias for value in action[1].values() for alias in aliases(value)}


def resolve(action, observed, original=None):
    name, args = action
    def resolve_value(value):
        if isinstance(value, str) and value.startswith("$"):
            reference = value[1:]
            alias, field = reference.split(".")
            value = original[reference] if original is not None and reference in original else observed[alias][field]
        elif isinstance(value, list):
            return [resolve_value(item) for item in value]
        return value
    return name, {key: resolve_value(value) for key, value in args.items()}


def proved(clauses, observed):
    return not clauses or any(all(alias in observed for alias in clause) for clause in clauses)


def normalize(action):
    name, args = action
    args = dict(args)
    if name == "flights.book" and args.get("seat_class") is None:
        args["seat_class"] = "economy"
    if name == "tasks.add":
        for key, value in {"due": "", "priority": "normal"}.items():
            if args.get(key) is None:
                args[key] = value
    if name == "home_automation.create_rule":
        args["time"] = args["time"][:5]
        if args.get("title") is None:
            args["title"] = ""
    return canonical([name, args])


def state_matches(initial, final, actions):
    expected = deepcopy(initial)
    created = defaultdict(list)
    for name, args in actions:
        app, operation = name.split(".")
        state = expected[app]
        if app == "flights":
            if operation == "book":
                created[app, "bookings"].append({
                    **args, "seat_class": args.get("seat_class") or "economy", "status": "confirmed",
                })
            elif operation == "cancel":
                row(state["bookings"], args["booking_id"])["status"] = "cancelled"
            elif operation == "check_in":
                row(state["bookings"], args["booking_id"])["checked_in"] = True
        elif app == "tv":
            if operation == "record":
                program = row(state["programs"], args["program_id"])
                created[app, "recordings"].append({
                    "program_id": program["id"], "channel": program["channel"],
                    "start": program["start"], "status": "scheduled",
                })
            elif operation == "tune":
                state.update(power="on", channel=args["channel"])
            elif operation == "control":
                control = args["action"]
                if control == "volume":
                    state["volume"] = args["volume"]
                elif control == "mute":
                    state["muted"] = True
                else:
                    state["power"] = control
        elif app == "podcast_radio":
            if operation == "play" and "episode_id" in args:
                episode = row(state["episodes"], args["episode_id"])
                state["now_playing"] = {
                    "episode_id": episode["id"], "show_id": episode["show_id"], "status": "playing",
                }
                if episode["id"] in state["queue"]:
                    state["queue"].remove(episode["id"])
            elif operation == "play":
                station = next(s for s in state["stations"] if s["name"] == args["station"])
                state["now_playing"] = {
                    "station_id": station["id"], "station": station["name"], "status": "playing",
                }
            elif operation == "queue":
                if args["episode_id"] not in state["queue"]:
                    state["queue"].append(args["episode_id"])
            elif operation == "subscribe":
                if args["show_id"] not in state["subscriptions"]:
                    state["subscriptions"].append(args["show_id"])
        elif app == "tasks":
            if operation == "complete":
                row(state["tasks"], args["task_id"])["done"] = True
            elif operation == "add":
                created[app, "tasks"].append({"due": "", "priority": "normal", **args, "done": False})
        elif app == "home_security":
            if operation == "arm":
                state["mode"] = args["mode"]
            elif operation == "acknowledge_alert":
                row(state["alerts"], args["alert_id"])["acknowledged"] = True
        elif app == "subscriptions":
            row(state["subscriptions"], args["subscription_id"])["status"] = "cancelled"
        elif app == "home_automation":
            if operation == "delete_rule":
                state["rules"].remove(row(state["rules"], args["rule_id"]))
            elif operation == "create_rule":
                created[app, "rules"].append({
                    **args, "time": args["time"][:5], "title": args.get("title") or "", "enabled": True,
                })
        elif app == "smart_home":
            row(state["devices"], args["device_id"])["state"]["power"] = args["power"]
        elif app == "household_chores":
            row(state["chores"], args["chore_id"])["assignee"] = args["assignee"]
        else:
            raise AssertionError(f"Missing effect check for {name}")

    for (app, collection), payloads in created.items():
        previous = {r["id"] for r in initial[app][collection]}
        records = final[app][collection]
        added = [r for r in records if r["id"] not in previous]
        if len({r["id"] for r in records}) != len(records):
            return False
        actual = [{k: v for k, v in r.items() if k != "id"} for r in added]
        if Counter(map(canonical, actual)) != Counter(map(canonical, payloads)):
            return False
        expected[app][collection].extend(added)
    # Multiple independent subscriptions can be appended in either order.
    if "podcast_radio" in expected:
        before = initial["podcast_radio"]["subscriptions"]
        want = expected["podcast_radio"]["subscriptions"]
        actual = final["podcast_radio"]["subscriptions"]
        if actual[:len(before)] == before and Counter(actual[len(before):]) == Counter(want[len(before):]):
            expected["podcast_radio"]["subscriptions"] = actual
    return expected == final


IDEMPOTENT = {
    "flights.check_in", "flights.cancel", "tv.record", "tv.tune", "tv.control",
    "tasks.complete", "home_security.arm", "home_security.acknowledge_alert",
    "subscriptions.cancel", "home_automation.delete_rule", "smart_home.switch_set",
    "household_chores.assign", "podcast_radio.subscribe", "podcast_radio.queue",
    "calendar.update_event", "calendar.cancel_event", "video_meeting.join", "news.save",
    "package_tracking.reschedule_delivery", "music.add_to_playlist", "music.control",
}


def verify(world, scenario, initial, calls, final, kinds, *, effects=state_matches, normalize_action=normalize):
    oracle = scenario["oracle_draft"]
    actions = oracle["actions"]
    private = gold_observations(world, initial)
    intended = [resolve(action, private) for action in actions]
    tokens = {normalize_action(action): template for action, template in zip(intended, actions)}
    observed, history, attempts, notes, reasons = {}, [], [], [], set()
    original = None
    clauses = oracle["decision_evidence"]
    for call in calls:
        name, args, result = (call[k] for k in ("name", "arguments", "result"))
        if name not in scenario["agent_visible"]["allowed_tools"]:
            reasons.add("permission")
            continue
        if kinds[name] == "read":
            observe(world, call, observed, history)
            continue
        if original is None:
            original = {}
            for reference in oracle.get("original_values", []):
                alias, field = reference.split(".")
                if field in observed.get(alias, {}):
                    original[reference] = observed[alias][field]
        token = normalize_action((name, args))
        if token in attempts and name in IDEMPOTENT:
            notes.append("repeated_idempotent_attempt")
        else:
            attempts.append(token)
            if result.get("ok") is not True or result.get("done") is False:
                reasons.add("write_did_not_succeed")
        if not proved(clauses, observed):
            reasons.add("decision_evidence")
        if token in tokens:
            template = tokens[token]
            missing_original = any(
                value == "$" + reference and reference not in original
                for reference in oracle.get("original_values", [])
                for value in template[1].values()
            )
            if missing_original or not references(template) <= observed.keys() or normalize_action(resolve(template, observed, original)) != token:
                reasons.add("grounding")
    expected = [normalize_action(action) for action in intended]
    if Counter(attempts) != Counter(expected):
        reasons.add("authorized_actions")
    elif oracle.get("ordered") and attempts != expected:
        reasons.add("write_order")
    if not intended and not proved(clauses, observed):
        reasons.add("decision_evidence")
    if not effects(initial, final, intended):
        reasons.add("state")
    return {
        "verdict": "reject" if reasons else "pass",
        "reasons": sorted(reasons),
        "trace_policy_notes": notes,
        "official_call_matching": "not_evaluated",
    }


def evidence_aliases(actions):
    return set().union(*(references(action) for action in actions))


def read_sources(world, actions, clauses, alternative=False):
    needed = evidence_aliases(actions) | set(clauses[0] if clauses else [])
    pending = list(needed)
    while pending:
        alias = pending.pop()
        if not alias.startswith("@"):
            dependencies = references(("", world["witnesses"][alias][1])) - needed
            needed.update(dependencies)
            pending.extend(dependencies)
    readers = {
        alias[1:] if alias.startswith("@") else world["witnesses"][alias][0]
        for alias in needed
    }
    calls = []
    for reader, (tool, _, *queries) in world["readers"].items():
        if reader in readers:
            args = queries[-1 if alternative else 0]
            if (tool, args) not in calls:
                calls.append((tool, args))
    return calls


def validate(design, docs):
    inventory = validate_previous(next(d for d in docs if d["version"] == "train_wave_07"), docs)
    assert (design["split"], design["status"], design["exportable"]) == ("train", "spec_only", False)
    worlds = {w["world_id"]: w for w in design["worlds"]}
    matched_requests = defaultdict(list)
    for world in worlds.values():
        inherited = bool(world["ancestry"]["parent_lineage_ids"])
        expected_origin = "train_derivative" if inherited else "independently_authored"
        assert world["split"] == "train" and world["origin"] == expected_origin
    for scenario in design["scenarios"]:
        world = worlds[scenario["world_id"]]
        assert world["split"] == "train"
        assert scenario["status"] == "spec_only" and scenario["exportable"] is False
        visible = scenario["agent_visible"]
        matched_requests[visible["request"]].append(scenario)
        assert visible["allowed_tools"] == world.get("tool_variants", {}).get(
            scenario.get("permission_variant"), world["relevant_tools"]
        )
        state = fixture(world, scenario)

        def private_ids(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == "id":
                        assert item not in canonical(visible), ("hidden ID", scenario["scenario_id"])
                    else:
                        private_ids(item)
            if isinstance(value, list):
                for item in value:
                    private_ids(item)

        private_ids(state)
        oracle = scenario["oracle_draft"]
        observed = gold_observations(world, state)
        assert proved(oracle["decision_evidence"], observed)
        for action in oracle["actions"] + oracle["counterexample"]:
            assert action[0] in visible["allowed_tools"]
            resolve(action, observed)
    for controls in matched_requests.values():
        if len(controls) > 1:
            assert len({s["world_id"] for s in controls}) == 1
            visible = [s["agent_visible"] for s in controls]
            if all(v == visible[0] for v in visible):
                assert len({s["fixture_variant"] for s in controls}) == len(controls)
            else:
                if design["version"] == "train_wave_14":
                    assert len({s["fixture_variant"] for s in controls}) == 1
                    stripped = [{k: v for k, v in entry.items() if k != "context"} for entry in visible]
                    assert all(v == stripped[0] for v in stripped)
                    assert len({canonical(v["context"]) for v in visible}) == len(visible)
                    continue
                # Informational history and capability controls use an
                # unchanged fixture. Each declared pair is audited by its runner.
                assert len({s["fixture_variant"] for s in controls}) == 1
                stripped = [{k: v for k, v in entry.items() if k not in {"history", "allowed_tools"}}
                            for entry in visible]
                assert all(v == stripped[0] for v in stripped)
    wave_label = "Wave" + design["version"].rsplit("_", 1)[-1]
    inventory["near_duplicate_review"] = (
        f"{wave_label} handoff records structural controls, ancestry and the request overlap audit."
    )
    return inventory


def run(archive, output, *, design_path=DESIGN, effects=state_matches, normalize_action=normalize,
        verifier=verify):
    start = perf_counter()
    design = load_design(design_path)
    docs = [load_design(p) for p in sorted(design_path.parent.glob("*.yaml"))]
    inventory = validate(design, docs)
    worlds = {w["world_id"]: w for w in design["worlds"]}
    fixtures = {s["scenario_id"]: fixture(worlds[s["world_id"]], s) for s in design["scenarios"]}
    provenance = design["provenance"]
    runtime = ["__init__.py", "executor.py", "validate.py", "utils.py", "apps/__init__.py", "apps/base.py", "apps/sys.py"]
    apps = sorted({tool.split(".")[0] for w in worlds.values() for tool in w["relevant_tools"]} - {"sys"})
    runtime += [f"apps/{app}.py" for app in apps]
    members = [provenance["runtime_root"] + p for p in runtime]
    output.parent.mkdir(parents=True, exist_ok=True)
    replays = []
    with tempfile.TemporaryDirectory(prefix="wave08_runtime_", dir=output.parent) as directory:
        temp = Path(directory)
        with zipfile.ZipFile(archive) as source:
            for name, member in zip(runtime, members):
                target = temp / "zaic_tools" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read(member))
            catalog_path = temp / "catalog.json"
            catalog_path.write_bytes(source.read(provenance["catalog_member"]))
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        assert catalog["schema_version"] == provenance["schema"]
        kinds = {t["name"]: t["kind"] for a in catalog["apps"] for t in a["tools"]}
        assert "zaic_tools" not in sys.modules, "fresh process required"
        sys.path.insert(0, str(temp))
        from zaic_tools.executor import Executor

        path = temp / "authored.json"
        path.write_text(canonical(fixtures), encoding="utf-8")
        executor = Executor(str(path), str(catalog_path))
        original = deepcopy(executor.db)

        for scenario in design["scenarios"]:
            sid = scenario["scenario_id"]
            world = worlds[scenario["world_id"]]
            oracle = scenario["oracle_draft"]
            actions, wrong, clauses = (oracle[k] for k in ("actions", "counterexample", "decision_evidence"))

            def replay(case, writes, reads, expected, reason=None, blind=False, reads_after=False,
                       between=None, use_original=True):
                if between is None:
                    between = reads if oracle.get("reread_after_first") else ()
                session = executor.open(sid)
                initial = session.get_state()
                assert session.allowed == set(scenario["agent_visible"]["allowed_tools"]) | {"sys.ask_missing_info"}
                observed, history, calls = {}, [], []

                def call(name, args):
                    old = session.get_state()
                    result = session.call(name, args)
                    item = {"name": name, "arguments": deepcopy(args), "result": deepcopy(result)}
                    calls.append(item)
                    if kinds[name] == "read":
                        assert session.get_state() == old and result.get("ok") is True
                        observe(world, item, observed, history)
                    return result

                if not reads_after:
                    for name, args in reads:
                        call(name, args)
                values = gold_observations(world, initial) if blind else observed
                if use_original:
                    values = deepcopy(values)
                for index, action in enumerate(writes):
                    if index == 1:
                        for name, args in between:
                            call(name, args)
                    call(*resolve(action, values))
                if reads_after:
                    for name, args in reads:
                        call(name, args)
                final = session.get_state()
                verdict = verifier(world, scenario, initial, calls, final, kinds, effects=effects, normalize_action=normalize_action)
                assert verdict["verdict"] == expected and (reason is None or reason in verdict["reasons"]), (sid, case, verdict)
                if case in {"unobserved", "late_read"} and writes:
                    assert "state" not in verdict["reasons"], (sid, verdict)
                if case == "wrong":
                    assert all(c["result"].get("ok") is True and c["result"].get("done") is not False
                               for c in calls if kinds[c["name"]] == "write"), (sid, calls)
                assert session.log == calls and executor.db == original
                assert executor.open(sid).get_state() == initial
                replays.append({
                    "scenario_id": sid, "trace_case": case, "evidence_kind": "actual_runtime_trace",
                    "expected_verdict": expected, "required_reason": reason,
                    "calls": calls, "final_state": final, "verdict": verdict,
                })

            reads = [tuple(call) for call in oracle.get("clarification_reads", [])] or read_sources(world, actions, clauses)
            replay("standard", actions, reads, "pass")
            alternative = reads if oracle.get("clarification_reads") else read_sources(world, actions, clauses, alternative=True)
            if alternative != reads:
                replay("alternative_read", actions, alternative, "pass")
            for branch, clause in enumerate(clauses[1:], start=2):
                other_reads = read_sources(world, actions, [clause])
                if other_reads != reads:
                    replay(f"sufficient_branch_{branch}", actions, other_reads, "pass")
            if len(actions) > 1 and not oracle.get("ordered"):
                replay("independent_reverse", actions[::-1], reads, "pass")
            if reads:
                if oracle.get("clarification_reads"):
                    assert oracle["outcome"] == "ask_missing" and not clauses
                    replay("direct_clarification", actions, [], "pass")
                else:
                    reason = "decision_evidence" if clauses else "grounding"
                    replay("unobserved", actions, [], "reject", reason, blind=True)
            if sid in {"TR8_FLIGHT_REBOOK", "TR8_PODCAST_PLAY", "TR8_AUTO_COPY", "TR8_CHORE_SWAP"}:
                replay("late_read", actions, reads, "reject", "grounding", blind=True, reads_after=True)
            if actions:
                replay("omitted", actions[:-1], reads, "reject", "authorized_actions")
            if wrong:
                reason = "write_order" if oracle.get("ordered") and wrong == actions[::-1] else "authorized_actions"
                replay("wrong", wrong, read_sources(world, actions + wrong, clauses), "reject", reason)
            if sid == "TR8_TASK_ADD":
                replay("explicit_default", [("tasks.add", {**actions[0][1], "priority": "normal"})], reads, "pass")
            if sid == "TR8_PODCAST_NEWEST":
                replay("host_lookup", actions, [("podcast_radio.search", {"query": "Hà Lam"})], "pass")
            if sid == "TR8_SECURITY_INCLUSIVE":
                replay("utc_boundary", actions, [("home_security.list_alerts", {"since": "2027-02-10T01:00:00Z"})], "pass")
            if sid == "TR8_AUTO_RULE":
                replay("minute_representation", [("home_automation.create_rule", {
                    **actions[0][1], "time": "07:15:00", "title": "",
                })], reads, "pass")
            if sid in {"TR8_TV_REC", "TR8_SUB_LITERAL", "TR8_AUTO_REMOVE"}:
                replay("idempotent_repeat", actions * 2, reads, "pass")
            if sid == "TR8_AUTO_REMOVE":
                replay("rule_first", actions, reads[::-1], "pass")
                replay("read_after_delete", actions, reads[::-1], "reject", "grounding", blind=True, reads_after=True)
            if oracle.get("original_values") and len(actions) == 2:
                replay("reread_keep_original", actions, reads, "pass", between=reads)
                replay("reread_use_updated", actions, reads, "reject", "authorized_actions",
                       between=reads, use_original=False)
            for case, alternate in oracle.get("alternatives", {}).items():
                replay(case, alternate, reads, "pass")
            for case, control in oracle.get("negative_alternatives", {}).items():
                replay(case, control["actions"], reads, "reject", control["reason"])
            if oracle.get("reread_after_first"):
                replay("missing_current_read", actions, reads, "reject", "current_alert_evidence", between=[])

    counts = Counter(r["expected_verdict"] for r in replays)
    result = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "replay_wall_seconds": perf_counter() - start,
        "declared_volatile_fields": VOLATILE,
        "kind": "hand_authored_runtime_replay",
        "inventory": inventory,
        "status": {
            "scenarios": len(design["scenarios"]),
            "outcomes": dict(Counter(s["oracle_draft"]["outcome"] for s in design["scenarios"])),
            "positive_runtime_paths": counts["pass"],
            "rejected_runtime_paths": counts["reject"],
            "exportable": False,
            "execution_verified": 0,
        },
        "provenance": {**provenance, "archive": str(archive), "python": sys.version,
                       "allowlisted_members": members + [provenance["catalog_member"]]},
        "agent_visible": {s["scenario_id"]: s["agent_visible"] for s in design["scenarios"]},
        "fixtures": fixtures,
        "replays": replays,
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["status"]), f"replay seconds: {result['replay_wall_seconds']:.3f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    arguments = parser.parse_args()
    run(arguments.archive, arguments.output)
