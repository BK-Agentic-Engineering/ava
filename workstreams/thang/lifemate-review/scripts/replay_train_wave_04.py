"""Wave 04 local hand-authored replay, not a generator, model or team harness."""
from __future__ import annotations
import os

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import tempfile
from time import perf_counter
import zipfile

import yaml
from replay_batch03 import ROOT, StrictLoader
from replay_train_wave_01 import canonical
from replay_train_wave_03 import validate as validate_previous


def fixture(w,s):
    state=deepcopy(w['initial_state']);patch=w['variants'].get(s['fixture_variant'],{})
    if 'preferred_available' in patch:state['bike_rental']['bikes'][0]['available']=patch['preferred_available']
    if 'backup_available' in patch:state['bike_rental']['bikes'][1]['available']=patch['backup_available']
    if 'front_locked' in patch:state['door_lock']['locks'][0]['locked']=patch['front_locked']
    if 'today_steps' in patch:state['fitness']['activity'][s['agent_visible']['context']['current_time'][:10]]={'steps':patch['today_steps'],'calories':160,'distance_km':3}
    return state


def validate(d,docs=None):
    if docs is None:docs=[yaml.load(p.read_text(encoding='utf-8'),Loader=StrictLoader) for p in sorted((ROOT/'data/synthetic/design').glob('*.yaml'))]
    inventory=validate_previous(next(p for p in docs if p['version']=='train_wave_03'),docs)
    assert d['split']=='train' and d['status']=='spec_only' and d['exportable'] is False,'Wave 04 status'
    sm={s['scenario_id']:s for s in d['scenarios']};wm={w['world_id']:w for w in d['worlds']}
    roots={w['lineage_id'] for p in docs if p['version']!=d['version'] for w in p['worlds'] if not any(w.get('ancestry',{}).get(k) for k in ['parent_world_ids','parent_scenario_ids','parent_lineage_ids'])}
    for w in wm.values():
        assert w['split']=='train' and w['origin']=='independently_authored' and w['lineage_id'] not in roots
        assert w['ancestry']==dict(parent_world_ids=[],parent_scenario_ids=[],parent_lineage_ids=[])
        assert w['design_base'] in sm
    for s in sm.values():
        assert s['status']=='spec_only' and s['exportable'] is False,'Wave 04 scenario status'
        assert s['agent_visible']['allowed_tools']==wm[s['world_id']]['relevant_tools']
        def hidden(v):
            if isinstance(v,dict):
                for k,value in v.items():
                    if k=='id':assert value not in canonical(s['agent_visible']),'private ID leak'
                    else:hidden(value)
            elif isinstance(v,list):
                for value in v:hidden(value)
        hidden(fixture(wm[s['world_id']],s))
    a,b=sm['TR4_B_PREFERRED'],sm['TR4_B_FALLBACK'];assert a['agent_visible']==b['agent_visible']
    x=fixture(wm[a['world_id']],a);y=fixture(wm[b['world_id']],b);y['bike_rental']['bikes'][0]['available']=True;assert x==y
    a,b=sm['TR4_B_FALLBACK'],sm['TR4_B_NEITHER'];assert a['agent_visible']==b['agent_visible']
    x=fixture(wm[a['world_id']],a);y=fixture(wm[b['world_id']],b);y['bike_rental']['bikes'][1]['available']=True;assert x==y
    assert sm['TR4_B_FALLBACK']['fixture_variant']==sm['TR4_B_FORBID']['fixture_variant']
    if 'TR4_F_TODAY' in sm:
        a,b=sm['TR4_F_TODAY'],sm['TR4_F_TODAY_RECORDED'];assert a['agent_visible']==b['agent_visible']
        x=fixture(wm[a['world_id']],a);y=fixture(wm[b['world_id']],b)
        y['fitness']['activity'].pop(a['agent_visible']['context']['current_time'][:10]);assert x==y
    inventory['near_duplicate_review']='Wave 04 handoff records actual request/oracle comparisons; controlled repeats retained; TR1_E_SEND split pending.'
    return inventory


