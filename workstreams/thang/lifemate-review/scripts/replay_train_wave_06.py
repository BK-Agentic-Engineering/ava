"""Bounded Wave 06 hand-authored replay; no model, generator or replacement harness."""
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
from replay_train_wave_05 import validate as validate_previous


def fixture(w,s):
    state=deepcopy(w['initial_state']);patch=w['variants'].get(s['fixture_variant'],{})
    if 'month_kwh' in patch:state['home_energy']['usage']['month']['kwh']=patch['month_kwh']
    if 'saved' in patch:state['maps']['saved_places'].append(deepcopy(patch['saved']))
    if 'progress' in patch:state['learning']['courses'][0]['progress_minutes']=patch['progress']
    return state


def validate(d,docs=None):
    if docs is None:docs=[yaml.load(p.read_text(encoding='utf-8'),Loader=StrictLoader) for p in sorted((ROOT/'data/synthetic/design').glob('*.yaml'))]
    inventory=validate_previous(next(p for p in docs if p['version']=='train_wave_05'),docs)
    assert d['split']=='train' and d['status']=='spec_only' and d['exportable'] is False,'Wave06 status'
    sm={s['scenario_id']:s for s in d['scenarios']};wm={w['world_id']:w for w in d['worlds']}
    for w in wm.values():
        assert w['split']=='train' and w['design_base'] in sm
        if w['origin']=='train_derivative':
            assert w['lineage_id']=='TRAIN_FITNESS_DATES_04' and w['ancestry']['parent_scenario_ids']==['TR4_F_LATEST','TR4_F_BOTH']
        else:
            assert w['origin']=='independently_authored' and w['ancestry']==dict(parent_world_ids=[],parent_scenario_ids=[],parent_lineage_ids=[])
            assert not any(p['lineage_id']==w['lineage_id'] and not any(p.get('ancestry',{}).get(k) for k in ['parent_world_ids','parent_scenario_ids','parent_lineage_ids']) for other in docs if other['version']!=d['version'] for p in other['worlds'])
    for s in sm.values():
        assert s['status']=='spec_only' and s['exportable'] is False,'Wave06 scenario status'
        assert s['agent_visible']['allowed_tools']==wm[s['world_id']]['relevant_tools']
        def private(v):
            if isinstance(v,dict):
                for k,value in v.items():
                    if k=='id':assert value not in canonical(s['agent_visible'])
                    else:private(value)
            elif isinstance(v,list):
                for value in v:private(value)
        state=fixture(wm[s['world_id']],s);private(state)
        if s['scenario_id'][4]=='E':
            o=s['oracle_draft']
            if o['field']:
                source=state['home_energy']['alert_threshold_kwh'] if o['field']=='alert_threshold_kwh' else state['home_energy']['usage'][o['period']]['kwh']
                assert source*o['multiply']+o['add']==o['threshold']
    assert sm['TR6_E_MONTH']['agent_visible']==sm['TR6_E_CHANGED']['agent_visible']
    x=fixture(wm[sm['TR6_E_MONTH']['world_id']],sm['TR6_E_MONTH']);y=fixture(wm[sm['TR6_E_CHANGED']['world_id']],sm['TR6_E_CHANGED'])
    y['home_energy']['usage']['month']['kwh']=x['home_energy']['usage']['month']['kwh'];assert x==y
    if 'TR6_M_SAVE' in sm:
        assert sm['TR6_M_SAVE']['agent_visible']==sm['TR6_M_EXISTING']['agent_visible']
        x=fixture(wm[sm['TR6_M_SAVE']['world_id']],sm['TR6_M_SAVE']);y=fixture(wm[sm['TR6_M_EXISTING']['world_id']],sm['TR6_M_EXISTING']);y['maps']['saved_places'].pop();assert x==y
        assert sm['TR6_L_TOTAL']['agent_visible']==sm['TR6_L_CHANGED']['agent_visible']
        x=fixture(wm[sm['TR6_L_TOTAL']['world_id']],sm['TR6_L_TOTAL']);y=fixture(wm[sm['TR6_L_CHANGED']['world_id']],sm['TR6_L_CHANGED']);y['learning']['courses'][0]['progress_minutes']=40;assert x==y
        for s in sm.values():
            if s['scenario_id'][4]=='L':
                o=s['oracle_draft'];course=next(r for r in fixture(wm[s['world_id']],s)['learning']['courses'] if r['name']==o['course'])
                assert o['total_after']==course['progress_minutes']+(o['delta'] or 0)
                if o['mode']=='total':assert o['total_after']==o['value']
    inventory['near_duplicate_review']='Wave06 handoff: source transforms as train derivative, place upsert and cumulative progress. Controlled repeated inputs; TR1_E_SEND pending.'
    return inventory


