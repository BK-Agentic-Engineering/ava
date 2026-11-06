"""Bounded Wave 07 hand-authored synthetic replay; no model/generator/team harness."""
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
from replay_train_wave_06 import validate as validate_previous


def fixture(w,s):
    state=deepcopy(w['initial_state']);patch=w['variants'].get(s['fixture_variant'],{})
    if 'late_price' in patch:state['flights']['flights'][0]['price']=patch['late_price']
    if 'forward_content' in patch:state['chat_ott']['chats'][0]['messages'][-1]['content']=patch['forward_content']
    return state


def flight_rows(rows,j):
    return [r for r in rows if all(r[k]==j[k] for k in ['origin','destination','date'])]


def choose_flight(rows,j):
    choices=flight_rows(rows,j)
    if j['cutoff']:choices=[r for r in choices if r['depart']<j['cutoff']]
    if j['criterion']=='explicit':return next(r for r in choices if r['flight_no']==j['flight_no'])
    key='depart' if j['criterion']=='earliest' else 'price'
    return min(choices,key=lambda r:r[key])


def validate(d,docs=None):
    if docs is None:docs=[yaml.load(p.read_text(encoding='utf-8'),Loader=StrictLoader) for p in sorted((ROOT/'data/synthetic/design').glob('*.yaml'))]
    inventory=validate_previous(next(p for p in docs if p['version']=='train_wave_06'),docs)
    assert d['split']=='train' and d['status']=='spec_only' and d['exportable'] is False,'Wave07 status'
    sm={s['scenario_id']:s for s in d['scenarios']};wm={w['world_id']:w for w in d['worlds']}
    for w in wm.values():
        assert w['split']=='train' and w['design_base'] in sm
        if w['origin']=='train_derivative':
            expected={'C':('TRAIN_NOTE_LIFECYCLE_01',{'TR1_N_COPY','TR3_M_PLAY'}),'D':('TRAIN_LEARNING_DELTA_06',{'TR6_L_ADD','TR6_L_SCHEDULE'})}[w['family']]
            assert w['lineage_id']==expected[0] and set(w['ancestry']['parent_scenario_ids'])==expected[1]
        else:
            assert w['origin']=='independently_authored' and w['ancestry']==dict(parent_world_ids=[],parent_scenario_ids=[],parent_lineage_ids=[])
            assert not any(p['lineage_id']==w['lineage_id'] and not any(p.get('ancestry',{}).get(k) for k in ['parent_world_ids','parent_scenario_ids','parent_lineage_ids']) for other in docs if other['version']!=d['version'] for p in other['worlds'])
    for s in sm.values():
        assert s['status']=='spec_only' and s['exportable'] is False,'Wave07 scenario status'
        assert s['agent_visible']['allowed_tools']==wm[s['world_id']]['relevant_tools']
        def private(v):
            if isinstance(v,dict):
                for k,value in v.items():
                    if k=='id':assert value not in canonical(s['agent_visible'])
                    else:private(value)
            elif isinstance(v,list):
                for value in v:private(value)
        state=fixture(wm[s['world_id']],s);private(state)
        if s['scenario_id'][4]=='F':
            for j in s['oracle_draft']['journeys']:assert choose_flight(state['flights']['flights'],j)['id']==j['selected']
    assert sm['TR7_F_CHEAP']['agent_visible']==sm['TR7_F_PRICE_CHANGED']['agent_visible']
    a=fixture(wm[sm['TR7_F_CHEAP']['world_id']],sm['TR7_F_CHEAP']);b=fixture(wm[sm['TR7_F_PRICE_CHANGED']['world_id']],sm['TR7_F_PRICE_CHANGED'])
    b['flights']['flights'][0]['price']=a['flights']['flights'][0]['price'];assert a==b
    if 'TR7_C_FORWARD' in sm:
        assert sm['TR7_C_FORWARD']['agent_visible']==sm['TR7_C_FORWARD_CHANGED']['agent_visible']
        a=fixture(wm[sm['TR7_C_FORWARD']['world_id']],sm['TR7_C_FORWARD']);b=fixture(wm[sm['TR7_C_FORWARD_CHANGED']['world_id']],sm['TR7_C_FORWARD_CHANGED'])
        b['chat_ott']['chats'][0]['messages'][-1]['content']=a['chat_ott']['chats'][0]['messages'][-1]['content'];assert a==b
    inventory['near_duplicate_review']='Wave07 handoff: optimization and train-derived chat/schedule controls, connected ancestry; email export recommendation recorded without split mutation.'
    return inventory


