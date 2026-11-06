"""Prepare author-assigned VN-SLU test records and original WAVs. No inference or semantic scoring."""
import argparse
import binascii
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import struct
import sys
import zipfile
import zlib

from prepare_vimd_test import inspect_audio,flag_groups,normalize,NORMALIZER

ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'artifacts/vnslu'
REVISION='aad93e560f8ec4ab979e76d5dfe36528160b797f'
REPOSITORY='https://github.com/tuyen-tran1/VN-SLU'
FOLDER='https://drive.google.com/drive/folders/1BDKK8vg-tByTY2EUWi6aYDjqG1NIFG8H'
FILES={'data.zip':'1Kx2AGykuyqsWgKMaJF_fXPFxfx-PncoB','test.jsonl':'1SU0j995v8Ue_0BRYSac3wMdryctlSrU-',
       'dev.jsonl':'1nsr7S050mMZvIk5ZL1K41IQh0fdzHyC7','train.jsonl':'1XHQPddYzcNa8iSsoRI4AdWnCYe5jPbjP'}


def url(name):return 'https://drive.usercontent.google.com/download?id='+FILES[name]+'&export=download'


class DownloadForm(HTMLParser):
    def __init__(self):super().__init__();self.action=None;self.fields={}
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='form':self.action=a.get('action')
        if tag=='input' and a.get('name'):self.fields[a['name']]=a.get('value','')


def archive_url():
    import requests
    response=requests.get(url('data.zip'),timeout=45);response.raise_for_status()
    form=DownloadForm();form.feed(response.text)
    if form.action!='https://drive.usercontent.google.com/download':raise ValueError('Unexpected public download form.')
    return requests.Request('GET',form.action,params=form.fields).prepare().url


def range_bytes(address,start,end):
    import requests
    with requests.get(address,headers={'Range':f'bytes={start}-{end-1}'},timeout=(15,90),stream=True) as response:
        response.raise_for_status()
        if response.status_code!=206 or not response.headers.get('Content-Range','').startswith(f'bytes {start}-{end-1}/'):
            raise ValueError('Source did not return the exact requested archive range.')
        data=response.content
        if len(data)!=end-start:raise ValueError('Incomplete archive range.')
        return data


def acquire_metadata(cache):
    import requests
    import fsspec
    source=cache/'source';source.mkdir(parents=True,exist_ok=True)
    for name in ['train.jsonl','dev.jsonl','test.jsonl','author_README.md']:
        path=source/name
        if path.exists():continue
        address=url(name) if name!='author_README.md' else f'https://raw.githubusercontent.com/tuyen-tran1/VN-SLU/{REVISION}/README.md'
        response=requests.get(address,timeout=60);response.raise_for_status()
        if 'text/html' in response.headers.get('Content-Type',''):raise ValueError('Download returned HTML: '+name)
        with path.open('xb') as stream:stream.write(response.content)
    release=source/'release.json'
    if release.exists():return json.loads(release.read_text(encoding='utf-8'))
    address=archive_url()
    with fsspec.open(address,'rb',block_size=1024*1024,cache_type='blockcache',cache_options={'maxblocks':4}).open() as handle:
        size=handle.size
        with zipfile.ZipFile(handle) as archive:
            # One source-directory fingerprint identifies the mutable archive inventory.
            # It is explicitly not a hash of all archive/audio bytes.
            handle.seek(archive.start_dir);directory=handle.read(size-archive.start_dir)
            inventory=[dict(filename=i.filename,bytes=i.file_size,compressed_bytes=i.compress_size,
                            crc32=f'{i.CRC:08x}',header_offset=i.header_offset) for i in archive.infolist()]
            data=dict(dataset='VN-SLU',author_repository=REPOSITORY,repository_revision=REVISION,
                download_folder=FOLDER,retrieved_utc=datetime.now(timezone.utc).isoformat(),
                annotation_sources={name:dict(drive_id=FILES[name],url=url(name),bytes=(source/name).stat().st_size) for name in ['train.jsonl','dev.jsonl','test.jsonl']},
                archive=dict(name='data.zip',drive_id=FILES['data.zip'],url=url('data.zip'),bytes=size,
                    central_directory_offset=archive.start_dir,central_directory_sha256=hashlib.sha256(directory).hexdigest(),
                    revision=None,identity_note='Mutable author-linked Drive download; directory fingerprint and supplied ZIP CRCs, not a full archive checksum.',
                    acquisition='HTTP ranges for test member intervals; no train/dev WAV export'),
                license='not found',split_assignment='Author-linked test.jsonl; no reconstruction from IDs or paper sampling algorithm')
    (source/'archive_inventory.json').write_text(json.dumps(inventory,indent=2)+'\n',encoding='utf-8')
    release.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    return data


