"""Prepare the full pinned ViMD test manifest; never run ASR or filter records.

Requires the existing numpy, soundfile, pyarrow and fsspec/aiohttp environment.
Reads validation metadata only and test audio incrementally via HTTP ranges.
"""
import argparse
from collections import Counter, defaultdict
import io
import json
from pathlib import Path
import platform
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lifemate.benchmark import NORMALIZER, normalize

DATASET = 'nguyendv02/ViMD_Dataset'
REVISION = '3a5b30157034e7eadd5c75fae1a820c6f9383398'
BASE = f'https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}/'
METADATA_COLUMNS = ['filename', 'text', 'speakerID', 'region', 'province_code', 'province_name', 'gender']


def missing(value):
    return value is None or isinstance(value, str) and not value.strip()


def make_record(source, shard, row_group, row_in_group, row_in_shard):
    filename = source['filename']
    row = dict(sample_id='ViMD_Dataset/test/' + (filename if not missing(filename)
               else f'@{shard}:{row_in_shard}'), filename=filename, shard=shard,
               row_group=row_group, row_in_group=row_in_group, row_in_shard=row_in_shard,
               reference=source['text'], speaker_id=source['speakerID'], region=source['region'],
               province_code=source['province_code'], province_name=source['province_name'],
               gender=source['gender'], audio=None, audio_check='pending', issues=[])
    for key in ['filename', 'speaker_id', 'region', 'province_code', 'province_name']:
        if missing(row[key]):
            row['issues'].append('missing_' + key)
    if missing(row['reference']):
        row['issues'].append('empty_reference')
    elif not normalize(row['reference']):
        row['issues'].append('empty_normalized_reference')
    return row


def flag_groups(rows, key, issue):
    groups = defaultdict(list)
    for row in rows:
        value = key(row)
        if not missing(value):
            groups[value].append(row)
    repeated = [group for group in groups.values() if len(group) > 1]
    for group in repeated:
        for row in group:
            row['issues'].append(issue)
    return [[r['sample_id'] for r in group] for group in repeated]


def audit_metadata(rows, valid):
    findings = {}
    for name, key in [('duplicate_id', lambda r: r['sample_id']),
                      ('duplicate_source_filename', lambda r: r['filename']),
                      ('duplicate_source_location', lambda r: (r['shard'], r['row_group'], r['row_in_group'])),
                      ('repeated_exact_transcript', lambda r: r['reference'])]:
        findings[name] = flag_groups(rows, key, name)
    valid_speakers = {r['speakerID'] for r in valid if not missing(r['speakerID'])}
    valid_sources = {r['filename'] for r in valid if not missing(r['filename'])}
    for row in rows:
        if row['speaker_id'] in valid_speakers:
            row['issues'].append('speaker_overlap_valid')
        if row['filename'] in valid_sources:
            row['issues'].append('source_filename_overlap_valid')
    findings['valid_records'] = len(valid)
    findings['overlapping_speaker_ids'] = sorted({r['speaker_id'] for r in rows
                                                 if 'speaker_overlap_valid' in r['issues']})
    findings['overlapping_source_filenames'] = sorted({r['filename'] for r in rows
                                                     if 'source_filename_overlap_valid' in r['issues']})
    # A speaker's conflicting source labels would invalidate naive cluster strata.
    regions = defaultdict(set)
    for row in rows:
        if not missing(row['speaker_id']) and not missing(row['region']):
            regions[row['speaker_id']].add(row['region'])
    findings['speaker_region_conflicts'] = {k: sorted(v) for k, v in regions.items() if len(v) > 1}
    for row in rows:
        if row['speaker_id'] in findings['speaker_region_conflicts']:
            row['issues'].append('speaker_region_conflict')
    return findings


