"""Concrete Wave 09 regressions against local runtime evidence."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from replay_train_wave_01 import validate_ancestry
from replay_train_wave_08 import load_design, verify
from replay_train_wave_09 import DESIGN, OUTPUT, effects, normalize


class Wave09Tests(unittest.TestCase):
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
        kinds = {tool: "write" for tool in world["relevant_tools"]}
        kinds.update({spec[0]: "read" for spec in world["readers"].values()})
        initial = {k: v for k, v in self.fixtures[sid].items() if k != "_meta"}
        record = self.replays[sid, case]
        return verify(world, scenario, initial, record["calls"] if calls is None else calls,
                      record["final_state"] if final is None else final, kinds,
                      effects=effects, normalize_action=normalize)

    def test_default_duration_and_explicit_short_duration_remain_distinct(self):
        sid = "TR9_CAL_DEFAULT"
        self.assertEqual(self.check(sid, "explicit_hour")["verdict"], "pass")
        self.assertEqual(self.replays[sid, "standard"]["final_state"],
                         self.replays[sid, "explicit_hour"]["final_state"])
        self.assertIn("authorized_actions", self.check(sid, "wrong")["reasons"])

    def test_calendar_null_end_preserves_scope_and_grounding(self):
        for sid in ("TR9_CAL_PLACE", "TR9_CAL_TITLE"):
            with self.subTest(scenario=sid):
                record = self.replays[sid, "null_end"]
                self.assertEqual(record["final_state"], self.replays[sid, "standard"]["final_state"])
                self.assertIsNone(record["calls"][-1]["arguments"]["end"])
                self.assertEqual(self.check(sid, "null_end")["verdict"], "pass")
                self.assertEqual(self.check(sid, "null_end", calls=record["calls"][-1:])["reasons"], ["grounding"])

                # Verifier-only probe. Keep the correct edit and introduce an
                # unauthorized end field and its corresponding state change.
                calls, final = deepcopy(record["calls"]), deepcopy(record["final_state"])
                args = calls[-1]["arguments"]
                event = next(r for r in final["calendar"]["events"] if r["id"] == args["event_id"])
                args["end"] = event["end"] = "2027-03-12T17:00:00+07:00"
                reasons = self.check(sid, "null_end", calls=calls, final=final)["reasons"]
                self.assertEqual(reasons, ["authorized_actions", "state"])
        name = "calendar.update_event"
        self.assertNotEqual(normalize((name, {"event_id": "x", "end": ""})),
                            normalize((name, {"event_id": "x"})))

    def test_attendee_order_is_flexible_but_membership_is_grounded(self):
        sid = "TR9_MEET_TWO"
        self.assertEqual(self.check(sid, "attendee_order")["verdict"], "pass")
        self.assertEqual(self.check(sid, "unobserved")["reasons"], ["grounding"])
        self.assertIn("authorized_actions", self.check(sid, "wrong")["reasons"])

    def test_one_dong_changes_the_savings_floor_branch(self):
        self.assertEqual(self.check("TR9_BANK_FLOOR")["verdict"], "pass")
        sid = "TR9_BANK_FLOORLOW"
        self.assertEqual(self.check(sid)["verdict"], "pass")
        self.assertEqual(self.check(sid, "unobserved")["reasons"], ["decision_evidence"])
        self.assertIn("state", self.check(sid, "wrong")["reasons"])

    def test_wallet_debits_leave_existing_ledger_entries_intact(self):
        sid = "TR9_WALLET_SPLIT"
        final = deepcopy(self.replays[sid, "standard"]["final_state"])
        self.assertEqual(final["ewallet"]["balance"], 0)
        final["ewallet"]["transactions"][0]["amount"] = 0  # verifier-only mutation
        self.assertEqual(self.check(sid, final=final)["reasons"], ["state"])

    def test_business_headlines_cannot_prove_tech_ranking(self):
        sid = "TR9_NEWS_LATEST"
        business = self.replays["TR9_NEWS_ALREADY", "standard"]["calls"][0]
        standard = self.replays[sid, "standard"]
        reasons = self.check(sid, calls=[business, standard["calls"][-1]])["reasons"]
        self.assertIn("decision_evidence", reasons)
        self.assertIn("grounding", reasons)

    def test_parcel_old_slot_remains_available_after_reread(self):
        sid = "TR9_PARCEL_PREVIOUS"
        self.assertEqual(self.check(sid, "reread_keep_original")["verdict"], "pass")
        self.assertIn("authorized_actions", self.check(sid, "reread_use_updated")["reasons"])
        self.assertEqual(self.check("TR9_PARCEL_NEW", "wrong")["reasons"], ["write_order"])

    def test_wrong_city_response_cannot_authorize_fieldwork(self):
        sid = "TR9_WEATHER_WRONGCITY"
        wrong_city = self.replays[sid, "standard"]["calls"][0]
        self.assertTrue(wrong_city["result"]["forecast"])
        self.assertTrue(all(r["location"] != "Huế" for r in wrong_city["result"]["forecast"]))
        self.assertEqual(self.check(sid)["verdict"], "pass")
        allowed = self.replays["TR9_WEATHER_BELOW", "standard"]
        self.assertIn("decision_evidence", self.check("TR9_WEATHER_BELOW",
                      calls=[wrong_city, allowed["calls"][-1]])["reasons"])

    def test_playlist_append_order_is_part_of_requested_state(self):
        sid = "TR9_MUSIC_TWOADD"
        self.assertEqual(self.check(sid)["verdict"], "pass")
        self.assertEqual(self.check(sid, "wrong")["reasons"], ["state", "write_order"])

    def test_multi_parent_savings_lineage_requires_both_declared_sources(self):
        docs = [load_design(path) for path in DESIGN.parent.glob("*.yaml")]
        worlds = {w["world_id"]: w for document in docs for w in document["worlds"]}
        scenarios = {s["scenario_id"]: s for document in docs for s in document["scenarios"]}
        validate_ancestry(worlds, scenarios)
        worlds["W_TR9_BANK"]["ancestry"]["parent_scenario_ids"].remove("TR5_B_PAY")
        with self.assertRaisesRegex(AssertionError, "parent lineage IDs disagree"):
            validate_ancestry(worlds, scenarios)
        worlds["W_TR9_BANK"]["ancestry"]["parent_lineage_ids"].remove("TRAIN_BILL_AUTOPAY_05")
        with self.assertRaisesRegex(AssertionError, "primary lineage lacks an ancestry path"):
            validate_ancestry(worlds, scenarios)


if __name__ == "__main__":
    unittest.main()
