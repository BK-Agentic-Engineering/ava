"""Regression checks for Wave 15's evidence and authorized effects."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from replay_train_wave_15 import DESIGN, OUTPUT, audit_sources, load_design, verify


class Wave15Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design = {s["scenario_id"]: s for s in load_design(DESIGN)["scenarios"]}
        evidence = json.loads(OUTPUT.read_text(encoding="utf-8"))
        cls.scenarios = evidence["scenarios"]
        cls.rows = {(r["scenario_id"], r["trace_case"]): r for r in evidence["replays"]}

    def test_standard_covers_every_design_and_serializes_actual_history(self):
        self.assertEqual(set(self.design), {sid for sid, case in self.rows if case == "standard"})
        for sid, e in self.scenarios.items():
            history = e["agent_visible"]["history"]
            self.assertEqual(set(e["agent_visible"]), {"request", "context", "history", "allowed_tools"})
            calls = [{**call, "result": result} for turn in history if turn["role"] == "assistant"
                     for call, result in zip(turn["tool_calls"], turn["tool_results"], strict=True)]
            self.assertEqual(calls, e["historical_calls"])
            self.assertEqual(self.rows[sid, "standard"]["verdict"]["verdict"], "pass")

    def test_midnight_and_timezone_leave_history_fixed_and_change_gold(self):
        base = self.scenarios["TR15_PLANNING_TOMORROW"]
        for case, start in [("MIDNIGHT", "2027-09-17T08:20:00+07:00"),
                            ("ZONE", "2027-09-17T08:20:00+00:00")]:
            other = self.scenarios["TR15_PLANNING_" + case]
            self.assertEqual(base["historical_calls"], other["historical_calls"])
            self.assertEqual(base["post_history_state"], other["post_history_state"])
            self.assertEqual(other["gold_actions"][0][1]["start"], start)

    def test_early_historical_default_and_latest_default_use_distinct_clocks(self):
        sid = "TR15_FITNESS_NOW"
        e = self.scenarios[sid]
        self.assertEqual(e["historical_calls"][0]["result"]["workout"]["time"],
                         e["historical_current_times"][0])
        row = self.rows[sid, "runtime_default"]
        self.assertNotIn("time", row["calls"][0]["arguments"])
        self.assertEqual(row["calls"][0]["result"]["workout"]["time"],
                         e["agent_visible"]["context"]["current_time"])
        self.assertNotEqual(e["historical_current_times"][0], e["agent_visible"]["context"]["current_time"])

    def test_correction_changes_history_and_gold_with_same_state(self):
        a, b = (self.scenarios["TR15_PICKUP_" + name] for name in ("CORRECTION", "CORRECTIONALT"))
        self.assertEqual(a["post_history_state"], b["post_history_state"])
        self.assertEqual(a["historical_calls"], b["historical_calls"])
        self.assertNotEqual(a["agent_visible"]["history"], b["agent_visible"]["history"])
        self.assertNotEqual(a["gold_actions"], b["gold_actions"])
        sid = "TR15_PICKUP_CORRECTION"
        row = self.rows[sid, "standard"]
        visible = deepcopy(a["agent_visible"])
        visible["history"].pop(2)
        result = verify(self.design[sid], visible, {}, a["post_history_state"],
                        row["calls"], row["final_state"], a["gold_actions"])
        self.assertEqual(result["reasons"], ["historical_grounding"])

    def test_fresh_contact_requires_matching_record_before_any_consumer(self):
        sid = "TR15_CONTACT_TASK"
        standard = self.rows[sid, "standard"]
        for case in ["unobserved", "late", "unrelated", "empty"]:
            row = self.rows[sid, case]
            self.assertEqual(row["final_state"], standard["final_state"])
            self.assertEqual(row["verdict"]["reasons"], ["fresh_observation"])
        for case in ["get", "broad_read"]:
            self.assertEqual(self.rows[sid, case]["verdict"]["verdict"], "pass")
        sid = "TR15_CONTACT_BOTH"
        self.assertEqual(self.rows[sid, "read_after_note"]["verdict"]["reasons"], ["fresh_observation"])
        self.assertEqual(self.rows[sid, "reverse"]["verdict"]["verdict"], "pass")

    def test_successful_wrong_tool_changes_state_and_noop_is_separate(self):
        sid = "TR15_PICKUP_OUTBOUND"
        wrong = self.rows[sid, "wrong_tool"]
        self.assertTrue(wrong["calls"][-1]["result"]["ok"])
        self.assertNotEqual(wrong["final_state"], self.scenarios[sid]["post_history_state"])
        self.assertEqual(wrong["verdict"]["reasons"], ["authorized_actions", "state"])
        sid = "TR15_PICKUP_AFTER_NOOP"
        self.assertFalse(self.scenarios[sid]["historical_calls"][-1]["result"]["done"])
        self.assertEqual(self.rows[sid, "copy_failed_time"]["verdict"]["reasons"],
                         ["authorized_actions", "state"])

    def test_context_audit_rejects_stale_runtime_clock(self):
        sid = "TR15_FITNESS_NOW"
        e = self.scenarios[sid]
        gold = deepcopy(e["gold_actions"])
        gold[0][1]["time"] = e["historical_current_times"][0]
        events = {"workout": e["historical_calls"][0]}
        with self.assertRaises(AssertionError):
            audit_sources(self.design[sid]["oracle_draft"], e["agent_visible"]["context"],
                          events, e["post_history_state"], gold)


if __name__ == "__main__":
    unittest.main()
