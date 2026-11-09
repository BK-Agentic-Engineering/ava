"""CPU-only single-run ViMD scoring under the frozen reference-agreement protocol."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import platform
import random
import sys
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lifemate.benchmark import NORMALIZER, evaluate, normalize, summary

RUN_ID = 'gip15_vimd_test_fp16_20261101_02'
LABEL = 'GIPFormer 1.5 — FP16 weights with mixed computation, greedy decoding.'
TOTALS = ('word_errors', 'words', 'char_errors', 'chars')
REGIONS = ('North', 'Central', 'South')
BOOTSTRAP = dict(replicates=2000, seed=42, strata=['source','region'], cluster='speaker_id',
                 percentile='sorted draws[int(q*(B-1))], q=0.025 and 0.975',
                 stratum_order='sorted (source, region); sorted speaker IDs',
                 multiplicity='each speaker draw contributes every utterance; repeated draws count repeatedly')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def validate_join(rows, predictions):
    if not rows:
        raise ValueError('Empty manifest.')
    for label, records in [('manifest',rows),('predictions',predictions)]:
        ids = []
        for record in records:
            if not isinstance(record,dict) or not isinstance(record.get('sample_id'),str) or not record['sample_id'].strip():
                raise ValueError('Malformed ' + label + ' record/sample_id.')
            ids.append(record['sample_id'])
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate ' + label + ' ID.')
    if {r['sample_id'] for r in rows} != {p['sample_id'] for p in predictions}:
        raise ValueError('Prediction/manifest IDs differ: missing or unknown IDs.')
    by_id = {r['sample_id']:r for r in rows}
    for p in predictions:
        if p.get('status') not in {'ok','error'}:
            raise ValueError('Only actual ok/error statuses are supported; no timeout mechanism was used.')
        if 'text' not in p or 'error' not in p:
            raise ValueError('Missing prediction text/error fields.')
        if p['status']=='ok' and (not isinstance(p['text'],str) or p['error'] is not None):
            raise ValueError('Malformed successful prediction.')
        if p['status']=='error' and (p['text'] is not None or not isinstance(p['error'],dict)
                or any(not isinstance(p['error'].get(k),str) for k in ['stage','type','message'])):
            raise ValueError('Malformed error prediction.')
        duration = p.get('duration_seconds')
        if isinstance(duration,bool) or not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<=0:
            raise ValueError('Missing/invalid prediction duration.')
        if duration != by_id[p['sample_id']]['audio']['duration_seconds']:
            raise ValueError('Prediction duration differs from manifest.')


def ratio(errors, denominator):
    if denominator<=0:
        raise ValueError('Zero reference denominator: review required; no silent exclusion or fabricated rate.')
    return errors/denominator


def score_rows(rows, predictions):
    validate_join(rows,predictions)
    for r in rows:
        if not isinstance(r.get('reference'),str) or not normalize(r['reference']):
            raise ValueError('Zero reference denominator: review required before scoring.')
    # Existing evaluate uses the exact ID join, frozen normalization and edit distances.
    evaluated = evaluate(rows,predictions)
    pred = {p['sample_id']:p for p in predictions}
    result = []
    for r in evaluated:
        p = pred[r['sample_id']]
        ref = normalize(r['reference'])
        hyp = normalize(p['text']) if p['status']=='ok' else ''
        result.append(dict(sample_id=r['sample_id'],source=r['source'],split=r['split'],
            filename=r['filename'],speaker_id=r['speaker_id'],region=r['region'],
            province_code=r['province_code'],province_name=r['province_name'],issues=r['issues'],
            issue_status=r['issue_status'],duration_seconds=r['audio']['duration_seconds'],
            status=p['status'],error=p['error'],raw_reference=r['reference'],raw_hypothesis=p['text'],
            normalized_reference=ref,normalized_hypothesis=hyp,
            word_errors=r['word_errors'],words=r['words'],char_errors=r['char_errors'],chars=r['chars'],
            failed=r['failed'],wer_whitespace=ratio(r['word_errors'],r['words']),cer=ratio(r['char_errors'],r['chars'])))
    return result


def aggregate(rows):
    existing = summary(rows)
    return dict(**existing,unique_speakers=len({(r['source'],r['speaker_id']) for r in rows}),
                duration_seconds=math.fsum(r['duration_seconds'] for r in rows),
                **{key:sum(r[key] for r in rows) for key in TOTALS},
                errors=sum(r['failed'] for r in rows),
                empty_successful=sum(r['status']=='ok' and r['raw_hypothesis']=='' for r in rows))


def speaker_totals(rows):
    strata = defaultdict(lambda:defaultdict(lambda:[0,0,0,0]))
    for r in rows:
        if not r.get('speaker_id') or not r.get('region'):
            return None
        values = strata[(r['source'],r['region'])][r['speaker_id']]
        for i,key in enumerate(TOTALS):
            values[i] += r[key]
    return strata


def bootstrap_draw(strata,rng):
    total = [0,0,0,0]
    for stratum in sorted(strata):
        speakers = strata[stratum]
        keys = sorted(speakers)
        for key in rng.choices(keys,k=len(keys)):
            for i,value in enumerate(speakers[key]):
                total[i] += value
    return ratio(total[0],total[1]),ratio(total[2],total[3])


def speaker_ci(rows,replicates=2000,seed=42):
    strata = speaker_totals(rows)
    if not strata or any(len(s)<2 for s in strata.values()):
        return dict(available=False,reason='Missing cluster metadata or fewer than two speakers in a source/region stratum.')
    rng = random.Random(seed)
    draws = [bootstrap_draw(strata,rng) for _ in range(replicates)]
    result = dict(available=True,replicates=replicates,seed=seed)
    for index,key in enumerate(['wer_whitespace','cer']):
        values = sorted(draw[index] for draw in draws)
        result[key] = [values[int(.025*(replicates-1))],values[int(.975*(replicates-1))]]
    return result


def make_metrics(rows):
    overall = aggregate(rows)
    overall['ci95'] = speaker_ci(rows)
    regional = {}
    for region in REGIONS:
        group = [r for r in rows if r['region']==region]
        regional[region] = dict(**aggregate(group),ci95=speaker_ci(group))
    provinces = {}
    for code,name in sorted({(r['province_code'],r['province_name']) for r in rows}):
        group = [r for r in rows if r['province_code']==code and r['province_name']==name]
        provinces[str(code)] = dict(province_name=name,region=group[0]['region'],**aggregate(group))
    # Explicit reconciliation for every additive quantity before writing outputs.
    reconciliation = {}
    for label,groups in [('regions',regional),('provinces',provinces)]:
        for key in ('n','errors','empty_successful',*TOTALS):
            if sum(g[key] for g in groups.values()) != overall[key]:
                raise ValueError(f'{label} do not reconcile: {key}')
        if not math.isclose(math.fsum(g['duration_seconds'] for g in groups.values()),overall['duration_seconds'],abs_tol=1e-8):
            raise ValueError(label+' durations do not reconcile.')
        reconciliation[label] = True
    return dict(overall=overall,by_region=regional,by_province=provinces,
                region_macro=dict(wer_whitespace=math.fsum(g['wer_whitespace'] for g in regional.values())/3,
                                  cer=math.fsum(g['cer'] for g in regional.values())/3,
                                  policy='unweighted mean of North/Central/South corpus rates; not corpus micro'),
                reconciliation=reconciliation)


def load_inputs(run_directory,manifest_path):
    run_directory = Path(run_directory)
    canonical = read_json(manifest_path)
    if read_json(run_directory/'manifest.json') != canonical:
        raise ValueError('Archived manifest does not match canonical manifest.')
    config = read_json(run_directory/'configuration.json')
    metadata = read_json(run_directory/'run_metadata.json')
    completion = read_json(run_directory/'completion_summary.json')
    predictions = []
    for line in (run_directory/'predictions.jsonl').read_text(encoding='utf-8').splitlines():
        if not line.strip():
            raise ValueError('Blank/malformed prediction line.')
        predictions.append(json.loads(line))
    rows = [{**r,'source':canonical['provenance']['source'],'split':canonical['provenance']['split']}
            for r in canonical['records']]
    validate_join(rows,predictions)
    successful = sum(p['status']=='ok' for p in predictions)
    empty = [p['sample_id'] for p in predictions if p['status']=='ok' and p['text']=='']
    expected = dict(expected=len(rows),recorded=len(predictions),remaining=0,coverage_complete=True,
                    successful=successful,errors=len(predictions)-successful,
                    empty_successful_count=len(empty),empty_successful_transcripts=empty,
                    all_successful_inference=successful==len(rows),review_status='pending_human_review',
                    recognition_quality='not_assessed')
    if completion != expected:
        raise ValueError('Completion summary disagrees with validated records.')
    if metadata['run_id'] != RUN_ID or len(rows)!=2026 or successful!=2026 or empty:
        raise ValueError('Inputs do not match the specified completed run coverage.')
    if config['precision']!='fp16' or config['revisions']['dataset']!=canonical['provenance']['revision']:
        raise ValueError('Run configuration/dataset revision conflict.')
    return rows,predictions,canonical,config,metadata


def report(metrics):
    def pct(value): return f'{100*value:.3f}%'
    def interval(group,key):
        ci=group['ci95']
        return 'unavailable' if not ci['available'] else '–'.join(pct(x) for x in ci[key])
    lines=['# GIPFormer 1.5 ViMD full-test reference agreement','',LABEL,'',
           '## Full corpus and regions','',
           '| Group | Clips | Speakers | Audio hours | WER | 95% speaker CI | CER | 95% speaker CI |',
           '| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |']
    for name,group in [('Full test',metrics['overall']),*metrics['by_region'].items()]:
        lines.append(f"| {name} | {group['n']} | {group['unique_speakers']} | {group['duration_seconds']/3600:.6f} | {pct(group['wer_whitespace'])} | {interval(group,'wer_whitespace')} | {pct(group['cer'])} | {interval(group,'cer')} |")
    macro=metrics['region_macro']
    total=metrics['overall']
    lines += ['',f"Unweighted three-region macro: **WER {pct(macro['wer_whitespace'])}; CER {pct(macro['cer'])}**. This is a mean of three regional corpus rates, distinct from full-test corpus micro.",
              f"Corpus totals: {total['word_errors']}/{total['words']} whitespace-token edits/reference tokens; {total['char_errors']}/{total['chars']} character edits/reference characters.",
              f"Coverage is complete: {total['n']}/2026 records, {total['errors']} inference errors, {total['empty_successful']} successful empty predictions. All three speaker-overlap-flagged test records are included.", '',
              '## Scoring and uncertainty','',
              '- Normalizer `nfc-lower-punctuation-space-v1`: NFC → lowercase → Unicode P* punctuation to spaces → whitespace collapse. Diacritics, numbers and fillers are preserved. No linguistic Vietnamese word segmentation: WER uses whitespace units, often syllables.',
              '- CER removes all normalized spaces from both strings, then compares Unicode code points. It does not count whitespace, bytes or grapheme clusters. Corpus WER/CER divide summed edit counts by summed reference denominators; per-clip averages are not used.',
              '- Zero normalized reference denominators halt scoring for review. They are not assigned zero, infinity or silently excluded. No such reference occurs in this audited run. Empty successful hypotheses and failed calls would score as empty; failures remain distinct in counts.',
              '- 2,000 speaker-cluster bootstrap replicates, seed 42, stratified by source/region. Sorted strata and sorted speaker IDs; sample each stratum’s original number of speakers with replacement, retaining all utterances and repeated-draw multiplicity. Recompute corpus ratios for every draw; empirical endpoints use sorted draws[int(q*(B−1))], q=0.025/0.975. Overall and each regional interval use independent RNG instances reset to seed 42. No province intervals or macro interval were required or added.',
              '- All required speaker/region/province labels are present; no unknown subgroup is omitted. IDs identify clusters as supplied and do not verify speaker independence. Sparse subgroup support can make estimates unstable; the intervals do not prove population representativeness.', '',
              '## Descriptive province results','',
              'Provinces are listed by source code, not ranked. Province scores are descriptive; differences are not statistically established. Limited speaker support is shown explicitly.', '',
              '| Code | Province | Region | Clips | Speakers | Audio hours | WER | CER |',
              '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for code,g in metrics['by_province'].items():
        lines.append(f"| {code} | {g['province_name']} | {g['region']} | {g['n']} | {g['unique_speakers']} | {g['duration_seconds']/3600:.6f} | {pct(g['wer_whitespace'])} | {pct(g['cer'])} |")
    minimum=min(g['unique_speakers'] for g in metrics['by_province'].values())
    least=[g['province_name'] for g in metrics['by_province'].values() if g['unique_speakers']==minimum]
    lines += ['',f"Least province speaker support: {minimum} supplied speaker IDs in {', '.join(least)}. This relative observation is not an adequacy pass/fail threshold.", '',
              '## Provenance, validation and limits','',
              f"- Source run: `{metrics['provenance']['run_id']}`. Dataset revision `{metrics['provenance']['dataset_revision']}`; source/model/icefall revisions, normalization and bootstrap settings are in metrics.json.",
              '- Validated exact archived/canonical manifest equality, one-to-one ID join, statuses and completion counts. Reconciled clips, durations, edits and denominators across all regions and provinces. Raw texts and all source artifacts remain unchanged; normalized copies are in per_sample.jsonl.',
              '- Metrics measure agreement with supplied references. Reference correctness, model-training overlap, and FP16/FP32 equivalence remain unverified. No claim of model-card WER reproduction, semantic correctness, or accuracy on all LifeMate speech is made.',
              '- Two speaker IDs overlap validation/test across three retained test records; speaker-ID overlap alone does not establish leakage. No overlap-based filtering was performed.',
              '- The 24m43s Kaggle session includes setup/downloads and is not model inference latency or RTF. Performance benchmarking and human gold correction are outside this iteration.',
              '- Recognition-quality acceptance remains pending human review. No inference, Kaggle access, GPU, model installation or reference correction was performed during scoring.', '',
              'Reproduce from the project root: `python scripts/score_vimd_test.py`. Outputs are per_sample.jsonl, metrics.json and this report in `artifacts/scoring/gip15_vimd_test_fp16_20261101_02/`.']
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,default=Path('artifacts/kaggle_vimd_test')/RUN_ID)
    parser.add_argument('--manifest',type=Path,default=Path('manifests/vimd_test.json'))
    parser.add_argument('--out',type=Path,default=Path('artifacts/scoring')/RUN_ID)
    args=parser.parse_args()
    if args.out.resolve().is_relative_to(args.run_dir.resolve()) or args.out.resolve()==args.manifest.resolve().parent:
        raise ValueError('Scoring outputs must be separate from completed run artifacts and manifests.')
    rows,predictions,canonical,config,metadata=load_inputs(args.run_dir,args.manifest)
    scored=score_rows(rows,predictions)
    metrics=make_metrics(scored)
    metrics.update(label=LABEL,normalizer=NORMALIZER,
        scoring=dict(wer='corpus whitespace Levenshtein',cer='corpus Unicode code points, normalized spaces removed',
                     zero_denominator='reject and require review',number_normalization=False,
                     failures='empty hypothesis; no excluded references',bootstrap=BOOTSTRAP),
        provenance=dict(run_id=metadata['run_id'],dataset=canonical['provenance']['dataset'],
                        dataset_revision=canonical['provenance']['revision'],revisions=config['revisions'],
                        precision=config['precision'],decoder='greedy_search_batch',
                        input_run_directory=str(args.run_dir),canonical_manifest=str(args.manifest),
                        python=platform.python_version(),unicode_version=unicodedata.unidata_version),
        review_status='pending_human_review',reference_correctness='unverified',fp16_fp32_equivalence='unverified')
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/'per_sample.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in scored),encoding='utf-8')
    (args.out/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (args.out/'report.md').write_text(report(metrics),encoding='utf-8')
    print(json.dumps(dict(overall=metrics['overall'],regional=metrics['by_region'],macro=metrics['region_macro']),indent=2))


if __name__=='__main__':
    main()