def verify(initial,s,calls,final,kinds):
    o=s['oracle_draft'];family=s['scenario_id'][4];expected=deepcopy(initial);reasons={'state':[],'trace':[],'grounding':[]};seen=set()
    def created(app,key,payloads):
        old={r['id'] for r in initial[app][key]};added=[r for r in final[app][key] if r['id'] not in old]
        if Counter(canonical({k:v for k,v in r.items() if k!='id'}) for r in added)!=Counter(map(canonical,payloads)):reasons['state'].append('new_payload_or_count')
        expected[app][key].extend(deepcopy(added))
    if family=='E':
        expected['home_energy']['alert_threshold_kwh']=o['threshold']
        intended=[{'name':'home_energy.set_alert','arguments':{'threshold_kwh':o['threshold']}}];required={'energy'} if o['field'] else set()
    elif family=='M':
        places={r['id']:r for r in initial['maps']['places'] if any(r['name']==v['name'] and r['address']==v['address'] for v in o['saves'])};required=set(places);intended=[];new_payloads=[]
        for save in o['saves']:
            place=next(r for r in places.values() if r['name']==save['name'] and r['address']==save['address'])
            intended.append({'name':'maps.save_place','arguments':{'place_id':place['id'],'label':save['label']}})
            existing=next((r for r in expected['maps']['saved_places'] if r['place_id']==place['id']),None)
            if existing is not None:existing['label']=save['label']
            else:new_payloads.append({'place_id':place['id'],'label':save['label']})
        created('maps','saved_places',new_payloads)
    elif family=='L':
        course=next(r for r in initial['learning']['courses'] if r['name']==o['course']);required={course['id']};intended=[]
        next(r for r in expected['learning']['courses'] if r['id']==course['id'])['progress_minutes']=o['total_after']
        progress=[];lessons=[]
        if o['delta'] is not None:
            progress=[{'course_id':course['id'],'minutes':o['delta']}];intended.append({'name':'learning.log_progress','arguments':progress[0]})
        if o['lesson'] is not None:
            lessons=[{'course_id':course['id'],'time':o['lesson'],'status':'scheduled'}];intended.append({'name':'learning.schedule_lesson','arguments':{'course_id':course['id'],'time':o['lesson']}})
        created('learning','progress',progress);created('learning','lessons',lessons)
    else:raise AssertionError(family)
    if final!=expected:reasons['state'].append('goal_or_frame')
    writes=[]
    for c in calls:
        name,args,result=c['name'],c['arguments'],c['result'];permitted=name in s['agent_visible']['allowed_tools']
        if not permitted:reasons['trace'].append('unpermitted_attempt')
        if permitted and kinds.get(name)=='read' and result.get('ok') is True and result.get('done') is not False:
            if family=='E' and name=='home_energy.get_usage':
                period=args.get('period');actual=initial['home_energy']['usage'].get(period)
                if actual is not None and result.get('period')==period and result.get('usage')==actual and result.get('alert_threshold_kwh')==initial['home_energy']['alert_threshold_kwh']:
                    if o['field']=='alert_threshold_kwh' or o['field']=='usage.kwh' and period==o['period']:seen.add('energy')
            if family=='M' and name=='maps.search_place':
                for r in result.get('places',[]):
                    if r.get('id') in places and r==places[r['id']]:seen.add(r['id'])
            if family=='L' and name=='learning.list_courses' and course in result.get('courses',[]):seen.add(course['id'])
        if kinds.get(name,'write')=='write':
            writes.append(canonical({k:c[k] for k in ['name','arguments']}))
            consuming={args.get('place_id')} if family=='M' else required
            if not consuming<=seen:reasons['grounding'].append('source_before_consuming_write')
        if name=='sys.ask_missing_info':reasons['trace'].append('unjustified_ask')
    if Counter(writes)!=Counter(map(canonical,intended)):reasons['trace'].append('authorized_action_or_count')
    return {'verdict':'reject' if any(reasons.values()) else 'pass',**{k:sorted(set(v)) for k,v in reasons.items()}}


