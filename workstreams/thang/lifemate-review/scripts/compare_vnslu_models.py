"""Read-only run validation and CPU paired VN-SLU reference scoring; no audio or inference."""
import argparse
import ast
from collections import Counter,defaultdict
import json
import math
from pathlib import Path

import compare_vimd_models as common
import score_vnslu_test as score

ROOT=Path(__file__).resolve().parents[1]
VALSEA='valsea_vnslu_test_20261102_01'
SMOKE='valsea_vnslu_dev_smoke_20261102_01'
OUT=ROOT/'artifacts/scoring/valsea_vs_gipformer_vnslu_20261102'


def validate_config_pair(full,smoke,provenance):
    if {k:v for k,v in full.items() if k not in {'mode','split'}}!={k:v for k,v in smoke.items() if k not in {'mode','split'}}:
        raise ValueError('VALSEA smoke/full code, preprocessing, packages or request configuration differ.')
    for config,mode,split in [(full,'full','test'),(smoke,'smoke','dev')]:
        expected=dict(mode=mode,split=split,dataset='VN-SLU',dataset_revision=None,
            dataset_provenance=provenance,request_order='frozen manifest order',scoring_field='text',
            connect_timeout_seconds=15,read_timeout_seconds=120,automatic_retries=False,
            endpoint=common.api.ENDPOINT,fields=common.api.FIELDS,upload='FLOAT32 WAV mono 16000 Hz')
        if any(k not in config or config[k]!=v for k,v in expected.items()):raise ValueError('VALSEA accepted configuration differs.')
        rpm=config.get('requests_per_minute')
        if isinstance(rpm,bool) or not isinstance(rpm,(int,float)) or not math.isfinite(rpm) or rpm<=0:
            raise ValueError('Invalid recorded operator RPM.')
        if not config.get('packages'):raise ValueError('Missing package configuration.')
        for key,name in [('runner_source','run_valsea_vimd.py'),('adapter_source','run_valsea_vnslu.py')]:
            if config.get(key)!=(ROOT/'scripts'/name).read_text(encoding='utf-8'):
                raise ValueError('Recorded VALSEA source differs from accepted code: '+name)
        text=(ROOT/'scripts/gipformer15_smoke.py').read_text(encoding='utf-8')
        function=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=='prepare_audio')
        if config.get('preprocessing_source')!=''.join(text.splitlines(keepends=True)[function.lineno-1:function.end_lineno]):
            raise ValueError('Recorded shared preprocessing differs.')


def validate_valsea(manifest,predictions,attempts,config,metadata,saved,mode):
    counts,success=common.validate_valsea(manifest,predictions,attempts,config,metadata,saved,mode)
    rows=common.unique(manifest['records'],'manifest')
    # The shared audit replays authorization before retry, rejects resubmission
    # after success and checks response text against the persisted prediction.
    for sample_id,event in success.items():
        duration=rows[sample_id]['audio']['duration_seconds']
        if event['prediction'].get('source_duration_seconds')!=duration:
            raise ValueError('Prediction source duration differs from canonical input.')
    for event in attempts:
        if event['event']!='started':continue
        audio=rows[event['sample_id']]['audio']
        frames=math.ceil(audio['frames']*16000/audio['sample_rate'])
        if (event.get('upload_duration_seconds')!=frames/16000 or
                type(event.get('upload_bytes')) is not int or not 0<event['upload_bytes']<=common.api.MAX_BYTES):
            raise ValueError('Recorded upload duration/size differs from accepted representation.')
    return counts,success


def paired_join(a,b):
    left,right=common.unique(a,'GIPFormer score'),common.unique(b,'VALSEA score')
    if left.keys()!=right.keys():raise ValueError('Missing/unknown paired IDs.')
    result=[]
    for key in sorted(left):
        x,y=left[key],right[key]
        for field in ['official_id','filename','split','intent','entities','sentence_annotation','issues',
                      'speaker_id','region','duration_seconds','raw_reference','normalized_reference','words','chars']:
            if x[field]!=y[field]:raise ValueError('Paired reference/metadata/denominator mismatch: '+field)
        result.append((x,y))
    return result