def verify(initial,s,calls,final,kinds):
    o=s['oracle_draft'];family=s['scenario_id'][4];expected=deepcopy(initial);reasons={'state':[],'authorization':[],'grounding':[]};seen=set();read_details=set()
    def created(app,key,payloads):
        old={r['id'] for r in initial[app][key]};added=[r for r in final[app][key] if r['id'] not in old]
        def payload(r):
            value={k:deepcopy(v) for k,v in r.items() if k!='id'}
            if app=='medication' and key=='schedules':value['times']=sorted(value['times'])
            return canonical(value)
        if Counter(map(payload,added))!=Counter(map(payload,payloads)):reasons['state'].append('new_payload_or_count')
        expected[app][key].extend(deepcopy(added))
    if family=='F':
        payloads=[{'flight_id':j['selected'],'passengers':j['passengers'],'seat_class':j['seat_class'],'status':'confirmed'} for j in o['journeys']]
        intended=[{'name':'flights.book','arguments':{k:v for k,v in p.items() if k!='status'}} for p in payloads]
        created('flights','bookings',payloads)
    elif family=='C':
        dest=next(r for r in initial['chat_ott']['chats'] if r['name']==o['destination'])
        source=next((r for r in initial['chat_ott']['chats'] if r['name']==o['source']),None)
        messages=[];call_payloads=[];intended=[]
        for op in o['operations']:
            if op=='text':
                messages.append({'from':'me','content':o['content']});intended.append({'name':'chat_ott.send_message','arguments':{'chat_id':dest['id'],'content':o['content']}})
            if op=='location':
                messages.append({'from':'me','type':'location','content':'Vị trí hiện tại'});intended.append({'name':'chat_ott.send_location','arguments':{'chat_id':dest['id']}})
            if op in ['voice','video']:
                call_payloads.append({'chat_id':dest['id'],'video':op=='video','status':'dialing'});intended.append({'name':'chat_ott.call','arguments':{'chat_id':dest['id'],'video':op=='video'}})
        final_dest=next(r for r in final['chat_ott']['chats'] if r['id']==dest['id'])
        added=final_dest['messages'][len(dest['messages']):]
        if Counter(map(canonical,added))!=Counter(map(canonical,messages)):reasons['state'].append('message_types_payload_or_count')
        next(r for r in expected['chat_ott']['chats'] if r['id']==dest['id'])['messages'].extend(deepcopy(added))
        created('chat_ott','calls',call_payloads)
    elif family=='D':
        schedule=next((r for r in initial['medication']['schedules'] if r['name']==o['existing']),None);intended=[]
        if o['remove']:
            expected['medication']['schedules']=[r for r in expected['medication']['schedules'] if r['id']!=schedule['id']]
            intended.append({'name':'medication.remove','arguments':{'schedule_id':schedule['id']}})
        add=deepcopy(o['add'])
        created('medication','schedules',[] if add is None else [add])
        if add:intended.append({'name':'medication.add','arguments':add})
        log=not o['remove'] and schedule is not None
        payloads=[{'schedule_id':schedule['id'],'time':o['log']}] if log else []
        old=initial['medication']['logs'];added=final['medication']['logs'][len(old):]
        if Counter(map(canonical,added))!=Counter(map(canonical,payloads)):reasons['state'].append('dose_log_payload_or_count')
        expected['medication']['logs'].extend(deepcopy(added))
        if log:intended.append({'name':'medication.log_taken','arguments':{'schedule_id':schedule['id'],**({'time':o['log']} if o['log'] is not None else {})}})
    else:raise AssertionError(family)
    if expected!=final:reasons['state'].append('goal_or_frame')
    def norm(name,args):
        args=deepcopy(args)
        if name=='flights.book' and args.get('seat_class') is None:args['seat_class']='economy'
        if name=='chat_ott.call' and args.get('video') is None:args['video']=False
        if name=='medication.add':
            if args.get('days') is None:args['days']='daily'
            args['times']=sorted(args['times'])
        if name=='medication.log_taken' and args.get('time') is None:args.pop('time',None)
        return canonical({'name':name,'arguments':args})
    writes=[];trace_notes=[]
    for index,c in enumerate(calls):
        name,args,result=c['name'],c['arguments'],c['result'];permitted=name in s['agent_visible']['allowed_tools']
        if not permitted:reasons['authorization'].append('unpermitted_attempt')
        if permitted and kinds.get(name)=='read' and result.get('ok') is True and result.get('done') is not False:
            if family=='F' and name=='flights.search':
                rows=result.get('flights',[])
                for j in o['journeys']:
                    correct=flight_rows(initial['flights']['flights'],j)
                    selected=next(r for r in correct if r['id']==j['selected'])
                    enough=selected in rows if j['criterion']=='explicit' else all(r in rows for r in correct)
                    if enough:seen.add(j['selected'])
            if family=='C':
                if name=='chat_ott.list_chats':
                    for r in [dest,source]:
                        if r is not None and {k:v for k,v in r.items() if k!='messages'} in result.get('chats',[]):seen.add(r['id'])
                if name=='chat_ott.read_chat' and source is not None and args.get('chat_id')==source['id'] and source['id'] in seen:
                    messages=result.get('messages',[])
                    if messages and messages[-1]==source['messages'][-1]:read_details.add(source['id'])
            if family=='D' and schedule is not None and name=='medication.list' and schedule in result.get('schedules',[]):seen.add(schedule['id'])
        if kinds.get(name,'write')=='write':
            token=norm(name,args)
            # Removing an already removed schedule is harmless/idempotent. Retain
            # the attempt and a trace note; do not invent a one-call semantic rule.
            if family=='D' and name=='medication.remove' and token in writes:trace_notes.append('redundant_idempotent_remove_not_semantic_failure')
            else:writes.append(token)
            if family=='F' and args.get('flight_id') not in seen:reasons['grounding'].append('flight_selection_before_booking')
            if family=='C':
                if args.get('chat_id') not in seen:reasons['grounding'].append('destination_chat_before_write')
                if source is not None and source['id'] not in read_details:reasons['grounding'].append('source_content_before_forward')
            if family=='D' and name in ['medication.log_taken','medication.remove'] and args.get('schedule_id') not in seen:reasons['grounding'].append('schedule_ID_before_write')
        if name=='sys.ask_missing_info':reasons['authorization'].append('unjustified_ask')
    if Counter(writes)!=Counter(norm(a['name'],a['arguments']) for a in intended):reasons['authorization'].append('authorized_action_or_count')
    return {'verdict':'reject' if any(reasons.values()) else 'pass',**{k:sorted(set(v)) for k,v in reasons.items()},
            'trace_policy_notes':trace_notes, 'official_call_matching':'not_evaluated'}


