"""Bounded Wave 03 hand-authored replay; no model, generator or substitute harness."""
from __future__ import annotations
import os

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
from time import perf_counter
import zipfile

import yaml
from replay_batch03 import ROOT, StrictLoader
from replay_train_wave_01 import canonical
from replay_train_wave_02 import validate as validate_previous


def fixture(w,s):
    state = deepcopy(w['initial_state']); patch = w['variants'].get(s['fixture_variant'],{})
    if 'points' in patch: state['loyalty']['programs'][0]['points'] = patch['points']
    if 'available' in patch: state['library']['books'][0]['available'] = patch['available']
    if 'member' in patch: state['music']['playlists'][0]['track_ids'].append(state['music']['tracks'][0]['id'])
    return state


def validate(d,docs=None):
    if docs is None:
        docs = [yaml.load(p.read_text(encoding='utf-8'),Loader=StrictLoader) for p in sorted((ROOT/'data/synthetic/design').glob('*.yaml'))]
    # Reuse collection integrity/ancestry checks; this does not execute previous replays.
    result = validate_previous(next(p for p in docs if p['version']=='train_wave_02'),docs)
    assert d['split']=='train' and d['status']=='spec_only' and d['exportable'] is False
    own = {s['scenario_id']:s for s in d['scenarios']}; wm = {w['world_id']:w for w in d['worlds']}
    other_roots = {w['lineage_id'] for p in docs if p['version']!=d['version'] for w in p['worlds']
                   if not any(w.get('ancestry',{}).get(k) for k in ['parent_world_ids','parent_scenario_ids','parent_lineage_ids'])}
    for w in wm.values():
        assert w['split']=='train' and w['origin']=='independently_authored' and w['lineage_id'] not in other_roots
        assert w['ancestry']==dict(parent_world_ids=[],parent_scenario_ids=[],parent_lineage_ids=[])
        assert w['design_base'] in own
    for s in own.values():
        assert s['status']=='spec_only' and s['exportable'] is False
        assert s['agent_visible']['allowed_tools']==wm[s['world_id']]['relevant_tools']
        state = fixture(wm[s['world_id']],s)
        def private(value):
            if isinstance(value,dict):
                for k,v in value.items():
                    if k=='id': assert v not in canonical(s['agent_visible'])
                    else: private(v)
            elif isinstance(value,list):
                for v in value: private(v)
        private(state)
        if s['scenario_id'][4]=='R':
            o=s['oracle_draft']; p=next(p for p in state['loyalty']['programs'] if p['name']==o['program'])
            reward=next(r for r in p['rewards'] if r['name']==o['reward'])
            allowed=p['points']-reward['cost']>=o['minimum_remaining']
            assert (o['outcome']=='execute')==allowed
            assert o['points_after']==p['points']-(reward['cost'] if allowed else 0)
    assert own['TR3_R_EXACT']['agent_visible']==own['TR3_R_LOW']['agent_visible']==own['TR3_R_BASE']['agent_visible']
    for variant in ['TR3_R_EXACT','TR3_R_LOW']:
        a=fixture(wm[own[variant]['world_id']],own[variant]); b=fixture(wm[own['TR3_R_BASE']['world_id']],own['TR3_R_BASE'])
        a['loyalty']['programs'][0]['points']=b['loyalty']['programs'][0]['points']; assert a==b
    if 'TR3_L_WAIT' in own:
        assert own['TR3_L_READY']['agent_visible']==own['TR3_L_WAIT']['agent_visible']
        assert own['TR3_L_NOWAIT_READY']['agent_visible']==own['TR3_L_NOWAIT']['agent_visible']
        a=fixture(wm[own['TR3_L_WAIT']['world_id']],own['TR3_L_WAIT']); b=fixture(wm[own['TR3_L_READY']['world_id']],own['TR3_L_READY'])
        a['library']['books'][0]['available']=True; assert a==b
        assert own['TR3_M_ADD']['agent_visible']==own['TR3_M_MEMBER']['agent_visible']
        a=fixture(wm[own['TR3_M_MEMBER']['world_id']],own['TR3_M_MEMBER']); b=fixture(wm[own['TR3_M_ADD']['world_id']],own['TR3_M_ADD'])
        a['music']['playlists'][0]['track_ids']=deepcopy(b['music']['playlists'][0]['track_ids']); assert a==b
    result['near_duplicate_review']='Family comparisons/shared controls in Wave 03 handoff; intentional source-fact contrasts, TR1_E_SEND split pending.'
    return result