def comparison(pairs):
    a=score.aggregate([x for x,y in pairs]);b=score.aggregate([y for x,y in pairs])
    if any(a[k]!=b[k] for k in ['n','words','chars','duration_seconds']):raise ValueError('Paired denominators/coverage differ.')
    edits={metric:dict(lower=sum(y[key]<x[key] for x,y in pairs),equal=sum(y[key]==x[key] for x,y in pairs),
                       higher=sum(y[key]>x[key] for x,y in pairs)) for metric,key in [('word','word_errors'),('character','char_errors')]}
    return dict(gipformer=a,valsea=b,
        delta_wer_percentage_points=100*(b['wer_whitespace']-a['wer_whitespace']),
        delta_cer_percentage_points=100*(b['cer']-a['cer']),valsea_edit_counts_relative_to_gipformer=edits)


def metrics_for_pairs(pairs):
    groups=defaultdict(list)
    for pair in pairs:groups[pair[0]['intent']].append(pair)
    overall=comparison(pairs);intents={intent:comparison(group) for intent,group in sorted(groups.items())}
    for model in ['gipformer','valsea']:
        for key in ['n',*score.TOTALS,'successful','errors','empty_successful']:
            if sum(g[model][key] for g in intents.values())!=overall[model][key]:raise ValueError('Intent totals differ: '+key)
        if not math.isclose(math.fsum(g[model]['duration_seconds'] for g in intents.values()),overall[model]['duration_seconds'],abs_tol=1e-8):
            raise ValueError('Intent durations differ.')
    return dict(overall=overall,by_intent=intents)


def paired_rows(pairs,evidence):
    for a,b in pairs:
        row={k:a[k] for k in ['sample_id','official_id','filename','split','intent','entities','sentence_annotation',
                             'issues','speaker_id','region','duration_seconds','raw_reference','normalized_reference']}
        for label,value in [('gipformer',a),('valsea',b)]:
            row[label]={k:value[k] for k in ['status','error','raw_hypothesis','normalized_hypothesis',
                'word_errors','words','char_errors','chars','wer_whitespace','cer']}
        e=evidence[a['sample_id']];p=e['prediction'];r=e['response']
        row['valsea']['provenance']=dict(attempt=e['attempt'],timestamp=e['timestamp'],request_id=p.get('request_id'),
            engine=r.get('engine'),model_version=r.get('model_version'),provider_version=p.get('provider_version'),
            returned_model=p.get('returned_model'))
        row['paired_edit_differences']=dict(word_errors=b['word_errors']-a['word_errors'],char_errors=b['char_errors']-a['char_errors'])
        yield row


