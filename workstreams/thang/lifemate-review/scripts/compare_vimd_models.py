"""Read-only input audit and CPU paired scoring of the completed ViMD runs."""
import argparse
from collections import Counter
from datetime import datetime
import json
import math
from pathlib import Path
import random
import sys
import unicodedata

sys.path.insert(0,str(Path(__file__).resolve().parent))
import score_vimd_test as score
import run_valsea_vimd as api  # Pure state/summary checks only; no account/transport calls.

ROOT=Path(__file__).resolve().parents[1]
VALSEA_RUN='valsea_vimd_full_20261101_01'
SMOKE_RUN='valsea_vimd_smoke_pacing_20261101_01'


def unique(rows,label):
    result={}
    for row in rows:
        key=row.get('sample_id') if isinstance(row,dict) else None
        if not isinstance(key,str) or not key or key in result:
            raise ValueError('Duplicate/malformed '+label+' ID.')
        result[key]=row
    return result


def jsonl(data):
    if data and not data.endswith(b'\n'):
        raise ValueError('Interrupted final JSONL record; inputs preserved, no repair.')
    result=[]
    for line in data.splitlines():
        if not line.strip():raise ValueError('Blank JSONL record.')
        row=json.loads(line.decode('utf-8'))
        if not isinstance(row,dict):raise ValueError('Malformed JSONL object.')
        result.append(row)
    return result


def stamp(value):
    if not isinstance(value,str):raise ValueError('Missing execution timestamp.')
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None:raise ValueError('Execution timestamp has no timezone.')
    return result


def validate_valsea(manifest,predictions,attempts,config,metadata,saved,mode):
    if config.get('mode')!=mode or config.get('endpoint')!=api.ENDPOINT or config.get('fields')!=api.FIELDS:
        raise ValueError('VALSEA submitted endpoint/model/flags conflict with reviewed contract.')
    if config.get('automatic_retries') is not False or config.get('upload')!='FLOAT32 WAV mono 16000 Hz':
        raise ValueError('VALSEA retry/upload configuration conflicts.')
    ids=unique(manifest['records'],'manifest')
    pred=unique(predictions,'prediction')
    if ids.keys()!=pred.keys():raise ValueError(f'Incomplete/unknown prediction IDs: expected {len(ids)}, found {len(pred)}.')
    sessions=metadata.get('sessions',[])
    if not sessions or sessions[-1].get('status')!='completed':raise ValueError('VALSEA final session is not completed; no scoring of a running run.')
    for session in sessions:
        if session.get('status') not in {'completed','stopped'} or 'ended_utc' not in session:
            raise ValueError('Unfinished/unknown VALSEA session; no scoring.')
        if (session.get('mode')!=mode or session.get('account_endpoint_confirmed')!=config['endpoint']
                or session.get('account_model_confirmed')!=config['fields']['model']
                or session.get('packages')!=config.get('packages')):
            raise ValueError('Session configuration differs from frozen account/model/packages.')
        if stamp(session['ended_utc'])<stamp(session['started_utc']):raise ValueError('Session timestamps are inconsistent.')
    if metadata.get('model_alias')!=config['fields']['model']:raise ValueError('Recorded alias mismatch.')
    # Replay chronological attempts independently of the operator's summary.
    starts,ends,authorized,last,success={},{},set(),{},{}
    for event in attempts:
        sample_id=event.get('sample_id')
        if sample_id not in ids:raise ValueError('Unknown attempt sample ID.')
        event_time=stamp(event.get('timestamp'))
        if not any(stamp(s['started_utc'])<=event_time<=stamp(s['ended_utc']) for s in sessions):
            raise ValueError('Attempt timestamp lies outside recorded execution sessions.')
        kind=event.get('event')
        if kind=='source_error':continue
        number=event.get('attempt')
        if type(number) is not int or number<=0:raise ValueError('Malformed attempt number.')
        if kind=='started':
            if number!=len(starts)+1:raise ValueError('Duplicate/missing/out-of-order request intent.')
            if sample_id in success:raise ValueError('An already successful sample was submitted again.')
            if sample_id in last and last[sample_id] not in authorized:
                raise ValueError('Failed/uncertain remote attempt retried without explicit prior authorization.')
            starts[number]=event
            last[sample_id]=number
            if event.get('source_duration_seconds')!=(ids[sample_id].get('audio') or {}).get('duration_seconds',ids[sample_id].get('source_duration')):
                raise ValueError('Attempt source duration differs from manifest.')
        elif kind=='retry_authorized':
            if number not in starts or starts[number]['sample_id']!=sample_id or number in authorized or sample_id in success:
                raise ValueError('Invalid retry reconciliation.')
            if not isinstance(event.get('note'),str) or not event['note'].strip():raise ValueError('Retry lacks an operator reconciliation note.')
            authorized.add(number)
        elif kind in {'ok','error','unresolved'}:
            if number not in starts or number in ends or starts[number]['sample_id']!=sample_id:
                raise ValueError('Duplicate/unknown/mismatched attempt outcome.')
            ends[number]=event
            if kind=='ok':
                response=event.get('response')
                record=event.get('prediction')
                if (not isinstance(event.get('http_status'),int) or not 200<=event['http_status']<300
                        or not isinstance(response,dict) or not isinstance(response.get('text'),str)
                        or not isinstance(record,dict) or pred.get(sample_id)!=record
                        or record.get('sample_id')!=sample_id or record.get('status')!='ok'
                        or record.get('text')!=response['text'] or record.get('error') is not None):
                    raise ValueError('Prediction does not match valid successful HTTP text evidence.')
                headers=event.get('response_headers',{})
                if record.get('request_id')!=(headers.get('x-request-id') or headers.get('request-id') or response.get('request_id')):
                    raise ValueError('Returned request-ID evidence differs.')
                if record.get('provider_version')!=(headers.get('x-model-version') or response.get('model_version')):
                    raise ValueError('Returned provider-version evidence differs.')
                if record.get('returned_model')!=response.get('model'):raise ValueError('Returned model evidence differs.')
                expected_duration=(ids[sample_id].get('audio') or {}).get('duration_seconds',ids[sample_id].get('source_duration'))
                if record.get('duration_seconds')!=expected_duration:
                    raise ValueError('Successful prediction duration differs from the manifest.')
                stamp(record.get('timestamp'))
                success[sample_id]=event
        else:raise ValueError('Unknown attempt event.')
    # Existing pure runner logic also detects outstanding failed/unresolved work.
    done,_,blocked,_,_=api.state(manifest,predictions,attempts)
    if blocked or success.keys()!=ids.keys() or done.keys()!=ids.keys():
        raise ValueError('Outstanding unsuccessful/unresolved samples or missing successful evidence.')
    recomputed=api.completion(manifest,predictions,attempts)
    if saved!=recomputed or not recomputed['coverage_complete'] or recomputed['remaining']:
        raise ValueError('Completion summary does not reconcile with actual attempts/predictions.')
    return recomputed,success