def inspect_audio(audio):
    import numpy as np
    import soundfile as sf
    data = (audio or {}).get('bytes')
    if data is None:
        return {'source_path': (audio or {}).get('path')}, ['missing_audio']
    info = {'source_path': audio.get('path'), 'encoded_bytes': len(data)}
    if not data:
        return info, ['empty_audio']
    try:
        with sf.SoundFile(io.BytesIO(data)) as handle:
            info.update(sample_rate=handle.samplerate, channels=handle.channels,
                        frames=handle.frames, duration_seconds=handle.frames / handle.samplerate,
                        format=handle.format, subtype=handle.subtype)
            frames_read, finite = 0, True
            for block in handle.blocks(blocksize=65536, dtype='float32', always_2d=True):
                frames_read += len(block)
                finite = bool(np.isfinite(block).all()) and finite
            info.update(decoded_frames=frames_read, all_finite=finite)
            issues = []
            if frames_read == 0:
                issues.append('empty_audio')
            if frames_read != handle.frames:
                issues.append('audio_frame_count_mismatch')
            if not finite:
                issues.append('nonfinite_audio')
            return info, issues
    except Exception as error:
        info['error'] = f'{type(error).__name__}: {error}'
        return info, ['unreadable_audio']


def list_shards():
    url = f'https://huggingface.co/api/datasets/{DATASET}/tree/{REVISION}/data?limit=1000'
    files = []
    while url:
        with urllib.request.urlopen(url) as response:
            files.extend(json.load(response))
            links = response.headers.get('Link', '')
        url = next((part.split('>')[0].strip().lstrip('<') for part in links.split(',')
                    if 'rel="next"' in part), None)
    return {split: sorted([{'path': f['path'], 'bytes': f['size']} for f in files
                           if f['type'] == 'file' and f['path'].startswith('data/' + split + '-')
                           and f['path'].endswith('.parquet')], key=lambda f: f['path'])
            for split in ['test', 'valid']}


def read_metadata(shards):
    import fsspec
    import pyarrow.parquet as pq
    rows, valid, schemas = [], [], {}
    for split in ['valid', 'test']:
        for shard in shards[split]:
            print('Metadata:', shard['path'], flush=True)
            with fsspec.open(BASE + shard['path'], 'rb', block_size=65536, cache_type='none') as handle:
                parquet = pq.ParquetFile(handle, pre_buffer=False)
                schema = str(parquet.schema_arrow.remove_metadata())
                if split in schemas and schemas[split] != schema:
                    raise ValueError('Schema differs across shards: ' + shard['path'])
                schemas[split] = schema
                shard['records'] = parquet.metadata.num_rows
                shard['row_group_records'] = []
                offset = 0
                for group in range(parquet.metadata.num_row_groups):
                    batch = parquet.read_row_group(group, columns=METADATA_COLUMNS).to_pylist()
                    assert len(batch) == parquet.metadata.row_group(group).num_rows
                    shard['row_group_records'].append(len(batch))
                    for index, source in enumerate(batch):
                        if split == 'test':
                            rows.append(make_record(source, shard['path'], group, index, offset + index))
                        else:
                            valid.append(source)
                    offset += len(batch)
                assert offset == shard['records']
    assert rows and len(rows) == sum(s['records'] for s in shards['test'])
    return rows, valid, schemas


def audit_audio(rows, shards):
    import fsspec
    import pyarrow.parquet as pq
    by_shard = defaultdict(list)
    for row in rows:
        by_shard[row['shard']].append(row)
    failures = []
    for shard in shards['test']:
        print('Audio:', shard['path'], flush=True)
        try:
            with fsspec.open(BASE + shard['path'], 'rb', block_size=65536, cache_type='none') as handle:
                parquet = pq.ParquetFile(handle, pre_buffer=False)
                count = 0
                for batch in parquet.iter_batches(batch_size=1, columns=['filename', 'audio'], use_threads=False):
                    source = batch.to_pylist()[0]
                    row = by_shard[shard['path']][count]
                    assert row['filename'] == source['filename']
                    row['audio'], issues = inspect_audio(source['audio'])
                    row['issues'].extend(issues)
                    row['audio_check'] = 'issues' if issues else 'passed'
                    count += 1
                assert count == shard['records']
        except Exception as error:
            failures.append({'shard': shard['path'], 'error': f'{type(error).__name__}: {error}'})
            print('Audio check incomplete:', failures[-1], flush=True)
    return failures