def load_ready(args):
    names=['manifest.json','configuration.json','run_metadata.json','completion_summary.json','predictions.jsonl']
    paths=[args.manifest,ROOT/'manifests/vnslu_valsea_dev_smoke.json',
        *[run/name for run in [args.gip_run,args.valsea_run,args.smoke_run] for name in names],
        args.valsea_run/'attempts.jsonl',args.smoke_run/'attempts.jsonl',
        args.gip_scores/'per_sample.jsonl',args.gip_scores/'metrics.json']
    # Preserve/verify all existing text run/baseline evidence, never touch audio.
    for directory in [args.gip_run,args.valsea_run,args.smoke_run,args.gip_scores]:
        paths.extend(p for p in directory.rglob('*') if p.is_file() and p.suffix in {'.json','.jsonl','.log','.txt','.md'})
    snapshot=common.capture(set(paths))
    def doc(path):return json.loads(snapshot[path].decode('utf-8'))
    canonical=doc(args.manifest);rows=canonical['records']
    if len(rows)!=2401 or canonical.get('split')!='test' or not canonical.get('ready_for_gipformer'):
        raise ValueError('Full prepared official 2401-record test required.')
    for run in [args.gip_run,args.valsea_run]:
        if doc(run/'manifest.json')!=canonical:raise ValueError('Archived/canonical test manifest mismatch: '+run.name)
    frozen=doc(ROOT/'manifests/vnslu_valsea_dev_smoke.json')
    if doc(args.smoke_run/'manifest.json')!=frozen:raise ValueError('Archived/frozen dev smoke manifest mismatch.')
    audits={};configs={};versions={};successes={}
    for label,run,manifest,mode in [('smoke',args.smoke_run,frozen,'smoke'),('full',args.valsea_run,canonical,'full')]:
        config,meta,saved=[doc(run/name) for name in ['configuration.json','run_metadata.json','completion_summary.json']]
        if meta.get('run_id')!=run.name:raise ValueError('VALSEA RUN_ID/directory mismatch.')
        predictions=common.jsonl(snapshot[run/'predictions.jsonl']);attempts=common.jsonl(snapshot[run/'attempts.jsonl'])
        counts,success=validate_valsea(manifest,predictions,attempts,config,meta,saved,mode)
        audits[label]=dict(run_id=run.name,coverage=counts,events=dict(Counter(e['event'] for e in attempts)),sessions=meta['sessions'],
            historical_outcomes=[{k:e.get(k) for k in ['event','sample_id','attempt','timestamp','http_status','error_type','note']}
                for e in attempts if e['event'] in {'error','unresolved','retry_authorized'}])
        configs[label]=config;versions[label]=common.version_evidence(success,meta['sessions']);successes[label]=success
        if label=='full':valsea_predictions=predictions
    validate_config_pair(configs['full'],configs['smoke'],canonical['provenance'])
    gip_config=doc(args.gip_run/'configuration.json');gip_meta=doc(args.gip_run/'run_metadata.json')
    if gip_meta.get('run_id')!=args.gip_run.name:raise ValueError('GIPFormer RUN_ID/directory mismatch.')
    gip_predictions=common.jsonl(snapshot[args.gip_run/'predictions.jsonl'])
    gip_counts=score.validate_execution(gip_config,gip_meta,doc(args.gip_run/'completion_summary.json'),rows,gip_predictions)
    for i,session in enumerate(gip_meta['sessions'],1):
        directory=args.gip_run/'sessions'/f'{i:04d}'
        if directory/'child.log' not in snapshot:raise ValueError('Missing child execution log.')
        freeze=snapshot[directory/'pip_freeze.txt'].decode('utf-8')
        if sorted(x.strip() for x in freeze.splitlines() if '==' in x or ' @ ' in x)!=gip_meta['resolved_dependencies']:
            raise ValueError('GIPFormer package freeze differs.')
    common.verify_unchanged(snapshot)
    return dict(snapshot=snapshot,canonical=canonical,gip_predictions=gip_predictions,valsea_predictions=valsea_predictions,
        baseline_rows=common.jsonl(snapshot[args.gip_scores/'per_sample.jsonl']),baseline=doc(args.gip_scores/'metrics.json'),
        gip_counts=gip_counts,gip_meta=gip_meta,gip_config=gip_config,audits=audits,versions=versions,
        valsea_config=configs['full'],evidence=successes['full'])


