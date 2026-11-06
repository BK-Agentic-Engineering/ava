"""Checks against the context and competing-tool runtime evidence."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from replay_train_wave_08 import load_design
from replay_train_wave_14 import DESIGN, OUTPUT, audit_context, verify


class Wave14Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design = load_design(DESIGN)
        cls.scenarios = {s["scenario_id"]: s for s in cls.design["scenarios"]}
        cls.worlds = {w["world_id"]: w for w in cls.design["worlds"]}
        cls.evidence = json.loads(OUTPUT.read_text(encoding="utf-8"))
        cls.records = {(r["scenario_id"], r["trace_case"]): r for r in cls.evidence["replays"]}

    def test_correction_history_is_agent_visible(self):
        scenario = self.scenarios["TR14_PLAN_CORRECT"]
        history = scenario["agent_visible"]["history"]
        self.assertEqual(len(history), 1)
        self.assertIn("chặn lịch Kiểm Mành", history[0]["text"])
        self.assertNotIn("history", scenario["oracle_draft"])
        self.assertEqual(self.evidence["agent_visible"]["TR14_PLAN_CORRECT"]["history"], history)

    def test_local_date_and_timezone_each_change_calendar_start(self):
        for pair, expected in [
            (("BEFORE", "AFTER"), ("2027-08-11T09:00:00+07:00", "2027-08-12T09:00:00+07:00")),
            (("ZONEUTC", "ZONEVN"), ("2027-08-11T09:00:00+00:00", "2027-08-12T09:00:00+07:00")),
        ]:
            ids = ["TR14_DATE_" + name for name in pair]
            self.assertEqual(*(self.scenarios[sid]["agent_visible"]["request"] for sid in ids))
            self.assertEqual(tuple(self.records[sid, "standard"]["calls"][-1]["arguments"]["start"]
                                   for sid in ids), expected)
        audit_context(self.design)

    def test_pickup_context_and_explicit_override(self):
        for sid, address in [
            ("HOME", "18 Ngõ Chạc Mây"), ("HOMECHANGE", "29 Hẻm Nếp Gỗ"), ("EXPLICIT", "29 Hẻm Nếp Gỗ"),
        ]:
            record = self.records["TR14_PICK_" + sid, "standard"]
            self.assertEqual(record["final_state"]["package_tracking"]["pickups"][-1]["address"], address)

    def test_successful_fallback_is_not_forecast_for_requested_city(self):
        record = self.records["TR14_CITY_MISSING", "standard"]
        self.assertTrue(record["calls"][0]["result"]["ok"])
        self.assertNotIn("Cần Thơ", {r["location"] for r in record["calls"][0]["result"]["forecast"]})
        self.assertEqual(record["final_state"]["reminders"]["reminders"], [])
        self.assertEqual(self.records["TR14_CITY_MISSING", "unobserved"]["verdict"]["reasons"],
                         ["decision_evidence"])

    def test_runtime_default_uses_the_same_rendered_current_time(self):
        for sid in ["TR14_FIT_NOW", "TR14_FIT_NOWSHIFT"]:
            expected = self.scenarios[sid]["agent_visible"]["context"]["current_time"]
            self.assertEqual(self.evidence["fixtures"][sid]["_meta"]["current_time"], expected)
            record = self.records[sid, "standard"]
            self.assertNotIn("time", record["calls"][-1]["arguments"])
            self.assertEqual(record["calls"][-1]["result"]["workout"]["time"], expected)
        self.assertEqual(self.records["TR14_FIT_NOW", "explicit_now"]["verdict"]["verdict"], "pass")

    def test_competing_tool_succeeds_but_changes_unauthorized_app(self):
        for sid in ["TR14_PLAN_ALARM", "TR14_PLAN_REM", "TR14_PLAN_CAL", "TR14_PLAN_TASK"]:
            good, wrong = (self.records[sid, case] for case in ["standard", "wrong"])
            self.assertNotEqual(good["calls"][-1]["name"], wrong["calls"][-1]["name"])
            self.assertTrue(wrong["calls"][-1]["result"]["ok"])
            self.assertEqual(wrong["verdict"]["reasons"], ["authorized_actions", "state"])

    def test_context_audit_detects_an_incorrect_gold_timestamp(self):
        design = deepcopy(self.design)
        scenario = next(s for s in design["scenarios"] if s["scenario_id"] == "TR14_DATE_AFTER")
        scenario["oracle_draft"]["actions"][0][1]["start"] = "2027-08-11T09:00:00+07:00"
        with self.assertRaises(AssertionError):
            audit_context(design)


if __name__ == "__main__":
    unittest.main()
