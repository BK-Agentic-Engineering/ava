"""Focused CPU scoring/validation tests. No inference or semantic metrics."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import score_vnslu_test as score


def row(id,text,intent='intent'):
    return dict(sample_id=id,official_id=id,filename=id+'.wav',split='test',reference=text,
                speaker_id=None,region=None,issues=['repeated_exact_reference'],intent=intent,
                entities=[dict(type='device',filler='đèn')],sentence_annotation='[ device : đèn ]',
                audio=dict(duration_seconds=1.))


def prediction(id,text,status='ok'):
    return dict(sample_id=id,status=status,text=text,error=None if status=='ok' else
        dict(stage='inference',type='ValueError',message='fixture'),duration_seconds=1.)


class ScoringTests(unittest.TestCase):
    def test_exact_join_reordered_preserves_null_optional_metadata_and_labels(self):
        rows=[row('a','Xin chào!'),row('b','Đèn này, 12 giờ.')]
        p=[prediction('b','ĐÈN NÀY 12 GIỜ'),prediction('a','XIN CHÀO')]
        before=copy.deepcopy((rows,p));scored=score.score_rows(rows,p)
        self.assertEqual([r['sample_id'] for r in scored],['a','b'])
        self.assertTrue(all(r['word_errors']==0 and r['char_errors']==0 for r in scored))
        self.assertTrue(all(r['speaker_id'] is None and r['region'] is None for r in scored))
        for actual,original in zip(scored,rows):
            self.assertEqual(actual['raw_reference'],original['reference'])
            for field in ['issues','intent','entities','sentence_annotation']:self.assertEqual(actual[field],original[field])
        self.assertEqual((rows,p),before)

    def test_missing_duplicate_unknown_and_duplicate_reference_ids_rejected(self):
        rows=[row('a','a'),row('b','b')];p=[prediction('a','a'),prediction('b','b')]
        for bad in [p[:1],p+[p[0]],[p[0],prediction('unknown','x')]]:
            with self.assertRaises(ValueError):score.score_rows(rows,bad)
        with self.assertRaises(ValueError):score.score_rows([rows[0],rows[0]],p)

    def test_known_distances_diacritics_and_corpus_weighting(self):
        rows=[row('a','a'),row('b','b c d e f g h i j')]
        scored=score.score_rows(rows,[prediction('a','x'),prediction('b','b c d e f g h i j')])
        metrics=score.aggregate(scored)
        self.assertEqual(metrics['word_errors'],1);self.assertEqual(metrics['words'],10)
        self.assertEqual(metrics['wer_whitespace'],.1)
        self.assertNotEqual(metrics['wer_whitespace'],sum(r['wer_whitespace'] for r in scored)/2)
        r=score.score_rows([row('x','mỉ')],[prediction('x','mì')])[0]
        self.assertEqual((r['word_errors'],r['char_errors'],r['words'],r['chars']),(1,1,1,2))
        r=score.score_rows([row('x','a b')],[prediction('x','a c b')])[0]
        self.assertEqual((r['word_errors'],r['char_errors']),(1,1))

    def test_failures_and_empty_success_keep_denominators(self):
        rows=[row('a','xin chào'),row('b','xin chào')]
        preds=[prediction('a',None,'error'),prediction('b','')]
        scored=score.score_rows(rows,preds);aggregate=score.aggregate(scored)
        self.assertEqual((aggregate['words'],aggregate['word_errors']),(4,4))
        self.assertEqual((aggregate['chars'],aggregate['char_errors']),(14,14))
        self.assertEqual(aggregate['errors'],1);self.assertEqual(aggregate['empty_successful'],1)
        self.assertIsNone(scored[0]['raw_hypothesis']);self.assertEqual(scored[0]['normalized_hypothesis'],'')
        counts=score.coverage(rows,preds)
        self.assertTrue(counts['coverage_complete']);self.assertFalse(counts['all_successful_inference'])

    def test_empty_normalized_reference_rejected_without_exclusion(self):
        rows=[row('a','...'),row('b','valid')]
        with self.assertRaises(ValueError):score.score_rows(rows,[prediction('a',''),prediction('b','valid')])
        self.assertEqual(len(rows),2)

    def test_intent_aggregation_reconciles_and_no_fabricated_bootstrap(self):
        rows=[row('a','a','x'),row('b','b c','y'),row('c','d','x')]
        scored=score.score_rows(rows,[prediction('a','x'),prediction('b','b c'),prediction('c','d')])
        metrics=score.make_metrics(scored,{},score.coverage(rows,[prediction('a','x'),prediction('b','b c'),prediction('c','d')]))
        self.assertEqual(metrics['by_intent']['x']['n'],2)
        for key in ['n',*score.TOTALS]:self.assertEqual(sum(g[key] for g in metrics['by_intent'].values()),metrics['overall'][key])
        self.assertFalse(metrics['uncertainty']['available'])
        self.assertNotIn('by_region',metrics);self.assertNotIn('intent_accuracy',metrics)

    def test_actual_validation_rejects_configuration_coverage_or_failed_child(self):
        root=score.ROOT/'artifacts/kaggle_vnslu_test'/score.RUN
        config=score.read_json(root/'configuration.json');metadata=score.read_json(root/'run_metadata.json')
        summary=score.read_json(root/'completion_summary.json');rows=score.read_json(root/'manifest.json')['records']
        p=[json.loads(x) for x in (root/'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertTrue(score.validate_execution(config,metadata,summary,rows,p)['all_successful_inference'])
        for key,value in [('precision','fp32'),('python','3.13.15')]:
            bad=copy.deepcopy(config);bad[key]=value
            with self.assertRaises(ValueError):score.validate_execution(bad,metadata,summary,rows,p)
        bad=copy.deepcopy(summary);bad['successful']=2400
        with self.assertRaises(ValueError):score.validate_execution(config,metadata,bad,rows,p)
        bad=copy.deepcopy(metadata);bad['sessions'][-1]['launcher']['child_exit_code']=1
        with self.assertRaises(ValueError):score.validate_execution(config,bad,summary,rows,p)
        for key,value in [('device','cuda:1'),('visible_gpu_count',2),('deterministic_algorithms',False)]:
            bad=copy.deepcopy(metadata);bad['sessions'][-1]['inference'][key]=value
            with self.assertRaises(ValueError):score.validate_execution(config,bad,summary,rows,p)


if __name__=='__main__':unittest.main()
