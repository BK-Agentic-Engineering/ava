"""CPU-only validation/scoring of archived GIPFormer VN-SLU predictions. No inference imports."""
import argparse
from collections import defaultdict
from datetime import datetime
import json
import math
from pathlib import Path
import platform
import sys
import unicodedata

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lifemate.benchmark import NORMALIZER,normalize,distance,summary
from score_vimd_test import validate_join,ratio

ROOT=Path(__file__).resolve().parents[1]
RUN='gip15_vnslu_test_fp16_20261102_06'
LABEL='GIPFormer 1.5 — FP16 weights with mixed computation, greedy decoding; VN-SLU author-released official test split.'
TOTALS=('word_errors','words','char_errors','chars')


def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def expected_configuration():
    baseline=read_json(ROOT/'artifacts/kaggle_vimd_test/gip15_vimd_test_fp16_20261101_02/configuration.json')
    baseline['revisions']={k:v for k,v in baseline['revisions'].items() if k!='dataset'}
    baseline.update(dataset='VN-SLU',dataset_assignment='author test.jsonl, 2401 records',
                    dataset_repository_revision='aad93e560f8ec4ab979e76d5dfe36528160b797f')
    # Compare the exact accepted code without importing an inference entry point.
    baseline['implementation']={name:(ROOT/'scripts'/name).read_text(encoding='utf-8') for name in
        ['gipformer15_smoke.py','gipformer15_vimd_test.py','gipformer15_vnslu_test.py']}
    return baseline


def coverage(rows,predictions):
    validate_join(rows,predictions)
    empty=[p['sample_id'] for p in predictions if p['status']=='ok' and p['text']=='']
    errors=sum(p['status']=='error' for p in predictions)
    return dict(expected=len(rows),recorded=len(predictions),remaining=0,coverage_complete=True,
        successful=len(predictions)-errors,errors=errors,empty_successful_count=len(empty),
        empty_successful_transcripts=empty,all_successful_inference=errors==0)


def validate_execution(config,metadata,reported,rows,predictions):
    if config!=expected_configuration():raise ValueError('Archived model/dataset configuration or executed code differs from accepted setup.')
    counts=coverage(rows,predictions)
    if any(reported.get(k)!=v for k,v in counts.items()):raise ValueError('Completion summary does not reconcile with exact prediction evidence.')
    sessions=metadata.get('sessions')
    if not isinstance(sessions,list) or not sessions:raise ValueError('No execution-session evidence.')
    last=sessions[-1];launcher=last['launcher'];inference=last['inference']
    if launcher.get('stage')!='child_completed' or launcher.get('child_exit_code')!=0 or not launcher.get('ended_utc'):
        raise ValueError('Final session lacks successful child completion evidence.')
    baseline=read_json(ROOT/'artifacts/kaggle_vimd_test/gip15_vimd_test_fp16_20261101_02/run_metadata.json')['sessions'][0]['inference']
    for session in sessions:
        run=session['inference']
        if not run.get('fp16_path_loaded'):continue  # Historical failed setup remains in provenance.
        for key in ['cuda_visible_devices','device','visible_gpu_count','decoder','precision','fbank','seed',
                    'deterministic_algorithms','parameter_dtypes','parameter_count','checkpoint_keys','model_arguments']:
            if run.get(key)!=baseline[key]:raise ValueError('Runtime configuration mismatch: '+key)
        if (run.get('packages')!=config['dependencies'] or run.get('expected_packages')!=config['dependencies']
                or run.get('native_wheels')!=config['native_wheels'] or run.get('torch')!='2.8.0+cu128'
                or run.get('cuda_runtime')!='12.8' or not run.get('python','').startswith('3.12.12 ')
                or 'T4' not in run.get('gpu','') or not run.get('platform','').startswith('Linux')):
            raise ValueError('Observed interpreter/native environment differs from accepted pins.')
        encoder=run.get('encoder_output',{})
        if encoder.get('actual_dtype') not in ['torch.float16','torch.float32'] or not encoder.get('all_finite') or not encoder.get('dtype_allowed'):
            raise ValueError('Encoder precision/finiteness check failed.')
        neural=run.get('observed_neural_dtypes',{})
        if set(neural)!=set(baseline['observed_neural_dtypes']) or any(v.get('output')!='torch.float16' or not v.get('all_finite') for v in neural.values()):
            raise ValueError('FP16 neural warmup checks failed.')
    if not inference.get('fp16_path_loaded') or inference.get('stage')!='completed' or inference.get('prediction_status')!='coverage_complete':
        raise ValueError('Final inference stage is not complete.')
    return counts


