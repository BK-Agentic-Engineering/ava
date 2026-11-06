import unittest
from lifemate.benchmark import evaluate, summary, normalize, paired_ci

class ScoringTests(unittest.TestCase):
    def rows(self):
        return [dict(sample_id=str(i),source="demo",split="dev",speaker_id=str(i),region="North",reference=t) for i,t in enumerate(["một hai ba", "bốn"])]
    def test_corpus_weighting_and_failure(self):
        scored=evaluate(self.rows(),[dict(sample_id="0",status="ok",text="một hai ba"),dict(sample_id="1",status="timeout")])
        self.assertEqual(summary(scored)["wer_whitespace"],.25)
        self.assertEqual(summary(scored)["failure_rate"],.5)
    def test_numbers_and_negation_not_erased(self):
        self.assertNotEqual(normalize("500 nghìn"),normalize("500"))
        self.assertNotEqual(normalize("đừng tắt"),normalize("tắt"))
        self.assertEqual(normalize("ĐÈN, bếp!"),"đèn bếp")
    def test_ids_and_empty_reference_rejected(self):
        with self.assertRaises(ValueError): evaluate(self.rows(),[])
        rows=self.rows(); rows[0]["reference"]=""
        with self.assertRaises(ValueError): evaluate(rows,[])
    def test_pairing_bootstrap(self):
        a=evaluate(self.rows(),[dict(sample_id=str(i),status="ok",text=r["reference"]) for i,r in enumerate(self.rows())])
        result=paired_ci(a,a,100)
        self.assertEqual(result["ci95"],[0,0])
        with self.assertRaises(ValueError):paired_ci(a,a[::-1],100)

if __name__ == "__main__": unittest.main()
