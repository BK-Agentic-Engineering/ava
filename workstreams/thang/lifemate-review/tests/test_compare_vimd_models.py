"""Synthetic paired-scoring/readiness tests; no HTTP, models or GPU execution."""
import argparse
import copy
from datetime import datetime,timezone
import importlib.util
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import compare_vimd_models as comparison


def rows():
    result=[]
    for region,code in [('North',11),('Central',37),('South',84)]:
        for speaker in range(2):
            result.append(dict(sample_id=f'{region}_{speaker}',source='ViMD',split='test',
                filename=f'{region}_{speaker}.wav',speaker_id=f'{region}_speaker{speaker}',region=region,
                province_code=code,province_name=region,reference='xin chào bạn',issues=[],issue_status='clear',
                audio={'duration_seconds':1.}))
    return result


def predictions(source,text='xin chào bạn'):
    return [dict(sample_id=r['sample_id'],status='ok',text=text,error=None,duration_seconds=1.) for r in source]


def readiness_fixture():
    manifest=dict(records=rows())
    pred=predictions(rows())
    config=dict(mode='full',endpoint=comparison.api.ENDPOINT,fields=copy.deepcopy(comparison.api.FIELDS),
                upload='FLOAT32 WAV mono 16000 Hz',automatic_retries=False,packages={})
    session=dict(status='completed',mode='full',account_endpoint_confirmed=config['endpoint'],
                 account_model_confirmed=config['fields']['model'],packages={},
                 started_utc='2026-11-01T10:00:00+00:00',ended_utc='2026-11-01T11:00:00+00:00')
    metadata=dict(sessions=[session],model_alias='glot-transcribe')
    events=[]
    for number,p in enumerate(pred,1):
        p.update(request_id=f'req{number}',provider_version=None,returned_model=None,
                 timestamp='2026-11-01T10:01:00+00:00')
        events.append(dict(event='started',sample_id=p['sample_id'],attempt=number,
                           source_duration_seconds=1.,timestamp='2026-11-01T10:00:30+00:00'))
        events.append(dict(event='ok',sample_id=p['sample_id'],attempt=number,
                           timestamp=p['timestamp'],http_status=200,prediction=copy.deepcopy(p),
                           response={'text':p['text'],'raw_transcript':'not the scored field','engine':'valsea-4','model_version':None},
                           response_headers={'x-request-id':p['request_id']}))
    saved=comparison.api.completion(manifest,pred,events)
    return manifest,pred,events,config,metadata,saved


