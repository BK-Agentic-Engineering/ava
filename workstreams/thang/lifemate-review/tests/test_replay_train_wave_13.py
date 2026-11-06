"""History materialization, target provenance and latest-session regressions."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from replay_train_wave_13 import DESIGN, OUTPUT, canonical_state, load_design, verify


class Wave13Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design = load_design(DESIGN)
        cls.scenarios = {s["scenario_id"]: s for s in cls.design["scenarios"]}
        cls.evidence = json.loads(OUTPUT.read_text(encoding="utf-8"))
        cls.rows = {(r["scenario_id"], r["trace_case"], r["ordering"]): r
                    for r in cls.evidence["replays"]}

    def test_reminder_order_pair_selects_different_logical_target(self):
        identities = []
        for sid, content, expected_time in [
            ("TR13_REM_AB", "Gom Nẹp Tre", "2027-07-15T11:00:00+07:00"),
            ("TR13_REM_BA", "Soát Cuộn Mây", "2027-07-15T09:30:00+07:00"),
        ]:
            scenario = self.scenarios[sid]
            self.assertEqual(scenario["agent_visible"]["request"], "Lùi cái vừa tạo sau cùng nửa tiếng nhé.")
            row = self.rows[sid, "standard", "original"]
            self.assertEqual(row["verdict"]["verdict"], "pass")
            records = row["final_state"]["reminders"]["reminders"]
            target = next(r for r in records if r["content"] == content)
            self.assertEqual(target["time"], expected_time)
            old = self.evidence["histories"][sid]["post_state"]["reminders"]["reminders"]
            identities.append(sorted((r["content"], r["time"], r["repeat"], r["done"]) for r in old))
            self.assertEqual(len(records), 3)
            self.assertEqual(self.rows[sid, "other", "original"]["verdict"]["verdict"], "reject")
            self.assertEqual(self.rows[sid, "replay_creations", "original"]["verdict"]["verdict"], "reject")
        self.assertEqual(identities[0], identities[1])

    def test_first_last_and_largest_id_do_not_pass_all_orderings(self):
        for heuristic in ["first_row", "last_row", "largest_id"]:
            verdicts = [self.rows[sid, heuristic, ordering]["verdict"]["verdict"]
                        for sid in ["TR13_REM_AB", "TR13_REM_BA"]
                        for ordering in ["original", "reversed"]]
            self.assertIn("reject", verdicts)
        for sid in ["TR13_REM_AB", "TR13_REM_BA"]:
            history = self.evidence["histories"][sid]
            for ordering in ["original", "reversed"]:
                row = self.rows[sid, "fresh_lookup", ordering]
                self.assertEqual(canonical_state(row["initial_state"]), canonical_state(history["post_state"]))
                self.assertEqual(row["verdict"]["verdict"], "pass")
                self.assertEqual(row["calls"][0]["name"], "reminders.list")

    def test_visible_history_uses_real_paired_assistant_results(self):
        for sid in ["TR13_REM_AB", "TR13_REM_BA"]:
            visible = self.evidence["agent_visible"][sid]
            turns = visible["history"]
            self.assertEqual([t["role"] for t in turns], ["user", "assistant"])
            self.assertIn("audio_text", turns[0])
            self.assertNotIn("audio", turns[0])
            assistant = turns[1]
            self.assertEqual(len(assistant["tool_calls"]), len(assistant["tool_results"]))
            self.assertEqual(assistant["tool_results"], [
                c["result"] for c in self.evidence["histories"][sid]["calls"]
            ])
            row = self.rows[sid, "standard", "original"]
            hidden = deepcopy(visible)
            for turn in hidden["history"]:
                if turn["role"] == "assistant":
                    turn["tool_calls"] = []
                    turn["tool_results"] = []
            verdict = verify(self.scenarios[sid], row["initial_state"], row["calls"],
                             row["final_state"], self.evidence["histories"][sid]["events"], hidden)
            self.assertIn("historical_grounding", verdict["reasons"])

    def test_busy_attempt_does_not_replace_successful_start_referent(self):
        a, b = "TR13_APP_A", "TR13_APP_B"
        self.assertEqual(self.evidence["histories"][a]["post_state"], self.evidence["histories"][b]["post_state"])
        selected_ids = []
        for sid in [a, b]:
            history = self.evidence["histories"][sid]
            self.assertFalse(history["events"]["busy"]["result"]["done"])
            self.assertTrue(history["events"]["started"]["result"]["ok"])
            row = self.rows[sid, "standard", "original"]
            self.assertEqual(row["calls"][0]["name"], "appliances.stop")
            selected_ids.append(row["calls"][0]["arguments"]["appliance_id"])
            self.assertEqual(row["verdict"]["verdict"], "pass")
            self.assertEqual(self.rows[sid, "other", "original"]["verdict"]["verdict"], "reject")
        self.assertNotEqual(*selected_ids)

    def test_old_contact_values_differ_despite_identical_current_state(self):
        a, b = "TR13_CONTACT_OLD_EMAIL", "TR13_CONTACT_OLD_PAIR"
        self.assertEqual(self.evidence["histories"][a]["post_state"], self.evidence["histories"][b]["post_state"])
        expected = {a: "thu.cu@daymoc.example.test", b: "khac.cu@daymoc.example.test"}
        for sid in [a, b]:
            row = self.rows[sid, "standard", "original"]
            self.assertEqual(row["calls"][-1]["arguments"]["content"], expected[sid])
            self.assertEqual(row["verdict"]["verdict"], "pass")
        middle = self.rows["TR13_CONTACT_INTERMEDIATE", "standard", "original"]
        self.assertEqual(middle["calls"][-1]["arguments"]["content"], "thu.giua@daymoc.example.test")

    def test_private_correct_id_needs_observation_but_named_fresh_lookup_can_replace_history(self):
        for case, expected in [("standard", "reject"), ("fresh_lookup", "pass")]:
            sid = "TR13_REM_NAMED"
            row = self.rows[sid, case, "original"]
            visible = deepcopy(self.evidence["agent_visible"][sid])
            visible["history"] = []
            result = verify(self.scenarios[sid], row["initial_state"], row["calls"], row["final_state"],
                            self.evidence["histories"][sid]["events"], visible)
            self.assertEqual(result["verdict"], expected)
            if case == "standard":
                self.assertIn("source_grounding", result["reasons"])

    def test_historical_completion_survives_reminder_replacement(self):
        sid = "TR13_REM_DONE"
        for ordering in ["original", "reversed"]:
            row = self.rows[sid, "standard", ordering]
            reminders = row["final_state"]["reminders"]["reminders"]
            target = next(r for r in reminders if r["content"] == "Gom Nẹp Tre")
            self.assertTrue(target["done"])
            self.assertEqual(target["repeat"], "weekly")
            self.assertEqual(target["time"], "2027-07-15T11:00:00+07:00")
            self.assertEqual([c["name"] for c in row["calls"]], [
                "reminders.delete", "reminders.create", "reminders.complete",
            ])

    def test_six_explicit_current_checks_reject_history_only_path(self):
        scenarios = [s for s in self.scenarios.values() if s["oracle_draft"].get("fresh_required")]
        self.assertEqual(len(scenarios), 6)
        for scenario in scenarios:
            row = self.rows[scenario["scenario_id"], "history_only", "original"]
            self.assertEqual(row["verdict"]["verdict"], "reject")
            self.assertIn("fresh_observation", row["verdict"]["reasons"])

    def test_fresh_reads_require_the_requested_record_before_use(self):
        sid = "TR13_CONTACT_CURRENT_CHECK"
        standard = self.rows[sid, "standard", "original"]
        for case in ["empty_read", "unrelated_read", "late_read"]:
            record = self.rows[sid, case, "original"]
            self.assertEqual(record["verdict"]["reasons"], ["fresh_observation"])
            self.assertEqual(record["final_state"], standard["final_state"])
        self.assertEqual(self.rows[sid, "empty_read", "original"]["calls"][0]["result"]["contacts"], [])
        self.assertEqual(self.rows[sid, "broad_read", "original"]["verdict"]["verdict"], "pass")
        self.assertEqual(self.rows["TR13_APP_READ", "unrelated_read", "original"]["verdict"]["reasons"],
                         ["fresh_observation"])
        self.assertEqual(self.rows["TR13_REM_READ", "empty_read", "original"]["verdict"]["reasons"],
                         ["fresh_observation"])

    def test_financial_noop_and_new_transfer_are_reconciled_separately(self):
        sid = "TR13_BANK_A"
        history = self.evidence["histories"][sid]
        self.assertFalse(history["events"]["failed"]["result"]["done"])
        self.assertEqual(history["post_state"]["banking"]["accounts"][0]["balance"], 350000)
        row = self.rows[sid, "standard", "original"]
        self.assertEqual(row["calls"][-1]["arguments"]["amount"], 100000)
        account = next(a for a in row["final_state"]["banking"]["accounts"] if a["id"] == "hist_fund_A")
        self.assertEqual(account["balance"], 250000)
        self.assertEqual(len(row["final_state"]["banking"]["transactions"]), 3)
        self.assertEqual(self.rows[sid, "replay_action", "original"]["verdict"]["verdict"], "reject")

    def test_frozen_histories_match_materialized_calls_and_are_separate_from_latest_logs(self):
        for sid, scenario in self.scenarios.items():
            self.assertEqual(scenario["agent_visible"]["history"], self.evidence["agent_visible"][sid]["history"])
            history = self.evidence["histories"][sid]
            reconstructed = [
                {"name": c["name"], "arguments": c["arguments"], "result": r}
                for turn in history["turns"] if turn["role"] == "assistant"
                for c, r in zip(turn["tool_calls"], turn["tool_results"])
            ]
            self.assertEqual(reconstructed, history["calls"])
        self.assertEqual(len(self.scenarios), 40)


if __name__ == "__main__":
    unittest.main()
