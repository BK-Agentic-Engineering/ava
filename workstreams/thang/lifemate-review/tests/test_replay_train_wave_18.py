"""Focused profile, returned landmark and saved-place preservation regressions."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from replay_train_wave_18 import DESIGN, OUTPUT, load_design, verify


class Wave18Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design=load_design(DESIGN)
        cls.scenarios={s["scenario_id"]:s for s in cls.design["scenarios"]}
        cls.evidence=json.loads(OUTPUT.read_text(encoding="utf8"))
        cls.rows={(r["scenario_id"],r["trace_case"]):r for r in cls.evidence["replays"]}

    def test_profile_only_changes_target_and_both_same_names_are_observable(self):
        a,b=(deepcopy(self.scenarios[sid]["agent_visible"]) for sid in ["TR18_WORK_A","TR18_WORK_B"])
        self.assertNotEqual(a["context"]["user_profile"].pop("work_address"),b["context"]["user_profile"].pop("work_address"))
        self.assertEqual(a,b)
        chosen=[]
        for sid in ["TR18_WORK_A","TR18_WORK_B"]:
            row=self.rows[sid,"standard"]
            self.assertEqual(row["verdict"]["verdict"],"pass")
            places=row["calls"][0]["result"]["places"]
            self.assertEqual(len(places),2)
            self.assertEqual(len({p["name"] for p in places}),1)
            chosen.append(row["calls"][1]["arguments"]["place_id"])
        self.assertEqual(chosen,["w18_lam","w18_dao"])

    def test_broad_search_retains_sufficient_landmark_evidence(self):
        for sid in self.scenarios:
            standard,broad=(self.rows[sid,case] for case in ["standard","broad_search"])
            self.assertEqual(standard["final_state"],broad["final_state"])
            self.assertEqual(broad["verdict"]["verdict"],"pass")

    def test_explicit_override_and_wording_control_keep_the_same_saved_target(self):
        for sid in ["TR18_WORK_A","TR18_ADDRESS","TR18_WORDING"]:
            self.assertEqual(self.rows[sid,"standard"]["calls"][1]["arguments"],
                             {"place_id":"w18_lam","label":"Chỗ làm chìa"})
        self.assertEqual(self.scenarios["TR18_ADDRESS"]["agent_visible"]["context"]["user_profile"]["work_address"],
                         "Tòa Bạch Đào")

    def test_relabel_preserves_id_and_unrelated_bookmark(self):
        sid="TR18_RELABEL"
        before=self.evidence["fixtures"][sid]["maps"]["saved_places"]
        after=self.rows[sid,"standard"]["final_state"]["maps"]["saved_places"]
        self.assertEqual(len(before),len(after))
        self.assertEqual(after[0],before[0])
        self.assertEqual(after[1],{**before[1],"label":"Chỗ làm chìa"})

    def test_successful_wrong_effects_and_guessed_correct_state_are_rejected(self):
        for sid in self.scenarios:
            for case in ["distractor","damage_existing","wrong_label"]:
                row=self.rows[sid,case]
                self.assertTrue(all(c["result"]["ok"] for c in row["calls"]))
                self.assertEqual(row["verdict"]["reasons"],["authorized_actions","state"])
            for case in ["guessed_id","late_read"]:
                self.assertEqual(self.rows[sid,case]["final_state"],self.rows[sid,"standard"]["final_state"])
                self.assertEqual(self.rows[sid,case]["verdict"]["reasons"],["grounding","place_evidence"])

    def without_details(self, sid):
        # Verifier-only probe. SDK trace and its canonical saved result stay intact.
        row = self.rows[sid, "standard"]
        calls = deepcopy(row["calls"])
        for place in calls[0]["result"]["places"]:
            place.pop("detail", None)
        initial = {k: v for k, v in self.evidence["fixtures"][sid].items() if k != "_meta"}
        return verify(self.design["worlds"][0], self.scenarios[sid], initial, calls, row["final_state"])

    def test_verifier_probe_explicit_address_accepts_no_detail(self):
        verdict = self.without_details("TR18_ADDRESS")
        self.assertEqual(verdict["verdict"], "pass")
        self.assertEqual(verdict["reasons"], [])
        self.assertIn("detail", self.design["worlds"][0]["witnesses"]["a"][1])
        self.assertIn("detail", self.rows["TR18_ADDRESS", "standard"]["calls"][0]["result"]["places"][0])

    def test_verifier_probe_profile_still_needs_landmark(self):
        for sid in ["TR18_WORK_A", "TR18_WORK_B", "TR18_HOME"]:
            verdict = self.without_details(sid)
            self.assertEqual(verdict["verdict"], "reject")
            self.assertEqual(verdict["reasons"], ["grounding", "place_evidence"])

    def test_verifier_probe_explicit_address_rejects_ambiguous_ids(self):
        sid = "TR18_ADDRESS"
        row = self.rows[sid, "standard"]
        calls = deepcopy(row["calls"])
        target = next(p for p in calls[0]["result"]["places"] if p["id"] == "w18_lam")
        calls[0]["result"]["places"].append({**target, "id": "probe_other_id"})
        initial = {k: v for k, v in self.evidence["fixtures"][sid].items() if k != "_meta"}
        verdict = verify(self.design["worlds"][0], self.scenarios[sid], initial, calls, row["final_state"])
        self.assertEqual(verdict["reasons"], ["grounding", "place_evidence"])

    def test_verifier_probe_profile_rejects_two_matching_ids(self):
        for sid in ["TR18_WORK_A", "TR18_HOME"]:
            with self.subTest(scenario_id=sid):
                row = self.rows[sid, "broad_search"]
                calls = deepcopy(row["calls"])
                saved_id = calls[-1]["arguments"]["place_id"]
                target = next(p for p in calls[0]["result"]["places"] if p["id"] == saved_id)
                # In-memory response probe, not an SDK search result.
                calls[0]["result"]["places"].append({
                    **target, "id": "probe_second_shop", "address": "51 Ngách Khác",
                })
                initial = {k: v for k, v in self.evidence["fixtures"][sid].items() if k != "_meta"}
                verdict = verify(self.design["worlds"][0], self.scenarios[sid], initial, calls, row["final_state"])
                self.assertEqual(verdict["verdict"], "reject")
                self.assertEqual(verdict["reasons"], ["grounding", "place_evidence"])

    def test_verifier_probe_profile_accepts_landmark_without_street_address(self):
        for sid in ["TR18_WORK_A", "TR18_HOME"]:
            with self.subTest(scenario_id=sid):
                row = self.rows[sid, "broad_search"]
                calls = deepcopy(row["calls"])
                saved_id = calls[-1]["arguments"]["place_id"]
                target = next(p for p in calls[0]["result"]["places"] if p["id"] == saved_id)
                target.pop("address")  # Only this optional response field changes.
                initial = {k: v for k, v in self.evidence["fixtures"][sid].items() if k != "_meta"}
                verdict = verify(self.design["worlds"][0], self.scenarios[sid], initial, calls, row["final_state"])
                self.assertEqual(verdict["verdict"], "pass")
                self.assertEqual(verdict["reasons"], [])


if __name__=="__main__":
    unittest.main()
