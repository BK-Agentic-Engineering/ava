"""Bounded hand-authored Wave 05; local Executor, no model or general generator."""
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
from replay_train_wave_04 import validate as validate_previous


def fixture(w,s):
    state=deepcopy(w['initial_state']);patch=w['variants'].get(s['fixture_variant'],{})
    for i,key in [(0,'dryer_status'),(1,'washer_status')]:
        if key in patch:
            status=patch[key];state['appliances']['appliances'][i]['state']={'status':status,'cycle':'eco' if i==1 and status=='running' else 'normal' if status=='running' else None,'delay_minutes':0}
    return state


def validate(d,docs=None):
    if docs is None:docs=[yaml.load(p.read_text(encoding='utf-8'),Loader=StrictLoader) for p in sorted((ROOT/'data/synthetic/design').glob('*.yaml'))]
    inventory=validate_previous(next(p for p in docs if p['version']=='train_wave_04'),docs)
    assert d['split']=='train' and d['status']=='spec_only' and d['exportable'] is False,'Wave 05 status'
    sm={s['scenario_id']:s for s in d['scenarios']};wm={w['world_id']:w for w in d['worlds']}
    for w in wm.values():
        assert w['split']=='train' and w['design_base'] in sm
        if w['origin']=='train_derivative':
            assert w['lineage_id']=='TRAIN_ALARM_EDIT_02'
            assert set(w['ancestry']['parent_scenario_ids'])=={'TR2_A_TIME','TR2_A_TIME_LABEL','TR1_N_COPY'}
        else:
            assert w['origin']=='independently_authored' and w['ancestry']==dict(parent_world_ids=[],parent_scenario_ids=[],parent_lineage_ids=[])
            assert not any(p['lineage_id']==w['lineage_id'] and not any(p.get('ancestry',{}).get(k) for k in ['parent_world_ids','parent_scenario_ids','parent_lineage_ids']) for other in docs if other['version']!=d['version'] for p in other['worlds'])
    for s in sm.values():
        assert s['status']=='spec_only' and s['exportable'] is False,'Wave 05 scenario status'
        assert s['agent_visible']['allowed_tools']==wm[s['world_id']]['relevant_tools']
        def hidden(v):
            if isinstance(v,dict):
                for k,value in v.items():
                    if k=='id':assert value not in canonical(s['agent_visible'])
                    else:hidden(value)
            elif isinstance(v,list):
                for value in v:hidden(value)
        state=fixture(wm[s['world_id']],s);hidden(state)
        if s['scenario_id'][4]=='A':
            o=s['oracle_draft'];records=[next(r for r in state['appliances']['appliances'] if r['name']==name) for name in o['targets']]
            ready=[r['id'] for r in records if r['state']['status']=='idle']
            intended=ready if o['policy']=='each_ready' else ready if len(ready)==len(records) else []
            assert o['start_ids']==intended
            assert (o['outcome']=='execute')==bool(intended)
    partial=[sm[k] for k in ['TR5_A_PARTIAL_BUSY','TR5_A_PARTIAL_READY','TR5_A_NEITHER','TR5_A_WASHER_ONLY']]
    assert all(s['agent_visible']==partial[0]['agent_visible'] for s in partial)
    assert sm['TR5_A_ALL_BUSY']['agent_visible']==sm['TR5_A_ALL_READY']['agent_visible']
    assert sm['TR5_A_PARTIAL_BUSY']['fixture_variant']==sm['TR5_A_ALL_BUSY']['fixture_variant']
    x=fixture(wm[partial[0]['world_id']],partial[0]);y=fixture(wm[partial[1]['world_id']],partial[1]);y['appliances']['appliances'][1]=deepcopy(x['appliances']['appliances'][1]);assert x==y
    inventory['near_duplicate_review']='Wave 05 handoff: explicit partial authorization, bill/autopay and declared train contact derivative; controlled repeats retained; TR1_E_SEND pending.'
    return inventory


