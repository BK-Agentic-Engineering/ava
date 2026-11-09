"""Concrete Wave 10 state, source, order and boundary regressions."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from replay_train_wave_01 import validate_ancestry
from replay_train_wave_08 import load_design
from replay_train_wave_10 import DESIGN, OUTPUT, effects, normalize, verify


class Wave10Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        design = load_design(DESIGN)
        cls.scenarios = {s["scenario_id"]: s for s in design["scenarios"]}
        cls.worlds = {w["world_id"]: w for w in design["worlds"]}
        evidence = json.loads(OUTPUT.read_text(encoding="utf-8"))
        cls.fixtures = evidence["fixtures"]
        cls.replays = {(r["scenario_id"], r["trace_case"]): r for r in evidence["replays"]}

    def check(self, sid, case="standard", *, calls=None, final=None):
        scenario = self.scenarios[sid]
        world = self.worlds[scenario["world_id"]]
        kinds = dict.fromkeys(world["relevant_tools"], "write")
        kinds.update({spec[0]: "read" for spec in world["readers"].values()})
        record = self.replays[sid, case]
        initial = {k: v for k, v in self.fixtures[sid].items() if k != "_meta"}
        return verify(world, scenario, initial, record["calls"] if calls is None else calls,
                      record["final_state"] if final is None else final, kinds,
                      effects=effects, normalize_action=normalize)

    def test_reminder_completion_does_not_authorize_deletion(self):
        sid = "TR10_REM_COMPLETE"
        final = self.replays[sid, "standard"]["final_state"]["reminders"]["reminders"]
        selected = next(r for r in final if r["id"] == "w10_rem_5")
        self.assertTrue(selected["done"])
        self.assertEqual(selected["repeat"], "daily")
        self.assertEqual(self.check(sid, "wrong")["reasons"], ["authorized_actions", "state"])

    def test_cycle_replacement_accepts_runtime_case_and_zero_delay(self):
        sid = "TR10_APPL_RESTART"
        self.assertEqual(self.check(sid, "case_zero")["verdict"], "pass")
        self.assertEqual(self.replays[sid, "case_zero"]["final_state"],
                         self.replays[sid, "standard"]["final_state"])
        sid = "TR10_APPL_AFTER"
        self.assertEqual(self.check(sid, "wrong")["reasons"], ["write_order"])

    def test_access_grant_and_lock_order_preserve_existing_codes(self):
        sid = "TR10_ACCESS_LOCKCODE"
        self.assertEqual(self.check(sid, "wrong")["reasons"], ["write_order"])
        final = deepcopy(self.replays[sid, "standard"]["final_state"])
        self.assertEqual(len(final["door_lock"]["guest_codes"]), 2)
        final["door_lock"]["guest_codes"][0]["label"] = "Changed"  # verifier-only
        self.assertEqual(self.check(sid, final=final)["reasons"], ["state"])
        self.assertEqual(self.check("TR10_ACCESS_ONEOPEN", "unobserved")["reasons"], ["decision_evidence"])

    def test_scene_then_override_differs_from_manual_mode_change(self):
        sid = "TR10_CLIMATE_OVERRIDE"
        self.assertEqual(self.check(sid, "wrong")["reasons"], ["state", "write_order"])
        sid = "TR10_CLIMATE_SCENE"
        final = self.replays[sid, "standard"]["final_state"]["smart_home"]
        self.assertEqual(final["active_scene"], "w10_scene_7")
        self.assertIn("authorized_actions", self.check(sid, "wrong")["reasons"])

    def test_fuel_inclusive_boundary_requires_the_correct_grade(self):
        self.assertEqual(self.check("TR10_FUEL_EXACT")["verdict"], "pass")
        self.assertEqual(self.check("TR10_FUEL_INCLUSIVE")["verdict"], "pass")
        record = self.replays["TR10_FUEL_INCLUSIVE", "standard"]
        wrong_grade = self.replays["TR10_FUEL_E5HIGH", "standard"]["calls"][0]
        self.assertEqual(self.check("TR10_FUEL_INCLUSIVE",
                         calls=[wrong_grade, record["calls"][-1]])["reasons"], ["decision_evidence"])
        self.assertEqual(self.check("TR10_FUEL_CHEAPCHANGE")["verdict"], "pass")

    def test_callback_rank_does_not_use_last_row_or_latest_outgoing(self):
        expected = {
            "TR10_PHONE_LATEST": "0900001009",
            "TR10_PHONE_FLIP": "0900001002",
            "TR10_PHONE_OLDEST": "0900001006",
            "TR10_PHONE_OUT": "0900001008",
        }
        for sid, number in expected.items():
            self.assertEqual(self.replays[sid, "standard"]["calls"][-1]["arguments"]["phone_number"], number)
        self.assertEqual(self.check("TR10_PHONE_LATEST", "unobserved")["reasons"], ["decision_evidence", "grounding"])

    def test_alarm_replacement_preserves_other_recurrence_and_disabled_edit(self):
        final = self.replays["TR10_ALARM_MOVE", "standard"]["final_state"]["alarm"]["alarms"]
        alarm = next(r for r in final if r["id"] == "w10_alarm_7")
        self.assertFalse(alarm["enabled"])
        self.assertEqual(alarm["repeat"], "weekends")
        self.assertEqual(self.check("TR10_ALARM_MOVE", "wrong")["reasons"], ["authorized_actions", "state"])
        self.assertIn("state", self.check("TR10_ALARM_REPLACE", "wrong")["reasons"])

    def test_robot_scalar_status_and_room_order_match_runtime(self):
        sid = "TR10_ROBOT_BATTERY"
        first = self.replays[sid, "standard"]["calls"][0]
        self.assertEqual(first["result"]["battery"], 15)
        self.assertEqual(self.check(sid)["verdict"], "pass")
        self.assertEqual(self.check(sid, "unobserved")["reasons"], ["decision_evidence"])
        self.assertEqual(self.check("TR10_ROBOT_LOW")["verdict"], "pass")
        self.assertEqual(self.check("TR10_ROBOT_TWO", "room_order")["verdict"], "pass")
        self.assertEqual(self.check("TR10_ROBOT_WHOLE", "empty_rooms")["verdict"], "pass")
        sid = "TR10_ROBOT_INHERIT"
        self.assertEqual(self.fixtures[sid]["robot_vacuum"]["current_job"]["mode"], "vacuum")
        final = self.replays[sid, "standard"]["final_state"]["robot_vacuum"]
        self.assertEqual(final["current_job"]["mode"], "mop")
        self.assertIn("authorized_actions", self.check(sid, "wrong")["reasons"])

    def test_observed_default_can_be_passed_explicitly(self):
        # Modified-call probes, not new SDK execution evidence.
        for sid in ["TR10_ROBOT_INHERIT", "TR10_ROBOT_RESTARTALL"]:
            calls = deepcopy(self.replays[sid, "standard"]["calls"])
            calls[-1]["arguments"]["mode"] = "mop"
            self.assertEqual(self.check(sid, calls=calls)["verdict"], "pass")
            self.assertEqual(self.check(sid, calls=calls[1:])["verdict"], "reject")
            calls[-1]["arguments"]["mode"] = "vacuum"
            self.assertIn("authorized_actions", self.check(sid, calls=calls)["reasons"])

    def test_null_rooms_preserves_whole_house_but_exceeds_subset(self):
        sid = "TR10_ROBOT_WHOLE"
        record = self.replays[sid, "null_rooms"]
        self.assertIsNone(record["calls"][-1]["arguments"]["rooms"])
        self.assertEqual(record["final_state"], self.replays[sid, "standard"]["final_state"])
        self.assertEqual(self.check(sid, "null_rooms")["verdict"], "pass")
        sid = "TR10_ROBOT_TWO"
        record = self.replays[sid, "null_subset"]
        job = record["final_state"]["robot_vacuum"]["current_job"]
        self.assertTrue(job["whole_house"])
        self.assertIn("Kho Ván", job["rooms"])
        self.assertEqual(self.check(sid, "null_subset")["reasons"], ["authorized_actions", "state"])

    def test_null_enabled_preserves_disabled_alarm_but_true_is_unauthorized(self):
        sid = "TR10_ALARM_MOVE"
        record = self.replays[sid, "null_enabled"]
        self.assertIsNone(record["calls"][-1]["arguments"]["enabled"])
        self.assertEqual(record["final_state"], self.replays[sid, "standard"]["final_state"])
        self.assertEqual(self.check(sid, "null_enabled")["verdict"], "pass")
        record = self.replays[sid, "enabled_true"]
        alarm = next(a for a in record["final_state"]["alarm"]["alarms"] if a["id"] == "w10_alarm_7")
        self.assertTrue(alarm["enabled"])
        self.assertEqual(alarm["time"], "06:45")
        self.assertEqual(self.check(sid, "enabled_true")["reasons"], ["authorized_actions", "state"])

    def test_derived_access_requires_both_actual_parent_lineages(self):
        docs = [load_design(path) for path in DESIGN.parent.glob("*.yaml")]
        worlds = {w["world_id"]: w for document in docs for w in document["worlds"]}
        scenarios = {s["scenario_id"]: s for document in docs for s in document["scenarios"]}
        validate_ancestry(worlds, scenarios)
        worlds["W_TR10_ACCESS"]["ancestry"]["parent_lineage_ids"].remove("TRAIN_ALERT_TRIAGE_08")
        with self.assertRaisesRegex(AssertionError, "parent lineage IDs disagree"):
            validate_ancestry(worlds, scenarios)


if __name__ == "__main__":
    unittest.main()
