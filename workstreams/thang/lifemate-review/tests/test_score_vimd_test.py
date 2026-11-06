"""CPU transcript/scoring tests; no inference or source mutation."""
import copy
import importlib.util
import json
from pathlib import Path
import random
import tempfile
import unittest

from lifemate.benchmark import distance,normalize

SPEC=importlib.util.spec_from_file_location('score_test',Path(__file__).resolve().parents[1]/'scripts/score_vimd_test.py')
SCORE=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCORE)


def row(sample_id,reference='xin chào',speaker='one',region='North'):
    return dict(sample_id=sample_id,reference=reference,source='ViMD',split='test',
                filename=sample_id+'.wav',speaker_id=speaker,region=region,province_code=11,
                province_name='CaoBang',issues=[],issue_status='clear',audio={'duration_seconds':1.})


def prediction(sample_id,text):
    return dict(sample_id=sample_id,status='ok',text=text,error=None,duration_seconds=1.)


class ScoreTests(unittest.TestCase):
    def test_known_insert_delete_substitute_distances(self):
        self.assertEqual(distance(['a','b'],['a','x','b']),1)
        self.assertEqual(distance(['a','b'],['a']),1)
        self.assertEqual(distance(['a','b'],['a','c']),1)
        self.assertEqual(distance('kitten','sitting'),3)
        self.assertEqual(distance([],['a','b']),2)

    def test_vietnamese_normalization_diacritics_digits_and_cer_spaces(self):
        self.assertEqual(normalize('  XIN, CHA\u0300O!  12—bạn\tơi. '),'xin chào 12 bạn ơi')
        result=SCORE.score_rows([row('a','xin chào')],[prediction('a','xinchào')])[0]
        self.assertEqual(result['char_errors'],0)
        self.assertEqual(result['chars'],7)
        self.assertEqual(result['word_errors'],2)
        result=SCORE.score_rows([row('a','chào')],[prediction('a','chao')])[0]
        self.assertEqual(result['char_errors'],1)
        result=SCORE.score_rows([row('a','12')],[prediction('a','mười hai')])[0]
        self.assertGreater(result['word_errors'],0)

    def test_corpus_weighting_is_not_mean_per_utterance(self):
        rows=[row('a','a'),row('b','b c d e f g h i j')]
        predictions=[prediction('b','b c d e f g h i j'),prediction('a','x')]
        original=copy.deepcopy((rows,predictions))
        scored=SCORE.score_rows(rows,predictions)
        self.assertEqual([r['sample_id'] for r in scored],['a','b'])
        self.assertEqual(SCORE.aggregate(scored)['wer_whitespace'],.1)
        self.assertEqual(sum(r['wer_whitespace'] for r in scored)/2,.5)
        self.assertEqual((rows,predictions),original)
        self.assertEqual(scored[0]['raw_reference'],'a')
        self.assertEqual(scored[0]['normalized_hypothesis'],'x')

    def test_bad_id_joins_statuses_and_denominators_rejected(self):
        rows=[row('a')]
        cases=[[],[prediction('unknown','x')],[prediction('a','x')]*2,
               [dict(sample_id='a',status='ok',text=None,error=None,duration_seconds=1.)],
               [{**prediction('a','x'),'status':'timeout'}]]
        for predictions in cases:
            with self.subTest(predictions=predictions),self.assertRaises(ValueError):
                SCORE.score_rows(rows,predictions)
        with self.assertRaises(ValueError):
            SCORE.score_rows(rows*2,[prediction('a','x')])
        for reference in ['', '  ', '...']:
            with self.subTest(reference=reference),self.assertRaisesRegex(ValueError,'Zero reference denominator'):
                SCORE.score_rows([row('a',reference)],[prediction('a','')])
        with self.assertRaises(ValueError): SCORE.ratio(1,0)

    def test_error_and_empty_predictions_keep_reference_denominators(self):
        rows=[row('a'),row('b')]
        p=[prediction('a',''),dict(sample_id='b',status='error',text=None,duration_seconds=1.,
                                  error=dict(stage='inference',type='ValueError',message='fixture'))]
        scored=SCORE.score_rows(rows,p)
        total=SCORE.aggregate(scored)
        self.assertEqual(total['words'],4)
        self.assertEqual(total['word_errors'],4)
        self.assertEqual(total['wer_whitespace'],1.)
        self.assertEqual(total['cer'],1.)
        self.assertEqual(total['errors'],1)
        self.assertEqual(total['empty_successful'],1)

    def test_bootstrap_clusters_all_utterances_and_repeated_draws_count(self):
        scored=SCORE.score_rows([row('a','a','one'),row('b','b c','one'),row('c','d','two')],
                                [prediction('a','x'),prediction('b','b c'),prediction('c','d')])
        strata=SCORE.speaker_totals(scored)
        self.assertEqual(strata[('ViMD','North')]['one'][:2],[1,3])
        class DrawTwice:
            def choices(self,keys,k):
                self_outer.assertEqual(keys,['one','two'])
                self_outer.assertEqual(k,2)
                return ['one','one']
        self_outer=self
        wer,cer=SCORE.bootstrap_draw(strata,DrawTwice())
        self.assertEqual(wer,2/6)
        self.assertEqual(cer,2/6)
        # Repeated-draw multiplicity changes a draw including both clusters.
        class DrawBoth:
            def choices(self,keys,k): return ['one','two']
        self.assertEqual(SCORE.bootstrap_draw(strata,DrawBoth())[0],1/4)

    def test_stratification_seed_and_percentile_convention(self):
        rows=[row('n1','a','one','North'),row('n2','a b','two','North'),
              row('s1','c','three','South'),row('s2','c d','four','South')]
        scored=SCORE.score_rows(rows,[prediction(r['sample_id'],'x') for r in rows])
        a=SCORE.speaker_ci(scored)
        self.assertEqual(a,SCORE.speaker_ci(list(reversed(scored))))
        self.assertEqual(a['replicates'],2000)
        self.assertEqual(a['seed'],42)
        rng=random.Random(42)
        strata=SCORE.speaker_totals(scored)
        draws=[SCORE.bootstrap_draw(strata,rng) for _ in range(2000)]
        for index,key in enumerate(['wer_whitespace','cer']):
            values=sorted(x[index] for x in draws)
            self.assertEqual(a[key],[values[int(.025*1999)],values[int(.975*1999)]])
        self.assertFalse(SCORE.speaker_ci(scored[:1])['available'])
        scored[0]['speaker_id']=None
        self.assertFalse(SCORE.speaker_ci(scored)['available'])

    def test_mixed_repeated_draws_are_not_deduplicated(self):
        strata={('ViMD','North'):{'one':[1,3,1,3],
                                 'two':[0,1,0,1], 'three':[0,9,0,9]}}
        class Draw:
            def choices(self,keys,k):
                self_outer.assertEqual(k,3)
                return ['one','one','two']
        self_outer=self
        wer,cer=SCORE.bootstrap_draw(strata,Draw())
        self.assertEqual(wer,2/7)
        self.assertEqual(cer,2/7)
        self.assertNotEqual(wer,1/4)  # Deduplicating one/two would give 1/4.

    def test_archived_manifest_and_summary_mismatches_rejected_before_scoring(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            canonical={'provenance':{'source':'ViMD','split':'test'},'records':[row('a')]}
            manifest=root/'canonical.json'
            manifest.write_text(json.dumps(canonical),encoding='utf-8')
            (root/'manifest.json').write_text('{}',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'Archived manifest'):
                SCORE.load_inputs(root,manifest)
            (root/'manifest.json').write_text(json.dumps(canonical),encoding='utf-8')
            for name,data in [('configuration',{}),('run_metadata',{}),('completion_summary',{})]:
                (root/(name+'.json')).write_text(json.dumps(data),encoding='utf-8')
            (root/'predictions.jsonl').write_text(json.dumps(prediction('a','xin chào'))+'\n',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'Completion summary'):
                SCORE.load_inputs(root,manifest)


if __name__=='__main__': unittest.main()
