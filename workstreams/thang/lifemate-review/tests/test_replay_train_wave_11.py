"""Wave 11 history, missing-required-argument and capability regressions."""
import os
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from replay_train_wave_01 import validate_ancestry
from replay_train_wave_08 import load_design
from replay_train_wave_11 import DESIGN, OUTPUT, audit_contrasts, effects, normalize, verify


class Wave11Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        design = load_design(DESIGN)
        cls.scenarios = {s["scenario_id"]: s for s in design["scenarios"]}
        cls.worlds = {w["world_id"]: w for w in design["worlds"]}
        evidence = json.loads(OUTPUT.read_text(encoding="utf-8"))
        cls.fixtures = evidence["fixtures"]
        cls.records = {(r["scenario_id"], r["trace_case"]): r for r in evidence["replays"]}

    def check(self, sid, case="standard", calls=None, final=None):
        scenario = self.scenarios[sid]
        world = self.worlds[scenario["world_id"]]
        kinds = dict.fromkeys(world["relevant_tools"], "write")
        kinds.update({spec[0]: "read" for spec in world["readers"].values()})
        kinds["sys.ask_missing_info"] = "meta"
        record = self.records[sid, case]
        initial = {k: v for k, v in self.fixtures[sid].items() if k != "_meta"}
        return verify(world, scenario, initial, record["calls"] if calls is None else calls,
                      record["final_state"] if final is None else final, kinds,
                      effects=effects, normalize_action=normalize)

    def test_history_only_contrast_changes_pickup_despite_identical_state(self):
        left, right = "TR11_PICK_SECOND", "TR11_PICK_SWAPHISTORY"
        self.assertEqual(self.fixtures[left], self.fixtures[right])
        self.assertEqual(self.scenarios[left]["agent_visible"]["request"],
                         self.scenarios[right]["agent_visible"]["request"])
        self.assertNotEqual(self.records[left, "standard"]["calls"][-1]["arguments"]["address"],
                            self.records[right, "standard"]["calls"][-1]["arguments"]["address"])
        self.assertIn("authorized_actions", self.check(left, "wrong")["reasons"])

    def test_retracted_amount_is_missing_even_when_old_number_is_visible(self):
        sid = "TR11_SAVE_RETRACT"
        args = self.records[sid, "standard"]["calls"][-1]["arguments"]
        self.assertEqual(args, {"tool_name": "banking.open_savings", "params": ["amount"]})
        self.assertEqual(self.check(sid)["verdict"], "pass")
        self.assertIn("authorized_actions", self.check(sid, "wrong")["reasons"])
        self.assertEqual(self.check(sid, "direct_clarification")["verdict"], "pass")

    def test_nine_direct_clarifications_and_original_read_paths_are_accepted(self):
        affected = [
            "TR11_SAVE_AMOUNT", "TR11_SAVE_TERM", "TR11_SAVE_BOTH", "TR11_SAVE_RETRACT",
            "TR11_CHORE_MISSING", "TR11_CHORE_RETRACT",
            "TR11_AUTO_MISSING", "TR11_AUTO_ACTION", "TR11_AUTO_BOTH",
        ]
        for sid in affected:
            with self.subTest(scenario=sid):
                direct = self.records[sid, "direct_clarification"]
                standard = self.records[sid, "standard"]
                self.assertEqual(direct["calls"], standard["calls"][-1:])
                self.assertEqual(direct["final_state"], standard["final_state"])
                self.assertEqual(self.check(sid)["verdict"], "pass")
                self.assertEqual(self.check(sid, "direct_clarification")["verdict"], "pass")
                self.assertNotIn((sid, "unobserved"), self.records)
                self.assertIn("authorized_actions", self.check(sid, "wrong")["reasons"])
        for sid, case in [
            ("TR11_SAVE_AMOUNT", "wrong_parameter"), ("TR11_CHORE_MISSING", "wrong_parameter"),
            ("TR11_AUTO_MISSING", "wrong_parameter"), ("TR11_SAVE_BOTH", "partial_question"),
            ("TR11_AUTO_BOTH", "partial_question"),
        ]:
            self.assertEqual(self.check(sid, case)["reasons"], ["authorized_actions"])

    def test_optional_task_due_is_not_a_required_missing_parameter(self):
        self.assertEqual(self.check("TR11_TASK_DEFAULT")["verdict"], "pass")
        self.assertEqual(self.check("TR11_TASK_DEFAULT", "wrong")["reasons"], ["authorized_actions", "state"])
        sid = "TR11_TASK_MISSING"
        self.assertEqual(self.records[sid, "standard"]["calls"][-1]["arguments"]["params"], ["title"])
        self.assertEqual(self.check(sid)["verdict"], "pass")

    def test_clarification_parameter_order_and_target_stay_explicit(self):
        sid = "TR11_CAL_BOTH"
        self.assertEqual(self.check(sid, "params_order")["verdict"], "pass")
        calls = deepcopy(self.records[sid, "standard"]["calls"])
        calls[-1]["arguments"]["tool_name"] = "tasks.add"  # verifier-only edit
        self.assertIn("authorized_actions", self.check(sid, calls=calls)["reasons"])
        calls[-1]["arguments"] = {"tool_name": "calendar.create_event", "params": ["start"]}
        self.assertIn("authorized_actions", self.check(sid, calls=calls)["reasons"])

    def test_unavailable_capability_rejects_even_read_and_meta_calls(self):
        sid = "TR11_ALARM_NOAUTH"
        self.assertEqual(self.records[sid, "standard"]["calls"], [])
        self.assertEqual(self.check(sid)["verdict"], "pass")
        self.assertEqual(self.check(sid, "wrong")["reasons"], ["authorized_actions"])
        # A real metadata result from another clarification trace.
        meta = self.records["TR11_ALARM_MISSING", "standard"]["calls"][-1]
        self.assertIn("authorized_actions", self.check(sid, calls=[meta])["reasons"])
        self.assertNotIn("alarm.create", self.scenarios[sid]["agent_visible"]["allowed_tools"])

    def test_chore_history_still_requires_a_real_target_observation(self):
        sid = "TR11_CHORE_FINAL"
        self.assertEqual(self.check(sid, "unobserved")["reasons"], ["grounding"])
        self.assertEqual(self.check(sid)["verdict"], "pass")
        final = deepcopy(self.records[sid, "standard"]["final_state"])
        final["household_chores"]["chores"][-1]["done"] = False  # verifier-only collateral edit
        self.assertEqual(self.check(sid, final=final)["reasons"], ["state"])

    def test_media_history_distinguishes_playlist_namespace(self):
        left, right = "TR11_MUSIC_PLAYLIST", "TR11_MUSIC_TRACK"
        self.assertEqual(self.check(left)["verdict"], "pass")
        self.assertEqual(self.check(right)["verdict"], "pass")
        self.assertIn("playlist_id", self.records[left, "standard"]["calls"][-1]["arguments"])
        self.assertIn("track_id", self.records[right, "standard"]["calls"][-1]["arguments"])
        self.assertEqual(self.check(left, "wrong")["reasons"], ["authorized_actions", "state"])

    def test_history_and_permission_contrasts_and_ancestry_resolve(self):
        audit_contrasts()
        docs = [load_design(path) for path in DESIGN.parent.glob("*.yaml")]
        worlds = {w["world_id"]: w for doc in docs for w in doc["worlds"]}
        scenarios = {s["scenario_id"]: s for doc in docs for s in doc["scenarios"]}
        validate_ancestry(worlds, scenarios)
        invalid = deepcopy(worlds["W_TR11_PICK"])
        invalid["world_id"] = "UNIT_UNRELATED_PRIMARY"
        invalid["lineage_id"] = "TRAIN_MAIL_DISPOSITION_01"
        worlds[invalid["world_id"]] = invalid
        with self.assertRaisesRegex(AssertionError, "primary lineage lacks an ancestry path"):
            validate_ancestry(worlds, scenarios)

    def test_all_clarifications_target_available_required_parameters(self):
        with zipfile.ZipFile(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")) as source:
            catalog = json.loads(source.read("train+public_test/train/train_tools_catalog.json"))
        tools = {tool["name"]: tool for app in catalog["apps"] for tool in app["tools"]}
        count = 0
        for sid, scenario in self.scenarios.items():
            if scenario["oracle_draft"]["outcome"] != "ask_missing":
                continue
            count += 1
            with self.subTest(scenario=sid):
                record = self.records[sid, "standard"]
                call = record["calls"][-1]
                args = call["arguments"]
                self.assertEqual(call["name"], "sys.ask_missing_info")
                self.assertTrue(call["result"]["waiting_for_user"])
                self.assertIn(args["tool_name"], scenario["agent_visible"]["allowed_tools"])
                self.assertTrue(set(args["params"]) <= set(tools[args["tool_name"]]["parameters"]["required"]))
                initial = {k: v for k, v in self.fixtures[sid].items() if k != "_meta"}
                self.assertEqual(initial, record["final_state"])
        self.assertEqual(count, 21)


if __name__ == "__main__":
    unittest.main()