def version_evidence(success,sessions):
    def values(field):
        groups={}
        for event in success.values():
            value=(event['response'].get(field) if field not in {'provider_version','returned_model'}
                   else event['prediction'].get(field))
            key=json.dumps(value,sort_keys=True,ensure_ascii=False)
            time=event['timestamp']
            if key not in groups:groups[key]=dict(value=value,count=0,first_observed_utc=time,last_observed_utc=time)
            item=groups[key]
            item['count']+=1
            item['first_observed_utc']=min(item['first_observed_utc'],time)
            item['last_observed_utc']=max(item['last_observed_utc'],time)
        return list(groups.values())
    by_session=[]
    for session in sessions:
        events=[e for e in success.values() if stamp(session['started_utc'])<=stamp(e['timestamp'])<=stamp(session['ended_utc'])]
        by_session.append(dict(started_utc=session['started_utc'],ended_utc=session['ended_utc'],
            status=session['status'],successful_outcomes=len(events),
            engine_counts=dict(Counter(str(e['response'].get('engine')) for e in events)),
            provider_version_counts=dict(Counter(str(e['prediction'].get('provider_version')) for e in events))))
    request_ids=[e['prediction'].get('request_id') for e in success.values()]
    return dict(engine=values('engine'),model_version=values('model_version'),
                exposed_provider_version=values('provider_version'),returned_model=values('returned_model'),
                request_ids_present=sum(bool(x) for x in request_ids),distinct_request_ids=len({x for x in request_ids if x}),
                sessions=by_session,immutable_provider_revision='not exposed; no revision invented')


