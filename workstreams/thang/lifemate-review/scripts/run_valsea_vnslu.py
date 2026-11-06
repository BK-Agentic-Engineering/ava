"""VN-SLU adapter for the sequential VALSEA runner. Offline preparation or explicit manual execution."""
import argparse
import binascii
import io
import json
from pathlib import Path
import random
import re
import sys

import prepare_vnslu_test as source
import run_valsea_vimd as api

ROOT=Path(__file__).resolve().parents[1]
SMOKE=ROOT/'manifests/vnslu_valsea_dev_smoke.json'
CACHE=ROOT/'artifacts/vnslu'
PREPARATION=ROOT/'artifacts/valsea_vnslu_preparation'
SELECTION='Sort official dev IDs; one random.Random(42).sample(ordered_ids, 6); preserve returned order.'


def select_smoke(dev,test):
    by_id={r['id']:r for r in dev}
    if len(by_id)!=len(dev) or len({r['file'] for r in dev})!=len(dev):
        raise ValueError('Duplicate dev ID/source filename.')
    selected=[by_id[i] for i in random.Random(42).sample(sorted(by_id),6)]
    if ({r['id'] for r in selected}&{r['id'] for r in test} or
            {r['file'] for r in selected}&{r['file'] for r in test}):
        raise ValueError('Selected dev IDs/source filenames overlap test.')
    return selected


def validate_records(manifest,annotations,split):
    rows=manifest['records']
    if len(rows)!=len(annotations) or len({r['sample_id'] for r in rows})!=len(rows):
        raise ValueError('Missing/duplicate manifest records.')
    if len({r['filename'] for r in rows})!=len(rows):raise ValueError('Duplicate audio references.')
    for row,raw in zip(rows,annotations):
        if (row['sample_id']!='VN-SLU/'+split+'/'+raw['id'] or row['official_id']!=raw['id'] or
                row['split']!=split or row['raw_annotation']!=raw):raise ValueError('Annotation identity/order differs.')
        for target,field in [('filename','file'),('reference','sentence'),('intent','intent'),
                             ('entities','entities'),('sentence_annotation','sentence_annotation')]:
            if row[target]!=raw[field]:raise ValueError('Official text/label mapping differs.')
        if (row['speaker_id']!=raw.get('speakerID',raw.get('speaker_id')) or row['region']!=raw.get('region')):
            raise ValueError('Optional metadata differs; do not infer speakers/regions.')
        if row['status']!='valid' or any(i!='repeated_exact_reference' for i in row['issues']):
            raise ValueError('Flagged incompatible input retained; review before requests.')
        name=row['filename']
        if Path(name).name!=name or '/' in name or '\\' in name:raise ValueError('Unsafe audio filename.')
        if row['audio_locator']['member']!='data/audio/'+name:raise ValueError('Archive member identity differs.')


def load_manifest(mode):
    full=json.loads((ROOT/'manifests/vnslu_test.json').read_text(encoding='utf-8'))
    test=source.annotations(CACHE/'source/test.jsonl')
    if len(full['records'])!=2401:raise ValueError('Full official test requires all 2401 records.')
    if full['provenance']!=json.loads((CACHE/'source/release.json').read_text(encoding='utf-8')):
        raise ValueError('Canonical manifest and preserved release provenance differ.')
    validate_records(full,test,'test')
    if mode=='full':return full  # Exact canonical object, including flags/null optional metadata.
    selected=select_smoke(source.annotations(CACHE/'source/dev.jsonl'),test)
    smoke=json.loads(SMOKE.read_text(encoding='utf-8'))
    validate_records(smoke,selected,'dev')
    if smoke['selection']!=dict(rule=SELECTION,seed=42,engineering_only=True):raise ValueError('Smoke selection changed.')
    if smoke['provenance']!=full['provenance']:raise ValueError('Source snapshot differs.')
    return smoke