def run(archive,output):
    start=perf_counter();path=ROOT/'data/synthetic/design/train_wave_07.yaml';before=path.read_bytes();d=yaml.load(before.decode('utf-8'),Loader=StrictLoader);inventory=validate(d)
    sm={s['scenario_id']:s for s in d['scenarios']};wm={w['world_id']:w for w in d['worlds']};fixtures={}
    for sid,s in sm.items():
        state=fixture(wm[s['world_id']],s);state['sys']={};state['notes']={'notes':[{'id':'tr7_guard','title':'Giữ riêng','content':'Không sửa.'}]}
        state['_meta']={'tools':s['agent_visible']['allowed_tools'],'current_time':s['agent_visible']['context']['current_time']};fixtures[sid]=state;reverse=deepcopy(state)
        for app in wm[s['world_id']]['initial_state']:
            for value in reverse[app].values():
                if isinstance(value,list):value.reverse()
        fixtures[sid+'/reversed']=reverse
    p=d['provenance'];files=['__init__.py','executor.py','validate.py','utils.py','apps/__init__.py','apps/base.py','apps/sys.py','apps/flights.py','apps/chat_ott.py','apps/medication.py']
    output.parent.mkdir(parents=True,exist_ok=True);rows=[]
    with tempfile.TemporaryDirectory(prefix='wave07_runtime_',dir=output.parent) as temp:
        temp=Path(temp)
        with zipfile.ZipFile(archive) as z:
            for name in files:
                target=temp/'zaic_tools'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(p['runtime_root']+name))
            cat=temp/'catalog.json';cat.write_bytes(z.read(p['catalog_member']))
        catalog=json.loads(cat.read_text(encoding='utf-8'));assert catalog['schema_version']==p['schema'];tools={t['name']:t for a in catalog['apps'] for t in a['tools']};kinds={n:t['kind'] for n,t in tools.items()}
        assert tools['flights.book']['parameters']['required']==['flight_id','passengers']
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
                if r.get('done') is False:assert case=='repeat_remove' and tool=='medication.remove',(sid,case,r)
                calls.append({'name':tool,'arguments':deepcopy(args),'result':deepcopy(r)});return r
            family=sid[4];actions=[]
            if family=='F':
                for j in o['journeys']:
                    if case in ['hidden_ID','late_read']:flights=initial['flights']['flights']
                    else:
                        query={k:j[k] for k in ['origin','destination','date']}
                        if case=='city_alias':query.update(origin='TP Hồ Chí Minh' if j['origin']=='SGN' else 'Đà Nẵng',destination='Đà Nẵng' if j['destination']=='DAD' else 'TP Hồ Chí Minh')
                        flights=call('flights.search',**query)['flights']
                    chosen=choose_flight(flights,j)
                    args={'flight_id':chosen['id'],'passengers':j['passengers'],'seat_class':j['seat_class']}
                    if case=='default_economy':args.pop('seat_class')
                    if case=='null_seat_class':args['seat_class']=None
                    if case=='extra_reads':call('flights.my_bookings')
                    if case=='sequential_legs':call('flights.book',**args)
                    else:actions.append({'name':'flights.book','arguments':args})
                if case=='wrong_criterion':actions[0]['arguments']['flight_id']='tr7_flight_63' if actions[0]['arguments']['flight_id']!='tr7_flight_63' else 'tr7_flight_21'
                if case=='stale_price':actions[0]['arguments']['flight_id']='tr7_flight_63'
                if case=='wrong_count':actions[0]['arguments']['passengers']=1
                if case=='omit_return':actions=actions[:1]
                if case=='reverse_writes':actions.reverse()
                if case=='duplicate_booking':actions.append(deepcopy(actions[0]))
            elif family=='C':
                if case in ['hidden_ID','late_read']:chats=initial['chat_ott']['chats']
                else:chats=call('chat_ott.list_chats')['chats']
                dest=next(r for r in chats if r['name']==o['destination']);source=next((r for r in chats if r['name']==o['source']),None);content=o['content']
                if source is not None:
                    if case in ['hidden_content','hidden_ID','late_read']:content=next(r for r in initial['chat_ott']['chats'] if r['name']==o['source'])['messages'][-1]['content']
                    else:content=call('chat_ott.read_chat',chat_id=source['id'],**({'limit':1} if case=='last_only' else {}))['messages'][-1]['content']
                if case=='extra_reads':call('chat_ott.list_chats')
                for op in o['operations']:
                    if op=='text':actions.append({'name':'chat_ott.send_message','arguments':{'chat_id':dest['id'],'content':content}})
                    if op=='location':actions.append({'name':'chat_ott.send_location','arguments':{'chat_id':dest['id']}})
                    if op in ['voice','video']:actions.append({'name':'chat_ott.call','arguments':{'chat_id':dest['id'],'video':op=='video'}})
                if case=='voice_default':actions[0]['arguments'].pop('video')
                if case=='null_video':actions[0]['arguments']['video']=None
                if case=='omit_video':actions[0]['arguments'].pop('video')
                if case=='wrong_recipient':actions[0]['arguments']['chat_id']='tr7_chat_25'
                if case=='location_as_text':actions=[{'name':'chat_ott.send_message','arguments':{'chat_id':dest['id'],'content':'Vị trí hiện tại'}}]
                if case=='voice_as_video':actions[0]['arguments']['video']=True
                if case=='stale_content':actions[0]['arguments']['content']='Nhận ở cửa Nam; không qua cửa Tây.'
                if case=='omit_location':actions=actions[:1]
                if case=='extra_call':actions.append({'name':'chat_ott.call','arguments':{'chat_id':dest['id'],'video':False}})
                if case=='reverse_writes':actions.reverse()
            elif family=='D':
                add=deepcopy(o['add']);schedule=None
                if case in ['add_before_lookup','log_new_schedule']:
                    new=call('medication.add',**add)
                if o['existing'] is not None:
                    schedules=initial['medication']['schedules'] if case in ['hidden_ID','late_read'] else call('medication.list')['schedules']
                    schedule=next(r for r in schedules if r['name']==o['existing'])
                if add and case not in ['add_before_lookup','log_new_schedule']:actions.append({'name':'medication.add','arguments':add})
                if schedule is not None:
                    if o['remove']:actions.append({'name':'medication.remove','arguments':{'schedule_id':schedule['id']}})
                    else:actions.append({'name':'medication.log_taken','arguments':{'schedule_id':schedule['id'],**({'time':o['log']} if o['log'] is not None else {})}})
                if case=='extra_reads':call('medication.list')
                if case in ['daily_default','omit_weekdays']:actions[0]['arguments'].pop('days')
                if case=='null_days':actions[0]['arguments']['days']=None
                if case=='null_time':actions[-1]['arguments']['time']=None
                if case=='times_reverse':actions[0]['arguments']['times'].reverse()
                if case=='split_schedules':actions=[{'name':'medication.add','arguments':{**add,'times':[t]}} for t in add['times']]
                if case=='wrong_time':actions[-1]['arguments']['time']=s['agent_visible']['context']['current_time']
                if case=='wrong_schedule':actions[-1]['arguments']['schedule_id']='tr7_med_31' if schedule['id']!='tr7_med_31' else 'tr7_med_64'
                if case=='log_instead_remove':actions=[{'name':'medication.log_taken','arguments':{'schedule_id':schedule['id'],'time':'2027-01-15T08:00:00+07:00'}}]
                if case=='omit_log':actions=actions[:1]
                if case=='reverse_writes':actions.reverse()
                if case=='log_new_schedule':actions[-1]['arguments']['schedule_id']=new['id']
                if case=='repeat_remove':actions.append(deepcopy(actions[0]))
            for a in actions:call(a['name'],**a['arguments'])
            if case=='late_read':
                if family=='F':
                    for j in o['journeys']:call('flights.search',**{k:j[k] for k in ['origin','destination','date']})
                if family=='C':
                    call('chat_ott.list_chats')
                    if source is not None:call('chat_ott.read_chat',chat_id=source['id'])
                if family=='D':call('medication.list')
            runtime_final=session.get_state();final=deepcopy(runtime_final)
            if case=='old_booking_snapshot':final['flights']['bookings'][0]['status']='cancelled'
            if case=='source_history_snapshot':final['chat_ott']['chats'][0]['messages'][0]['content']='Verifier-only changed history'
            if case=='dose_history_snapshot':final['medication']['logs'][0]['time']='2027-01-01T00:00:00+07:00'
            v=verify(initial,s,calls,final,kinds)
            assert v['verdict']==expected,(sid,case,v)
            if reason:assert reason in v['authorization']+v['state']+v['grounding'],(sid,case,v)
            if case in ['hidden_ID','late_read']:assert not v['state']
            assert session.log==calls and session.get_tool_calls()==[{k:c[k] for k in ['name','arguments']} for c in calls]
            assert ex.db==original_db and ex.open(key).get_state()==initial
            rows.append({'scenario_id':sid,'lineage_id':s['lineage_id'],'trace_case':case,'ordering':'reversed' if reverse else 'original','initial_fixture_ref':key,
                         'expected_verdict':expected,'required_reason':reason,'calls':calls,'final_state':final,'verdict':v,'evidence_kind':'verifier_only_snapshot' if case.endswith('_snapshot') else 'actual_runtime_trace',
                         'construction':'hand_authored_positive' if expected=='pass' else 'deliberate_counterexample'})
            if case.endswith('_snapshot'):rows[-1]['actual_runtime_final_state']=runtime_final
        for sid in sm:replay(sid);replay(sid,'extra_reads');replay(sid,reverse=True)
        for sid in [s for s in sm if s[4]=='F']:replay(sid,'city_alias')
        for sid in ['TR7_F_EARLY','TR7_F_CHEAP','TR7_F_THREE','TR7_F_EXPLICIT']:replay(sid,'default_economy')
        replay('TR7_F_RETURN','sequential_legs');replay('TR7_F_RETURN','reverse_writes')
        for sid in ['TR7_F_EARLY','TR7_F_CHEAP','TR7_F_CUTOFF']:replay(sid,'wrong_criterion',expected='reject',reason='authorized_action_or_count')
        for sid,case in [('TR7_F_PRICE_CHANGED','stale_price'),('TR7_F_BUSINESS','default_economy'),('TR7_F_THREE','wrong_count'),('TR7_F_RETURN','omit_return'),('TR7_F_EARLY','duplicate_booking')]:
            replay(sid,case,expected='reject',reason='authorized_action_or_count')
        for sid in ['TR7_F_EARLY','TR7_F_CHEAP','TR7_F_EXPLICIT','TR7_F_PRICE_CHANGED']:
            for case in ['hidden_ID','late_read']:replay(sid,case,expected='reject',reason='flight_selection_before_booking')
        if 'TR7_C_TEXT' in sm:
            replay('TR7_C_VOICE','voice_default');replay('TR7_C_TWO','reverse_writes')
            for sid in ['TR7_C_FORWARD','TR7_C_FORWARD_CHANGED']:replay(sid,'last_only')
            for sid,case in [('TR7_C_TEXT','wrong_recipient'),('TR7_C_LOCATION','location_as_text'),('TR7_C_VOICE','voice_as_video'),
                             ('TR7_C_VIDEO','omit_video'),('TR7_C_FORWARD_CHANGED','stale_content'),('TR7_C_OTHER','wrong_recipient'),
                             ('TR7_C_TWO','omit_location'),('TR7_C_TEXT','extra_call')]:replay(sid,case,expected='reject',reason='authorized_action_or_count')
            for sid in ['TR7_C_TEXT','TR7_C_LOCATION','TR7_C_VOICE','TR7_C_VIDEO']:
                for case in ['hidden_ID','late_read']:replay(sid,case,expected='reject',reason='destination_chat_before_write')
            for sid in ['TR7_C_FORWARD','TR7_C_FORWARD_CHANGED']:replay(sid,'hidden_content',expected='reject',reason='source_content_before_forward')
            replay('TR7_D_DAILY','daily_default');replay('TR7_D_TWICE','times_reverse');replay('TR7_D_BOTH','reverse_writes')
            replay('TR7_D_BOTH','add_before_lookup');replay('TR7_D_REMOVE','repeat_remove')
            for sid,case in [('TR7_D_WEEKDAYS','omit_weekdays'),('TR7_D_TWICE','split_schedules'),('TR7_D_LOG','wrong_time'),('TR7_D_REMOVE','log_instead_remove'),
                             ('TR7_D_OTHER','wrong_schedule'),('TR7_D_UNTIMED','wrong_time'),('TR7_D_BOTH','omit_log')]:replay(sid,case,expected='reject',reason='authorized_action_or_count')
            replay('TR7_D_BOTH','log_new_schedule',expected='reject',reason='authorized_action_or_count')
            for sid in ['TR7_D_LOG','TR7_D_REMOVE','TR7_D_OTHER','TR7_D_UNTIMED']:
                for case in ['hidden_ID','late_read']:replay(sid,case,expected='reject',reason='schedule_ID_before_write')
            for sid,case in [('TR7_F_EARLY','old_booking_snapshot'),('TR7_C_FORWARD','source_history_snapshot'),('TR7_D_REMOVE','dose_history_snapshot')]:
                replay(sid,case,expected='reject',reason='goal_or_frame')
            for sid,case in [('TR7_F_EARLY','null_seat_class'),('TR7_C_VOICE','null_video'),
                             ('TR7_D_DAILY','null_days'),('TR7_D_UNTIMED','null_time')]:
                replay(sid,case)
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
            'limitations':['Gold before trace; no model/semantics interpreter or official call matcher.','Intended train only, export ineligible. Email recommendation and independent checkpoint review in handoff.']}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(status));print('Replay seconds:',result['replay_wall_seconds'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/synthetic/train_wave_07_replay/replay.json')
    args=parser.parse_args();run(args.archive,args.output)