def verify(initial,s,calls,final,kinds):
    o=s['oracle_draft'];family=s['scenario_id'][4];expected=deepcopy(initial);reasons={'state':[],'trace':[],'grounding':[]};seen=set()
    def created(app,key,payloads):
        old={r['id'] for r in initial[app][key]};added=[r for r in final[app][key] if r['id'] not in old]
        if Counter(canonical({k:v for k,v in r.items() if k!='id'}) for r in added)!=Counter(map(canonical,payloads)):reasons['state'].append('new_payload_or_count')
        expected[app][key].extend(deepcopy(added))
    if family=='A':
        records={r['id']:r for r in initial['appliances']['appliances'] if r['name'] in o['targets']}
        intended=[{'name':'appliances.start_cycle','arguments':{'appliance_id':i,'cycle':'normal','delay_minutes':0}} for i in o['start_ids']]
        for r in expected['appliances']['appliances']:
            if r['id'] in o['start_ids']:r['state'].update(status='running',cycle='normal',delay_minutes=0)
        required=set(records)
    elif family=='B':
        bill=next((r for r in initial['bill_payment']['bills'] if r['type']==o['pay_type'] and not r['paid']),None);required=set();intended=[]
        if bill:
            required.add(bill['id']);next(r for r in expected['bill_payment']['bills'] if r['id']==bill['id']).update(paid=True,paid_with=o['source'])
            intended.append({'name':'bill_payment.pay','arguments':{'bill_id':bill['id'],'source':o['source']}})
            if o['source']=='ewallet':required.add('wallet')
        if o['autopay']:
            rule=o['autopay'];next(r for r in expected['bill_payment']['autopays'] if r['type']==rule['type'])['enabled']=rule['enabled']
            intended.append({'name':'bill_payment.schedule_autopay','arguments':rule})
        expected['ewallet']['balance']=o['wallet_after']
        tx=[] if not bill or o['source']!='ewallet' else [{'type':'bill_payment','bill_id':bill['id'],'amount':-bill['amount']}]
        created('ewallet','transactions',tx)
    elif family=='C':
        records={r['id']:r for r in initial['contacts']['contacts'] if r['name'] in o['targets']};required=set(records)
        for identity,patch in o['updates'].items():next(r for r in expected['contacts']['contacts'] if r['id']==identity).update(patch)
        intended=[{'name':'contacts.update','arguments':{'contact_id':identity,**patch}} for identity,patch in o['updates'].items()]
    else:raise AssertionError(family)
    if expected!=final:reasons['state'].append('goal_or_frame')
    def norm(name,args):
        args=deepcopy(args)
        if name=='appliances.start_cycle':args.setdefault('delay_minutes',0)
        if name=='contacts.update':
            return [canonical({'name':name,'contact_id':args.get('contact_id'),'field':k,'value':v}) for k,v in args.items() if k!='contact_id'] or [canonical({'empty':args})]
        return [canonical({'name':name,'arguments':args})]
    writes=[]
    for c in calls:
        name,args,result=c['name'],c['arguments'],c['result'];permitted=name in s['agent_visible']['allowed_tools']
        if not permitted:reasons['trace'].append('unpermitted_attempt')
        if permitted and kinds.get(name)=='read' and result.get('ok') is True and result.get('done') is not False:
            if family=='A' and name=='appliances.list':
                for r in result.get('appliances',[]):
                    if r.get('id') in records and r==records[r['id']]:seen.add(r['id'])
            if family=='B':
                if name=='bill_payment.list_bills' and bill and bill in result.get('bills',[]):seen.add(bill['id'])
                if name=='ewallet.get_balance' and result.get('balance')==initial['ewallet']['balance']:seen.add('wallet')
            if family=='C' and name in ['contacts.search','contacts.get']:
                for r in result.get('contacts',[]):
                    if r.get('id') in records and r==records[r['id']]:seen.add(r['id'])
        if kinds.get(name,'write')=='write':
            writes.extend(norm(name,args))
            consuming=required if family=='A' and o['policy']=='all_ready' else {args.get('appliance_id')} if family=='A' else required if family=='C' or name=='bill_payment.pay' else set()
            if not consuming<=seen:reasons['grounding'].append('source_before_consuming_write')
        if name=='sys.ask_missing_info':reasons['trace'].append('unjustified_ask')
    decision_resolved=required<=seen
    if family=='A' and o['policy']=='all_ready' and o['outcome']=='observe_no_write':
        # One observed running target disproves the conjunction. Idle-only,
        # unrelated or private fixture knowledge cannot establish that branch.
        decision_resolved=any(records[i]['state']['status']=='running' for i in seen)
    if not decision_resolved:reasons['grounding'].append('decision_observation_missing')
    if Counter(writes)!=Counter(token for a in intended for token in norm(a['name'],a['arguments'])):reasons['trace'].append('authorized_action_or_count')
    return {'verdict':'reject' if any(reasons.values()) else 'pass',**{k:sorted(set(v)) for k,v in reasons.items()}}