def verify(initial,s,calls,final,kinds):
    o=s['oracle_draft'];family=s['scenario_id'][4];expected=deepcopy(initial)
    reasons={'state':[],'trace':[],'grounding':[]};observed=set()
    def created(app,key,payloads):
        old={r['id'] for r in initial[app][key]};added=[r for r in final[app][key] if r['id'] not in old]
        if Counter(canonical({k:v for k,v in r.items() if k!='id'}) for r in added)!=Counter(map(canonical,payloads)):reasons['state'].append('new_payload_or_count')
        expected[app][key].extend(deepcopy(added))
    if family=='B':
        pref=next(b for b in initial['bike_rental']['bikes'] if b['name']==o['preferred'])
        fallback=next((b for b in initial['bike_rental']['bikes'] if b['name']==o['fallback']),None)
        required={pref['id']:pref}
        if not pref['available'] and fallback is not None:required[fallback['id']]=fallback
        selected=next((b for b in initial['bike_rental']['bikes'] if b['id']==o['selected']),None)
        payloads=[];intended=[]
        if selected:
            next(b for b in expected['bike_rental']['bikes'] if b['id']==selected['id'])['available']=False
            payloads=[{'bike_id':selected['id'],'station':selected['station'],'status':'reserved'}]
            intended=[{'name':'bike_rental.reserve','arguments':{'bike_id':selected['id']}}]
        created('bike_rental','reservations',payloads)
    elif family=='G':
        lock=next(l for l in initial['door_lock']['locks'] if l['name']==o['lock']);required={lock['id']:lock};intended=[]
        if o['locked_after'] is not None:
            next(l for l in expected['door_lock']['locks'] if l['id']==lock['id'])['locked']=o['locked_after']
            intended.append({'name':'door_lock.set_lock','arguments':{'lock_id':lock['id'],'locked':o['locked_after']}})
        if o['credential'] is not None:intended.append({'name':'door_lock.grant_guest_code','arguments':{'lock_id':lock['id'],**o['credential']}})
        old={r['id'] for r in initial['door_lock']['guest_codes']};added=[r for r in final['door_lock']['guest_codes'] if r['id'] not in old]
        expected_payloads=[] if o['credential'] is None else [{'lock_id':lock['id'],**o['credential']}]
        payloads=[]
        for record in added:
            payload={k:v for k,v in record.items() if k not in ['id','code']}
            if 'label' not in (o['credential'] or {}) and payload.get('label')=='':payload.pop('label')
            payloads.append(payload)
            returned=any(c['name']=='door_lock.grant_guest_code' and c['result'].get('ok') is True and c['result'].get('guest_code')==record for c in calls)
            if not returned or not re.fullmatch(r'[0-9]{6}',str(record.get('code',''))):reasons['state'].append('generated_code_response_binding')
        if Counter(map(canonical,payloads))!=Counter(map(canonical,expected_payloads)):reasons['state'].append('credential_payload_or_count')
        expected['door_lock']['guest_codes'].extend(deepcopy(added))
    elif family=='F':
        required={};expected['fitness']['goal_steps']=o['goal_after'];created('fitness','workouts',o['workouts']);intended=[]
        if o['goal_source'] and o['outcome']=='execute':intended.append({'name':'fitness.set_goal','arguments':{'steps':o['goal_after']}})
        for workout in o['workouts']:intended.append({'name':'fitness.log_workout','arguments':workout})
    else:raise AssertionError(family)
    if final!=expected:reasons['state'].append('goal_or_frame')
    writes=[];goal_observed=False;latest_day=None
    def norm(name,args):
        args=deepcopy(args)
        if name=='fitness.log_workout':args.setdefault('time',s['agent_visible']['context']['current_time'])
        if name=='door_lock.grant_guest_code' and args.get('label')=='':args.pop('label')
        return canonical({'name':name,'arguments':args})
    for c in calls:
        name,args,result=c['name'],c['arguments'],c['result']
        permitted=name in s['agent_visible']['allowed_tools']
        if not permitted:reasons['trace'].append('unpermitted_attempt')
        if permitted and kinds.get(name)=='read' and result.get('ok') is True and result.get('done') is not False:
            if family=='B' and name=='bike_rental.find_bikes':
                for b in result.get('bikes',[]):
                    if b.get('id') in required and b==required[b['id']]:observed.add(b['id'])
            if family=='G' and name=='door_lock.list_locks':
                for l in result.get('locks',[]):
                    if l.get('id') in required and l==required[l['id']]:observed.add(l['id'])
            if family=='F' and name=='fitness.get_activity':
                activity=result.get('activity',{});date=activity.get('date')
                if o['goal_source']=='latest':
                    if not args.get('date'):latest_day=date
                    if latest_day and date==latest_day and date==max(initial['fitness']['activity']) and activity.get('steps')==initial['fitness']['activity'][date]['steps']:goal_observed=True
                if o['goal_source']=='today':
                    today=s['agent_visible']['context']['current_time'][:10]
                    if date==today and activity.get('steps')==initial['fitness']['activity'].get(today,{}).get('steps',0):goal_observed=True
        if kinds.get(name,'write')=='write':
            writes.append(norm(name,args))
            if not set(required)<=observed:reasons['grounding'].append('source_before_consuming_write')
            if family=='F' and name=='fitness.set_goal' and o['goal_source'] in ['latest','today'] and not goal_observed:reasons['grounding'].append('activity_source_before_goal')
        if name=='sys.ask_missing_info':reasons['trace'].append('unjustified_ask')
    if not set(required)<=observed:reasons['grounding'].append('decision_observation_missing')
    if family=='F' and o['goal_source'] in ['latest','today'] and not goal_observed:reasons['grounding'].append('activity_decision_observation_missing')
    if Counter(writes)!=Counter(norm(a['name'],a['arguments']) for a in intended):reasons['trace'].append('authorized_action_or_count')
    return {'verdict':'reject' if any(reasons.values()) else 'pass',**{k:sorted(set(v)) for k,v in reasons.items()}}