def annotations(path):
    rows=[]
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        try:rows.append(json.loads(line))
        except ValueError:rows.append(dict(unparsed_line=line))
    return rows


def record(raw,line):
    issues=[]
    source=raw if isinstance(raw,dict) else {}
    for field in ['id','sentence','intent','sentence_annotation','file']:
        if not isinstance(source.get(field),str) or not source[field].strip():issues.append('invalid_'+field)
    entities=source.get('entities')
    if not isinstance(entities,list) or any(not isinstance(e,dict) or any(not isinstance(e.get(k),str) or not e[k].strip() for k in ['type','filler']) for e in entities):
        issues.append('invalid_entities')
    filename=source.get('file')
    if isinstance(filename,str) and (Path(filename).name!=filename or '\\' in filename or '/' in filename or not filename.lower().endswith('.wav')):issues.append('unsafe_audio_filename')
    reference=source.get('sentence')
    if isinstance(reference,str) and not normalize(reference):issues.append('empty_normalized_reference')
    official_id=source.get('id')
    return dict(sample_id='VN-SLU/test/'+(official_id if isinstance(official_id,str) and official_id else '@line'+str(line)),
        official_id=official_id,split='test',annotation_line=line,filename=filename,reference=reference,
        intent=source.get('intent'),sentence_annotation=source.get('sentence_annotation'),entities=entities,
        speaker_id=source.get('speakerID',source.get('speaker_id')),region=source.get('region'),
        raw_annotation=raw,audio=None,issues=issues)


def extract_member(blob,start,entry):
    offset=entry['header_offset']-start
    header=struct.unpack('<4s5H3I2H',blob[offset:offset+30])
    signature,version,flags,compression,mtime,mdate,crc,compressed,size,name_length,extra_length=header
    if signature!=b'PK\x03\x04' or flags&1:raise ValueError('Invalid/encrypted ZIP local header.')
    name=blob[offset+30:offset+30+name_length].decode('utf-8' if flags&0x800 else 'cp437')
    if name!=entry['filename']:raise ValueError('ZIP source identity differs.')
    data_start=offset+30+name_length+extra_length
    data=blob[data_start:data_start+entry['compressed_bytes']]
    if compression==8:data=zlib.decompress(data,-15)
    elif compression!=0:raise ValueError('Unsupported source ZIP compression.')
    if len(data)!=entry['bytes'] or f'{binascii.crc32(data)&0xffffffff:08x}'!=entry['crc32']:raise ValueError('Original member size/ZIP CRC mismatch.')
    return data


