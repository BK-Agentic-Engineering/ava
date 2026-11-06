"""Focused branch and snapshot checks against Wave 16 canonical replay."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from replay_train_wave_16 import DESIGN, OUTPUT, load_design, verify


class Wave16Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads(OUTPUT.read_text(encoding="utf-8"))
        cls.rows = {(r["scenario_id"], r["trace_case"]): r for r in cls.evidence["replays"]}
        cls.design = {s["scenario_id"]: s for s in load_design(DESIGN)["scenarios"]}

    def row(self, sid, case="standard"):
        return self.rows["TR16_" + sid, case]

    def test_every_standard_and_noop_snapshot(self):
        self.assertEqual(set(self.design), {sid for sid, case in self.rows if case == "standard"})
        for sid, case in self.rows:
            row = self.rows[sid, case]
            if case == "standard":
                self.assertEqual(row["verdict"]["verdict"], "pass")
            before = self.evidence["scenarios"][sid]["post_history_state"]
            for call in row["calls"]:
                if call["result"].get("done") is False or not call["result"]["ok"]:
                    self.assertEqual(call["state_after"], before, (sid, case))
                before = call["state_after"]
            self.assertEqual(before, row["final_state"])

    def test_same_delivered_goal_accepts_read_or_qualified_noop(self):
        sid = "PARCEL_DELIVERED"
        expected = self.row(sid)["final_state"]
        for case in ["observed_noop", "broad_read"]:
            self.assertEqual(self.row(sid, case)["verdict"]["verdict"], "pass")
            self.assertEqual(self.row(sid, case)["final_state"], expected)
        self.assertIn("fallback_authorization", self.row("PARCEL_ATTEMPT", "read_only_trigger")["verdict"]["reasons"])
        redundant = self.row(sid, "redundant_attempt")
        self.assertEqual(redundant["verdict"]["verdict"], "pass")
        self.assertEqual(redundant["verdict"]["reasons"], [])
        self.assertEqual(redundant["verdict"]["efficiency_notes"], ["redundant_attempt"])
        self.assertEqual(redundant["calls"][0]["state_after"], redundant["calls"][1]["state_after"])
        self.assertEqual(redundant["final_state"], expected)
        self.assertEqual(self.row("PARCEL_MISSING", "broad_absence")["verdict"]["verdict"], "pass")

    def test_recovery_rejects_unsupported_trigger_and_duplicates(self):
        for sid, case, reason in [
            ("PARCEL_SUCCESS", "fallback_after_success", "fallback_authorization"),
            ("PARCEL_MISSING", "other_delivered", "fallback_authorization"),
            ("PARCEL_DELIVERED", "late", "fallback_authorization"),
            ("PARCEL_DELIVERED", "duplicate_fallback", "branch"),
            ("PARCEL_DELIVERED", "repeated_noop", "branch"),
            ("PARCEL_HIST", "repeat_history", "unauthorized_action"),
            ("MAP_HOME", "wrong_scope", "fallback_authorization"),
            ("MAP_HOME", "late", "fallback_authorization"),
        ]:
            self.assertIn(reason, self.row(sid, case)["verdict"]["reasons"])
        self.assertEqual(len(self.evidence["scenarios"]["TR16_PARCEL_HIST"]["historical_calls"]), 1)
        self.assertEqual(self.row("MAP_HOME", "broad_absence")["verdict"]["verdict"], "pass")

    def test_validation_failure_cannot_authorize_fallback(self):
        row = self.row("PARCEL_DELIVERED", "validation_failure")
        self.assertFalse(row["calls"][0]["validation"]["ok"])
        self.assertFalse(row["calls"][0]["result"]["ok"])
        self.assertEqual(row["verdict"]["reasons"], ["call_failure", "fallback_authorization"])

    def test_waitlist_success_and_held_noop_differ(self):
        waiting = self.row("LIB_WAIT")["calls"][-1]
        self.assertEqual(waiting["result"]["reservation"]["status"], "waiting")
        held = self.row("LIB_HELD")["calls"][1]
        self.assertFalse(held["result"]["done"])
        self.assertEqual(self.row("LIB_HELD", "skip_fallback_lookup")["verdict"]["reasons"], ["fallback_grounding"])

    def test_retry_requires_the_authorized_state_change(self):
        calls = self.row("APP_ATTEMPT")["calls"]
        self.assertFalse(calls[1]["result"]["done"])
        self.assertEqual(calls[2]["result"]["item"]["state"]["status"], "idle")
        self.assertEqual(calls[3]["result"]["item"]["state"]["cycle"], "quick")
        self.assertEqual(self.row("APP_BUSY", "retry_without_stop")["verdict"]["verdict"], "reject")

    def test_verifier_only_unqualified_response_and_mutating_noop(self):
        sid = "TR16_PARCEL_DELIVERED"
        s = self.design[sid]
        initial = self.evidence["scenarios"][sid]["post_history_state"]
        for mutate, reason in [
            (lambda call: call["result"].update(message="unclassified outcome"), "fallback_authorization"),
            (lambda call: call["state_after"]["package_tracking"]["shipments"].clear(), "state"),
        ]:
            calls = deepcopy(self.row("PARCEL_DELIVERED", "observed_noop")["calls"])
            mutate(calls[0])
            verdict = verify(s["oracle_draft"], s["agent_visible"]["allowed_tools"], initial, calls)
            self.assertIn("unqualified_noop", verdict["reasons"])
            self.assertIn(reason, verdict["reasons"])


if __name__ == "__main__":
    unittest.main()