def score_rows(rows,predictions):
    validate_join(rows,predictions)
    pred={p['sample_id']:p for p in predictions};result=[]
    for row in rows:
        if not isinstance(row.get('reference'),str) or not normalize(row['reference']):
            raise ValueError('Empty normalized reference denominator; explicit review required.')
        p=pred[row['sample_id']];ref=normalize(row['reference']);hyp=normalize(p['text']) if p['status']=='ok' else ''
        word_errors=distance(ref.split(),hyp.split());words=len(ref.split())
        char_errors=distance(ref.replace(' ',''),hyp.replace(' ',''));chars=len(ref.replace(' ',''))
        record={k:row[k] for k in ['sample_id','official_id','filename','split','issues','intent','entities','sentence_annotation','speaker_id','region']}
        record.update(duration_seconds=row['audio']['duration_seconds'],status=p['status'],error=p['error'],
            raw_reference=row['reference'],raw_hypothesis=p['text'],normalized_reference=ref,normalized_hypothesis=hyp,
            word_errors=word_errors,words=words,char_errors=char_errors,chars=chars,failed=p['status']!='ok',
            wer_whitespace=ratio(word_errors,words),cer=ratio(char_errors,chars))
        result.append(record)
    return result


def aggregate(rows):
    return dict(**summary(rows),**{key:sum(r[key] for r in rows) for key in TOTALS},
        duration_seconds=math.fsum(r['duration_seconds'] for r in rows),
        successful=sum(r['status']=='ok' for r in rows),errors=sum(r['failed'] for r in rows),
        empty_successful=sum(r['status']=='ok' and r['raw_hypothesis']=='' for r in rows))


def make_metrics(scored,provenance,counts):
    groups=defaultdict(list)
    for row in scored:groups[row['intent']].append(row)
    overall=aggregate(scored);intents={label:aggregate(group) for label,group in sorted(groups.items())}
    for key in ['n',*TOTALS,'successful','errors','empty_successful']:
        if sum(g[key] for g in intents.values())!=overall[key]:raise ValueError('Intent aggregate totals do not reconcile: '+key)
    if not math.isclose(math.fsum(g['duration_seconds'] for g in intents.values()),overall['duration_seconds'],abs_tol=1e-8):
        raise ValueError('Intent duration totals do not reconcile.')
    return dict(label=LABEL,normalizer=NORMALIZER,
        scoring=dict(wer='corpus whitespace-token Levenshtein edits / summed reference tokens',
            cer='corpus Unicode code-point edits / summed reference characters, normalized spaces removed',
            normalization='NFC; lowercase; Unicode P* punctuation to spaces; split/join whitespace collapse',
            number_normalization=False,diacritics_fillers_repetitions='preserved',
            failure_policy='error hypotheses scored as empty; full reference denominators retained',
            empty_successful_policy='included unchanged; full reference denominators retained',
            python=platform.python_version(),unicode=unicodedata.unidata_version),
        coverage=counts,overall=overall,by_intent=intents,
        uncertainty=dict(available=False,protocol='established speaker-cluster bootstrap',
            reason='Official release supplies no speaker/region metadata; no invented clusters or utterance bootstrap.'),
        provenance=provenance,recognition_quality='official_reference_scored; no semantic/task acceptance claim')