def verify(initial,s,calls,final,kinds):
    o=s['oracle_draft']; expected=deepcopy(initial); family=s['scenario_id'][4]
    reasons={'state':[],'trace':[],'grounding':[]}
    def created(app,key,payloads):
        old={r['id'] for r in initial[app][key]}; added=[r for r in final[app][key] if r['id'] not in old]
        if Counter(canonical({k:v for k,v in r.items() if k!='id'}) for r in added)!=Counter(map(canonical,payloads)):
            reasons['state'].append('new_payload_or_count')
        expected[app][key].extend(deepcopy(added))
    if family=='R':
        program=next(p for p in initial['loyalty']['programs'] if p['name']==o['program'])
        reward=next(r for r in program['rewards'] if r['name']==o['reward'])
        next(p for p in expected['loyalty']['programs'] if p['id']==program['id'])['points']=o['points_after']
        created('loyalty','vouchers',[] if o['voucher'] is None else [o['voucher']])
        intended=[{'name':'loyalty.redeem','arguments':{'program':program['id'],'reward_id':reward['id']}}] if o['outcome']=='execute' else []
        required={'program':program}; observed=set()
    elif family=='L':
        books=[next(b for b in initial['library']['books'] if b['title']==title) for title in o['targets']]
        for payload in o['reservations']:
            next(b for b in expected['library']['books'] if b['id']==payload['book_id'])['available']=False
        created('library','reservations',o['reservations'])
        intended=[{'name':'library.reserve','arguments':{'book_id':r['book_id']}} for r in o['reservations']]
        required={b['id']:b for b in books};observed=set()
    elif family=='M':
        track=next((t for t in initial['music']['tracks'] if t['title']==o['track']),None)
        playlist=next((p for p in initial['music']['playlists'] if p['name']==o['playlist']),None)
        for identity,ids in o['membership_after'].items():next(p for p in expected['music']['playlists'] if p['id']==identity)['track_ids']=ids[:]
        if o['playback_after'] is not None:expected['music']['now_playing']=deepcopy(o['playback_after'])
        intended=[]
        for operation in o['operations']:
            if operation=='add':intended.append({'name':'music.add_to_playlist','arguments':{'track_id':track['id'],'playlist_id':playlist['id']}})
            if operation=='play_track':intended.append({'name':'music.play','arguments':{'track_id':track['id']}})
            if operation=='play_playlist':intended.append({'name':'music.play','arguments':{'playlist_id':playlist['id']}})
        required={r['id']:r for r in [track,playlist] if r is not None};observed=set()
    else:
        raise AssertionError(family)
    if final!=expected: reasons['state'].append('goal_or_frame')
    writes=[]
    def norm(name,args):
        args=deepcopy(args)
        if name=='loyalty.redeem':
            for p in initial['loyalty']['programs']:
                if args.get('program')==p['name']: args['program']=p['id']
        return canonical({'name':name,'arguments':args})
    for c in calls:
        name,args,result=c['name'],c['arguments'],c['result']
        if name not in s['agent_visible']['allowed_tools']: reasons['trace'].append('unpermitted_attempt')
        if kinds.get(name)=='read' and name in s['agent_visible']['allowed_tools'] and result.get('ok') is True and result.get('done') is not False:
            if family=='R' and name=='loyalty.get_points' and any(p==program for p in result.get('programs',[])): observed.add('program')
            if family=='L' and name=='library.search':
                for b in result.get('books',[]):
                    if b.get('id') in required and b==required[b['id']]:observed.add(b['id'])
            if family=='M' and name=='music.list_tracks':
                for r in result.get('tracks',[])+result.get('playlists',[]):
                    if r.get('id') in required and r==required[r['id']]:observed.add(r['id'])
        if kinds.get(name,'write')=='write':
            writes.append(norm(name,args))
            consumes = {args['book_id']} if family=='L' and name=='library.reserve' else set(required)
            if not consumes<=observed: reasons['grounding'].append('required_observation_before_write')
        if name=='sys.ask_missing_info': reasons['trace'].append('unjustified_ask')
    if not set(required)<=observed: reasons['grounding'].append('decision_observation_missing')
    if Counter(writes)!=Counter(norm(a['name'],a['arguments']) for a in intended): reasons['trace'].append('authorized_action_or_count')
    if family=='M' and writes!=[norm(a['name'],a['arguments']) for a in intended]:reasons['trace'].append('authorized_operation_order')
    return {'verdict':'reject' if any(reasons.values()) else 'pass',**{k:sorted(set(v)) for k,v in reasons.items()}}