def paired_join(a,b):
    left,right=unique(a,'GIPFormer scored'),unique(b,'VALSEA scored')
    if left.keys()!=right.keys():raise ValueError('Paired IDs are incomplete or unknown.')
    aligned=[]
    for key in sorted(left):
        x,y=left[key],right[key]
        for field in ['source','split','speaker_id','region','province_code','province_name','issues','duration_seconds',
                      'raw_reference','normalized_reference','words','chars']:
            if x[field]!=y[field]:raise ValueError('Paired reference/metadata/denominator mismatch: '+field)
        aligned.append((x,y))
    return aligned


def paired_draw(strata,rng):
    totals=[0]*8
    for stratum in sorted(strata):
        speakers=strata[stratum]
        for key in rng.choices(sorted(speakers),k=len(speakers)):
            for i,value in enumerate(speakers[key]):totals[i]+=value
    return (score.ratio(totals[4],totals[5])-score.ratio(totals[0],totals[1]),
            score.ratio(totals[6],totals[7])-score.ratio(totals[2],totals[3]))


def paired_metrics(a,b,replicates=2000,seed=42):
    aligned=paired_join(a,b)
    strata={}
    for x,y in aligned:
        if not x.get('speaker_id') or not x.get('region'):
            return dict(available=False,reason='Missing speaker/region metadata.')
        speakers=strata.setdefault((x['source'],x['region']),{})
        values=speakers.setdefault(x['speaker_id'],[0]*8)
        for i,value in enumerate([x[k] for k in score.TOTALS]+[y[k] for k in score.TOTALS]):values[i]+=value
    if not strata or any(len(group)<2 for group in strata.values()):
        return dict(available=False,reason='Fewer than two speakers in a source/region stratum.')
    rng=random.Random(seed)
    draws=[paired_draw(strata,rng) for _ in range(replicates)]
    first,second=score.aggregate(a),score.aggregate(b)
    result=dict(available=True,replicates=replicates,seed=seed,unit='absolute percentage points',
                direction='VALSEA minus GIPFormer; negative favors VALSEA')
    for index,metric in enumerate(['wer_whitespace','cer']):
        values=sorted(100*draw[index] for draw in draws)
        low,high=values[int(.025*(replicates-1))],values[int(.975*(replicates-1))]
        result[metric]=dict(delta_pp=100*(second[metric]-first[metric]),ci95_pp=[low,high],
                           interpretation=('inconclusive under this analysis; not equivalence' if low<=0<=high
                                           else 'lower VALSEA reference error' if high<0 else 'lower GIPFormer reference error'))
    return result


def capture(paths):
    before={p:(p.stat().st_size,p.stat().st_mtime_ns) for p in paths}
    data={p:p.read_bytes() for p in paths}
    if before!={p:(p.stat().st_size,p.stat().st_mtime_ns) for p in paths}:
        raise ValueError('Inputs changed during snapshot; no completed comparison.')
    return data


def verify_unchanged(snapshot):
    if any(p.read_bytes()!=data for p,data in snapshot.items()):
        raise ValueError('Input files changed while validating/scoring; no comparison outputs written.')


def validate_baseline(scored,saved_rows,saved_metrics,recomputed):
    first,second=unique(scored,'recomputed baseline'),unique(saved_rows,'saved baseline')
    if first!=second:raise ValueError('GIPFormer saved per-sample scores do not match rescoring.')
    for key in ['overall','by_region','by_province','region_macro','reconciliation']:
        if saved_metrics[key]!=recomputed[key]:raise ValueError('Saved baseline metrics do not reconcile: '+key)
    if saved_metrics.get('normalizer')!=score.NORMALIZER or saved_metrics['scoring']['bootstrap']!=score.BOOTSTRAP:
        raise ValueError('Saved GIPFormer scoring protocol differs.')


def validate_config_pair(full,smoke):
    if {k:v for k,v in full.items() if k!='mode'}!={k:v for k,v in smoke.items() if k!='mode'}:
        raise ValueError('Full-test configuration/code differs from verified smoke beyond mode.')


