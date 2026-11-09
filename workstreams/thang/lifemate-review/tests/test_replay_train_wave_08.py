"""Regression checks using Wave 08's local evidence and labeled verifier-only edits."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from replay_train_wave_08 import DESIGN, OUTPUT, load_design, observe, verify


class Wave08VerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        design = load_design(DESIGN)
        cls.scenarios = {s["scenario_id"]: s for s in design["scenarios"]}
        cls.worlds = {w["world_id"]: w for w in design["worlds"]}
        evidence = json.loads(OUTPUT.read_text(encoding="utf-8"))
        cls.fixtures = evidence["fixtures"]
        cls.replays = {(r["scenario_id"], r["trace_case"]): r for r in evidence["replays"]}

    def check(self, sid, replay, calls=None, final=None):
        scenario = self.scenarios[sid]
        world = self.worlds[scenario["world_id"]]
        kinds = {tool: "write" for tool in world["relevant_tools"]}
        kinds.update({spec[0]: "read" for spec in world["readers"].values()})
        initial = {k: v for k, v in self.fixtures[sid].items() if k != "_meta"}
        return verify(world, scenario, initial,
                      replay["calls"] if calls is None else calls,
                      replay["final_state"] if final is None else final, kinds)

    def test_rebooking_requires_successful_first_write_even_with_correct_state(self):
        sid = "TR8_FLIGHT_REBOOK"
        standard = self.replays[sid, "standard"]
        wrong_order = self.replays[sid, "wrong"]
        self.assertEqual(standard["final_state"], wrong_order["final_state"])
        self.assertEqual(self.check(sid, wrong_order)["reasons"], ["write_order"])
        calls = deepcopy(standard["calls"])
        calls[-2]["result"] = {"ok": True, "done": False}
        self.assertIn("write_did_not_succeed", self.check(sid, standard, calls)["reasons"])

    def test_other_show_cannot_establish_latest_episode(self):
        sid = "TR8_PODCAST_NEWEST"
        standard = self.replays[sid, "standard"]
        host_lookup = self.replays[sid, "host_lookup"]
        self.assertEqual(self.check(sid, host_lookup)["verdict"], "pass")
        # The play still has the intended final state. Here only the evidence
        # is replaced with a real search for the other show.
        wrong_scope = next(c for c in self.replays["TR8_PODCAST_OTHER", "standard"]["calls"]
                           if c["arguments"] == {"query": "Đồi Vân"})
        reasons = self.check(sid, standard, [wrong_scope, standard["calls"][-1]])["reasons"]
        self.assertIn("decision_evidence", reasons)
        self.assertIn("grounding", reasons)

    def test_no_write_accepts_decisive_door_alert_alone(self):
        sid = "TR8_SECURITY_GATEBOTH"
        door = self.replays[sid, "sufficient_branch_2"]
        self.assertEqual(len(door["calls"]), 1)
        self.assertEqual(self.check(sid, door)["verdict"], "pass")
        self.assertEqual(self.check(sid, door, [])["reasons"], ["decision_evidence"])
        calls = deepcopy(door["calls"])
        calls[0]["result"]["alerts"] = [
            a for a in calls[0]["result"]["alerts"] if a["location"] == "Lối Bên"
        ]
        self.assertEqual(self.check(sid, door, calls)["reasons"], ["decision_evidence"])

    def test_rule_payload_match_does_not_hide_live_device_change(self):
        sid = "TR8_AUTO_RULE"
        record = self.replays[sid, "minute_representation"]
        self.assertEqual(self.check(sid, record)["verdict"], "pass")
        final = deepcopy(record["final_state"])
        final["smart_home"]["devices"][0]["state"]["power"] = "on"
        self.assertEqual(self.check(sid, record, final=final)["reasons"], ["state"])

    def test_swapping_requires_each_original_source_value(self):
        sid = "TR8_CHORE_SWAP"
        self.assertEqual(self.check(sid, self.replays[sid, "independent_reverse"])["verdict"], "pass")
        self.assertEqual(self.check(sid, self.replays[sid, "late_read"])["reasons"], ["grounding"])
        kept = self.replays[sid, "reread_keep_original"]
        self.assertEqual(self.check(sid, kept)["verdict"], "pass")
        self.assertEqual(kept["final_state"], self.replays[sid, "standard"]["final_state"])
        updated = self.replays[sid, "reread_use_updated"]
        self.assertIn("authorized_actions", self.check(sid, updated)["reasons"])

        world = deepcopy(self.worlds["W_TR8_CHORE"])
        world["witnesses"]["former_current"] = [
            "list", {"title": "Lau Kệ", "room": "Phòng Mây", "done": False, "assignee": "An Mi"},
        ]
        history, current = [], {}
        observe(world, kept["calls"][0], current, history)
        self.assertIn("former_current", current)
        observe(world, kept["calls"][2], current, history)
        self.assertNotIn("former_current", current)
        self.assertEqual(current["cloud"]["assignee"], "Lâm Duy")

    def test_rule_and_device_evidence_can_arrive_in_either_order(self):
        sid = "TR8_AUTO_REMOVE"
        normal = self.replays[sid, "standard"]
        reversed_reads = self.replays[sid, "rule_first"]
        self.assertEqual(normal["calls"][:2], reversed_reads["calls"][:2][::-1])
        self.assertEqual(normal["final_state"], reversed_reads["final_state"])
        self.assertEqual(self.check(sid, reversed_reads)["verdict"], "pass")
        late = self.replays[sid, "read_after_delete"]
        self.assertEqual(self.check(sid, late)["reasons"], ["grounding"])
        wrong = self.replays[sid, "wrong"]
        self.assertIn("authorized_actions", self.check(sid, wrong)["reasons"])

    def test_duplicate_record_call_does_not_create_a_second_effect(self):
        sid = "TR8_TV_REC"
        record = self.replays[sid, "idempotent_repeat"]
        self.assertFalse(record["calls"][-1]["result"]["done"])
        result = self.check(sid, record)
        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(result["trace_policy_notes"], ["repeated_idempotent_attempt"])

    def test_ranked_choices_flip_only_for_decisive_fixture_changes(self):
        targets = {
            "TR8_PODCAST_NEWEST": ("episode_id", "w8_p_81"),
            "TR8_PODCAST_NEWDATE": ("episode_id", "w8_p_07"),
            "TR8_SUB_CHEAP": ("subscription_id", "w8_sub_8"),
            "TR8_SUB_CHEAPCHANGE": ("subscription_id", "w8_sub_5"),
            "TR8_SUB_EXPENSIVE": ("subscription_id", "w8_sub_5"),
            "TR8_SUB_LAST": ("subscription_id", "w8_sub_2"),
            "TR8_SUB_LASTCHANGE": ("subscription_id", "w8_sub_5"),
            "TR8_SUB_FIRST": ("subscription_id", "w8_sub_8"),
        }
        for sid, (argument, expected) in targets.items():
            with self.subTest(scenario=sid):
                calls = self.replays[sid, "standard"]["calls"]
                self.assertEqual(calls[-1]["arguments"][argument], expected)


if __name__ == "__main__":
    unittest.main()
