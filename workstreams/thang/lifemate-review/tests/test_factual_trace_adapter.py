"""Three-case trace binding, with runtime records and labeled adapter probes."""
from copy import deepcopy
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from factual_trace_adapter import evaluate_record, source
from replay_train_wave_15 import ARCHIVE

FRESH, OLD, KEEP = "TR10_APPL_LOOK", "TR13_CONTACT_INSPECT", "TR16_APP_KEEP"
ECO = "Đang chạy eco."
EMAIL = "thu.cu@daymoc.example.test"


def example(sid, case, text):
    spec, scenario, artifact, visible, initial = source(sid)
    row = next(r for r in artifact["replays"] if r["scenario_id"] == sid and r["trace_case"] == case
               and r.get("ordering", "original") == "original")
    run_id = f"{sid}/{case}"
    return deepcopy({"scenario_id": sid, "run_id": run_id,
                     "source_ref": {"scenario_id": sid, "run_id": run_id, "design": spec["design"],
                                    "fixture_variant": scenario["fixture_variant"]},
                     "visible": visible, "initial_state": initial, "calls": row["calls"],
                     "final_state": row["final_state"], "final_text": text,
                     "termination": "completed", "text_provenance": "authored_probe"})


def fresh_runtime_filters():
    """Execute two real reads against only the pinned synthetic appliance fixture."""
    _, _, artifact, _, _ = source(FRESH)
    provenance = artifact["provenance"]
    prefix = provenance["runtime_root"]
    members = ["__init__.py", "executor.py", "validate.py", "utils.py", "apps/__init__.py",
               "apps/base.py", "apps/sys.py", "apps/appliances.py"]
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        with zipfile.ZipFile(ARCHIVE) as archive:
            for member in members:
                path = root / "zaic_tools" / member
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(prefix + member))
            catalog = json.loads(archive.read(provenance["catalog_member"]))
        sys.path.insert(0, folder)
        try:
            session_class = importlib.import_module("zaic_tools.executor").Session
            records = []
            for device_type in ["microwave", "dryer"]:
                session = session_class(FRESH, artifact["fixtures"][FRESH], catalog)
                session.call("appliances.list", {"type": device_type})
                record = example(FRESH, "standard", ECO)
                record["run_id"] = record["source_ref"]["run_id"] = f"{FRESH}/runtime_{device_type}"
                record["calls"] = deepcopy(session.log)
                record["final_state"] = session.get_state()
                records.append(record)
            return records
        finally:
            sys.path.remove(folder)
            for name in tuple(sys.modules):
                if name == "zaic_tools" or name.startswith("zaic_tools."):
                    del sys.modules[name]


class FactualTraceTests(unittest.TestCase):
    def assert_result(self, record, trace, answer, combined):
        verdict = evaluate_record(record)
        self.assertEqual(verdict["input_status"], "compatible", verdict)
        self.assertEqual((verdict["trace_verdict"], verdict["answer_verdict"], verdict["overall"]),
                         (trace, answer, combined), verdict)
        self.assertEqual(verdict, evaluate_record(deepcopy(record)))
        return verdict

    def test_runtime_fresh_answer_and_wrong_answer(self):
        self.assert_result(example(FRESH, "standard", ECO), "pass", "pass", "pass")
        self.assert_result(example(FRESH, "standard", "Máy giặt Khe Sợi đang hẹn chu trình eco."),
                           "pass", "fail", "fail")

    def test_runtime_missing_empty_and_unrelated_observations(self):
        empty, unrelated = fresh_runtime_filters()
        self.assertEqual(empty["calls"][0]["result"]["appliances"], [])
        self.assertEqual([r["type"] for r in unrelated["calls"][0]["result"]["appliances"]], ["dryer"])
        for record in [example(FRESH, "unobserved", ECO), empty, unrelated]:
            self.assert_result(record, "fail", "unresolved", "fail")

    def test_runtime_wrong_write_overrides_correct_text(self):
        record = example(FRESH, "wrong", ECO)
        self.assertNotEqual(record["initial_state"], record["final_state"])
        record["trace_verdict"] = "pass"  # Caller claim has no authority.
        self.assert_result(record, "fail", "pass", "fail")

    def test_runtime_historical_answer_and_adapter_missing_result(self):
        record = example(OLD, "standard", EMAIL)
        self.assertEqual(record["calls"], [])
        self.assert_result(record, "pass", "pass", "pass")
        record["visible"]["history"][1]["tool_results"][0] = None  # Adapter probe.
        verdict = self.assert_result(record, "fail", "unresolved", "fail")
        self.assertIn("historical_grounding", verdict["trace_reasons"])

    def test_runtime_conditional_silence_and_missing_condition(self):
        self.assert_result(example(KEEP, "standard", None), "pass", "pass", "pass")
        self.assert_result(example(KEEP, "no_read", None), "fail", "unresolved", "fail")

    def test_adapter_reordering_and_mismatched_facts(self):
        history = example(OLD, "standard", EMAIL)
        history["visible"]["history"][1]["tool_results"][0]["contacts"].reverse()
        self.assert_result(history, "pass", "pass", "pass")
        record = example(FRESH, "alternative_read", ECO)
        record["calls"][0]["result"]["appliances"].reverse()
        self.assertNotEqual(record["calls"][0]["result"]["appliances"][0]["id"], "w10_ap_3")
        self.assert_result(record, "pass", "pass", "pass")
        entity = next(r for r in record["calls"][0]["result"]["appliances"] if r["id"] == "w10_ap_3")
        entity["state"]["cycle"] = "normal"
        verdict = self.assert_result(record, "pass", "unresolved", "unresolved")
        self.assertEqual(verdict["evidence_status"], "source_mismatch")

    def test_adapter_termination_and_text_presence(self):
        record = example(FRESH, "standard", ECO)
        for termination, combined in [("runner_error", "fail"), ("incomplete", "unresolved")]:
            record["termination"] = termination
            self.assert_result(record, "pass", "pass", combined)
        record["termination"] = "completed"
        for text, status in [(None, "absent"), ("", "empty")]:
            record["final_text"] = text
            verdict = self.assert_result(record, "pass", "fail", "fail")
            self.assertEqual((verdict["text_status"], verdict["answer_reason"]), (status, "missing_answer"))

    def test_adapter_mismatched_reference_and_initial_state(self):
        for key, value in [("run_id", "other_run"), ("scenario_id", KEEP)]:
            record = example(FRESH, "standard", ECO)
            record["source_ref"][key] = value
            self.assertEqual(evaluate_record(record)["overall"], "invalid")
        record = example(FRESH, "standard", ECO)
        record["initial_state"].clear()
        self.assertEqual(evaluate_record(record)["reason"], "input_or_initial_state")


if __name__ == "__main__":
    unittest.main()