def download_audio(cache,rows,inventory,release):
    by_name=defaultdict(list)
    for item in inventory:
        if item['filename'].endswith('.wav'):by_name[Path(item['filename']).name].append(item)
    missing=set();errors={};audio=cache/'audio';audio.mkdir(parents=True,exist_ok=True)
    for row in rows:
        name=row['filename']
        if not isinstance(name,str) or any(i in row['issues'] for i in ['invalid_file','unsafe_audio_filename']):continue
        entries=by_name[name]
        if len(entries)!=1:errors[name]='missing_audio_member' if not entries else 'ambiguous_audio_member';continue
        if not (audio/name).exists():missing.add(entries[0]['filename'])
    if not missing:return by_name,errors
    ordered=sorted(inventory,key=lambda r:r['header_offset']);groups=[]
    for i,item in enumerate(ordered):
        if item['filename'] not in missing:continue
        end=ordered[i+1]['header_offset'] if i+1<len(ordered) else release['archive']['central_directory_offset']
        if groups and groups[-1]['end']==item['header_offset']:
            groups[-1]['end']=end;groups[-1]['entries'].append(item)
        else:groups.append(dict(start=item['header_offset'],end=end,entries=[item]))
    address=archive_url()
    def fetch(group):
        failed={}
        try:blob=range_bytes(address,group['start'],group['end'])
        except Exception as error:return {Path(e['filename']).name:repr(error) for e in group['entries']}
        for entry in group['entries']:
            name=Path(entry['filename']).name
            try:
                data=extract_member(blob,group['start'],entry)
                with (audio/name).open('xb') as stream:stream.write(data)
            except Exception as error:failed[name]=repr(error)
        return failed
    # Four bounded I/O requests, not model workers; only selected original members are persisted.
    print('Retrieve',len(missing),'test WAVs in',len(groups),'exact member ranges;',sum(g['end']-g['start'] for g in groups),'compressed bytes',flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending=[pool.submit(fetch,group) for group in groups]
        for count,future in enumerate(as_completed(pending),1):
            errors.update(future.result())
            if count%50==0 or count==len(pending):print('Source ranges completed',count,'/',len(pending),'member failures',len(errors),flush=True)
    return by_name,errors


def prepare(cache):
    release=acquire_metadata(cache)
    splits={name:annotations(cache/'source'/(name+'.jsonl')) for name in ['train','dev','test']}
    rows=[record(raw,line) for line,raw in enumerate(splits['test'],1)]
    inventory=json.loads((cache/'source/archive_inventory.json').read_text(encoding='utf-8'))
    by_name,errors=download_audio(cache,rows,inventory,release)
    audit={key:flag_groups(rows,lambda r:r[field] if isinstance(r[field],str) else None,key) for key,field in [('duplicate_id','official_id'),('repeated_source_file','filename')]}
    repeated=flag_groups(rows,lambda r:r['reference'] if isinstance(r['reference'],str) else None,'repeated_exact_reference')
    audit['repeated_exact_reference_groups']=len(repeated)
    for row in rows:
        name=row['filename'];entry=by_name.get(name,[]) if isinstance(name,str) else []
        if isinstance(name,str) and name in errors:row['issues'].append('audio_retrieval_failed');row['audio_error']=errors[name]
        if len(entry)==1 and 'unsafe_audio_filename' not in row['issues']:
            path=cache/'audio'/name
            row['audio_locator']=dict(archive='data.zip',member=entry[0]['filename'],zip_crc32=entry[0]['crc32'],path=path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path))
            if path.is_file():
                data=path.read_bytes()
                if len(data)!=entry[0]['bytes'] or f'{binascii.crc32(data)&0xffffffff:08x}'!=entry[0]['crc32']:row['issues'].append('cached_audio_crc_mismatch')
                row['audio'],issues=inspect_audio(dict(bytes=data,path=entry[0]['filename']));row['issues']+=issues
            elif 'audio_retrieval_failed' not in row['issues']:row['issues'].append('missing_audio')
        row['issues']=sorted(set(row['issues']))
        row['status']='invalid' if any(i!='repeated_exact_reference' for i in row['issues']) else 'valid'
    def values(split,field):return {r[field] for r in splits[split] if isinstance(r,dict) and isinstance(r.get(field),str)}
    audit['split_annotation_counts']={name:len(items) for name,items in splits.items()}
    audit['test_overlap']={name:dict(ids=sorted(values('test','id')&values(name,'id')),source_files=sorted(values('test','file')&values(name,'file'))) for name in ['train','dev']}
    def speakers(split):
        return {value for r in splits[split] if isinstance(r,dict)
                for value in [r.get('speakerID',r.get('speaker_id'))] if isinstance(value,str) and value}
    audit['speaker_overlap']=({name:sorted(speakers('test')&speakers(name)) for name in ['train','dev']}
                              if any(speakers(name) for name in splits) else None)
    all_files=set().union(*(values(name,'file') for name in splits))
    audit['unreferenced_archive_audio']=[e['filename'] for e in inventory if e['filename'].endswith('.wav') and Path(e['filename']).name not in all_files]
    audit['audio_checks_passed']=sum(r['audio'] is not None and r['audio'].get('all_finite') is True and r['audio'].get('decoded_frames',0)>0 and not any(i in r['issues'] for i in ['cached_audio_crc_mismatch','audio_retrieval_failed','unreadable_audio','empty_audio','nonfinite_audio','audio_frame_count_mismatch']) for r in rows)
    audit['valid_records']=sum(r['status']=='valid' for r in rows)
    audit['duration_seconds']=sum(r['audio'].get('duration_seconds',0) for r in rows if r['audio'])
    return dict(provenance=release,normalizer_check=NORMALIZER,reference_field='sentence',split='test',
                ready_for_gipformer=audit['valid_records']==len(rows) and len(rows)>0,audit=audit,records=rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',type=Path,default=CACHE)
    parser.add_argument('--out',type=Path,default=ROOT/'manifests/vnslu_test.json')
    args=parser.parse_args();manifest=prepare(args.cache.resolve())
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(manifest['audit'],ensure_ascii=True,indent=2))
    print('Ready for GIPFormer:',manifest['ready_for_gipformer'],str(args.out),flush=True)
    if not manifest['ready_for_gipformer']:sys.exit(1)


if __name__=='__main__':main()