def run(archive,output):
    start=perf_counter();path=ROOT/'data/synthetic/design/train_wave_04.yaml';before=path.read_bytes();d=yaml.load(before.decode('utf-8'),Loader=StrictLoader);inventory=validate(d)
    sm={s['scenario_id']:s for s in d['scenarios']};wm={w['world_id']:w for w in d['worlds']};fixtures={}
    for sid,s in sm.items():
        state=fixture(wm[s['world_id']],s);state['sys']={};state['notes']={'notes':[{'id':'tr4_guard','title':'Giữ riêng','content':'Không sửa.'}]}
        state['_meta']={'tools':s['agent_visible']['allowed_tools'],'current_time':s['agent_visible']['context']['current_time']};fixtures[sid]=state
        rev=deepcopy(state)
        for app in wm[s['world_id']]['initial_state']:
            for value in rev[app].values():
                if isinstance(value,list):value.reverse()
        fixtures[sid+'/reversed']=rev
    p=d['provenance'];files=['__init__.py','executor.py','validate.py','utils.py','apps/__init__.py','apps/base.py','apps/sys.py','apps/bike_rental.py','apps/door_lock.py','apps/fitness.py']
    output.parent.mkdir(parents=True,exist_ok=True);rows=[]
    with tempfile.TemporaryDirectory(prefix='wave04_runtime_',dir=output.parent) as temp:
        temp=Path(temp)
        with zipfile.ZipFile(archive) as z:
            for name in files:
                target=temp/'zaic_tools'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(p['runtime_root']+name))
            cat=temp/'catalog.json';cat.write_bytes(z.read(p['catalog_member']))
        catalog=json.loads(cat.read_text(encoding='utf-8'));assert catalog['schema_version']==p['schema'];tools={t['name']:t for a in catalog['apps'] for t in a['tools']};kinds={n:t['kind'] for n,t in tools.items()}
        assert tools['bike_rental.reserve']['parameters']['required']==['bike_id']
        assert tools['door_lock.grant_guest_code']['parameters']['required']==['lock_id','valid_until']
        assert tools['fitness.log_workout']['parameters']['required']==['type','minutes']
        if 'zaic_tools' in sys.modules:raise RuntimeError('Fresh process required')
        sys.path.insert(0,str(temp))
        from zaic_tools.executor import Executor
        f=temp/'authored.json';f.write_text(canonical(fixtures),encoding='utf-8');ex=Executor(str(f),str(cat));original_db=deepcopy(ex.db)
        def replay(sid,case='standard',reverse=False,expected='pass',reason=None):
            s=sm[sid];o=s['oracle_draft'];key=sid+('/reversed' if reverse else '');session=ex.open(key);initial=session.get_state();calls=[]
            assert session.allowed==set(s['agent_visible']['allowed_tools'])|{'sys.ask_missing_info'}
            def call(tool,**args):
                old=session.get_state();r=session.call(tool,args)
                if kinds[tool]!='write':assert session.get_state()==old
                assert r.get('ok') is True
                if case=='reserve_busy' and kinds[tool]=='write':assert r.get('done') is False
                else:assert r.get('done') is not False,(sid,case,r)
                calls.append({'name':tool,'arguments':deepcopy(args),'result':deepcopy(r)});return r
            actions=[];family=sid[4]
            if family=='B':
                if case in ['hidden_ID','late_read','missing_read']:bikes=initial['bike_rental']['bikes']
                elif case=='separate_reads':
                    bikes=list(call('bike_rental.find_bikes',near=o['preferred'])['bikes'])
                    if o['fallback']:bikes+=call('bike_rental.find_bikes',near=o['fallback'])['bikes']
                else:bikes=call('bike_rental.find_bikes',**({'near':'Trạm Bờ Dâu'} if case=='filtered' else {}))['bikes']
                pref=next(b for b in bikes if b['name']==o['preferred']);backup=next((b for b in bikes if b['name']==o['fallback']),None)
                selected=pref if pref['available'] else backup if backup and backup['available'] and (o['fallback_max_price'] is None or backup['price_per_hour']<=o['fallback_max_price']) else None
                if selected:actions=[{'name':'bike_rental.reserve','arguments':{'bike_id':selected['id']}}]
                if case=='extra_reads':call('bike_rental.find_bikes',near=o['preferred'])
                if case in ['force_backup','reserve_busy']:actions=[{'name':'bike_rental.reserve','arguments':{'bike_id':'tr4_bike_63'}}]
                if case=='wrong_preference':actions=[{'name':'bike_rental.reserve','arguments':{'bike_id':'tr4_bike_27'}}]
                if case=='decline_fallback':actions=[]
            elif family=='G':
                if case in ['hidden_ID','late_read']:locks=initial['door_lock']['locks']
                else:locks=call('door_lock.list_locks')['locks']
                lock=next(l for l in locks if l['name']==o['lock'])
                if case=='extra_reads':call('door_lock.list_locks')
                if o['locked_after'] is not None:actions.append({'name':'door_lock.set_lock','arguments':{'lock_id':lock['id'],'locked':o['locked_after']}})
                if o['credential'] is not None:actions.append({'name':'door_lock.grant_guest_code','arguments':{'lock_id':lock['id'],**o['credential']}})
                if case=='extra_unlock':actions.append({'name':'door_lock.set_lock','arguments':{'lock_id':lock['id'],'locked':False}})
                if case=='code_instead_unlock':actions=[{'name':'door_lock.grant_guest_code','arguments':{'lock_id':lock['id'],'valid_until':'2026-12-29T18:00:00+07:00','label':'Khách nhận khay'}}]
                if case=='wrong_lock':actions[0]['arguments']['lock_id']='tr4_lock_31'
                if case=='omit_lock':actions=actions[1:]
                if case=='wrong_label':actions[0]['arguments']['label']='Khách nhận khay'
                if case=='wrong_expiry':actions[0]['arguments']['valid_until']='2026-12-29T18:00:00+07:00'
                if case=='empty_label':actions[0]['arguments']['label']=''
                if case=='reverse_writes':actions.reverse()
                if case=='duplicate_code':actions.append(deepcopy(actions[-1]))
            elif family=='F':
                source=o['goal_source'];activity=None
                if source in ['latest','today']:
                    if case=='hidden_goal':activity={'steps':initial['fitness']['activity'][max(initial['fitness']['activity'])]['steps']}
                    elif case in ['guess_latest_date','late_latest_read']:
                        activity=call('fitness.get_activity',date=max(initial['fitness']['activity']))['activity']  # Private-date negative only.
                    else:
                        args={'date':s['agent_visible']['context']['current_time'][:10]} if source=='today' and case!='wrong_today_default' else {}
                        activity=call('fitness.get_activity',**args)['activity']
                        if case=='explicit_after_latest':activity=call('fitness.get_activity',date=activity['date'])['activity']
                    if activity['steps']>0:actions.append({'name':'fitness.set_goal','arguments':{'steps':activity['steps']}})
                elif source=='literal':actions.append({'name':'fitness.set_goal','arguments':{'steps':o['goal_after']}})
                for workout in o['workouts']:
                    args=deepcopy(workout)
                    if args['time']==s['agent_visible']['context']['current_time']:args.pop('time')
                    actions.append({'name':'fitness.log_workout','arguments':args})
                if case=='extra_reads':call('fitness.get_activity')
                if case=='explicit_now':actions[-1]['arguments']['time']=s['agent_visible']['context']['current_time']
                if case=='omit_past_time':actions[0]['arguments'].pop('time')
                if case=='decline_today':actions=[]
                if case=='omit_goal':actions=[a for a in actions if a['name']!='fitness.set_goal']
                if case=='wrong_duration':actions[0]['arguments']['minutes']=50
                if case=='reverse_writes':actions.reverse()
            for a in actions:call(a['name'],**a['arguments'])
            if case=='late_read':call('bike_rental.find_bikes' if family=='B' else 'door_lock.list_locks')
            if case=='late_latest_read':call('fitness.get_activity')
            runtime_final=session.get_state();final=deepcopy(runtime_final)
            if case=='price_snapshot':final['bike_rental']['bikes'][0]['price_per_hour']=1
            if case=='other_lock_snapshot':next(l for l in final['door_lock']['locks'] if l['id']=='tr4_lock_92')['locked']=False
            if case=='activity_snapshot':final['fitness']['activity']['2026-12-26']['steps']=1
            v=verify(initial,s,calls,final,kinds)
            assert v['verdict']==expected,(sid,case,v)
            if reason:assert reason in v['trace']+v['state']+v['grounding'],(sid,case,v)
            if case in ['hidden_ID','late_read','hidden_goal','guess_latest_date','late_latest_read']:assert not v['state']
            assert session.log==calls and session.get_tool_calls()==[{k:c[k] for k in ['name','arguments']} for c in calls]
            assert ex.db==original_db and ex.open(key).get_state()==initial
            rows.append({'scenario_id':sid,'lineage_id':s['lineage_id'],'trace_case':case,'ordering':'reversed' if reverse else 'original','initial_fixture_ref':key,
                         'expected_verdict':expected,'required_reason':reason,'calls':calls,'final_state':final,'verdict':v,'evidence_kind':'verifier_only_snapshot' if case.endswith('_snapshot') else 'actual_runtime_trace',
                         'construction':'hand_authored_positive' if expected=='pass' else 'deliberate_counterexample'})
            if case.endswith('_snapshot'):rows[-1]['actual_runtime_final_state']=runtime_final
        for sid in sm:replay(sid);replay(sid,'extra_reads');replay(sid,reverse=True)
        for sid in [sid for sid in sm if sid[4]=='B']:replay(sid,'filtered');replay(sid,'separate_reads')
        for sid in ['TR4_B_PREFERRED','TR4_B_FORBID','TR4_B_LIMIT']:replay(sid,'force_backup',expected='reject',reason='authorized_action_or_count')
        replay('TR4_B_DIRECT','wrong_preference',expected='reject',reason='authorized_action_or_count')
        replay('TR4_B_FALLBACK','decline_fallback',expected='reject',reason='authorized_action_or_count')
        replay('TR4_B_NEITHER','reserve_busy',expected='reject',reason='authorized_action_or_count')
        for sid in ['TR4_B_PREFERRED','TR4_B_FALLBACK','TR4_B_DIRECT']:
            for case in ['hidden_ID','late_read']:replay(sid,case,expected='reject',reason='source_before_consuming_write')
        for sid in ['TR4_B_FORBID','TR4_B_NEITHER','TR4_B_LIMIT']:replay(sid,'missing_read',expected='reject',reason='decision_observation_missing')
        if 'TR4_G_CODE' in sm:
            for sid,case in [('TR4_G_CODE','extra_unlock'),('TR4_G_UNLOCK','code_instead_unlock'),('TR4_G_OTHER','wrong_lock'),
                             ('TR4_G_LOCK_CODE','omit_lock'),('TR4_G_UNLABELLED','wrong_label'),('TR4_G_LATER','wrong_expiry'),('TR4_G_CODE','duplicate_code')]:
                replay(sid,case,expected='reject',reason='authorized_action_or_count')
            for sid in [sid for sid in sm if sid[4]=='G']:
                for case in ['hidden_ID','late_read']:replay(sid,case,expected='reject',reason='source_before_consuming_write')
            replay('TR4_G_LOCK_CODE','reverse_writes');replay('TR4_G_UNLABELLED','empty_label')
            for sid,case in [('TR4_F_LATEST','hidden_goal'),('TR4_F_LATEST','guess_latest_date'),('TR4_F_LATEST','late_latest_read')]:
                replay(sid,case,expected='reject',reason='activity_source_before_goal')
            for sid,case in [('TR4_F_TODAY','wrong_today_default'),('TR4_F_TODAY_RECORDED','decline_today'),
                             ('TR4_F_LOG_NOW','wrong_duration'),('TR4_F_LOG_PAST','omit_past_time'),('TR4_F_BOTH','omit_goal')]:
                replay(sid,case,expected='reject',reason='authorized_action_or_count')
            replay('TR4_F_LATEST','explicit_after_latest');replay('TR4_F_LOG_NOW','explicit_now');replay('TR4_F_BOTH','reverse_writes')
            for sid,case in [('TR4_B_PREFERRED','price_snapshot'),('TR4_G_CODE','other_lock_snapshot'),('TR4_F_LOG_NOW','activity_snapshot')]:
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
            'limitations':['Reviewed gold before trace; no model or request interpreter.','Intended train only; TR1_E_SEND split and independent semantics/harness/template/official acceptance pending.']}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(status));print('Replay seconds:',result['replay_wall_seconds'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/synthetic/train_wave_04_replay/replay.json')
    args=parser.parse_args();run(args.archive,args.output)