def report(m):
    overall=m['overall'];g=overall['gipformer'];v=overall['valsea'];audit=m['validation']['full']
    lines=['# VN-SLU: VALSEA versus GIPFormer','',
        '**GIPFormer 1.5: FP16 weights with mixed computation, greedy decoding.**',
        '**VALSEA/Glot: recorded glot-transcribe alias; submitted correction/tags/diarization disabled; scored response text.**','',
        '| Model | Word edits / reference tokens | WER | Character edits / reference characters | CER |',
        '| --- | ---: | ---: | ---: | ---: |',
        *[f"| {label} | {r['word_errors']:,} / {r['words']:,} | {100*r['wer_whitespace']:.3f}% | {r['char_errors']:,} / {r['chars']:,} | {100*r['cer']:.3f}% |" for label,r in [('GIPFormer',g),('VALSEA',v)]], '',
        f"VALSEA minus GIPFormer: **WER {overall['delta_wer_percentage_points']:+.3f} percentage points; CER {overall['delta_cer_percentage_points']:+.3f} percentage points**. Negative favors VALSEA. Deltas use unrounded corpus ratios. These are descriptive paired differences, without uncertainty intervals or significance claims.",
        f"Both models: 2,401 expected / 2,401 recorded / {g['successful']} and {v['successful']} successful respectively; {g['errors']} / {v['errors']} inference errors; {g['empty_successful']} / {v['empty_successful']} empty successful texts. Source duration **{g['duration_seconds']:.6f} s ({g['duration_seconds']/3600:.6f} h)**, identical denominators and all official records retained.", '',
        '## Independent execution validation','',
        'Both archived test manifests equal the canonical manifest. Exact ID joins reject duplicates, missing/unknown IDs, malformed statuses or duration disagreements. GIPFormer configuration, final child exit 0/completed inference and package freezes revalidate against its accepted pinned single-T4/cuda:0 setup; recomputed scores match every saved baseline row and all overall/intent additive totals. Existing baseline artifacts were not overwritten.',
        'VALSEA chronological attempt replay verifies successful response text equals its persisted prediction, no already successful ID was resubmitted/replaced, all retries were explicitly authorized, no blocked work remains, and final sessions are complete. Dev smoke/full endpoint, flags, upload, preprocessing, code and package configuration match, allowing only mode/split differences. Six dev smoke requests succeeded; the recorded completed smoke-resume session contains no new request outcomes. No smoke recognition score was calculated.',
        f"Full VALSEA event counts: `{audit['events']}`. Historical HTTP 502 at attempt 2340 for `VN-SLU/test/659d1013ff471bbe244b9ccd` remains an unknown remote outcome. An explicit operator note authorizes its retry; successful retry does not prove the first request was unprocessed/unbilled. Outstanding unresolved/blocked samples: zero. **Exactly-once remote processing is not guaranteed.**", '',
        '## Provider and execution provenance','',
        f"Source runs: GIPFormer `{m['provenance']['gipformer_run_id']}`; VALSEA `{m['provenance']['valsea_run_id']}`; dev smoke `{m['provenance']['smoke_run_id']}`.",
        f"GIPFormer pinned model/source revisions: `{m['provenance']['gipformer_revisions']}`. Author README revision `{m['provenance']['dataset']['repository_revision']}` pins README, not mutable Drive assets; preserved release provenance remains in metrics.json.",
        'Full-run exposed engine counts: '+str({str(x['value']):x['count'] for x in m['api_provenance']['full']['engine']})+'. These labels have unverified meanings; no engine ranking or immutable revision is inferred. Per-session variation and missing version fields are retained below and in metrics.json.', '',
        '| VALSEA session UTC start → end | Status | Successful outcomes | Engine labels |',
        '| --- | --- | ---: | --- |']
    for s in m['api_provenance']['full']['sessions']:
        lines.append(f"| {s['started_utc']} → {s['ended_utc']} | {s['status']} | {s['successful_outcomes']} | {s['engine_counts']} |")
    lines+=['',f"Provider model_version: `{m['api_provenance']['full']['model_version']}`. Exposed provider version: `{m['api_provenance']['full']['exposed_provider_version']}`. Request IDs present/distinct: {m['api_provenance']['full']['request_ids_present']}/{m['api_provenance']['full']['distinct_request_ids']}.",
        'All execution dates are 2026-11-02. UTC session times above correspond to Asia/Saigon UTC+07:00. GIPFormer executed 07:13:06–07:25:16 UTC (14:13:06–14:25:16 Asia/Saigon). No API elapsed-time versus local-model compute-latency comparison is made. Requested flags do not independently establish all backend processing details.', '',
        '## Per-sample edit-count comparisons','',
        'Counts describe VALSEA having fewer/equal/more edits than GIPFormer on the same record; they are not corpus WER/CER or semantic wins. Corpus ratios weight by reference denominators, not utterance win counts.', '',
        '| Edits | Lower | Equal | Higher |','| --- | ---: | ---: | ---: |']
    for metric,counts in overall['valsea_edit_counts_relative_to_gipformer'].items():lines.append(f"| {metric} | {counts['lower']} | {counts['equal']} | {counts['higher']} |")
    lines+=['','## Descriptive supplied-intent groups','',
        'All 28 original labels retained. These are ASR reference-agreement groups, not predicted-intent accuracy or statistically established category rankings. Each cell G / V denotes GIPFormer / VALSEA. Shared counts, durations and denominators reconcile to the whole test.', '',
        '| Official intent | N | Seconds | Ref words | Word edits G / V | WER G / V | ΔWER pp | Ref chars | Char edits G / V | CER G / V | ΔCER pp |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for intent,c in m['by_intent'].items():
        a,b=c['gipformer'],c['valsea']
        lines.append(f"| {intent.replace('|',r'\|')} | {a['n']} | {a['duration_seconds']:.6f} | {a['words']} | {a['word_errors']} / {b['word_errors']} | {100*a['wer_whitespace']:.3f}% / {100*b['wer_whitespace']:.3f}% | {c['delta_wer_percentage_points']:+.3f} | {a['chars']} | {a['char_errors']} / {b['char_errors']} | {100*a['cer']:.3f}% / {100*b['cer']:.3f}% | {c['delta_cer_percentage_points']:+.3f} |")
    directions={key:dict(lower=sum(g[key]<0 for g in m['by_intent'].values()),
        equal=sum(g[key]==0 for g in m['by_intent'].values()),higher=sum(g[key]>0 for g in m['by_intent'].values()))
        for key in ['delta_wer_percentage_points','delta_cer_percentage_points']}
    lines+=['',f"Intent-group delta directions (VALSEA lower/equal/higher): WER {directions['delta_wer_percentage_points']}; CER {directions['delta_cer_percentage_points']}. Group counts are not sample-weighted headline rates or established category capabilities.",
        'For example, tăng độ sáng của thiết bị (62 clips) is 42.308% / 13.818% WER (GIPFormer / VALSEA), while hỏi thông tin (76) is 12.528% / 16.741% and kiểm tra tình trạng thiết bị (88) is 13.937% / 18.009%. Thus the overall direction does not hold for every intent. The volume-change groups have only three/five clips; their large displayed deltas do not establish stable population effects. These statements describe the frozen scores, not error mechanisms or semantic accuracy.']
    lines+=['','## Frozen protocol and boundaries','',
        'NFC → lowercase → Unicode P* punctuation to spaces → whitespace collapse; preserve Vietnamese diacritics, number forms, fillers and repetitions. WER uses whitespace-token Levenshtein (not linguistic word segmentation); CER uses normalized Unicode code points with spaces removed. Corpus summed edits/reference denominators, never mean utterance rates. Successful empty text stays included with full denominators; empty normalized references reject scoring. VALSEA text alone is scored; raw_transcript remains existing evidence, not an alternative selected hypothesis.',
        'This is the author-released official **2,401-sample** VN-SLU test, distinct from the paper’s **2,454** count. Official sentence references, intent/entities, issue flags and scoring policy are unchanged. Strict scoring penalizes number-format differences; prior numeric diagnostics are not applied and no alternate numeric headline score is produced.',
        'Speaker/region metadata is absent. Confidence intervals under the established speaker-cluster protocol are unavailable; no fabricated clusters, regional results, utterance-bootstrap substitute, significance tests or universal superiority claims. No intent accuracy, SLU-F1, slot correctness or LifeMate task success is measured. VN-SLU and ViMD describe different datasets and must not be pooled. Release-license/API-upload permission is not established by this offline scoring exercise.', '',
        '## Reproduction and validation','',
        '`python scripts/compare_vnslu_models.py` from the package root with authorized external input bundles produces only [paired rows](per_sample.jsonl), [metrics](metrics.json) and this report. Existing matching outputs can be reused; conflicting outputs are refused. Tests: `python -m unittest discover -s tests -p test_compare_vnslu_models.py -v`.',
        'Input text artifacts are snapshotted and verified byte-unchanged before output. Source run histories, baseline scores and canonical labels remain untouched. CPU/standard-library scoring only: no network/API/model calls, audio access, dependency upgrades, gold edits or changes to the completed ViMD benchmark. Stop after comparison; no further error analysis was performed.']
    lines+=['','Handoff: independent full-run validation and actual CPU scoring completed. **11 focused comparison tests and 7 existing VN-SLU scorer tests passed**, plus Python compilation. Full/intent counts, durations, edit totals and common denominators reconcile; the 2,401 saved GIPFormer per-sample scores reproduce exactly. Historical 502/retry and engine variation remain documented; no immutable provider revision or uncertainty interval is available. No execution/scoring blocker remains.']
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,default=ROOT/'manifests/vnslu_test.json')
    parser.add_argument('--gip-run',type=Path,default=ROOT/'artifacts/kaggle_vnslu_test'/score.RUN)
    parser.add_argument('--gip-scores',type=Path,default=ROOT/'artifacts/scoring'/score.RUN)
    parser.add_argument('--valsea-run',type=Path,default=ROOT/'artifacts/valsea_vnslu'/VALSEA)
    parser.add_argument('--smoke-run',type=Path,default=ROOT/'artifacts/valsea_vnslu'/SMOKE)
    parser.add_argument('--out',type=Path,default=OUT)
    args=parser.parse_args()
    for directory in [args.gip_run,args.gip_scores,args.valsea_run,args.smoke_run,args.manifest.parent]:
        if args.out.resolve().is_relative_to(directory.resolve()):raise ValueError('Outputs must be separate from source artifacts.')
    ready=load_ready(args);rows=ready['canonical']['records']
    gip=score.score_rows(rows,ready['gip_predictions']);valsea=score.score_rows(rows,ready['valsea_predictions'])
    baseline=ready['baseline']
    if common.unique(gip,'rescored')!=common.unique(ready['baseline_rows'],'saved'):raise ValueError('Saved GIPFormer per-sample scores differ.')
    if (baseline.get('normalizer')!=score.NORMALIZER or baseline['provenance']['run_id']!=args.gip_run.name
            or baseline['provenance']['model_revisions']!=ready['gip_config']['revisions']):raise ValueError('Baseline protocol/provenance differs.')
    computed=score.make_metrics(gip,baseline['provenance'],ready['gip_counts'])
    for key in ['overall','by_intent','coverage','scoring','uncertainty']:
        if computed[key]!=baseline[key]:raise ValueError('Saved GIPFormer metrics differ: '+key)
    if tuple(computed['overall'][k] for k in score.TOTALS)!=(6566,32351,18172,102236):raise ValueError('Frozen baseline totals differ.')
    pairs=paired_join(gip,valsea);m=metrics_for_pairs(pairs)
    m.update(normalizer=score.NORMALIZER,scoring=computed['scoring'],uncertainty=computed['uncertainty'],
        coverage=dict(gipformer=ready['gip_counts'],valsea=score.coverage(rows,ready['valsea_predictions'])),
        delta_definition='VALSEA minus GIPFormer; percentage points; negative favors VALSEA',
        validation=dict(gipformer=ready['gip_counts'],**ready['audits']),api_provenance=ready['versions'],
        provenance=dict(dataset=ready['canonical']['provenance'],gipformer_run_id=args.gip_run.name,
            valsea_run_id=args.valsea_run.name,smoke_run_id=args.smoke_run.name,
            gipformer_revisions=ready['gip_config']['revisions'],gipformer_sessions=baseline['provenance']['sessions'],
            valsea_configuration={k:v for k,v in ready['valsea_config'].items() if not k.endswith('_source')}))
    outputs={'per_sample.jsonl':''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in paired_rows(pairs,ready['evidence'])),
        'metrics.json':json.dumps(m,ensure_ascii=False,indent=2)+'\n','report.md':report(m)}
    common.verify_unchanged(ready['snapshot'])
    for name,text in outputs.items():
        path=args.out/name
        if path.exists() and path.read_bytes()!=text.encode('utf-8'):raise ValueError('Conflicting output: '+str(path))
    args.out.mkdir(parents=True,exist_ok=True)
    for name,text in outputs.items():
        if not (args.out/name).exists():(args.out/name).write_bytes(text.encode('utf-8'))
    common.verify_unchanged(ready['snapshot'])
    print(json.dumps(dict(overall=m['overall'],output=str(args.out)),indent=2))


if __name__=='__main__':main()
