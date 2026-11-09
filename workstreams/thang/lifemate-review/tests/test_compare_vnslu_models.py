"""Synthetic CPU comparison/attempt audits. No transport or audio reads."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import compare_vnslu_models as c


def row(sample_id,reference,intent='intent'):
    return dict(sample_id=sample_id,official_id=sample_id,filename=sample_id+'.wav',split='test',
        reference=reference,intent=intent,entities=[dict(type='fixture',filler=reference)],
        sentence_annotation=reference,issues=['repeated_exact_reference'],speaker_id=None,region=None,
        audio=dict(duration_seconds=1.,sample_rate=16000,frames=16000))


def prediction(sample_id,text):
    return dict(sample_id=sample_id,status='ok',text=text,error=None,duration_seconds=1.,source_duration_seconds=1.)


def stamp(second):return f'2026-11-02T00:00:{second:02d}+00:00'


def evidence(retry=False):
    manifest=dict(provenance={},records=[row('one','xin chào')])
    config=dict(mode='full',endpoint=c.common.api.ENDPOINT,fields=c.common.api.FIELDS,automatic_retries=False,
        upload='FLOAT32 WAV mono 16000 Hz',packages={'fixture':'1'})
    metadata=dict(model_alias='glot-transcribe',sessions=[dict(status='completed',mode='full',
        started_utc=stamp(0),ended_utc=stamp(30),account_endpoint_confirmed=config['endpoint'],
        account_model_confirmed='glot-transcribe',packages=config['packages'])])
    number=2 if retry else 1
    p={**prediction('one','xin chào'), 'timestamp':stamp(5),'request_id':'request',
       'provider_version':None,'returned_model':None}
    def start(n,t):return dict(event='started',sample_id='one',attempt=n,timestamp=stamp(t),
        source_duration_seconds=1.,upload_duration_seconds=1.,upload_bytes=64080)
    attempts=[]
    if retry:
        attempts=[start(1,1),dict(event='unresolved',sample_id='one',attempt=1,timestamp=stamp(2),http_status=502),
            dict(event='retry_authorized',sample_id='one',attempt=1,timestamp=stamp(3),note='Operator reconciles unknown remote outcome; authorizes retry.')]
    attempts+=[start(number,4),dict(event='ok',sample_id='one',attempt=number,timestamp=stamp(5),http_status=200,
        prediction=p,response=dict(text=p['text'],raw_transcript='not scored',engine='unverified'),
        response_headers={'x-request-id':'request'})]
    predictions=[p];saved=c.common.api.completion(manifest,predictions,attempts)
    return [manifest,predictions,attempts,config,metadata,saved,'full']


class ExecutionTests(unittest.TestCase):
    def test_valid_authorized_502_retry_retains_unknown_history(self):
        data=evidence(True);counts,success=c.validate_valsea(*data)
        self.assertEqual(counts['request_attempts'],2)
        self.assertEqual(counts['successful'],1)
        self.assertEqual(counts['historical_unknown_remote_outcomes'],1)
        self.assertEqual(counts['unresolved_attempts'],0)
        self.assertEqual(success['one']['attempt'],2)

    def test_unauthorized_retry_and_successful_replacement_rejected(self):
        data=evidence(True);data[2]=[e for e in data[2] if e['event']!='retry_authorized']
        with self.assertRaisesRegex(ValueError,'authorization'):c.validate_valsea(*data)
        data=evidence();extra=copy.deepcopy(data[2]);extra[0].update(attempt=2,timestamp=stamp(6))
        extra[1].update(attempt=2,timestamp=stamp(7));data[2]+=extra
        with self.assertRaisesRegex(ValueError,'already successful'):c.validate_valsea(*data)
        data=evidence();data[1][0]=dict(data[1][0],text='replacement')
        with self.assertRaises(ValueError):c.validate_valsea(*data)

    def test_incomplete_inconsistent_and_missing_success_evidence_rejected(self):
        for mutate in [lambda d:d[1].clear(),lambda d:d[2].pop(),
                       lambda d:d[4]['sessions'][-1].update(status='stopped'),
                       lambda d:d[5].update(successful=0),
                       lambda d:d[2][0].update(source_duration_seconds=2.),
                       lambda d:d[2][-1].update(response=dict(text='different'))]:
            data=copy.deepcopy(evidence());mutate(data)
            with self.assertRaises(ValueError):c.validate_valsea(*data)

    def test_recorded_upload_and_source_durations_are_checked(self):
        data=evidence();data[2][0]['upload_duration_seconds']=2.
        with self.assertRaisesRegex(ValueError,'upload'):c.validate_valsea(*data)
        data=evidence();data[1][0]['source_duration_seconds']=2.
        with self.assertRaisesRegex(ValueError,'source duration'):c.validate_valsea(*data)

    def test_smoke_full_config_allows_only_legitimate_differences(self):
        root=c.ROOT/'artifacts/valsea_vnslu'
        full=c.score.read_json(root/c.VALSEA/'configuration.json');smoke=c.score.read_json(root/c.SMOKE/'configuration.json')
        c.validate_config_pair(full,smoke,full['dataset_provenance'])
        for key,value in [('fields',dict(full['fields'],enable_correction='true')),('runner_source','changed'),
                          ('preprocessing_source','changed'),('packages',{'fixture':'different'})]:
            changed=copy.deepcopy(full);changed[key]=value
            with self.assertRaises(ValueError):c.validate_config_pair(changed,smoke,full['dataset_provenance'])


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.rows=[row('one','xin'),row('two','a b c d e f g h i','other')]
        self.a=[prediction('one','sai'),prediction('two','a b c d e f g h i')]
        self.b=[prediction('one','xin'),prediction('two','z z c d e f g h i')]

    def pairs(self,a=None,b=None):
        return c.paired_join(c.score.score_rows(self.rows,self.a if a is None else a),
                             c.score.score_rows(self.rows,self.b if b is None else b))

    def test_reordered_exact_joins_null_metadata_and_label_preservation(self):
        expected=self.pairs()
        self.assertEqual(expected,self.pairs(list(reversed(self.a)),list(reversed(self.b))))
        for x,y in expected:
            original=next(r for r in self.rows if r['sample_id']==x['sample_id'])
            for r in [x,y]:
                self.assertIsNone(r['speaker_id']);self.assertIsNone(r['region'])
                self.assertEqual(r['raw_reference'],original['reference'])
                self.assertEqual(r['entities'],original['entities']);self.assertEqual(r['issues'],original['issues'])

    def test_missing_duplicate_unknown_predictions_and_paired_ids_rejected(self):
        for bad in [self.b[:1],self.b+[self.b[0]],[self.b[0],prediction('unknown','x')]]:
            with self.assertRaises(ValueError):self.pairs(b=bad)
        scores=c.score.score_rows(self.rows,self.a)
        with self.assertRaises(ValueError):c.paired_join(scores,scores[:1])
        with self.assertRaises(ValueError):c.paired_join(scores,scores+[scores[0]])

    def test_empty_success_retains_full_denominators(self):
        b=[prediction('one',''),self.b[1]];m=c.metrics_for_pairs(self.pairs(b=b))
        self.assertEqual(m['overall']['valsea']['words'],10)
        self.assertEqual(m['overall']['valsea']['chars'],12)
        self.assertEqual(m['overall']['valsea']['empty_successful'],1)
        bad=copy.deepcopy(self.rows);bad[0]['reference']='!'
        with self.assertRaisesRegex(ValueError,'Empty normalized'):c.score.score_rows(bad,self.a)

    def test_corpus_weighting_delta_direction_and_edit_count_comparisons(self):
        m=c.metrics_for_pairs(self.pairs())['overall']
        self.assertAlmostEqual(m['gipformer']['wer_whitespace'],.1)
        self.assertAlmostEqual(m['valsea']['wer_whitespace'],.2)
        self.assertAlmostEqual(m['delta_wer_percentage_points'],10.)
        self.assertEqual(m['valsea_edit_counts_relative_to_gipformer']['word'],dict(lower=1,equal=0,higher=1))
        self.assertAlmostEqual(c.metrics_for_pairs(self.pairs(a=self.b,b=self.a))['overall']['delta_wer_percentage_points'],-10.)

    def test_identical_predictions_zero_deltas(self):
        m=c.metrics_for_pairs(self.pairs(b=self.a))['overall']
        self.assertEqual(m['delta_wer_percentage_points'],0.)
        self.assertEqual(m['delta_cer_percentage_points'],0.)
        self.assertEqual(m['valsea_edit_counts_relative_to_gipformer']['word'],dict(lower=0,equal=2,higher=0))

    def test_intent_additive_reconciliation(self):
        m=c.metrics_for_pairs(self.pairs())
        self.assertEqual(len(m['by_intent']),2)
        for model in ['gipformer','valsea']:
            for field in ['n',*c.score.TOTALS,'duration_seconds']:
                self.assertEqual(sum(g[model][field] for g in m['by_intent'].values()),m['overall'][model][field])


if __name__=='__main__':unittest.main()