def run(archive,output):
    start=perf_counter();path=ROOT/'data/synthetic/design/train_wave_05.yaml';before=path.read_bytes();d=yaml.load(before.decode('utf-8'),Loader=StrictLoader);inventory=validate(d)
    sm={s['scenario_id']:s for s in d['scenarios']};wm={w['world_id']:w for w in d['worlds']};fixtures={}
    for sid,s in sm.items():
        state=fixture(wm[s['world_id']],s);state['sys']={};state['notes']={'notes':[{'id':'tr5_guard','title':'Giữ riêng','content':'Không sửa.'}]}
        state['_meta']={'tools':s['agent_visible']['allowed_tools'],'current_time':s['agent_visible']['context']['current_time']};fixtures[sid]=state
        reverse=deepcopy(state)
        for app in wm[s['world_id']]['initial_state']:
            for value in reverse[app].values():
                if isinstance(value,list):value.reverse()
        fixtures[sid+'/reversed']=reverse
    p=d['provenance'];files=['__init__.py','executor.py','validate.py','utils.py','apps/__init__.py','apps/base.py','apps/sys.py','apps/appliances.py','apps/bill_payment.py','apps/ewallet.py','apps/contacts.py']
    output.parent.mkdir(parents=True,exist_ok=True);rows=[]
    with tempfile.TemporaryDirectory(prefix='wave05_runtime_',dir=output.parent) as temp:
        temp=Path(temp)
        with zipfile.ZipFile(archive) as z:
            for name in files:
                target=temp/'zaic_tools'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(p['runtime_root']+name))
            cat=temp/'catalog.json';cat.write_bytes(z.read(p['catalog_member']))
        catalog=json.loads(cat.read_text(encoding='utf-8'));assert catalog['schema_version']==p['schema'];tools={t['name']:t for a in catalog['apps'] for t in a['tools']};kinds={n:t['kind'] for n,t in tools.items()}
        assert tools['appliances.start_cycle']['parameters']['required']==['appliance_id','cycle']
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
            if family=='A':
                if case in ['sequential_partial','start_before_all']:records=[]
                elif case in ['hidden_ID','late_read','missing_read']:records=initial['appliances']['appliances']
                elif case=='running_target_only':records=call('appliances.list',type='washer')['appliances']
                elif case=='idle_target_only':records=call('appliances.list',type='dryer')['appliances']
                elif case=='unrelated_running_projection':records=call('appliances.list',type='dishwasher')['appliances']
                elif case=='filtered':
                    records=list(call('appliances.list',type='dryer')['appliances'])+call('appliances.list',type='washer')['appliances']
                else:records=call('appliances.list')['appliances']
                limited=case in ['sequential_partial','start_before_all','running_target_only','idle_target_only','unrelated_running_projection']
                targets=[next(r for r in records if r['name']==name) for name in o['targets']] if not limited else []
                if case=='extra_reads':call('appliances.list')
                ready=[r for r in targets if r['state']['status']=='idle']
                chosen=ready if o['policy']=='each_ready' or len(ready)==len(targets) else []
                actions=[{'name':'appliances.start_cycle','arguments':{'appliance_id':r['id'],'cycle':'normal'}} for r in chosen]
                if case=='omit_ready':actions=[]
                if case=='omit_second':actions=actions[:1]
                if case=='unauthorized_partial':actions=[{'name':'appliances.start_cycle','arguments':{'appliance_id':targets[0]['id'],'cycle':'normal'}}]
                if case=='stop_busy':
                    busy=next(r for r in targets if r['state']['status']=='running');actions.append({'name':'appliances.stop','arguments':{'appliance_id':busy['id']}})
                if case=='force_restart':
                    busy=next(r for r in targets if r['state']['status']=='running');actions=[{'name':'appliances.stop','arguments':{'appliance_id':busy['id']}},{'name':'appliances.start_cycle','arguments':{'appliance_id':busy['id'],'cycle':'normal'}}]
                if case=='wrong_cycle':actions[0]['arguments']['cycle']='quick' if targets[0]['type']=='dryer' else 'eco'
                if case=='reverse_writes':actions.reverse()
                if case=='explicit_zero':
                    for a in actions:a['arguments']['delay_minutes']=0
                if case in ['sequential_partial','start_before_all']:
                    assert o['policy']=='each_ready' or case=='start_before_all'
                    for kind in ['dryer','washer']:
                        found=call('appliances.list',type=kind)['appliances'];assert len(found)==1
                        if found[0]['state']['status']=='idle':call('appliances.start_cycle',appliance_id=found[0]['id'],cycle='normal')
            elif family=='B':
                bill=None
                if case=='auto_before_reads':call('bill_payment.schedule_autopay',**o['autopay'])
                if o['pay_type']:
                    if case in ['hidden_ID','late_read']:bills=initial['bill_payment']['bills']
                    else:
                        if case=='wallet_first' and o['source']=='ewallet':call('ewallet.get_balance')
                        bills=call('bill_payment.list_bills',**({'type':o['pay_type']} if case=='filtered' else {}))['bills']
                        if o['source']=='ewallet' and case!='wallet_first':call('ewallet.get_balance')
                    bill=next(r for r in bills if r['type']==o['pay_type'] and not r['paid'])
                    actions.append({'name':'bill_payment.pay','arguments':{'bill_id':bill['id'],'source':o['source']}})
                if o['autopay'] and case!='auto_before_reads':actions.append({'name':'bill_payment.schedule_autopay','arguments':deepcopy(o['autopay'])})
                if case=='extra_reads':call('bill_payment.list_bills');call('ewallet.get_balance')
                if case=='auto_instead_pay':actions=[{'name':'bill_payment.schedule_autopay','arguments':{'type':'electricity','enabled':True}}]
                if case=='unauthorized_pay':
                    found=call('bill_payment.list_bills',type='electricity')['bills'];call('ewallet.get_balance')
                    actions.append({'name':'bill_payment.pay','arguments':{'bill_id':found[0]['id'],'source':'ewallet'}})
                if case=='wrong_source':actions[0]['arguments']['source']='bank' if o['source']=='ewallet' else 'ewallet'
                if case=='wrong_bill':
                    other=call('bill_payment.list_bills',type='electricity')['bills'][0];actions[0]['arguments']['bill_id']=other['id']
                if case=='omit_auto':actions=actions[:1]
                if case=='omit_pay':actions=actions[1:]
                if case=='wrong_polarity':actions[0]['arguments']['enabled']=True
                if case=='reverse_writes':actions.reverse()
            elif family=='C':
                if case in ['hidden_ID','late_read']:contacts=initial['contacts']['contacts']
                elif case=='filtered':
                    contacts=[]
                    for name in o['targets']:contacts.extend(call('contacts.search',query=name)['contacts'])
                else:contacts=call('contacts.search')['contacts']
                found={name:next(r for r in contacts if r['name']==name) for name in o['targets']}
                if case=='extra_reads':call('contacts.search')
                for identity,patch in o['updates'].items():
                    destination=next(r for r in found.values() if r['id']==identity);args={'contact_id':destination['id'],**deepcopy(patch)}
                    if o['copy_from']:args['email']=found[o['copy_from']]['email']
                    actions.append({'name':'contacts.update','arguments':args})
                if case=='detail_get':
                    for r in found.values():call('contacts.get',contact_id=r['id'])
                if case=='split_fields':
                    args=actions[0]['arguments'];actions=[{'name':'contacts.update','arguments':{'contact_id':args['contact_id'],k:v}} for k,v in args.items() if k!='contact_id']
                if case=='wrong_person':actions[0]['arguments']['contact_id']='tr5_ct_74' if actions[0]['arguments']['contact_id']=='tr5_ct_32' else 'tr5_ct_32'
                if case=='wrong_field':actions[0]['arguments']={'contact_id':actions[0]['arguments']['contact_id'],'phone':'0907556123'}
                if case=='omit_email':actions[0]['arguments'].pop('email')
                if case=='wrong_direction':
                    source=found[o['copy_from']];dest=next(r for name,r in found.items() if name!=o['copy_from'])
                    actions=[{'name':'contacts.update','arguments':{'contact_id':source['id'],'email':dest['email']}}]
                if case=='duplicate_field':actions.append(deepcopy(actions[-1]))
            for a in actions:call(a['name'],**a['arguments'])
            if case=='late_read':
                if family=='A':call('appliances.list')
                if family=='B':call('bill_payment.list_bills');call('ewallet.get_balance')
                if family=='C':call('contacts.search')
            runtime_final=session.get_state();final=deepcopy(runtime_final)
            if case=='other_machine_snapshot':next(r for r in final['appliances']['appliances'] if r['id']=='tr5_app_93')['state']['status']='running'
            if case=='prior_tx_snapshot':final['ewallet']['transactions'][0]['amount']=-1
            if case=='phone_snapshot':next(r for r in final['contacts']['contacts'] if r['id']=='tr5_ct_32')['phone']='0900000000'
            actual_calls=deepcopy(calls)
            if case=='unrelated_running_projection':calls[0]['result']['appliances'][0]['state']['status']='running'
            v=verify(initial,s,calls,final,kinds)
            assert v['verdict']==expected,(sid,case,v)
            if reason:assert reason in v['trace']+v['state']+v['grounding'],(sid,case,v)
            if case in ['hidden_ID','late_read']:assert not v['state']
            assert session.log==actual_calls and session.get_tool_calls()==[{k:c[k] for k in ['name','arguments']} for c in actual_calls]
            assert ex.db==original_db and ex.open(key).get_state()==initial
            rows.append({'scenario_id':sid,'lineage_id':s['lineage_id'],'trace_case':case,'ordering':'reversed' if reverse else 'original','initial_fixture_ref':key,
                         'expected_verdict':expected,'required_reason':reason,'calls':calls,'final_state':final,'verdict':v,'evidence_kind':'verifier_only_observation_projection' if case=='unrelated_running_projection' else 'verifier_only_snapshot' if case.endswith('_snapshot') else 'actual_runtime_trace',
                         'construction':'hand_authored_positive' if expected=='pass' else 'deliberate_counterexample'})
            if case.endswith('_snapshot'):rows[-1]['actual_runtime_final_state']=runtime_final
            if case=='unrelated_running_projection':rows[-1]['actual_runtime_calls']=actual_calls
        for sid in sm:replay(sid);replay(sid,'extra_reads');replay(sid,reverse=True)
        for sid in [sid for sid in sm if sid[4]=='A']:replay(sid,'filtered');replay(sid,'explicit_zero')
        for sid in ['TR5_A_PARTIAL_READY','TR5_A_ALL_READY']:replay(sid,'reverse_writes')
        replay('TR5_A_PARTIAL_READY','sequential_partial')
        for sid,case in [('TR5_A_PARTIAL_BUSY','omit_ready'),('TR5_A_WASHER_ONLY','omit_ready'),('TR5_A_PARTIAL_READY','omit_second'),
                         ('TR5_A_ALL_READY','omit_second'),('TR5_A_ALL_BUSY','unauthorized_partial'),('TR5_A_PARTIAL_BUSY','stop_busy'),
                         ('TR5_A_NEITHER','force_restart'),('TR5_A_PARTIAL_BUSY','wrong_cycle')]:replay(sid,case,expected='reject',reason='authorized_action_or_count')
        for sid in ['TR5_A_PARTIAL_BUSY','TR5_A_ALL_READY','TR5_A_WASHER_ONLY']:
            for case in ['hidden_ID','late_read']:replay(sid,case,expected='reject',reason='source_before_consuming_write')
        for sid in ['TR5_A_ALL_BUSY','TR5_A_NEITHER']:replay(sid,'missing_read',expected='reject',reason='decision_observation_missing')
        replay('TR5_A_ALL_BUSY','running_target_only')
        replay('TR5_A_ALL_BUSY','idle_target_only',expected='reject',reason='decision_observation_missing')
        replay('TR5_A_ALL_BUSY','unrelated_running_projection',expected='reject',reason='decision_observation_missing')
        replay('TR5_A_ALL_READY','start_before_all',expected='reject',reason='source_before_consuming_write')
        if 'TR5_B_PAY' in sm:
            for sid in ['TR5_B_PAY','TR5_B_BOTH','TR5_B_BANK','TR5_B_WATER']:replay(sid,'filtered')
            for sid in ['TR5_B_PAY','TR5_B_BOTH','TR5_B_WATER']:replay(sid,'wallet_first')
            replay('TR5_B_BOTH','reverse_writes')
            replay('TR5_B_BOTH','auto_before_reads')
            for sid,case in [('TR5_B_PAY','auto_instead_pay'),('TR5_B_AUTO','unauthorized_pay'),('TR5_B_PAY','wrong_source'),
                             ('TR5_B_BANK','wrong_source'),('TR5_B_WATER','wrong_bill'),('TR5_B_BOTH','omit_auto'),('TR5_B_BOTH','omit_pay'),('TR5_B_OFF','wrong_polarity')]:
                replay(sid,case,expected='reject',reason='authorized_action_or_count')
            for sid in ['TR5_B_PAY','TR5_B_BANK']:
                for case in ['hidden_ID','late_read']:replay(sid,case,expected='reject',reason='source_before_consuming_write')
            for sid in [sid for sid in sm if sid[4]=='C']:replay(sid,'filtered');replay(sid,'detail_get')
            replay('TR5_C_BOTH','split_fields')
            for sid,case in [('TR5_C_PHONE','wrong_person'),('TR5_C_EMAIL','wrong_field'),('TR5_C_BOTH','omit_email'),
                             ('TR5_C_COPY','wrong_direction'),('TR5_C_REVERSE','wrong_direction'),('TR5_C_OTHER','wrong_person'),('TR5_C_PHONE','duplicate_field')]:
                replay(sid,case,expected='reject',reason='authorized_action_or_count')
            for sid in ['TR5_C_PHONE','TR5_C_EMAIL','TR5_C_COPY','TR5_C_REVERSE']:
                for case in ['hidden_ID','late_read']:replay(sid,case,expected='reject',reason='source_before_consuming_write')
            for sid,case in [('TR5_A_PARTIAL_BUSY','other_machine_snapshot'),('TR5_B_PAY','prior_tx_snapshot'),('TR5_C_COPY','phone_snapshot')]:
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
            'limitations':['Gold reviewed before traces; no request interpreter or official mixed-capability policy.','Intended train only; TR1_E_SEND split and independent semantic/harness/template/export review pending.']}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(status));print('Replay seconds:',result['replay_wall_seconds'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/synthetic/train_wave_05_replay/replay.json')
    args=parser.parse_args();run(args.archive,args.output)