def coverage(rows):
    durations = [r['audio']['duration_seconds'] for r in rows
                 if r['audio'] is not None and 'duration_seconds' in r['audio']]
    return dict(records=len(rows), speakers=len({r['speaker_id'] for r in rows if not missing(r['speaker_id'])}),
                duration_records=len(durations), duration_seconds=sum(durations))


def report(document):
    import numpy as np
    rows, findings = document['records'], document['audit']
    total = coverage(rows)
    issues = Counter(issue for r in rows for issue in r['issues'])
    audio = Counter(r['audio_check'] for r in rows)
    durations = [r['audio']['duration_seconds'] for r in rows
                 if r['audio'] is not None and 'duration_seconds' in r['audio']]
    lines = ['# Full ViMD test manifest and scoring protocol', '',
        f"Prepared {document['provenance']['prepared_utc']}; no ASR inference performed.", '',
        '## Provenance and scope', '',
        f'- Source: [{DATASET}](https://huggingface.co/datasets/{DATASET}/tree/{REVISION}); revision `{REVISION}`; official `test` split.',
        '- The manifest (`manifests/vimd_test.json` by default) stores common provenance, shard sizes/counts/schema, every test record and audit findings. References are unchanged. No row is excluded.',
        '- Stable ID: `ViMD_Dataset/test/<filename>`. A missing filename uses an explicit shard/row fallback and is flagged; duplicate IDs remain flagged, not renamed.',
        '- Retrieval: pinned base URL + shard; zero-based row_group/row_in_group or row_in_shard. Audio source path and header metadata are retained when inspected.',
        '- HTTP ranges read all test metadata/audio and validation metadata columns only. No train download or validation audio decoding. At most one clip is decoded in blocks; Parquet pages can contain multiple encoded clips.',
        '- Audio audit checks original audio, without resampling, trimming, denoising or modification. No fingerprints were generated: repeated text alone does not establish duplicate audio. Exhaustive audio-content duplicate detection and train overlap are not assessed.',
        '- Attribution: ViMD / Dinh et al., EMNLP 2024; source license CC BY-NC-ND 4.0. Keep audio private; this output contains metadata/transcripts, not audio.', '',
        '## Coverage', '',
        f"- Records: **{total['records']}**; unique IDs: **{len({r['sample_id'] for r in rows})}**; speakers: **{total['speakers']}**; province codes: **{len({r['province_code'] for r in rows if not missing(r['province_code'])})}**.",
        f"- Available duration: **{total['duration_seconds']:.3f} seconds ({total['duration_seconds']/3600:.6f} hours)** from {total['duration_records']}/{total['records']} headers.",
        f'- Audio inspection: `{dict(audio)}`. Pending checks are not counted as audio passes.',
        f'- Metadata issues / overlap flags (record counts): `{dict(sorted(issues.items()))}`.',
        '- Missing metadata counts: `' + str({k: sum(missing(r[k]) for r in rows) for k in ['filename','speaker_id','region','province_code','province_name']}) + '`.',
        '- Empty references: ' + str(sum('empty_reference' in r['issues'] for r in rows)) + '; nonempty references empty after scoring normalization: ' + str(sum('empty_normalized_reference' in r['issues'] for r in rows)) + '.', '',
        '| Region / province code / province name | Records | Speakers | Duration records | Hours |',
        '| --- | ---: | ---: | ---: | ---: |']
    groups = defaultdict(list)
    for r in rows:
        groups['Region: ' + str(r['region'])].append(r)
        groups['Province: ' + str(r['province_code']) + ' / ' + str(r['province_name']) + ' / ' + str(r['region'])].append(r)
    for name, group in sorted(groups.items(), key=lambda x: (not x[0].startswith('Region:'), x[0])):
        c = coverage(group)
        lines.append(f"| {name} | {c['records']} | {c['speakers']} | {c['duration_records']} | {c['duration_seconds']/3600:.6f} |")
    if durations:
        values = np.quantile(durations, [0, .25, .5, .75, .95, 1], method='linear')
        lines += ['', '- Duration distribution, seconds (linear quantiles): ' +
                  ', '.join(f'{k}={v:.3f}' for k, v in zip(['min','p25','median','p75','p95','max'], values)) + '.']
    provinces = [(name, coverage(group)) for name, group in groups.items() if name.startswith('Province:')]
    if provinces:
        minimum = min(c['speakers'] for _, c in provinces)
        lines += [f"- Least observed province speaker coverage: {minimum} speaker(s): " +
                  '; '.join(name for name, c in provinces if c['speakers'] == minimum) +
                  '. This is a relative coverage observation, not a sufficiency threshold. Counts/durations do not prove demographic or acoustic coverage; broadcast provenance is not proof of speaker birthplace.']
    lines += ['', '## Issues and overlap', '',
        f"- Validation metadata records: {findings['valid_records']}; shared speaker IDs: {len(findings['overlapping_speaker_ids'])}; shared source filenames: {len(findings['overlapping_source_filenames'])}.",
        '- Shared speaker IDs: ' + ', '.join('`' + x + '`' for x in findings['overlapping_speaker_ids']) + ('.' if findings['overlapping_speaker_ids'] else 'none.'),
        '- Affected test records retained: ' + '; '.join(r['sample_id'] + ' (' + str(r['speaker_id']) + ')' for r in rows if 'speaker_overlap_valid' in r['issues']) + ('.' if findings['overlapping_speaker_ids'] else 'none.'),
        '- Split-prefixed IDs differ by construction; overlap compares original filenames and speaker IDs instead. Observed overlap is not by itself evidence of leakage or shared audio. No training-overlap claim is made.',
        '- Duplicate-ID, source-filename/location and exact repeated-reference groups, overlapping IDs, speaker/region conflicts, and pending-audio errors are enumerated in the manifest audit. Every affected row retains its flags.',
        '- Empty/unreadable/nonfinite audio and empty raw/normalized references require individual review before scoring; do not silently remove them. Source errors and inference failures are distinct. No exclusion is proposed automatically. This audit does not certify transcript correctness or speaker identity; `clear` means no issue detected by these checks.',
        '- Audio source paths are also checked for repeats among test records; equal paths are a provenance flag, not proof of identical audio.',
        f"- Pending audio records: {audio.get('pending',0)}. Shard errors: `{findings['audio_shard_errors']}`.", '',
        '## Frozen scoring specification (before test predictions)', '',
        '- Use existing `lifemate/benchmark.py`, normalizer `' + NORMALIZER + '`: Unicode NFC, Python `str.lower()`, replace each Unicode punctuation-category P* character with a space, collapse all whitespace using split/join. Preserve Vietnamese diacritics, digits, symbols and letter distinctions. No accent stripping, number rewriting, filler removal, dialect correction or reference edits.',
        '- WER: Levenshtein edits on normalized whitespace-separated tokens, summed over the corpus divided by total reference tokens. Vietnamese whitespace units are often syllables; this is not linguistic word segmentation. CER: Levenshtein edits on normalized Unicode characters after removing spaces, summed over the corpus divided by total reference characters. Neither metric is mean per-clip error rate.',
        '- Report full-corpus micro WER/CER, each observed region, and an unweighted macro of the three named regional corpus rates with all components and denominators shown. Report province results descriptively; speaker coverage constrains interpretation. Do not balance, cap or create a challenge subset.',
        '- Require an exact one-to-one prediction/manifest ID join. Duplicates or absent predictions halt scoring for audit; explicitly encode unresolved inference failures rather than dropping rows. `error`/`timeout` predictions score as empty hypotheses, retaining full reference denominators; report failure counts/rate. An `ok` empty string also scores as empty, but remains a successful call with a recognition failure. Never pick the best repeated output or retry based on transcript quality.',
        '- Speaker-cluster uncertainty: freeze 2,000 bootstrap draws and seed 42; sample speakers with replacement within source/region and include all their clips. Recompute corpus ratios for each draw and use empirical 2.5/97.5 percentiles (index int(q*(B-1)) on sorted draws). Regional intervals use the same method within that region. Missing speaker IDs or a stratum with fewer than two independent speakers makes the corresponding interval unavailable, not zero-width; even larger sparse strata can yield unstable intervals. Report all speaker counts. For model comparisons later, use paired draws and B-minus-A corpus WER/CER differences, not independent resamples.',
        '- Missing region/province records stay in the aggregate and an explicit unknown subgroup, without inferring labels from speech/text. Unknown-region records do not enter the named three-region macro; disclose its reduced coverage. Missing speaker IDs retain descriptive scores but prevent complete-population cluster intervals; a labeled-speaker subset must be explicitly secondary. Speaker/region conflicts require resolution before stratified intervals. Zero-token/character references cannot use this scorer; freeze a reviewed handling decision first, without silently deleting them.',
        '- Current scorer enforces nonempty speaker/region/reference metadata and flat JSONL rows. This manifest is one JSON object: materialize common `source`/`split` on each scoring row, map `province_code` to the existing `province` grouping field, and use its unchanged reference. Missing-metadata handling above and single-model/regional intervals are specifications for the future inference/scoring iteration; the existing `paired_ci` implements paired whitespace-WER intervals only. Do not claim these missing features already run.',
        '- No semantic-slot metrics without annotations, no model-card-WER reproduction claim, and no test-driven normalization changes. Preserve the successful GIPFormer smoke model, mono 16 kHz FP32 preprocessing, FP16 weights with mixed computation and explicit greedy configuration unchanged.', '',
        '## Execution and reproduction', '',
        '- Dependencies are the existing numpy, soundfile, pyarrow, fsspec and aiohttp stack; versions and execution mode are recorded once in provenance. No model imports or calls.',
        '- Focused audit tests: `python -m unittest discover -s tests -p test_prepare_vimd_test.py -v` (run separately; manifest generation does not imply tests were executed).',
        '- From the repository root: `python scripts/prepare_vimd_test.py`. Default paths: `manifests/vimd_test.json` and `docs/implementation/VIMD_TEST_MANIFEST_AUDIT.md`.',
        '- `--metadata-only` enumerates every test record but labels audio inspection pending; it does not fabricate duration. Use only when actual audio inspection is unavailable. A partial audio audit exits nonzero after saving the complete metadata manifest/report; rerun the same preparation command after fixing the reported access problem.',
        '- Scope ends at manifest preparation/audit. No smoke rerun, full-test ASR, other models, challenge-set creation or training.']
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=Path('manifests/vimd_test.json'))
    parser.add_argument('--report', type=Path, default=Path('docs/implementation/VIMD_TEST_MANIFEST_AUDIT.md'))
    parser.add_argument('--metadata-only', action='store_true')
    args = parser.parse_args()
    from importlib.metadata import version
    shards = list_shards()
    if not all(shards.values()):
        raise ValueError('Pinned repository listing must contain both test and valid shards.')
    rows, valid, schemas = read_metadata(shards)
    audit = audit_metadata(rows, valid)
    audit['audio_shard_errors'] = [] if args.metadata_only else audit_audio(rows, shards)
    audit['duplicate_audio_source_path'] = flag_groups(rows,
        lambda r: (r['audio'] or {}).get('source_path'), 'duplicate_audio_source_path')
    for row in rows:
        row['issue_status'] = 'flagged' if row['issues'] else ('pending' if row['audio_check'] == 'pending' else 'clear')
    document = dict(provenance=dict(dataset=DATASET, revision=REVISION, split='test', source=DATASET,
        audio_base_url=BASE, license='CC-BY-NC-ND-4.0', prepared_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        python=platform.python_version(), packages={n:version(n) for n in ['numpy','soundfile','pyarrow','fsspec','aiohttp']},
        audio_inspection='metadata_only' if args.metadata_only else 'full_decode_original_float32_blocks',
        schema=schemas, no_exclusions=True), shards=shards, audit=audit, records=rows)
    for path, content in [(args.manifest,json.dumps(document,ensure_ascii=False,indent=2)+'\n'),
                          (args.report,report(document))]:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(content,encoding='utf-8')
    print('Saved',args.manifest,args.report,coverage(rows),flush=True)
    if not args.metadata_only and any(r['audio_check']=='pending' for r in rows):
        raise SystemExit('Audio audit incomplete; all metadata records retained. See report.')


if __name__ == '__main__':
    main()