def prepare_smoke():
    if SMOKE.exists():return load_manifest('smoke')  # Never replace conflicting frozen inputs.
    full=load_manifest('full')
    dev=source.annotations(CACHE/'source/dev.jsonl');test=source.annotations(CACHE/'source/test.jsonl')
    selected=select_smoke(dev,test)
    lines={r['id']:i for i,r in enumerate(dev,1)}
    rows=[source.record(r,lines[r['id']]) for r in selected]
    for row in rows:
        row.update(sample_id='VN-SLU/dev/'+row['official_id'],split='dev')
    inventory=json.loads((CACHE/'source/archive_inventory.json').read_text(encoding='utf-8'))
    by_name,errors=source.download_audio(CACHE,rows,inventory,full['provenance'])
    if errors:raise ValueError('Dev retrieval failures retained: '+json.dumps(errors))
    for row in rows:
        entries=by_name[row['filename']]
        if len(entries)!=1:raise ValueError('Ambiguous/missing dev archive member.')
        entry=entries[0];path=CACHE/'audio'/row['filename']
        payload=path.read_bytes()
        if len(payload)!=entry['bytes'] or f'{binascii.crc32(payload)&0xffffffff:08x}'!=entry['crc32']:
            raise ValueError('Dev original ZIP CRC/size differs; cache preserved.')
        row['audio'],issues=source.inspect_audio(dict(bytes=payload,path=entry['filename']))
        row['issues']+=issues
        row['audio_locator']=dict(archive='data.zip',member=entry['filename'],zip_crc32=entry['crc32'],path=path.relative_to(ROOT).as_posix())
        row['status']='invalid' if row['issues'] else 'valid'
    doc=dict(provenance=full['provenance'],split='dev',reference_field='sentence',
             selection=dict(rule=SELECTION,seed=42,engineering_only=True),records=rows)
    validate_records(doc,selected,'dev')
    with SMOKE.open('x',encoding='utf-8') as stream:stream.write(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
    return doc


def source_audio(row,source_audio_dir=None):
    import soundfile as sf
    path=Path(source_audio_dir)/row['filename'] if source_audio_dir else ROOT/row['audio_locator']['path']
    payload=path.read_bytes();expected=row['audio']
    if (len(payload)!=expected['encoded_bytes'] or
            f'{binascii.crc32(payload)&0xffffffff:08x}'!=row['audio_locator']['zip_crc32']):
        raise ValueError('Source ZIP CRC/size differs.')
    info=sf.info(io.BytesIO(payload))
    if (info.frames,info.samplerate,info.channels,info.format,info.subtype)!=(
            expected['frames'],expected['sample_rate'],expected['channels'],expected['format'],expected['subtype']):
        raise ValueError('Source audio metadata differs.')
    return payload


def preflight(manifest,source_audio_dir=None):
    import numpy as np
    import soundfile as sf
    check=api.compatibility(manifest)
    check.update(checked_originals=0,lossless_float_uploads=0,max_actual_upload_bytes=0,failures=[])
    for row in manifest['records']:
        stage='original_identity'
        try:
            payload=source_audio(row,source_audio_dir)
            check['checked_originals']+=1
            stage='shared_preprocessing_and_encoding'
            expected,_=api.shared.prepare_audio(payload)
            encoded,info=api.encode_upload(payload)
            stage='lossless_round_trip'
            decoded,rate=sf.read(io.BytesIO(encoded),dtype='float32')
            if (rate!=16000 or decoded.ndim!=1 or sf.info(io.BytesIO(encoded)).subtype!='FLOAT' or
                    not np.array_equal(decoded,expected) or info['duration']!=len(decoded)/rate):
                raise ValueError('FLOAT32 upload round-trip differs.')
            check['lossless_float_uploads']+=1
            check['max_actual_upload_bytes']=max(check['max_actual_upload_bytes'],len(encoded))
        except Exception as error:
            check['failures'].append(dict(sample_id=row['sample_id'],stage=stage,error_type=type(error).__name__))
    check.update(packages={name:api.version(name) for name in ['numpy','scipy','soundfile','pyarrow','fsspec','aiohttp']},
                 python=sys.version,libsndfile=sf.__libsndfile_version__,docs_checked='2026-11-02',
                 limits_source='https://valsea.ai/docs/api/transcribe',
                 preprocessing= 'gipformer15_smoke.prepare_audio; environment-specific, no cross-environment bitwise claim',
                 source_duration_seconds=sum(api.duration(r) for r in manifest['records']),
                 live_requests_sent=0)
    return check


def configuration(mode,rpm,manifest):
    config=api.configuration(mode,rpm)
    config.update(dataset_revision=None,dataset_provenance=manifest['provenance'],
                  dataset='VN-SLU',split=manifest['split'],docs_checked='2026-11-02',
                  request_order='frozen manifest order',scoring_field='text',
                  adapter_source=Path(__file__).read_text(encoding='utf-8'))
    return config


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['smoke','full'],required=True)
    parser.add_argument('--run-id')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--preflight-only',action='store_true')
    parser.add_argument('--prepare-smoke',action='store_true')
    parser.add_argument('--source-audio-dir',type=Path)
    parser.add_argument('--output-root',type=Path,default=ROOT/'artifacts/valsea_vnslu')
    parser.add_argument('--retry-sample-id',action='append',default=[])
    parser.add_argument('--retry-note',default='')
    args=parser.parse_args()
    if args.prepare_smoke and (args.mode!='smoke' or not args.preflight_only):
        raise ValueError('--prepare-smoke requires --mode smoke --preflight-only.')
    manifest=prepare_smoke() if args.prepare_smoke else load_manifest(args.mode)
    if args.preflight_only:
        check=preflight(manifest,args.source_audio_dir)
        PREPARATION.mkdir(parents=True,exist_ok=True)
        api.save(PREPARATION/(args.mode+'_audio_compatibility.json'),check)
        print(json.dumps(check,indent=2))
        if check['incompatible_ids'] or check['failures']:raise SystemExit(1)
        return
    check=api.compatibility(manifest)
    if check['incompatible_ids']:raise ValueError('Upload limit incompatibility; review before execution.')
    if not args.run_id or not re.fullmatch(r'[A-Za-z0-9_-]+',args.run_id):raise ValueError('Explicit safe RUN_ID required.')
    key,rpm=api.account()  # Same account-confirmation gate; only process environment.
    with api.single_writer(args.output_root,args.run_id):
        api.execute(args,manifest,check,key,rpm,config=configuration(args.mode,rpm,manifest),
                    get_audio=lambda row:source_audio(row,args.source_audio_dir),preserve_manifest_order=True)


if __name__=='__main__':
    try:main()
    except Exception as error:
        print('VN-SLU runner stopped:',type(error).__name__,
              'Review local input/attempt evidence; no implicit retry.',file=sys.stderr)
        raise SystemExit(1) from None
