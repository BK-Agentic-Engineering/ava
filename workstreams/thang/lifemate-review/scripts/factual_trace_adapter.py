"""Local final-text contract pilot for three existing observe-only tasks."""
from copy import deepcopy
from functools import cache

from evaluate_factual_answer_pilot import SPEC, at, canonical_sources, grade, load_design, overall
from replay_train_wave_08 import verify as verify_wave10
from replay_train_wave_13 import verify as verify_wave13
from replay_train_wave_16 import verify as verify_wave16

# Stable entity identities in the selected synthetic WORLDs.
ENTITIES = {
    "TR10_APPL_LOOK": ("appliances", "w10_ap_3", "Máy Giặt Khe Sợi"),
    "TR13_CONTACT_INSPECT": ("contacts", "hist_contact_A", "Đặng Minh Thu"),
    "TR16_APP_KEEP": ("appliances", "w16_washer", "Máy giặt hiên"),
}
TERMINATIONS = {"completed", "runner_error", "incomplete"}
VERDICTS = {"pass": "pass", "reject": "fail", "fail": "fail"}


@cache
def source(sid):
    case = next(c for c in load_design(SPEC)["cases"] if c["scenario_id"] == sid)
    version = case["design"]
    scenarios, artifact = canonical_sources(version)
    scenario = scenarios[sid]
    if sid == "TR16_APP_KEEP":
        entry = artifact["scenarios"][sid]
        visible, initial = entry["agent_visible"], entry["post_history_state"]
    elif sid == "TR13_CONTACT_INSPECT":
        visible = artifact["agent_visible"][sid]
        initial = artifact["histories"][sid]["post_state"]
    else:
        visible = artifact["agent_visible"][sid]
        initial = {k: v for k, v in artifact["fixtures"][sid].items() if k != "_meta"}
    return case, scenario, artifact, visible, initial


def compatible_view(visible, expected):
    # The rendering must match. Missing or changed result payloads remain observable
    # evidence defects, rather than being replaced by the canonical history.
    if not isinstance(visible, dict) or not isinstance(visible.get("history"), list):
        return False
    if {k: v for k, v in visible.items() if k != "history"} != {
        k: v for k, v in expected.items() if k != "history"
    } or len(visible["history"]) != len(expected["history"]):
        return False
    return all(isinstance(turn, dict) and
               {k: v for k, v in turn.items() if k != "tool_results"} ==
               {k: v for k, v in original.items() if k != "tool_results"}
               for turn, original in zip(visible["history"], expected["history"]))


def observations(case, record):
    evidence = case["evidence"]
    if evidence["kind"] == "latest":
        return [c["result"] for c in record["calls"] if c["name"] == evidence["tool"]]
    turn = record["visible"]["history"][evidence["turn"]]
    index = evidence["call"]
    if turn["tool_calls"][index]["name"] != evidence["tool"]:
        return []
    results = turn.get("tool_results", [])
    return [results[index]] if index < len(results) else []


def answer_source(case, record):
    collection, identity, name = ENTITIES[case["scenario_id"]]
    facts = [c for c in case["evidence"]["claims"] if c["path"][0] == collection
             and c["path"][1] == 0]
    matched, mismatch = False, False
    for result in observations(case, record):
        if not isinstance(result, dict) or result.get("ok") is not True or result.get("done") is False:
            continue
        hits = [row for row in result.get(collection, []) if row.get("id") == identity]
        if not hits:
            continue
        if len(hits) != 1 or hits[0].get("name") != name:
            mismatch = True
            continue
        try:
            actual = [at(hits[0], c["path"][2:]) for c in facts]
        except (KeyError, TypeError):
            mismatch = True
            continue
        if actual != [c["value"] for c in facts]:
            mismatch = True
        else:
            matched = True
    if mismatch:
        return "source_mismatch"
    return "supported" if matched else "missing_observation"