def report(metrics):
    a=metrics['overall'];p=metrics['provenance'];c=metrics['coverage']
    lines=['# GIPFormer VN-SLU official-reference scores','',LABEL,'',
        f"Run: `{p['run_id']}`. **WER {100*a['wer_whitespace']:.3f}%; CER {100*a['cer']:.3f}%.**",
        f"Word edits/reference tokens: **{a['word_errors']:,}/{a['words']:,}**; character edits/reference characters: **{a['char_errors']:,}/{a['chars']:,}**.",'',
        f"Coverage: expected {c['expected']}, recorded {c['recorded']}, remaining {c['remaining']}; successful {c['successful']}, errors {c['errors']}, empty successful {c['empty_successful_count']}. All official records and repeated-reference flags retained.",
        f"Audio: {a['duration_seconds']:.6f} seconds ({a['duration_seconds']/3600:.6f} hours). Confidence intervals: **unavailable** under the established speaker-cluster protocol, because supplied speaker/region metadata is absent. No regional results or substitute utterance bootstrap.",
        'Metrics include inference failures as empty hypotheses with all reference denominators.' if a['errors'] else 'No inference failures or empty successful predictions occurred in this returned run.', '',
        '## Execution validation','',
        'Archived manifest equals canonical manifest; exactly 2,401 expected unique IDs; statuses/durations and saved summary reconcile. Exact configuration/executed code match accepted pinned model, source, dependencies and shared preprocessing. Final child exit 0 and completed inference stage verified.',
        'Recorded runtime: isolated CPython 3.12.12; Torch 2.8.0+cu128 / CUDA runtime 12.8; one visible T4, CUDA_VISIBLE_DEVICES=0, cuda:0, batch 1; explicit greedy_search_batch, max_sym_per_frame=1, blank_penalty=0; seed 20261031, deterministic algorithms. FP16 weights/input with FP16 autocast and permitted FP32 internal operations; CPU FP32 audio/fbank. Checkpoint missing keys none, expected auxiliary CTC-head keys only. Finite permitted encoder output and five finite FP16 neural outputs observed at warmup. No inference was rerun to validate this evidence.',
        f"Sessions: {len(p['sessions'])}. Final launcher start/end: {p['sessions'][-1]['started_utc']} / {p['sessions'][-1]['ended_utc']}. Total recorded session elapsed: {p['total_session_seconds']:.3f} seconds, including setup/downloads; **not isolated inference latency or RTF**.",
        f"Actual run ID is `{p['run_id']}`; the request expected `_01`, but the sole returned ZIP and notebook internally identify `_06`. Selection was by evidence identity, not recognition results.", '',
        '## Protocol and interpretation','',
        'Official author-released test.jsonl supplies **2,401** records, distinct from paper Table 2’s 2,454. The provided sentence field is the official reference baseline. Raw labels/references/predictions and the frozen scoring policy are unchanged. No new manual gold audit is required to complete these scores.',
        'NFC → lowercase → Unicode punctuation P* to spaces → whitespace collapse. Diacritics, number forms, fillers and repetitions retained. WER uses whitespace tokens, not Vietnamese linguistic word segmentation. CER uses normalized Unicode code points without spaces. Corpus ratios use summed edits/reference denominators, never mean per-utterance rates. Explicit errors and valid empty predictions retain all denominators.',
        'Reference agreement is not intent/slot accuracy, SLU-F1 or LifeMate task success. The author’s Speaker–Value split is not a random real-world-usage sample. No semantic alignment or scoring is performed. VN-SLU and ViMD are different datasets and must not be pooled. Local source/license and split limitations remain in the preparation note.', '',
        '## Descriptive results by supplied intent','',
        'These are ASR reference-agreement groups, **not intent-classification accuracy**; no inferred labels, semantic scores or subgroup confidence intervals. Sparse/support differences limit comparison. All intent sums reconcile with the full test.', '',
        '| Official intent | Clips | Words | Word edits | WER | Characters | Character edits | CER | Audio seconds |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for intent,g in metrics['by_intent'].items():
        lines.append(f"| {intent.replace('|',r'\|')} | {g['n']} | {g['words']} | {g['word_errors']} | {100*g['wer_whitespace']:.3f}% | {g['chars']} | {g['char_errors']} | {100*g['cer']:.3f}% | {g['duration_seconds']:.6f} |")
    lines+=['','## Provenance and reproduction','',
        f"Author repository revision: `{p['dataset_repository_revision']}`; Drive archive identity remains mutable and is preserved in manifest provenance. Model/source revisions: `{p['model_revisions']}`. Exact source configuration and sessions remain in the preserved run directory.",
        'See [per-sample scores](per_sample.jsonl) and [exact metrics](metrics.json). Original issue flags, supplied semantic labels, raw/normalized strings, statuses/errors, edits and denominators are retained per sample.', '',
        f"From project root: `python scripts/score_vnslu_test.py --run-dir artifacts/kaggle_vnslu_test/{p['run_id']}`.",
        'Standard-library CPU scoring only. Input snapshots checked unchanged before writing these three derived outputs. No model/API/GPU/Kaggle access, dependency upgrades, gold changes or modifications to the completed ViMD benchmark.']
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,default=ROOT/'artifacts/kaggle_vnslu_test'/RUN)
    parser.add_argument('--manifest',type=Path,default=ROOT/'manifests/vnslu_test.json')
    parser.add_argument('--out',type=Path)
    args=parser.parse_args();run=args.run_dir.resolve();out=args.out or ROOT/'artifacts/scoring'/run.name
    if out.resolve().is_relative_to(run) or out.resolve().is_relative_to(args.manifest.resolve().parent):
        raise ValueError('Scoring outputs must be separate from input artifacts.')
    paths=[args.manifest,*[p for p in run.rglob('*') if p.is_file()]]
    snapshot={p:p.read_bytes() for p in paths}
    before=lambda name:json.loads(snapshot[run/name].decode('utf-8'))
    manifest=json.loads(snapshot[args.manifest].decode('utf-8'))
    if before('manifest.json')!=manifest or snapshot[run/'manifest.json']!=snapshot[args.manifest]:raise ValueError('Archived/canonical manifest differs.')
    rows=manifest['records']
    if len(rows)!=2401 or manifest.get('split')!='test' or not manifest.get('ready_for_gipformer'):raise ValueError('Full official prepared 2401-record test manifest required.')
    data=snapshot[run/'predictions.jsonl']
    if not data.endswith(b'\n'):raise ValueError('Interrupted prediction write; preserve for review, no repair.')
    predictions=[json.loads(line.decode('utf-8')) for line in data.splitlines()]
    metadata=before('run_metadata.json');config=before('configuration.json')
    if metadata['run_id']!=run.name:raise ValueError('Internal RUN_ID differs from input directory.')
    counts=validate_execution(config,metadata,before('completion_summary.json'),rows,predictions)
    sessions=[]
    for index,s in enumerate(metadata['sessions'],1):
        l=s['launcher'];entry={k:l.get(k) for k in ['started_utc','ended_utc','resume','restored_from','stage','child_exit_code']}
        for name in ['child.log','pip_freeze.txt']:
            if run/'sessions'/f'{index:04d}'/name not in snapshot:raise ValueError('Essential child/freeze evidence missing.')
        frozen=snapshot[run/'sessions'/f'{index:04d}'/'pip_freeze.txt'].decode('utf-8')
        packages=sorted(line.strip() for line in frozen.splitlines() if '==' in line or ' @ ' in line)
        if packages!=metadata.get('resolved_dependencies'):raise ValueError('Resolved package freeze differs from run metadata.')
        entry['elapsed_seconds']=(datetime.fromisoformat(l['ended_utc'])-datetime.fromisoformat(l['started_utc'])).total_seconds()
        sessions.append(entry)
    provenance=dict(run_id=metadata['run_id'],dataset='VN-SLU',split='author-released official test',
        dataset_repository_revision=manifest['provenance']['repository_revision'],model_revisions=config['revisions'],
        source_run_directory=str(run.relative_to(ROOT)) if run.is_relative_to(ROOT) else str(run),sessions=sessions,
        total_session_seconds=math.fsum(s['elapsed_seconds'] for s in sessions),execution_validation='passed')
    scored=score_rows(rows,predictions);metrics=make_metrics(scored,provenance,counts)
    if any(p.read_bytes()!=content for p,content in snapshot.items()):raise ValueError('Source artifacts changed during scoring; no output written.')
    outputs={'per_sample.jsonl':''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in scored),
             'metrics.json':json.dumps(metrics,ensure_ascii=False,indent=2)+'\n','report.md':report(metrics)}
    # Reproducible output reuse; never silently replace a conflicting earlier report.
    for name,text in outputs.items():
        path=out/name
        if path.exists() and path.read_bytes()!=text.encode('utf-8'):raise ValueError('Conflicting scoring output: '+str(path))
    out.mkdir(parents=True,exist_ok=True)
    for name,text in outputs.items():
        if not (out/name).exists():(out/name).write_bytes(text.encode('utf-8'))
    print(json.dumps(dict(run_id=metadata['run_id'],coverage=counts,overall=metrics['overall'],output=str(out)),indent=2))


if __name__=='__main__':main()