def load_ready(args):
    names=['manifest.json','configuration.json','run_metadata.json','completion_summary.json','predictions.jsonl']
    paths=[args.manifest,*[args.gip_run/n for n in names],*[args.valsea_run/n for n in names],
           args.valsea_run/'attempts.jsonl',*[args.smoke_run/n for n in names],args.smoke_run/'attempts.jsonl',
           args.gip_scores/'per_sample.jsonl',args.gip_scores/'metrics.json',api.SMOKE_MANIFEST]
    snapshot=capture(paths)
    def doc(path):return json.loads(snapshot[path].decode('utf-8'))
    canonical=doc(args.manifest)
    if len(canonical['records'])!=2026 or canonical['provenance']['revision']!=api.shared.PINS['dataset']:
        raise ValueError('Canonical manifest is not the full pinned 2026-sample test split.')
    if doc(args.valsea_run/'manifest.json')!=canonical:raise ValueError('VALSEA/canonical manifest mismatch.')
    smoke=doc(args.smoke_run/'manifest.json')
    if smoke['records']!=doc(api.SMOKE_MANIFEST):raise ValueError('Reviewed smoke does not match the six frozen validation samples.')
    configs={}
    audits={}
    provenance={}
    for label,directory,manifest,mode in [('smoke',args.smoke_run,smoke,'smoke'),('full',args.valsea_run,canonical,'full')]:
        config,metadata,saved=(doc(directory/name) for name in ['configuration.json','run_metadata.json','completion_summary.json'])
        predictions,attempts=(jsonl(snapshot[directory/name]) for name in ['predictions.jsonl','attempts.jsonl'])
        counts,success=validate_valsea(manifest,predictions,attempts,config,metadata,saved,mode)
        if metadata['run_id']!=directory.name:raise ValueError('VALSEA RUN_ID/directory conflict.')
        configs[label]=config
        audits[label]=dict(run_id=metadata['run_id'],coverage=counts,events=dict(Counter(e['event'] for e in attempts)),
                          authorized_retry_events=[{k:e[k] for k in ['sample_id','attempt','timestamp','note']} for e in attempts if e['event']=='retry_authorized'])
        provenance[label]=version_evidence(success,metadata['sessions'])
        if label=='full':
            full_predictions=predictions
            full_success=success
    validate_config_pair(configs['full'],configs['smoke'])
    # Existing GIPFormer loader is read-only and strictly checks coverage/manifest.
    rows,gip_predictions,_,gip_config,gip_metadata=score.load_inputs(args.gip_run,args.manifest)
    baseline=doc(args.gip_scores/'metrics.json')
    if baseline['provenance']['run_id']!=gip_metadata['run_id'] or baseline['provenance']['revisions']!=gip_config['revisions']:
        raise ValueError('Saved baseline run/model revision provenance conflicts.')
    if gip_metadata['sessions'][-1]['launcher'].get('child_exit_code')!=0:
        raise ValueError('GIPFormer child did not complete successfully.')
    score.validate_join(rows,full_predictions)
    verify_unchanged(snapshot)
    return dict(snapshot=snapshot,rows=rows,gip_predictions=gip_predictions,valsea_predictions=full_predictions,
                baseline_rows=jsonl(snapshot[args.gip_scores/'per_sample.jsonl']),
                baseline_metrics=doc(args.gip_scores/'metrics.json'),gip_config=gip_config,
                audits=audits,api_provenance=provenance,valsea_config=configs['full'],successful_attempts=full_success)


def paired_rows(a,b,api_evidence=None):
    for first,second in paired_join(a,b):
        common={k:first[k] for k in ['sample_id','source','split','filename','speaker_id','region','province_code',
                                    'province_name','issues','issue_status','duration_seconds','raw_reference',
                                    'normalized_reference','words','chars']}
        for name,row in [('gipformer',first),('valsea',second)]:
            common[name]={k:row[k] for k in ['status','error','raw_hypothesis','normalized_hypothesis',
                                            'word_errors','char_errors','wer_whitespace','cer']}
        if api_evidence is not None:
            event=api_evidence[first['sample_id']]
            common['valsea'].update(attempt=event['attempt'],request_id=event['prediction'].get('request_id'),
                                    engine=event['response'].get('engine'),
                                    provider_version=event['prediction'].get('provider_version'))
        yield common