def tool_result(record, scenario, artifact):
    sid = record["scenario_id"]
    initial, calls, final = (record[k] for k in ("initial_state", "calls", "final_state"))
    if sid == "TR16_APP_KEEP":
        verdict = verify_wave16(scenario["oracle_draft"], record["visible"]["allowed_tools"], initial, calls)
        last_state = calls[-1]["state_after"] if calls else initial
        if final != last_state:
            return {**verdict, "verdict": "reject", "reasons": sorted(set(verdict["reasons"]) | {"final_snapshot"})}
        return verdict
    if sid == "TR13_CONTACT_INSPECT":
        # These events specify what the historical oracle expects. verify_wave13
        # compares exact payloads. Project only the search list's irrelevant order
        # and represent a missing paired response as an unsuccessful observation.
        events = deepcopy(artifact["histories"][sid]["events"])
        events["old_read"]["result"]["contacts"].sort(key=lambda row: row["id"])
        visible = deepcopy(record["visible"])
        for turn in visible["history"]:
            if turn["role"] != "assistant":
                continue
            results = turn.setdefault("tool_results", [])
            for index, result in enumerate(results):
                if result is None:
                    results[index] = {}
                elif turn["tool_calls"][index]["name"] == "contacts.search" and "contacts" in result:
                    result["contacts"].sort(key=lambda row: row["id"])
        return verify_wave13(scenario, initial, calls, final, events, visible)
    design = load_design(SPEC.parent / "design/train_wave_10.yaml")
    world = next(w for w in design["worlds"] if w["world_id"] == scenario["world_id"])
    kinds = {"appliances.list": "read", "appliances.stop": "write", "appliances.start_cycle": "write"}
    return verify_wave10(world, scenario, initial, calls, final, kinds)


def evaluate_record(record):
    def invalid(reason):
        return {"input_status": "incompatible", "reason": reason, "overall": "invalid"}

    if not isinstance(record, dict):
        return invalid("record_shape")
    sid, run_id = record.get("scenario_id"), record.get("run_id")
    if not isinstance(sid, str) or sid not in ENTITIES or not isinstance(run_id, str) or not run_id.strip():
        return invalid("identity")
    case, scenario, artifact, expected, initial = source(sid)
    ref = {"scenario_id": sid, "run_id": run_id, "design": case["design"],
           "fixture_variant": scenario["fixture_variant"]}
    if record.get("source_ref") != ref:
        return invalid("source_reference")
    if not compatible_view(record.get("visible"), expected) or record.get("initial_state") != initial:
        return invalid("input_or_initial_state")
    termination, text, calls = (record.get(k) for k in ("termination", "final_text", "calls"))
    if not isinstance(termination, str) or termination not in TERMINATIONS:
        return invalid("termination")
    if "final_text" not in record or (text is not None and not isinstance(text, str)):
        return invalid("final_text")
    if not isinstance(record.get("final_state"), dict) or not isinstance(calls, list):
        return invalid("trace_shape")
    for call in calls:
        if (not isinstance(call, dict) or not isinstance(call.get("name"), str)
                or not isinstance(call.get("arguments"), dict) or not isinstance(call.get("result"), dict)
                or (sid == "TR16_APP_KEEP" and not isinstance(call.get("state_after"), dict))):
            return invalid("call_shape")
    for turn in record["visible"]["history"]:
        results = turn.get("tool_results", [])
        if (not isinstance(results, list) or len(results) not in {0, len(turn.get("tool_calls", []))}
                or any(result is not None and not isinstance(result, dict) for result in results)):
            return invalid("history_pairing")
    try:
        trace = tool_result(record, scenario, artifact)
        evidence = answer_source(case, record)
    except (AttributeError, IndexError, KeyError, StopIteration, TypeError, ValueError):
        return invalid("trace_payload")

    trace_verdict = VERDICTS.get(trace.get("verdict"), "unresolved")
    if text is None or not text.strip():
        if case["required"] or evidence == "supported":
            answer_verdict, reason = grade(case, text)
        else:
            answer_verdict, reason = "unresolved", evidence
    elif evidence == "supported":
        answer_verdict, reason = grade(case, text)
    else:
        answer_verdict, reason = "unresolved", evidence

    combined = overall(trace_verdict, answer_verdict)
    if termination == "runner_error":
        combined = "fail"
    elif termination == "incomplete" and combined == "pass":
        combined = "unresolved"
    text_status = "absent" if text is None else "empty" if text == "" else "present"
    return {"input_status": "compatible", "scenario_id": sid, "run_id": run_id,
            "trace_verdict": trace_verdict, "trace_reasons": trace["reasons"],
            "answer_verdict": answer_verdict, "answer_reason": reason, "evidence_status": evidence,
            "termination": termination, "text_status": text_status,
            "overall": combined}