def run(archive,output):
    start=perf_counter(); path=ROOT/'data/synthetic/design/train_wave_03.yaml'; before=path.read_bytes()
    d=yaml.load(before.decode('utf-8'),Loader=StrictLoader); inventory=validate(d)
    wm={w['world_id']:w for w in d['worlds']}; sm={s['scenario_id']:s for s in d['scenarios']}; fixtures={}
    for sid,s in sm.items():
        state=fixture(wm[s['world_id']],s); state['sys']={}; state['notes']={'notes':[{'id':'tr3_guard','title':'Giữ riêng','content':'Không sửa.'}]}
        state['_meta']={'tools':s['agent_visible']['allowed_tools'],'current_time':s['agent_visible']['context']['current_time']}
        fixtures[sid]=state; reverse=deepcopy(state)
        for app in wm[s['world_id']]['initial_state']:
            for value in reverse[app].values():
                if isinstance(value,list):value.reverse()
        fixtures[sid+'/reversed']=reverse
    files=['__init__.py','executor.py','validate.py','utils.py','apps/__init__.py','apps/base.py','apps/sys.py','apps/loyalty.py','apps/library.py','apps/music.py']
    p=d['provenance']; output.parent.mkdir(parents=True,exist_ok=True); rows=[]
    with tempfile.TemporaryDirectory(prefix='wave03_runtime_',dir=output.parent) as temp:
        temp=Path(temp)
        with zipfile.ZipFile(archive) as z:
            for name in files:
                target=temp/'zaic_tools'/name; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(z.read(p['runtime_root']+name))
            cat=temp/'catalog.json';cat.write_bytes(z.read(p['catalog_member']))
        catalog=json.loads(cat.read_text(encoding='utf-8'));assert catalog['schema_version']==p['schema']
        tools={t['name']:t for a in catalog['apps'] for t in a['tools']};kinds={n:t['kind'] for n,t in tools.items()}
        assert tools['loyalty.redeem']['parameters']['required']==['program','reward_id']
        if 'zaic_tools' in sys.modules:raise RuntimeError('Fresh process required')
        sys.path.insert(0,str(temp))
        from zaic_tools.executor import Executor
        f=temp/'authored.json'; f.write_text(canonical(fixtures),encoding='utf-8');ex=Executor(str(f),str(cat));original_db=deepcopy(ex.db)

        def replay(sid,case='standard',reverse=False,expected='pass',reason=None):
            s=sm[sid];o=s['oracle_draft'];key=sid+('/reversed' if reverse else '');session=ex.open(key);initial=session.get_state();calls=[]
            assert session.allowed==set(s['agent_visible']['allowed_tools'])|{'sys.ask_missing_info'}
            def call(tool,**args):
                old=session.get_state();r=session.call(tool,args)
                if kinds[tool]!='write':assert session.get_state()==old
                assert r.get('ok') is True
                if case in ['attempt_insufficient','duplicate_member'] and kinds[tool]=='write':assert r.get('done') is False
                else:assert r.get('done') is not False,(sid,case,r)
                calls.append({'name':tool,'arguments':deepcopy(args),'result':deepcopy(r)});return r
            actions=[];family=sid[4]
            read_tool={'R':'loyalty.get_points','L':'library.search','M':'music.list_tracks'}[family]
            if family=='R':
                private=next(p for p in initial['loyalty']['programs'] if p['name']==o['program'])
                if case in ['hidden_ID','late_read','missing_read']:
                    program=private;reward=next(r for r in program['rewards'] if r['name']==o['reward'])
                else:
                    result=call('loyalty.get_points',**({'program':o['program']} if case=='filtered' else {}))
                    program=next(p for p in result['programs'] if p['name']==o['program']);reward=next(r for r in program['rewards'] if r['name']==o['reward'])
                    if case=='extra_reads':call('loyalty.get_points',program=o['program'])
                allowed=program['points']-reward['cost']>=o['minimum_remaining']
                if allowed:actions=[{'name':'loyalty.redeem','arguments':{'program':o['program'],'reward_id':reward['id']}}]
                if case in ['ignore_reserve','attempt_insufficient']:actions=[{'name':'loyalty.redeem','arguments':{'program':o['program'],'reward_id':reward['id']}}]
                if case=='wrong_program':actions=[{'name':'loyalty.redeem','arguments':{'program':'Ngõ Trúc' if o['program']=='Vườn Sen' else 'Vườn Sen','reward_id':reward['id']}}]
                if case=='decline_equality':actions=[]
            elif family=='L':
                if case=='sequential_reads':books=[]
                elif case in ['hidden_ID','late_read','missing_read']:books=initial['library']['books']
                elif case=='filtered':
                    books=[]
                    for title in o['targets']:books.extend(call('library.search',query=title)['books'])
                else:books=call('library.search')['books']
                chosen=[next(b for b in books if b['title']==title) for title in o['targets']] if case!='sequential_reads' else []
                if case=='extra_reads':call('library.search')
                if o['allow_wait'] or all(b['available'] for b in chosen):actions=[{'name':'library.reserve','arguments':{'book_id':b['id']}} for b in chosen]
                if case=='ignore_no_wait':actions=[{'name':'library.reserve','arguments':{'book_id':chosen[0]['id']}}]
                if case=='wrong_book':actions=[{'name':'library.reserve','arguments':{'book_id':'tr3_book_64' if chosen[0]['id']=='tr3_book_31' else 'tr3_book_31'}}]
                if case=='omit_second':actions=actions[:1]
                if case=='decline_available':actions=[]
                if case=='reverse_writes':actions.reverse()
                if case=='sequential_reads':
                    actions=[]
                    for title in o['targets']:
                        found=call('library.search',query=title)['books'];assert len(found)==1
                        call('library.reserve',book_id=found[0]['id'])
            elif family=='M':
                if case in ['hidden_ID','late_read','missing_read']:result=initial['music']
                else:result=call('music.list_tracks')
                t=next((t for t in result['tracks'] if t['title']==o['track']),None)
                pl=next((p for p in result['playlists'] if p['name']==o['playlist']),None)
                if case=='extra_reads':call('music.list_tracks')
                # ADD/MEMBER share the same reviewed guard; actions follow observed membership.
                operations=o['operations'][:]
                if sid in ['TR3_M_ADD','TR3_M_MEMBER']:operations=[] if t['id'] in pl['track_ids'] else ['add']
                for operation in operations:
                    if operation=='add':actions.append({'name':'music.add_to_playlist','arguments':{'track_id':t['id'],'playlist_id':pl['id']}})
                    if operation=='play_track':actions.append({'name':'music.play','arguments':{'track_id':t['id']}})
                    if operation=='play_playlist':actions.append({'name':'music.play','arguments':{'playlist_id':pl['id']}})
                if case=='play_instead_add':actions=[{'name':'music.play','arguments':{'track_id':t['id']}}]
                if case=='duplicate_member':actions=[{'name':'music.add_to_playlist','arguments':{'track_id':t['id'],'playlist_id':pl['id']}}]
                if case=='both_namespace_IDs':actions=[{'name':'music.play','arguments':{'track_id':'tr3_track_12','playlist_id':'tr3_list_44'}}]
                if case=='wrong_playlist':actions[0]['arguments']['playlist_id']='tr3_list_44'
                if case=='omit_play':actions=actions[:1]
                if case=='reverse_writes':actions.reverse()
            for a in actions:call(a['name'],**a['arguments'])
            if case=='late_read':call(read_tool)
            runtime_final=session.get_state();final=deepcopy(runtime_final)
            if case=='other_balance_snapshot':final['loyalty']['programs'][1]['points']=1
            if case=='third_book_snapshot':next(b for b in final['library']['books'] if b['id']=='tr3_book_92')['available']=True
            if case=='volume_snapshot':final['music']['volume']=99
            v=verify(initial,s,calls,final,kinds)
            assert v['verdict']==expected,(sid,case,v)
            if reason:assert reason in v['trace']+v['state']+v['grounding'],(sid,case,v)
            if case in ['hidden_ID','late_read']:assert not v['state']
            assert session.log==calls and session.get_tool_calls()==[{k:c[k] for k in ['name','arguments']} for c in calls]
            assert ex.db==original_db and ex.open(key).get_state()==initial
            rows.append({'scenario_id':sid,'lineage_id':s['lineage_id'],'trace_case':case,'ordering':'reversed' if reverse else 'original','initial_fixture_ref':key,
                         'expected_verdict':expected,'required_reason':reason,'calls':calls,'final_state':final,'verdict':v,'evidence_kind':'verifier_only_snapshot' if case.endswith('_snapshot') else 'actual_runtime_trace',
                         'construction':'hand_authored_positive' if expected=='pass' else 'deliberate_counterexample'})
            if case.endswith('_snapshot'):rows[-1]['actual_runtime_final_state']=runtime_final
        for sid in sm:
            replay(sid);replay(sid,'extra_reads');replay(sid,reverse=True)
        for sid in ['TR3_R_BASE','TR3_R_EXACT','TR3_R_LOW','TR3_R_RESERVE100','TR3_R_RESERVE150','TR3_R_OTHER']:replay(sid,'filtered')
        for sid in ['TR3_R_BASE','TR3_R_OTHER']:replay(sid,'wrong_program',expected='reject',reason='authorized_action_or_count')
        for sid in ['TR3_R_EXACT','TR3_R_RESERVE100']:replay(sid,'decline_equality',expected='reject',reason='authorized_action_or_count')
        replay('TR3_R_RESERVE150','ignore_reserve',expected='reject',reason='authorized_action_or_count')
        replay('TR3_R_LOW','attempt_insufficient',expected='reject',reason='authorized_action_or_count')
        for sid in ['TR3_R_BASE','TR3_R_EXACT','TR3_R_OTHER']:
            for case in ['hidden_ID','late_read']:replay(sid,case,expected='reject',reason='required_observation_before_write')
        replay('TR3_R_LOW','missing_read',expected='reject',reason='decision_observation_missing')
        if 'TR3_L_READY' in sm:
            for sid in ['TR3_L_READY','TR3_L_WAIT','TR3_L_NOWAIT_READY','TR3_L_NOWAIT','TR3_L_OTHER','TR3_L_TWO']:replay(sid,'filtered')
            replay('TR3_L_TWO','reverse_writes')
            replay('TR3_L_TWO','sequential_reads')
            for sid,case in [('TR3_L_NOWAIT','ignore_no_wait'),('TR3_L_READY','wrong_book'),('TR3_L_OTHER','wrong_book'),('TR3_L_TWO','omit_second'),('TR3_L_NOWAIT_READY','decline_available')]:
                replay(sid,case,expected='reject',reason='authorized_action_or_count')
            for sid in ['TR3_L_READY','TR3_L_WAIT','TR3_L_OTHER']:
                for case in ['hidden_ID','late_read']:replay(sid,case,expected='reject',reason='required_observation_before_write')
            replay('TR3_L_NOWAIT','missing_read',expected='reject',reason='decision_observation_missing')
            for sid,case in [('TR3_M_ADD','play_instead_add'),('TR3_M_MEMBER','duplicate_member'),('TR3_M_PLAY','both_namespace_IDs'),
                             ('TR3_M_PLAY_LIST','both_namespace_IDs'),('TR3_M_OTHER','wrong_playlist'),('TR3_M_BOTH','omit_play')]:
                replay(sid,case,expected='reject',reason='authorized_action_or_count')
            replay('TR3_M_BOTH','reverse_writes',expected='reject',reason='authorized_operation_order')
            for sid in ['TR3_M_ADD','TR3_M_PLAY','TR3_M_PLAY_LIST','TR3_M_OTHER']:
                for case in ['hidden_ID','late_read']:replay(sid,case,expected='reject',reason='required_observation_before_write')
            replay('TR3_M_MEMBER','missing_read',expected='reject',reason='decision_observation_missing')
            for sid,case in [('TR3_R_BASE','other_balance_snapshot'),('TR3_L_READY','third_book_snapshot'),('TR3_M_ADD','volume_snapshot')]:
                replay(sid,case,expected='reject',reason='goal_or_frame')
    assert path.read_bytes()==before
    status={'unique_scenarios_replayed':len(sm),'outcomes':dict(Counter(s['oracle_draft']['outcome'] for s in sm.values())),
            'positive_runtime_paths':sum(r['expected_verdict']=='pass' for r in rows),
            'rejected_counterexamples':sum(r['expected_verdict']=='reject' and r['evidence_kind']=='actual_runtime_trace' for r in rows),
            'verifier_only_checks':sum(r['evidence_kind']!='actual_runtime_trace' for r in rows),
            'all_expectations_met':True,'spec_only':len(sm),'exportable':False,'execution_verified':0}
    result={'created_utc':datetime.now(timezone.utc).isoformat(),'replay_wall_seconds':perf_counter()-start,'declared_volatile_fields':['created_utc','replay_wall_seconds'],
            'kind':'hand_authored_runtime_replay_not_model_evaluation','status':status,'inventory':inventory,'provenance':{'archive':str(archive),'release_recorded':p['release'],
            'schema':catalog['schema_version'],'allowlisted_members':[p['runtime_root']+n for n in files]+[p['catalog_member']],'runtime_modified':False,'python':sys.version},
            'fixtures':fixtures,'agent_visible':{sid:s['agent_visible'] for sid,s in sm.items()},'replays':rows,
            'limitations':['Gold reviewed before traces; Executor does not interpret requests.','Intended train only; semantic/split/harness/template and official acceptance unverified.']}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(status));print('Replay seconds:',result['replay_wall_seconds'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/synthetic/train_wave_03_replay/replay.json')
    args=parser.parse_args();run(args.archive,args.output)