def report(metrics):
    def pct(x):return f'{x*100:.3f}%'
    def ci(g,k):return '–'.join(pct(x) for x in g['ci95'][k])
    lines=['# VALSEA/Glot versus GIPFormer 1.5 — full ViMD test','',
           'GIPFormer 1.5: FP16 weights with mixed computation, greedy decoding.',
           'VALSEA/Glot: glot-transcribe alias; submitted correction/tags/diarization disabled; scored response text only.', '',
           '## Model reference agreement','',
           '| Group | Model | Clips | Speakers | Audio hours | WER | 95% CI | CER | 95% CI |',
           '| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | --- |']
    for region in ['overall',*score.REGIONS]:
        for name in ['gipformer','valsea']:
            model=metrics['models'][name]
            g=model['overall'] if region=='overall' else model['by_region'][region]
            lines.append(f"| {region} | {name} | {g['n']} | {g['unique_speakers']} | {g['duration_seconds']/3600:.6f} | {pct(g['wer_whitespace'])} | {ci(g,'wer_whitespace')} | {pct(g['cer'])} | {ci(g,'cer')} |")
    lines+=['','Unweighted regional macro (mean of three corpus rates, not full-corpus micro):']
    for name,m in metrics['models'].items():lines.append(f"- {name}: WER {pct(m['region_macro']['wer_whitespace'])}, CER {pct(m['region_macro']['cer'])}.")
    lines+=['','## Paired differences','',
            'Absolute percentage-point differences: VALSEA minus GIPFormer; negative favors VALSEA. Intervals use the same speaker draws for both models, not overlap of separate CIs. Regional comparisons are exploratory.', '',
            '| Group | Delta WER pp | Paired 95% CI pp | Interpretation | Delta CER pp | Paired 95% CI pp | Interpretation |',
            '| --- | ---: | --- | --- | ---: | --- | --- |']
    for region,pair in metrics['paired'].items():
        w,c=pair['wer_whitespace'],pair['cer']
        interval=lambda r:'–'.join(f'{x:+.3f}' for x in r['ci95_pp'])
        lines.append(f"| {region} | {w['delta_pp']:+.3f} | {interval(w)} | {w['interpretation']} | {c['delta_pp']:+.3f} | {interval(c)} | {c['interpretation']} |")
    lines+=['','## Descriptive provinces','',
            'Source-code order, not a ranking. No province CIs or statistically established province differences are claimed.', '',
            '| Province | Region | Clips | Speakers | Hours | GIP WER | VALSEA WER | GIP CER | VALSEA CER |',
            '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for code,g in metrics['models']['gipformer']['by_province'].items():
        v=metrics['models']['valsea']['by_province'][code]
        lines.append(f"| {code} {g['province_name']} | {g['region']} | {g['n']} | {g['unique_speakers']} | {g['duration_seconds']/3600:.6f} | {pct(g['wer_whitespace'])} | {pct(v['wer_whitespace'])} | {pct(g['cer'])} | {pct(v['cer'])} |")
    lines+=['','Smallest province speaker support: 10 supplied IDs in TienGiang and BacLieu. Counts alone do not establish adequacy.', '',
            '## Validation, provider provenance and limits','',
            '- All 2,026 IDs are unique, complete and successfully reconciled with successful attempt evidence. Empty text is valid and retains full reference denominators. All three speaker-overlap-flagged records remain included. No files were repaired or excluded.',
            '- Canonical test manifest matches both archived full-test manifests; smoke matches the six frozen validation records. Full VALSEA configuration equals the verified smoke configuration except mode. Final sessions are completed; summaries were recomputed, not trusted. Historical failed/uncertain attempts and explicit retry authorizations are retained in metrics.json, not used to exclude samples.',
            '- Baseline saved per-sample scores and aggregates reconcile with independent CPU rescoring; neither baseline nor inputs were overwritten. Counts/durations/edit totals/reference denominators reconcile across regions/provinces. Both models have identical reference denominators.',
            '- Frozen normalizer: NFC, lowercase, Unicode punctuation to spaces, collapse whitespace. WER uses whitespace units, not linguistic Vietnamese word segmentation. CER removes normalized spaces and compares Unicode code points. Diacritics, number forms, fillers and repetitions are not rewritten. Raw texts remain in paired per_sample.jsonl; raw_transcript remains evidence in the original attempt log and was never selected for scoring.',
            '- Single-model and paired intervals: 2,000 replicates, seed 42, sorted source/region strata and speaker IDs, speakers sampled with replacement with all their utterances and repeated-draw multiplicity. Sorted empirical endpoints int(q*(B−1)), q=0.025/0.975; each overall/regional call resets the seed. No significance tests or equivalence thresholds. A paired interval containing zero is inconclusive, not proof of equivalence.',
            '- Actual API alias/configuration, execution dates, exposed versions/engine variation and request-ID counts follow. Submitted false flags and HTTP success do not independently prove all backend processing details. No immutable API revision is invented.']
    provenance=metrics['provenance']['api']['full']
    for field in ['engine','model_version','exposed_provider_version','returned_model']:
        lines.append('- '+field+': '+json.dumps(provenance[field],ensure_ascii=False)+'.')
    for session in provenance['sessions']:
        lines.append('- API session: '+json.dumps(session,ensure_ascii=False)+'.')
    lines.append(f"- Request IDs: {provenance['request_ids_present']} present, {provenance['distinct_request_ids']} distinct.")
    for label,audit in metrics['validation'].items():
        lines.append('- '+label+' attempt accounting: '+json.dumps(audit['coverage'],ensure_ascii=False)+'.')
    lines+=['- Metrics measure agreement with official ViMD references. Reference correctness, training overlap and LifeMate generalization remain unresolved. Speaker-ID overlap alone does not establish leakage. Mixed backend engine labels are observed routing/provenance, not evidence of immutable model versions or a causal subgroup effect.',
            '- Client API elapsed times include upload/service/transfer; the 24m43s GIPFormer session includes setup/downloads. Neither is local-model compute latency or comparable performance/cost benchmarking. Those analyses are outside scope.',
            '- No inference, GPU/Kaggle use, gold changes or tuning was performed. Formal recognition-quality acceptance remains pending human review.', '',
            'Reproduce from project root: `python scripts/compare_vimd_models.py`. See metrics.json for exact ratios, additive totals, source run IDs, revisions and bootstrap settings.']
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,default=ROOT/'manifests/vimd_test.json')
    parser.add_argument('--gip-run',type=Path,default=ROOT/'artifacts/kaggle_vimd_test'/score.RUN_ID)
    parser.add_argument('--gip-scores',type=Path,default=ROOT/'artifacts/scoring'/score.RUN_ID)
    parser.add_argument('--valsea-run',type=Path,default=ROOT/'artifacts/valsea'/VALSEA_RUN)
    parser.add_argument('--smoke-run',type=Path,default=ROOT/'artifacts/valsea'/SMOKE_RUN)
    parser.add_argument('--out',type=Path,default=ROOT/'artifacts/scoring/valsea_vs_gipformer_vimd_20261101')
    args=parser.parse_args()
    for source in [args.gip_run,args.gip_scores,args.valsea_run,args.smoke_run,args.manifest.parent]:
        if args.out.resolve().is_relative_to(source.resolve()):raise ValueError('Outputs must be separate from all inputs.')
    ready=load_ready(args)
    gip=score.score_rows(ready['rows'],ready['gip_predictions'])
    valsea=score.score_rows(ready['rows'],ready['valsea_predictions'])
    models=dict(gipformer=score.make_metrics(gip),valsea=score.make_metrics(valsea))
    validate_baseline(gip,ready['baseline_rows'],ready['baseline_metrics'],models['gipformer'])
    paired=dict(overall=paired_metrics(gip,valsea))
    for region in score.REGIONS:
        paired[region]=paired_metrics([r for r in gip if r['region']==region],[r for r in valsea if r['region']==region])
    rows=list(paired_rows(gip,valsea,ready['successful_attempts']))
    metrics=dict(models=models,paired=paired,validation=ready['audits'],normalizer=score.NORMALIZER,
        scoring=ready['baseline_metrics']['scoring'],
        labels=dict(gipformer=score.LABEL,valsea='VALSEA/Glot glot-transcribe; submitted correction/tags/diarization false; scored text'),
        provenance=dict(gipformer_run_id=score.RUN_ID,valsea_run_id=args.valsea_run.name,
                        dataset_revision=ready['gip_config']['revisions']['dataset'],gipformer_revisions=ready['gip_config']['revisions'],
                        api=ready['api_provenance'],endpoint=ready['valsea_config']['endpoint'],submitted_fields=ready['valsea_config']['fields'],
                        python=sys.version.split()[0],unicode_version=unicodedata.unidata_version),
        review_status='pending_human_review')
    verify_unchanged(ready['snapshot'])
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/'per_sample.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
    (args.out/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (args.out/'report.md').write_text(report(metrics),encoding='utf-8')
    print(json.dumps(dict(overall={k:v['overall'] for k,v in models.items()},paired=paired),indent=2))


if __name__=='__main__':
    try:main()
    except (ValueError,KeyError,FileNotFoundError) as error:
        print('Comparison blocked:',str(error),file=sys.stderr)
        raise SystemExit(1) from None