class ReadinessTests(unittest.TestCase):
    def check(self,fixture):return comparison.validate_valsea(*fixture,'full')

    def test_exact_success_reconciliation_and_empty_text_allowed(self):
        fixture=list(readiness_fixture())
        fixture[1][0]['text']=''
        fixture[2][1]['prediction']['text']=''
        fixture[2][1]['response']['text']=''
        fixture[5]=comparison.api.completion(*fixture[:3])
        summary,success=self.check(fixture)
        self.assertEqual(summary['successful'],6)
        self.assertEqual(summary['empty_successful_transcripts'],['North_0'])
        self.assertEqual(len(success),6)
        scored=comparison.score.score_rows(fixture[0]['records'],fixture[1])
        self.assertEqual(scored[0]['words'],3)
        self.assertEqual(scored[0]['word_errors'],3)
        self.assertEqual(scored[0]['cer'],1.)

    def test_incomplete_duplicate_missing_attempt_or_running_run_rejected(self):
        for mutation in ['missing','duplicate','attempt','summary','running','evidence']:
            with self.subTest(mutation=mutation):
                f=list(copy.deepcopy(readiness_fixture()))
                if mutation=='missing':f[1].pop()
                if mutation=='duplicate':f[1].append(copy.deepcopy(f[1][0]))
                if mutation=='attempt':f[2].pop()
                if mutation=='summary':f[5]['remaining']=1
                if mutation=='running':f[4]['sessions'][0]['status']='running'
                if mutation=='evidence':f[2][1]['response']['text']='does not match'
                with self.assertRaises(ValueError):self.check(f)

    def test_conflicting_submission_flags_or_version_evidence_rejected(self):
        for mutation in ['correction','endpoint','session','version']:
            with self.subTest(mutation=mutation):
                f=list(copy.deepcopy(readiness_fixture()))
                if mutation=='correction':f[3]['fields']['enable_correction']='true'
                if mutation=='endpoint':f[3]['endpoint']='https://example.invalid'
                if mutation=='session':f[4]['sessions'][0]['account_model_confirmed']='other'
                if mutation=='version':f[2][1]['prediction']['provider_version']='invented'
                with self.assertRaises(ValueError):self.check(f)

    def test_authorized_historical_retry_retained_and_unauthorized_retry_rejected(self):
        f=list(copy.deepcopy(readiness_fixture()))
        old_start=copy.deepcopy(f[2][0])
        failed=dict(event='unresolved',sample_id=old_start['sample_id'],attempt=1,
                    timestamp=old_start['timestamp'])
        auth=dict(event='retry_authorized',sample_id=old_start['sample_id'],attempt=1,
                  timestamp=old_start['timestamp'],note='Operator reconciled usage and authorized another attempt.')
        shifted=copy.deepcopy(f[2])
        for event in shifted:event['attempt']+=1
        f[2]=[old_start,failed,auth]+shifted
        f[5]=comparison.api.completion(*f[:3])
        summary,_=self.check(f)
        self.assertEqual(summary['successful'],6)
        self.assertEqual(summary['request_attempts'],7)
        self.assertEqual(summary['historical_unknown_remote_outcomes'],1)
        self.assertEqual(summary['unresolved_attempts'],0)
        f[2].remove(auth)
        with self.assertRaises(ValueError):self.check(f)

    def test_smoke_full_only_mode_may_differ_and_baseline_must_reconcile(self):
        full=readiness_fixture()[3]
        smoke={**full,'mode':'smoke'}
        comparison.validate_config_pair(full,smoke)
        for key,value in [('requests_per_minute',30),('runner_source','changed code'),('packages',{'different':'version'})]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                comparison.validate_config_pair({**full,key:value},smoke)
        source=rows()
        scored=comparison.score.score_rows(source,predictions(source))
        metrics=comparison.score.make_metrics(scored)
        saved={**metrics,'normalizer':comparison.score.NORMALIZER,'scoring':{'bootstrap':comparison.score.BOOTSTRAP}}
        comparison.validate_baseline(scored,list(reversed(scored)),saved,metrics)
        changed=copy.deepcopy(scored);changed[0]['word_errors']+=1
        with self.assertRaises(ValueError):comparison.validate_baseline(changed,scored,saved,metrics)
        changed_metrics=copy.deepcopy(saved);changed_metrics['overall']['words']+=1
        with self.assertRaises(ValueError):comparison.validate_baseline(scored,scored,changed_metrics,metrics)

    def test_version_variation_is_reported_not_replaced_with_alias_revision(self):
        f=readiness_fixture()
        f[2][3]['response']['engine']='valsea-6'
        _,success=self.check(f)
        evidence=comparison.version_evidence(success,f[4]['sessions'])
        self.assertEqual({x['value']:x['count'] for x in evidence['engine']},{'valsea-4':5,'valsea-6':1})
        self.assertEqual(evidence['model_version'][0]['value'],None)
        self.assertEqual(evidence['request_ids_present'],6)

    def test_input_changes_and_truncated_jsonl_are_not_repaired(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'evidence.jsonl'
            p.write_bytes(b'{"sample_id":')
            with self.assertRaises(ValueError):comparison.jsonl(p.read_bytes())
            self.assertEqual(p.read_bytes(),b'{"sample_id":')
            p.write_bytes(b'{}\n')
            snapshot=comparison.capture([p])
            p.write_bytes(b'{}\n{}\n')
            with self.assertRaises(ValueError):comparison.verify_unchanged(snapshot)


class PairedScoreTests(unittest.TestCase):
    def models(self):
        source=rows()
        first=predictions(source,'xin bạn')
        first[0]['text']='xin chào bạn'
        second=predictions(source,'xin chào bạn')
        second[3]['text']='xin'
        a=comparison.score.score_rows(source,first)
        b=comparison.score.score_rows(source,second)
        return a,b

    def test_id_pairing_handles_arbitrary_order_and_rejects_missing_duplicate(self):
        a,b=self.models()
        pairs=comparison.paired_join(a,list(reversed(b)))
        self.assertTrue(all(x['sample_id']==y['sample_id'] for x,y in pairs))
        self.assertEqual(len(pairs),6)
        for bad in [b[:-1],b+[b[0]]]:
            with self.assertRaises(ValueError):comparison.paired_join(a,bad)
        changed=copy.deepcopy(b);changed[0]['words']+=1
        with self.assertRaises(ValueError):comparison.paired_join(a,changed)

    def test_corpus_weighting_and_negative_delta_favors_valsea(self):
        source=rows()
        source[0]['reference']='a'
        source[1]['reference']='b c d e f g h i j'
        bp=predictions(source)
        bp[0]['text']='a';bp[1]['text']='b c d e f g h i j'
        ap=copy.deepcopy(bp)
        ap[0]['text']='wrong'
        a=comparison.score.score_rows(source,ap)
        b=comparison.score.score_rows(source,bp)
        result=comparison.paired_metrics(a,b)
        expected=100*(comparison.score.aggregate(b)['wer_whitespace']-comparison.score.aggregate(a)['wer_whitespace'])
        self.assertEqual(result['wer_whitespace']['delta_pp'],expected)
        self.assertLess(expected,0)
        self.assertEqual(result['direction'],'VALSEA minus GIPFormer; negative favors VALSEA')
        mean_delta=sum(y['wer_whitespace']-x['wer_whitespace'] for x,y in zip(a,b))/6*100
        self.assertNotAlmostEqual(mean_delta,expected)

    def test_shared_cluster_multiplicity_and_reference_denominators(self):
        # One paired speaker draw contributes both models' four additive totals.
        strata={('ViMD','North'):{'one':[3,6,3,6,1,6,1,6],
                                 'two':[0,2,0,2,0,2,0,2],
                                 'three':[0,9,0,9,0,9,0,9]}}
        class Draw:
            def choices(self,keys,k):
                self_outer.assertEqual(keys,['one','three','two'])
                self_outer.assertEqual(k,3)
                return ['one','one','two']
        self_outer=self
        wer,cer=comparison.paired_draw(strata,Draw())
        self.assertAlmostEqual(wer,2/14-6/14)
        self.assertAlmostEqual(cer,2/14-6/14)
        self.assertNotAlmostEqual(wer,1/8-3/8)
        # Exercise the real cluster accumulator with multiple utterances for
        # one speaker, rather than only supplying already aggregated totals.
        from unittest.mock import patch
        source=rows()
        extra=copy.deepcopy(source[0])
        extra.update(sample_id='North_extra',filename='extra.wav')
        source.append(extra)
        a=comparison.score.score_rows(source,predictions(source,'xin'))
        b=comparison.score.score_rows(source,predictions(source,'xin chào bạn'))
        original=comparison.paired_draw
        observed=[]
        def traced(group,rng):
            if not observed:observed.append(group[('ViMD','North')]['North_speaker0'][:])
            return original(group,rng)
        with patch.object(comparison,'paired_draw',side_effect=traced):
            comparison.paired_metrics(a,b)
        self.assertEqual(observed[0][0:2],[4,6])
        self.assertEqual(observed[0][4:6],[0,6])

    def test_identical_models_have_zero_deltas_and_zero_intervals(self):
        a,_=self.models()
        result=comparison.paired_metrics(a,list(reversed(a)))
        for metric in ['wer_whitespace','cer']:
            self.assertEqual(result[metric]['delta_pp'],0.)
            self.assertEqual(result[metric]['ci95_pp'],[0.,0.])
            self.assertIn('inconclusive',result[metric]['interpretation'])
            self.assertIn('not equivalence',result[metric]['interpretation'])

    def test_reproducible_paired_percentiles_with_seed_and_sorted_clusters(self):
        a,b=self.models()
        result=comparison.paired_metrics(a,b)
        self.assertEqual(result,comparison.paired_metrics(list(reversed(a)),list(reversed(b))))
        aligned=comparison.paired_join(a,b)
        strata={}
        for x,y in aligned:
            strata.setdefault((x['source'],x['region']),{})[x['speaker_id']]=[x[k] for k in comparison.score.TOTALS]+[y[k] for k in comparison.score.TOTALS]
        rng=random.Random(42)
        draws=[comparison.paired_draw(strata,rng) for _ in range(2000)]
        for index,key in enumerate(['wer_whitespace','cer']):
            values=sorted(100*draw[index] for draw in draws)
            self.assertEqual(result[key]['ci95_pp'],[values[int(.025*1999)],values[int(.975*1999)]])


if __name__=='__main__':unittest.main()
