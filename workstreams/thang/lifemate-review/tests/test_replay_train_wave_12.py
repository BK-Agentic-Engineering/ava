"""Concrete Wave 12 lookup, scope, order and current-state regressions."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from replay_train_wave_01 import validate_ancestry
from replay_train_wave_08 import load_design
from replay_train_wave_12 import DESIGN, OUTPUT, effects, normalize, verify


class Wave12Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        design = load_design(DESIGN)
        cls.scenarios = {s["scenario_id"]: s for s in design["scenarios"]}
        cls.worlds = {w["world_id"]: w for w in design["worlds"]}
        evidence = json.loads(OUTPUT.read_text(encoding="utf-8"))
        cls.fixtures = evidence["fixtures"]
        cls.records = {(r["scenario_id"], r["trace_case"]): r for r in evidence["replays"]}

    def check(self, sid, case="standard", *, calls=None, final=None):
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

    def test_security_alerts_are_not_in_the_future(self):
        checked = []
        for sid, scenario in self.scenarios.items():
            if not sid.startswith("TR12_ALERT_"):
                continue
            now = datetime.fromisoformat(scenario["agent_visible"]["context"]["current_time"])
            for alert in self.fixtures[sid]["home_security"]["alerts"]:
                self.assertLessEqual(datetime.fromisoformat(alert["time"]), now, sid)
            checked.append(sid)
        self.assertEqual(len(checked), 12)

    def test_lookup_changes_whether_address_is_missing(self):
        found, empty = "TR12_SOURCE_FOUND", "TR12_SOURCE_EMPTY"
        self.assertEqual(self.scenarios[found]["agent_visible"], self.scenarios[empty]["agent_visible"])
        before, after = deepcopy(self.fixtures[found]), deepcopy(self.fixtures[empty])
        after["notes"]["notes"][0]["content"] = before["notes"]["notes"][0]["content"]
        self.assertEqual(before, after)
        for sid in [found, empty]:
            self.assertEqual(self.check(sid)["verdict"], "pass")
            self.assertIn("decision_evidence", self.check(sid, "unobserved")["reasons"])
        self.assertEqual(self.records[empty, "standard"]["calls"][-1]["arguments"]["params"], ["address"])
        self.assertEqual(self.check("TR12_SOURCE_DIRECTASK")["verdict"], "pass")
        self.assertEqual(len(self.records["TR12_SOURCE_DIRECTASK", "standard"]["calls"]), 1)

    def test_quoted_instruction_does_not_authorize_alarm(self):
        sid = "TR12_QUOTE_COPY"
        self.assertEqual(self.check(sid)["verdict"], "pass")
        wrong = self.records[sid, "wrong"]
        self.assertEqual(wrong["calls"][-1]["name"], "alarm.create")
        self.assertTrue(wrong["calls"][-1]["result"]["ok"])
        self.assertIn("authorized_actions", self.check(sid, "wrong")["reasons"])
        self.assertEqual(self.check("TR12_QUOTE_SNAPSHOT", "reread_keep_original")["verdict"], "pass")
        self.assertIn("authorized_actions", self.check("TR12_QUOTE_SNAPSHOT", "reread_use_updated")["reasons"])

    def test_same_name_lines_are_not_collapsed(self):
        sid = "TR12_SHOP_TWO"
        final = self.records[sid, "standard"]["final_state"]["shopping_list"]["items"]
        self.assertEqual(len([r for r in final if r["name"] == "dây cói"]), 3)
        self.assertTrue(next(r for r in final if r["id"] == "w12_item_3")["checked"])
        self.assertFalse(next(r for r in final if r["id"] == "w12_item_6")["checked"])
        self.assertIn("state", self.check(sid, "wrong")["reasons"])
        self.assertEqual(self.check("TR12_SHOP_DEFAULT", "explicit_one")["verdict"], "pass")

    def test_wait_permission_changes_commitment(self):
        self.assertEqual(self.check("TR12_LIB_NOBUSY")["verdict"], "pass")
        waiting = self.records["TR12_LIB_WAIT", "standard"]["final_state"]["library"]["reservations"][-1]
        self.assertEqual(waiting["status"], "waiting")
        self.assertEqual(self.check("TR12_LIB_WAIT")["verdict"], "pass")
        self.assertEqual(self.check("TR12_LIB_FALLBACK", "unobserved")["reasons"], ["decision_evidence", "grounding"])

    def test_financial_graph_and_ledger_are_preserved(self):
        sid = "TR12_BANK_CROSS"
        self.assertEqual(self.check(sid, "independent_reverse")["verdict"], "pass")
        self.assertIn("authorized_actions", self.check(sid, "wrong")["reasons"])
        final = deepcopy(self.records[sid, "standard"]["final_state"])
        final["banking"]["transactions"][0]["amount"] = 0  # verifier-only mutation
        self.assertEqual(self.check(sid, final=final)["reasons"], ["state"])
        self.assertEqual(self.check("TR12_BANK_FLOORLOW", "unobserved")["reasons"], ["decision_evidence"])

    def test_enrollment_schedule_and_progress_have_separate_effects(self):
        sid = "TR12_LEARN_SCHEDULE"
        course = self.records[sid, "standard"]["final_state"]["learning"]["courses"][0]
        self.assertFalse(course["enrolled"])
        self.assertEqual(course["progress_minutes"], 60)
        self.assertEqual(self.check("TR12_LEARN_BOTH", "wrong")["reasons"], ["write_order"])
        sid = "TR12_LEARN_COPYMIN"
        self.assertEqual(self.records[sid, "standard"]["calls"][-1]["arguments"]["minutes"], 30)

    def test_guide_date_argument_does_not_filter_runtime_response(self):
        sid = "TR12_TV_NEXTDAY"
        record = self.records[sid, "standard"]
        response = record["calls"][0]["result"]["programs"]
        self.assertTrue(any(r["start"].startswith("2027-06-12") for r in response))
        self.assertEqual(record["calls"][-1]["arguments"]["program_id"], "w12_tv_7")
        self.assertIn("authorized_actions", self.check(sid, "wrong")["reasons"])

    def test_current_alert_must_be_observed_after_acknowledgment(self):
        sid = "TR12_ALERT_VERIFY"
        record = self.records[sid, "standard"]
        self.assertEqual([c["name"] for c in record["calls"]], [
            "home_security.list_alerts", "home_security.acknowledge_alert",
            "home_security.list_alerts", "home_security.arm",
        ])
        self.assertEqual(self.check(sid)["verdict"], "pass")
        self.assertEqual(self.check(sid, "missing_current_read")["reasons"], ["current_alert_evidence"])
        self.assertEqual(record["final_state"], self.records[sid, "missing_current_read"]["final_state"])
        calls = deepcopy(record["calls"])
        calls[2]["result"]["alerts"] = [
            r for r in calls[2]["result"]["alerts"] if r["location"] != "Sân Nẹp"
        ]  # verifier-only projection of unrelated acknowledged rows
        self.assertEqual(self.check(sid, calls=calls)["reasons"], ["current_alert_evidence"])

    def test_source_family_retains_both_real_parent_lineages(self):
        docs = [load_design(path) for path in DESIGN.parent.glob("*.yaml")]
        worlds = {w["world_id"]: w for doc in docs for w in doc["worlds"]}
        scenarios = {s["scenario_id"]: s for doc in docs for s in doc["scenarios"]}
        validate_ancestry(worlds, scenarios)
        worlds["W_TR12_SOURCE"]["ancestry"]["parent_lineage_ids"].remove("TRAIN_LOGISTICS_DIRECTION_02")
        with self.assertRaisesRegex(AssertionError, "parent lineage IDs disagree"):
            validate_ancestry(worlds, scenarios)


if __name__ == "__main__":
    unittest.main()
