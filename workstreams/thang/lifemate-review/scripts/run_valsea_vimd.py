"""Sequential VALSEA/Glot ViMD runner. No model imports, automatic POST retries or scoring."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import http.client
import importlib.util
from importlib.metadata import version
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('valsea_audio_shared',ROOT/'scripts/gipformer15_smoke.py')
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
ENDPOINT = 'https://api.glotlabs.ai/v1/audio/transcriptions'
FIELDS = dict(model='glot-transcribe',language='vietnamese',enable_correction='false',
              enable_tags='false',diarize='false',response_format='verbose_json')
MAX_BYTES, MAX_SECONDS = 10_000_000, 3600  # conservative decimal interpretation of documented 10 MB
SMOKE_MANIFEST = ROOT/'artifacts/kaggle_smoke_launch/gip15_fp16_mixedcheck_20261101_04/inference/smoke_manifest.json'


def now(): return datetime.now(timezone.utc).isoformat()


def clean(value,key):
    """Retain useful responses but never secrets or echoed authorization fields."""
    if isinstance(value,dict):
        return {k:('[REDACTED]' if any(t in k.lower().replace('-','_') for t in ['authorization','api_key','apikey','access_token','secret'])
                   else clean(v,key)) for k,v in value.items()}
    if isinstance(value,list): return [clean(v,key) for v in value]
    if isinstance(value,str):
        if key: value=value.replace(key,'[REDACTED]')
        return re.sub(r'(?i)bearer\s+[^\s"<>]+','Bearer [REDACTED]',value)
    return value


def save(path,value):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temporary.replace(path)


def append(path,value):
    with path.open('a',encoding='utf-8') as stream:
        stream.write(json.dumps(value,ensure_ascii=False)+'\n')
        stream.flush()
        os.fsync(stream.fileno())


def read_log(path):
    data=path.read_bytes()
    if data and not data.endswith(b'\n'):
        raise ValueError('Unterminated/interrupted JSONL in '+path.name+'; bytes preserved. Review before resume; no requests sent.')
    records=[]
    for line in data.splitlines():
        try: record=json.loads(line.decode('utf-8'))
        except (UnicodeDecodeError,json.JSONDecodeError):
            raise ValueError('Malformed JSONL in '+path.name+'; evidence preserved, no repair.') from None
        if not isinstance(record,dict): raise ValueError('JSONL must contain objects.')
        records.append(record)
    return records


def load_manifest(mode):
    if mode=='full':
        manifest=json.loads((ROOT/'manifests/vimd_test.json').read_text(encoding='utf-8'))
        if len(manifest['records'])!=2026 or manifest['provenance']['revision']!=shared.PINS['dataset']:
            raise ValueError('Full mode requires all 2026 pinned test records.')
        return manifest
    records=json.loads(SMOKE_MANIFEST.read_text(encoding='utf-8'))
    expected=['ViMD_Dataset/valid/'+r['filename'] for r in shared.SMOKE]
    if [r['sample_id'] for r in records]!=expected: raise ValueError('Frozen six-sample smoke order differs.')
    return dict(provenance=dict(dataset='nguyendv02/ViMD_Dataset',revision=shared.PINS['dataset'],split='valid',
        audio_base_url='https://huggingface.co/datasets/nguyendv02/ViMD_Dataset/resolve/'+shared.PINS['dataset']+'/'),
        records=records)


def duration(row):
    return row['audio']['duration_seconds'] if 'audio' in row else row['source_duration']


def compatibility(manifest):
    incompatible=[]
    max_frames=0
    for row in manifest['records']:
        # scipy resample_poly output length is ceil(input_frames*16000/source_rate).
        frames=(math.ceil(row['audio']['frames']*16000/row['audio']['sample_rate']) if 'audio' in row
                else round(row['duration']*16000))
        max_frames=max(max_frames,frames)
        # libsndfile FLOAT WAV is 80-byte header locally; 4096 bytes is a
        # conservative allowance. Each actual upload is checked again.
        if frames/16000>MAX_SECONDS or 4096+frames*4>MAX_BYTES:
            incompatible.append(row['sample_id'])
    return dict(records=len(manifest['records']),upload='WAV IEEE FLOAT32 mono 16000 Hz; same FP32 waveform, no quantization',
                max_output_frames=max_frames,max_duration_seconds=max_frames/16000,
                max_bytes_conservative=4096+max_frames*4,max_allowed_bytes=MAX_BYTES,max_allowed_seconds=MAX_SECONDS,
                incompatible_ids=incompatible)


def encode_upload(payload):
    import soundfile as sf
    wave,info=shared.prepare_audio(payload)
    buffer=io.BytesIO()
    sf.write(buffer,wave,16000,format='WAV',subtype='FLOAT')
    data=buffer.getvalue()
    if len(data)>MAX_BYTES or len(wave)/16000>MAX_SECONDS: raise ValueError('Actual prepared upload exceeds documented limit.')
    return data,info


def source_audio(row,manifest,cache_dir=None,source_audio_dir=None,group_cache=None):
    import fsspec
    import pyarrow.parquet as pq
    import soundfile as sf
    cached=Path(source_audio_dir)/row['filename'] if source_audio_dir else None
    if cached and cached.exists():
        payload=cached.read_bytes()
    else:
        locator=(row['shard'],row['row_group'])
        table=group_cache.get('table') if group_cache and group_cache.get('locator')==locator else None
        if table is None:
            shard=Path(cache_dir)/Path(row['shard']).name if cache_dir else None
            if shard and shard.exists():
                sizes={s['path']:s['bytes'] for s in manifest.get('shards',{}).get('test',[])}
                if row['shard'] in sizes and shard.stat().st_size!=sizes[row['shard']]: raise ValueError('Cached shard size mismatch.')
                handle=shard.open('rb')
            else:
                handle=fsspec.open(manifest['provenance']['audio_base_url']+row['shard'],'rb',block_size=65536,cache_type='none').open()
            with handle:
                parquet=pq.ParquetFile(handle,pre_buffer=False)
                table=parquet.read_row_group(row['row_group'],columns=['filename','audio'])
            if group_cache is not None:
                group_cache.clear()  # Retain only the current encoded row group, not decoded corpus audio.
                group_cache.update(locator=locator,table=table)
        source=table.slice(row['row_in_group'],1).to_pylist()[0]
        if source['filename']!=row['filename']: raise ValueError('Pinned source ID/location mismatch.')
        payload=source['audio']['bytes']
    with sf.SoundFile(io.BytesIO(payload)) as audio:
        if abs(audio.frames/audio.samplerate-duration(row))>1/audio.samplerate: raise ValueError('Source audio duration mismatch.')
        if 'audio' in row:
            expected=row['audio']
            if len(payload)!=expected['encoded_bytes'] or (audio.frames,audio.samplerate,audio.channels)!=(expected['frames'],expected['sample_rate'],expected['channels']):
                raise ValueError('Source audio/header mismatch.')
        elif (audio.samplerate,audio.channels)!=(row['source_sample_rate'],row['source_channels']):
            raise ValueError('Smoke source format mismatch.')
    return payload


def multipart(wav):
    boundary='vimd_'+uuid.uuid4().hex
    chunks=[]
    for name,value in FIELDS.items():
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    chunks += [f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode(),
               wav,f'\r\n--{boundary}--\r\n'.encode()]
    return b''.join(chunks),'multipart/form-data; boundary='+boundary


def post_audio(wav,key,connect_timeout,read_timeout):
    """Fixed HTTPS host; no redirect forwarding, urllib proxy behavior or POST retry."""
    body,content_type=multipart(wav)
    connection=http.client.HTTPSConnection('api.glotlabs.ai',timeout=connect_timeout)
    try:
        connection.connect()
        connection.sock.settimeout(read_timeout)
        connection.request('POST','/v1/audio/transcriptions',body=body,
                           headers={'Authorization':'Bearer '+key,'Content-Type':content_type,'Accept':'application/json'})
        response=connection.getresponse()
        # Only allowlisted useful response headers; never save request objects/headers.
        headers={k.lower():v for k,v in response.getheaders() if k.lower() in
                 {'x-request-id','request-id','retry-after','x-model-version','x-credits-used','x-credits-remaining','x-credits-multiplier'}}
        return response.status,headers,response.read().decode('utf-8',errors='replace')
    finally:
        connection.close()


def retry_after(value,clock=time.time):
    if not value: return None
    try: return clock()+max(0,float(value))
    except ValueError:
        try: return max(clock(),parsedate_to_datetime(value).timestamp())
        except (TypeError,ValueError,OverflowError): return None


def account():
    if os.environ.get('VALSEA_ACCOUNT_ENDPOINT')!=ENDPOINT or os.environ.get('VALSEA_ACCOUNT_MODEL')!=FIELDS['model']:
        raise ValueError('Confirm account configuration via VALSEA_ACCOUNT_ENDPOINT and VALSEA_ACCOUNT_MODEL matching the documented contract. No credential sent.')
    try: rpm=float(os.environ.get('VALSEA_REQUESTS_PER_MINUTE',''))
    except ValueError: rpm=0
    if not math.isfinite(rpm) or rpm<=0: raise ValueError('Set VALSEA_REQUESTS_PER_MINUTE from the account quota; it is not documented numerically in the inspected API pages.')
    key=os.environ.get('VALSEA_API_KEY')
    if not key: raise ValueError('VALSEA_API_KEY is unavailable; no request sent.')
    return key,rpm


def configuration(mode,rpm):
    return dict(mode=mode,endpoint=ENDPOINT,fields=FIELDS,upload='FLOAT32 WAV mono 16000 Hz',
                connect_timeout_seconds=15,read_timeout_seconds=120,requests_per_minute=rpm,
                automatic_retries=False,idempotency='not documented; not used',docs_checked='2026-11-01',
                provider_revision='alias only; immutable remote revision not exposed in documentation',
                packages={name:version(name) for name in ['numpy','scipy','soundfile','pyarrow','fsspec','aiohttp']},
                dataset_revision=shared.PINS['dataset'],runner_source=Path(__file__).read_text(encoding='utf-8'),
                preprocessing_source=__import__('inspect').getsource(shared.prepare_audio))


def state(manifest,predictions,attempts):
    ids={r['sample_id'] for r in manifest['records']}
    if len(ids)!=len(manifest['records']): raise ValueError('Duplicate manifest IDs.')
    completed={}
    for record in predictions:
        key=record.get('sample_id')
        if key not in ids or key in completed or record.get('status')!='ok' or not isinstance(record.get('text'),str):
            raise ValueError('Duplicate/unknown/malformed completed prediction.')
        completed[key]=record
    starts,ends,resolved={},{},set()
    for event in attempts:
        key=event.get('sample_id')
        if key not in ids: raise ValueError('Unknown attempt sample ID.')
        number=event.get('attempt')
        if event.get('event')=='source_error':
            continue  # No POST was started; not a remote/billing attempt.
        if event.get('event')=='started':
            if number in starts: raise ValueError('Duplicate attempt number.')
            starts[number]=event
        elif event.get('event') in {'ok','error','unresolved'}:
            if number not in starts or starts[number]['sample_id']!=key or number in ends: raise ValueError('Malformed attempt completion.')
            ends[number]=event
        elif event.get('event')=='retry_authorized':
            if number not in starts or starts[number]['sample_id']!=key or number in resolved: raise ValueError('Invalid reconciliation event.')
            resolved.add(number)
        else: raise ValueError('Unknown attempt event.')
    successful={}
    blocked={}
    for number,start in starts.items():
        end=ends.get(number)
        key=start['sample_id']
        if end and end['event']=='ok':
            if key in successful or number in resolved: raise ValueError('Multiple successful attempts; no best-of-N selection permitted.')
            prediction=end.get('prediction')
            if not prediction or prediction.get('sample_id')!=key or not isinstance(prediction.get('text'),str): raise ValueError('Malformed successful attempt evidence.')
            successful[key]=prediction
        elif number not in resolved:
            blocked[key]=(number,end or start)
    if any(key not in successful or successful[key]!=record for key,record in completed.items()):
        raise ValueError('Prediction does not match its successful attempt evidence.')
    if completed.keys() & blocked.keys(): raise ValueError('Completed ID also has unresolved failure; review required.')
    return completed,successful,blocked,starts,ends


def completion(manifest,predictions,attempts):
    done,success,blocked,starts,ends=state(manifest,predictions,attempts)
    failed=sum(e['event']=='error' for e in ends.values())
    authorized={e['attempt'] for e in attempts if e['event']=='retry_authorized'}
    unresolved=sum((number not in ends or ends[number]['event']=='unresolved') and number not in authorized for number in starts)
    historical_unknown=sum(number not in ends or ends[number]['event']=='unresolved' for number in starts)
    return dict(expected=len(manifest['records']),attempted_samples=len({e['sample_id'] for e in starts.values()}),
                request_attempts=len(starts),successful=len(done),failed_attempts=failed,unresolved_attempts=unresolved,
                historical_unknown_remote_outcomes=historical_unknown,
                source_error_events=sum(e['event']=='source_error' for e in attempts),
                blocked_sample_ids=sorted(blocked),remaining=len(manifest['records'])-len(done),
                empty_successful_transcripts=[k for k,r in done.items() if r['text']==''],
                coverage_complete=len(done)==len(manifest['records']),review_status='pending_human_review',
                exactly_once_remote_processing='not guaranteed')


def prepare_run(output,run_id,manifest,config,resume):
    if not re.fullmatch(r'[A-Za-z0-9_-]+',run_id): raise ValueError('Invalid RUN_ID.')
    if not resume:
        output.mkdir(parents=True)  # exclusive; earlier attempts never overwritten
        save(output/'manifest.json',manifest)
        save(output/'configuration.json',config)
        save(output/'run_metadata.json',dict(run_id=run_id,sessions=[],model_alias=FIELDS['model']))
        for name in ['predictions.jsonl','attempts.jsonl']: (output/name).touch(exist_ok=False)
    if json.loads((output/'manifest.json').read_text(encoding='utf-8'))!=manifest: raise ValueError('Manifest mismatch on resume.')
    if json.loads((output/'configuration.json').read_text(encoding='utf-8'))!=config: raise ValueError('Configuration/code mismatch on resume.')
    if json.loads((output/'run_metadata.json').read_text(encoding='utf-8'))['run_id']!=run_id: raise ValueError('RUN_ID mismatch.')
    predictions,attempts=read_log(output/'predictions.jsonl'),read_log(output/'attempts.jsonl')
    state(manifest,predictions,attempts)
    return predictions,attempts


@contextmanager
def single_writer(output_root,run_id):
    locks=output_root/'.locks'
    locks.mkdir(parents=True,exist_ok=True)
    with (locks/(run_id+'.lock')).open('a+b') as stream:
        if os.name=='nt':
            import msvcrt
            if stream.seek(0,2)==0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            try: msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            except OSError: raise ValueError('RUN_ID already has an active writer; no second runner.') from None
            try: yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            try: fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise ValueError('RUN_ID already has an active writer.') from None
            yield


def run_requests(output,manifest,predictions,attempts,key,rpm,get_audio,transport=post_audio,
                 retry_ids=(),retry_note='',sleep=time.sleep,clock=time.time,preserve_manifest_order=False):
    """Sequential durable intent/result log; interrupted remote work remains blocked."""
    output=Path(output)
    def event(record):
        record=clean(record,key)
        append(output/'attempts.jsonl',record)
        attempts.append(record)
        return record
    def summarize(): save(output/'completion_summary.json',completion(manifest,predictions,attempts))
    done,success,blocked,starts,ends=state(manifest,predictions,attempts)
    # If the server success was durably logged before a local prediction write
    # interrupted, restore that exact text without making another API call.
    for sample_id,record in success.items():
        if sample_id not in done:
            append(output/'predictions.jsonl',record)
            predictions.append(record)
    done,success,blocked,starts,ends=state(manifest,predictions,attempts)
    if len(retry_ids)!=len(set(retry_ids)) or not set(retry_ids)<=blocked.keys():
        raise ValueError('Explicit retry IDs must be unique existing failed/unresolved IDs.')
    if retry_ids and not retry_note.strip(): raise ValueError('Explicit retry requires --retry-note with the operator reconciliation decision.')
    for sample_id in retry_ids:
        number,previous=blocked[sample_id]
        event(dict(event='retry_authorized',sample_id=sample_id,attempt=number,timestamp=now(),note=retry_note))
    done,success,blocked,starts,ends=state(manifest,predictions,attempts)
    summarize()
    if blocked: raise ValueError('Failed/unresolved attempts remain blocked. Reconcile and explicitly authorize retry; no automatic resubmission.')
    next_allowed=0.
    for e in attempts:
        next_allowed=max(next_allowed,e.get('not_before',0.))
        if e['event']=='started': next_allowed=max(next_allowed,e.get('unix_time',0.)+60/rpm)
    try:
        # Fixed smoke order; full order is pinned shard/row-group/source row order.
        rows=manifest['records']
        if not preserve_manifest_order and manifest['provenance']['split']=='test': rows=sorted(rows,key=lambda r:(r['shard'],r['row_group'],r['row_in_group']))
        for row in rows:
            sample_id=row['sample_id']
            if sample_id in done: continue
            # Source errors happen before any remote intent; preserve stage without
            # presenting them as model output or claiming a billed API attempt.
            try:
                wav,info=encode_upload(get_audio(row))
            except Exception as error:
                event(dict(event='source_error',sample_id=sample_id,timestamp=now(),
                           error_type=type(error).__name__,message='Source access/preparation failed before POST.'))
                raise RuntimeError('Source access/preparation failed before POST.') from None
            delay=max(0,next_allowed-clock())
            if delay: sleep(delay)
            number=max(starts,default=0)+1
            intent=event(dict(event='started',sample_id=sample_id,attempt=number,timestamp=now(),unix_time=clock(),
                         source_duration_seconds=duration(row),upload_duration_seconds=info['duration'],upload_bytes=len(wav)))
            starts[number]=intent
            started=time.perf_counter()
            try:
                status,headers,body=transport(wav,key,15,120)
            except BaseException as error:
                # Do not stringify exception/request objects: they may contain keys.
                event(dict(event='unresolved',sample_id=sample_id,attempt=number,timestamp=now(),
                           elapsed_seconds=time.perf_counter()-started,error_type=type(error).__name__,
                           message='Transport/interruption outcome unknown; provider may have processed/billed it.'))
                summarize()
                raise RuntimeError('Remote outcome unresolved; request not retried.') from None
            response_received_time=clock()
            elapsed=time.perf_counter()-started
            headers=clean(headers,key)
            try: response=json.loads(body)
            except (ValueError,TypeError): response=None
            evidence=dict(sample_id=sample_id,attempt=number,timestamp=now(),http_status=status,request_seconds=elapsed,
                          response_headers=headers,response=clean(response,key) if response is not None else clean(body,key))
            request_id=(headers.get('x-request-id') or headers.get('request-id') or
                        (response.get('request_id') if isinstance(response,dict) else None))
            if (200<=status<300 and isinstance(response,dict) and isinstance(response.get('text'),str)
                    and clean(response['text'],key)==response['text']):
                record=clean(dict(sample_id=sample_id,status='ok',text=response['text'],error=None,
                    source_duration_seconds=duration(row),duration_seconds=duration(row),request_seconds=elapsed,
                    request_timing_scope='client upload + remote service + response transfer; not provider compute latency',
                    timestamp=now(),request_id=request_id,provider_version=headers.get('x-model-version') or response.get('model_version'),
                    returned_model=response.get('model')),key)
                next_allowed=max(response_received_time+60/rpm,
                                 retry_after(headers.get('retry-after'),lambda:response_received_time) or 0.)
                event(dict(event='ok',prediction=record,not_before=next_allowed,**evidence))
                append(output/'predictions.jsonl',record)
                predictions.append(record)
                done[sample_id]=record
                summarize()
                print(sample_id,'ok',flush=True)
            else:
                kind=('response_schema' if 200<=status<300 else 'authentication' if status in [401,403]
                      else 'credit' if status==402 else 'rate_limit' if status==429 else 'configuration' if 300<=status<500 else 'server_outcome_unknown')
                event(dict(event='unresolved' if status>=500 else 'error',error_type=kind,
                           message='Stopped; inspect sanitized response evidence before explicit reconciliation/retry.',
                           not_before=retry_after(headers.get('retry-after'),clock) or 0.,**evidence))
                summarize()
                raise RuntimeError('API stopped: '+kind+'; no automatic retry.') from None
    finally:
        summarize()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['smoke','full'],required=True)
    parser.add_argument('--run-id')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--preflight-only',action='store_true')
    parser.add_argument('--output-root',type=Path,default=ROOT/'artifacts/valsea')
    parser.add_argument('--cache-dir',type=Path)
    parser.add_argument('--source-audio-dir',type=Path)
    parser.add_argument('--retry-sample-id',action='append',default=[])
    parser.add_argument('--retry-note',default='')
    args=parser.parse_args()
    manifest=load_manifest(args.mode)
    check=compatibility(manifest)
    if args.preflight_only:
        print(json.dumps(check,indent=2))
        return
    if check['incompatible_ids']: raise ValueError('Audio limit incompatibility; review before execution.')
    key,rpm=account()  # No destination guessed and no key sent before confirmation.
    if not args.run_id: raise ValueError('Explicit --run-id required.')
    if not re.fullmatch(r'[A-Za-z0-9_-]+',args.run_id): raise ValueError('Invalid RUN_ID.')
    with single_writer(args.output_root,args.run_id):
        execute(args,manifest,check,key,rpm)


def execute(args,manifest,check,key,rpm,config=None,get_audio=None,preserve_manifest_order=False):
    output=args.output_root.resolve()/args.run_id
    predictions,attempts=prepare_run(output,args.run_id,manifest,configuration(args.mode,rpm) if config is None else config,args.resume)
    metadata=json.loads((output/'run_metadata.json').read_text(encoding='utf-8'))
    metadata['audio_compatibility']=check
    session=dict(started_utc=now(),mode=args.mode,resume=args.resume,python=sys.version,
                 packages={name:version(name) for name in ['numpy','scipy','soundfile','pyarrow','fsspec','aiohttp']},
                 account_endpoint_confirmed=ENDPOINT,account_model_confirmed=FIELDS['model'])
    metadata['sessions'].append(session)
    save(output/'run_metadata.json',metadata)
    group_cache={}
    try:
        run_requests(output,manifest,predictions,attempts,key,rpm,
                     get_audio if get_audio is not None else lambda row:source_audio(row,manifest,args.cache_dir,args.source_audio_dir,group_cache),
                     retry_ids=args.retry_sample_id,retry_note=args.retry_note,preserve_manifest_order=preserve_manifest_order)
        session['status']='completed'
    except BaseException as error:
        session.update(status='stopped',error_type=type(error).__name__,message='Stopped; inspect attempt log and completion summary. No automatic retry.')
        # Never print arbitrary exception content or chained request objects.
        print('Stopped safely:',type(error).__name__,'Review local attempt evidence; no automatic retry.',file=sys.stderr)
    finally:
        session['ended_utc']=now()
        save(output/'run_metadata.json',metadata)
    if session['status']!='completed': raise SystemExit(1)


if __name__=='__main__':
    try: main()
    except Exception as error:
        # Configuration/source exceptions are also not printed as objects.
        print('Runner stopped before completion:',type(error).__name__,
              'Check account environment, run identity and local evidence; no implicit retry.',file=sys.stderr)
        raise SystemExit(1) from None
