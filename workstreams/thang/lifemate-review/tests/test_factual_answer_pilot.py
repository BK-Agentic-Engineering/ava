"""Regression checks for the scoped factual-answer pilot."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from evaluate_factual_answer_pilot import SPEC, check_source, evaluate, grade, load_design, overall


class FactualPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = {c["scenario_id"]: c for c in load_design(SPEC)["cases"]}

    def test_every_probe_and_source(self):
        output = evaluate()
        self.assertEqual(output["scenarios"], 8)
        self.assertEqual(output["verdict_counts"], {"pass": 17, "fail": 40, "unresolved": 8})

    def test_required_and_optional_text(self):
        self.assertEqual(grade(self.cases["TR13_CONTACT_INSPECT"], None), ("fail", "missing_answer"))
        self.assertEqual(grade(self.cases["TR16_APP_KEEP"], None), ("pass", "answer_optional"))

    def test_preserves_valid_forms_but_does_not_pass_keywords(self):
        case = self.cases["TR10_APPL_LOOK"]
        self.assertEqual(grade(case, unicodedata.normalize("NFD", "ĐANG GIẶT chế độ ECO!"))[0], "pass")
        self.assertEqual(grade(case, "Đang chạy.")[0], "fail")
        self.assertEqual(grade(case, "Đang chạy eco nhưng tôi không rõ máy nào.")[0], "unresolved")

    def test_canonical_evidence_guards_entity_and_temporal_selection(self):
        case = deepcopy(self.cases["TR13_CONTACT_INSPECT"])
        case["evidence"]["call"] = 1
        with self.assertRaises(AssertionError):
            check_source(case)
        case = deepcopy(self.cases["TR9_BANK_LOOK"])
        case["evidence"]["claims"][1]["value"] = 900000
        with self.assertRaises(AssertionError):
            check_source(case)

    def test_answer_and_trace_verdicts_combine_without_masking_failure(self):
        self.assertEqual(overall("fail", "pass"), "fail")
        self.assertEqual(overall("pass", "fail"), "fail")
        self.assertEqual(overall("pass", "unresolved"), "unresolved")
        self.assertEqual(overall("pass", "pass"), "pass")


if __name__ == "__main__":
    unittest.main()