def run(archive,output):
    start=perf_counter();path=ROOT/'data/synthetic/design/train_wave_06.yaml';before=path.read_bytes();d=yaml.load(before.decode('utf-8'),Loader=StrictLoader);inventory=validate(d)
    sm={s['scenario_id']:s for s in d['scenarios']};wm={w['world_id']:w for w in d['worlds']};fixtures={}
    for sid,s in sm.items():
        state=fixture(wm[s['world_id']],s);state['sys']={};state['notes']={'notes':[{'id':'tr6_guard','title':'Giữ riêng','content':'Không sửa.'}]}
        state['_meta']={'tools':s['agent_visible']['allowed_tools'],'current_time':s['agent_visible']['context']['current_time']};fixtures[sid]=state;reverse=deepcopy(state)
        for app in wm[s['world_id']]['initial_state']:
            for value in reverse[app].values():
                if isinstance(value,list):value.reverse()
        fixtures[sid+'/reversed']=reverse
    p=d['provenance'];files=['__init__.py','executor.py','validate.py','utils.py','apps/__init__.py','apps/base.py','apps/sys.py','apps/home_energy.py','apps/calculator.py','apps/maps.py','apps/learning.py']
    output.parent.mkdir(parents=True,exist_ok=True);rows=[]
    with tempfile.TemporaryDirectory(prefix='wave06_runtime_',dir=output.parent) as temp:
        temp=Path(temp)
        with zipfile.ZipFile(archive) as z:
            for name in files:
                target=temp/'zaic_tools'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(p['runtime_root']+name))
            cat=temp/'catalog.json';cat.write_bytes(z.read(p['catalog_member']))
        catalog=json.loads(cat.read_text(encoding='utf-8'));assert catalog['schema_version']==p['schema'];tools={t['name']:t for a in catalog['apps'] for t in a['tools']};kinds={n:t['kind'] for n,t in tools.items()}
        assert tools['home_energy.set_alert']['parameters']['required']==['threshold_kwh']
        assert tools['maps.save_place']['parameters']['required']==['place_id','label']
        assert tools['learning.log_progress']['parameters']['required']==['course_id','minutes']
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
                assert r.get('ok') is True and r.get('done') is not False,(sid,case,r)
                calls.append({'name':tool,'arguments':deepcopy(args),'result':deepcopy(r)});return r
            actions=[];family=sid[4]
            if family=='E':
                if o['field']:
                    period=o['period'] or ('week' if case=='other_period' else 'month')
                    if case in ['hidden_value','late_read']:result={'usage':initial['home_energy']['usage'][period],'alert_threshold_kwh':initial['home_energy']['alert_threshold_kwh']}
                    else:result=call('home_energy.get_usage',period='today' if case=='wrong_period' else period)
                    source=result['alert_threshold_kwh'] if o['field']=='alert_threshold_kwh' else result['usage']['kwh']
                    value=source*o['multiply']+o['add']
                    if case=='calculator':value=call('calculator.calculate',expression=f'({source}*{o["multiply"]})+{o["add"]}')['value']
                    if case=='extra_reads':call('home_energy.get_usage',period=period)
                else:
                    value=o['threshold']  # Supplied literal, no private-source lookup.
                    if case=='extra_reads':call('home_energy.get_usage',period='month')
                if case=='percent_only':value=source*0.2
                if case=='stale_value':value=230
                if case=='wrong_field':value=result['usage']['kwh']+50
                if case=='literal_wrong':value=300
                assert int(value)==value,'No implicit rounding policy'
                actions=[{'name':'home_energy.set_alert','arguments':{'threshold_kwh':int(value)}}]
            elif family=='M':
                if case in ['hidden_ID','late_read']:places=initial['maps']['places']
                elif case=='sequential_lookup':places=[]
                else:places=call('maps.search_place',query='*' if case=='all_places' else o['saves'][0]['name'],**({'near':o['saves'][0]['address']} if case=='near_filter' else {}))['places']
                if case=='extra_reads':call('maps.search_place',query='*')
                for save in o['saves']:
                    candidates=call('maps.search_place',query=save['name'],near=save['address'])['places'] if case=='sequential_lookup' else places
                    matches=[r for r in candidates if r['name']==save['name'] and r['address']==save['address']];assert len(matches)==1
                    action={'name':'maps.save_place','arguments':{'place_id':matches[0]['id'],'label':save['label']}}
                    if case=='sequential_lookup':call(action['name'],**action['arguments'])
                    else:actions.append(action)
                if case=='first_result':actions[0]['arguments']['place_id']=places[0]['id']
                if case=='wrong_label':actions[0]['arguments']['label']='Điểm nhận'
                if case=='omit_second':actions=actions[:1]
                if case=='swap_labels':actions[0]['arguments']['label'],actions[1]['arguments']['label']=actions[1]['arguments']['label'],actions[0]['arguments']['label']
                if case=='duplicate_save':actions.append(deepcopy(actions[-1]))
                if case=='reverse_writes':actions.reverse()
            elif family=='L':
                if case in ['hidden_ID','late_read']:courses=initial['learning']['courses']
                else:courses=call('learning.list_courses')['courses']
                course=next(r for r in courses if r['name']==o['course'])
                if case=='extra_reads':call('learning.list_courses')
                if o['delta'] is not None:
                    delta=o['value']-course['progress_minutes'] if o['mode']=='total' else o['value']
                    actions.append({'name':'learning.log_progress','arguments':{'course_id':course['id'],'minutes':delta}})
                if o['lesson'] is not None:actions.append({'name':'learning.schedule_lesson','arguments':{'course_id':course['id'],'time':o['lesson']}})
                if case=='total_as_delta':actions[0]['arguments']['minutes']=o['value']
                if case=='stale_delta':actions[0]['arguments']['minutes']=20
                if case=='sum_as_delta':actions[0]['arguments']['minutes']=course['progress_minutes']+o['value']
                if case=='extra_enroll':actions.append({'name':'learning.enroll','arguments':{'course_id':course['id']}})
                if case=='log_instead_schedule':actions=[{'name':'learning.log_progress','arguments':{'course_id':course['id'],'minutes':25}}]
                if case=='omit_lesson':actions=actions[:1]
                if case=='omit_progress':actions=actions[1:]
                if case=='reverse_writes':actions.reverse()
            for a in actions:call(a['name'],**a['arguments'])
            if case=='late_read':
                if family=='E':call('home_energy.get_usage',period=o['period'] or 'month')
                if family=='M':call('maps.search_place',query='*')
                if family=='L':call('learning.list_courses')
            runtime_final=session.get_state();final=deepcopy(runtime_final)
            if case=='usage_snapshot':final['home_energy']['usage']['week']['cost']=1
            if case=='duplicate_saved_snapshot':
                copy=deepcopy(next(r for r in final['maps']['saved_places'] if r['place_id']=='tr6_place_22'));copy['id']='verifier_only_duplicate';final['maps']['saved_places'].append(copy)
            if case=='old_ledger_snapshot':final['learning']['progress'][0]['minutes']=1
            v=verify(initial,s,calls,final,kinds)
            assert v['verdict']==expected,(sid,case,v)
            if reason:assert reason in v['trace']+v['state']+v['grounding'],(sid,case,v)
            if case in ['hidden_value','hidden_ID','late_read']:assert not v['state']
            assert session.log==calls and session.get_tool_calls()==[{k:c[k] for k in ['name','arguments']} for c in calls]
            assert ex.db==original_db and ex.open(key).get_state()==initial
            rows.append({'scenario_id':sid,'lineage_id':s['lineage_id'],'trace_case':case,'ordering':'reversed' if reverse else 'original','initial_fixture_ref':key,
                         'expected_verdict':expected,'required_reason':reason,'calls':calls,'final_state':final,'verdict':v,'evidence_kind':'verifier_only_snapshot' if case.endswith('_snapshot') else 'actual_runtime_trace',
                         'construction':'hand_authored_positive' if expected=='pass' else 'deliberate_counterexample'})
            if case.endswith('_snapshot'):rows[-1]['actual_runtime_final_state']=runtime_final
        for sid in sm:replay(sid);replay(sid,'extra_reads');replay(sid,reverse=True)
        for sid in [s for s in sm if s[4]=='E' and s!='TR6_E_LITERAL']:replay(sid,'calculator')
        replay('TR6_E_CURRENT','other_period')
        for sid,case in [('TR6_E_MONTH','wrong_period'),('TR6_E_CHANGED','stale_value'),('TR6_E_WEEK','wrong_period'),('TR6_E_PERCENT','percent_only'),('TR6_E_CURRENT','wrong_field'),('TR6_E_LITERAL','literal_wrong')]:
            replay(sid,case,expected='reject',reason='authorized_action_or_count')
        for sid in ['TR6_E_MONTH','TR6_E_CHANGED','TR6_E_WEEK','TR6_E_PERCENT','TR6_E_CURRENT']:
            for case in ['hidden_value','late_read']:replay(sid,case,expected='reject',reason='source_before_consuming_write')
        if 'TR6_M_SAVE' in sm:
            for sid in [s for s in sm if s[4]=='M']:replay(sid,'all_places');replay(sid,'sequential_lookup')
            for sid in ['TR6_M_SAVE','TR6_M_OTHER','TR6_M_EXISTING','TR6_M_LABEL']:replay(sid,'near_filter')
            for sid in ['TR6_M_TWO','TR6_M_SAME_LABEL']:replay(sid,'reverse_writes')
            for sid,case in [('TR6_M_SAVE','first_result'),('TR6_M_LABEL','wrong_label'),('TR6_M_TWO','swap_labels'),('TR6_M_SAME_LABEL','omit_second'),('TR6_M_EXISTING','duplicate_save')]:
                replay(sid,case,expected='reject',reason='authorized_action_or_count')
            for sid in ['TR6_M_SAVE','TR6_M_OTHER','TR6_M_EXISTING']:
                for case in ['hidden_ID','late_read']:replay(sid,case,expected='reject',reason='source_before_consuming_write')
            for sid,case in [('TR6_L_ADD','sum_as_delta'),('TR6_L_TOTAL','total_as_delta'),('TR6_L_CHANGED','stale_delta'),
                             ('TR6_L_OTHER','extra_enroll'),('TR6_L_SCHEDULE','log_instead_schedule'),('TR6_L_BOTH','omit_lesson'),('TR6_L_BOTH','omit_progress')]:
                replay(sid,case,expected='reject',reason='authorized_action_or_count')
            for sid in [s for s in sm if s[4]=='L']:
                for case in ['hidden_ID','late_read']:replay(sid,case,expected='reject',reason='source_before_consuming_write')
            replay('TR6_L_BOTH','reverse_writes')
            for sid,case in [('TR6_E_MONTH','usage_snapshot'),('TR6_M_EXISTING','duplicate_saved_snapshot'),('TR6_L_TOTAL','old_ledger_snapshot')]:
                replay(sid,case,expected='reject',reason='new_payload_or_count' if sid[4]=='M' else 'goal_or_frame')
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
            'limitations':['Reviewed gold before trace; no model, semantics interpreter or official scorer.','Intended train only; TR1_E_SEND split and independent semantic/harness/template/export review pending.']}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(status));print('Replay seconds:',result['replay_wall_seconds'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/synthetic/train_wave_06_replay/replay.json')
    args=parser.parse_args();run(args.archive,args.output)
