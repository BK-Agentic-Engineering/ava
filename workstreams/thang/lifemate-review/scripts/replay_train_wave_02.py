"""Hand-authored Wave 02 replay of local synthetic designs, not model evaluation."""
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
from replay_train_wave_01 import canonical, validate_ancestry


def validate(design, docs=None):
    if docs is None:
        docs = [yaml.load(p.read_text(encoding='utf-8'),Loader=StrictLoader)
                for p in sorted((ROOT/'data/synthetic/design').glob('*.yaml'))]
    worlds = [w for d in docs for w in d['worlds']]; scenarios = [s for d in docs for s in d['scenarios']]
    wm = {w['world_id']:w for w in worlds}; sm = {s['scenario_id']:s for s in scenarios}
    assert len(wm) == len(worlds) and len(sm) == len(scenarios), 'duplicate ID'
    validate_ancestry(wm, sm)
    for w in worlds:
        if 'design_base' in w: assert sm[w['design_base']]['world_id'] == w['world_id']
    for s in scenarios:
        w = wm[s['world_id']]
        assert w['lineage_id'] == s['lineage_id']
        assert s['fixture_variant'] == 'base' or s['fixture_variant'] in w['variants']
        refs = s.get('contrast',{}).get('with',[])
        for ref in [refs] if isinstance(refs,str) else refs: assert ref in sm, 'broken reference'
    assert design['split'] == 'train' and design['status'] == 'spec_only' and design['exportable'] is False, 'Wave 02 status'
    # Other independent roots cannot reuse these names. Later descendants may
    # legitimately inherit a Wave 02 lineage, so do not ban all later reuse.
    prior_roots = {w['lineage_id'] for d in docs if d['version'] != 'train_wave_02' for w in d['worlds']
                   if not any(w.get('ancestry',{}).get(k) for k in ['parent_world_ids','parent_scenario_ids','parent_lineage_ids'])}
    for w in design['worlds']:
        assert w['split'] == 'train' and w['origin'] == 'independently_authored'
        assert w['lineage_id'] not in prior_roots, 'independent root lineage collision'
        assert w['ancestry'] == dict(parent_world_ids=[],parent_scenario_ids=[],parent_lineage_ids=[])
    own = {s['scenario_id']:s for s in design['scenarios']}
    for s in own.values():
        assert s['status'] == 'spec_only' and s['exportable'] is False, 'Wave 02 scenario status'
        assert s['agent_visible']['allowed_tools'] == wm[s['world_id']]['relevant_tools']
        assert all(set(t) == {'role','text'} and t['role'] in ['user','assistant'] for t in s['agent_visible']['history'])
        state = fixture(wm[s['world_id']],s)
        def hidden_ids(value):
            if isinstance(value,dict):
                for k,v in value.items():
                    if k in ['id','tracking_id']: assert v not in canonical(s['agent_visible']), 'hidden ID leak'
                    else: hidden_ids(v)
            elif isinstance(value,list):
                for v in value: hidden_ids(v)
        hidden_ids(state)
        for n in s['oracle_draft']['observations']:
            if n.get('id'):
                app = n['tool'].split('.')[0]
                record = next(r for r in state[app][n['collection']] if r['id'] == n['id'])
                assert all(record[k] == v for k,v in n['fields'].items())
    a,b = (own[k] for k in ['TR2_P_HISTORY','TR2_P_ASK'])
    visible = deepcopy(a['agent_visible']); visible['history'] = b['agent_visible']['history']
    assert visible == b['agent_visible'] and a['agent_visible']['history'] != b['agent_visible']['history'], 'address contrast'
    assert a['world_id'] == b['world_id'] and a['fixture_variant'] == b['fixture_variant']
    assert a['agent_visible']['history'] == [{'role':'user','text':'Điểm lấy hàng của tôi là 18 ngõ Chồi, phường Vườn.'}]
    assert b['agent_visible']['history'] == [{'role':'user','text':'Tôi chưa chọn điểm lấy hàng.'}]
    assert b['oracle_draft']['ask'] == {'tool_name':'package_tracking.schedule_pickup','params':['address']}
    assert a['oracle_draft']['effects'] == own['TR2_P_EXPLICIT']['oracle_draft']['effects']
    if 'TR2_A_TIME' in own:
        a,b = (own[k] for k in ['TR2_A_TIME','TR2_A_TIME_DISABLED'])
        assert a['agent_visible'] == b['agent_visible']
        w = wm[a['world_id']]; base = fixture(w,a); disabled = fixture(w,b)
        assert base['alarm']['alarms'][0]['enabled'] is True and disabled['alarm']['alarms'][0]['enabled'] is False
        disabled['alarm']['alarms'][0]['enabled'] = True
        assert disabled == base and a['oracle_draft']['effects'] == b['oracle_draft']['effects']
        robot = wm[own['TR2_V_INHERIT']['world_id']]
        base = fixture(robot,own['TR2_V_ROOM']); configured = fixture(robot,own['TR2_V_INHERIT'])
        assert configured['robot_vacuum']['mode'] == 'mop'
        configured['robot_vacuum']['mode'] = base['robot_vacuum']['mode']; assert configured == base
    return {'scenarios_by_split':dict(Counter(wm[s['world_id']]['split'] for s in scenarios)),
            'worlds_by_split':dict(Counter(w['split'] for w in worlds)), 'named_lineages':len({w['lineage_id'] for w in worlds}),
            'integrity_contrast_visibility':'passed', 'near_duplicate_review':'Scoped Wave 01 email control flagged; Wave 02 family rationale and intentional context controls in handoff.'}


def fixture(world, scenario):
    state = deepcopy(world['initial_state'])
    variant = scenario['fixture_variant']
    if variant != 'base':
        patch = world['variants'][variant]
        if 'configured_mode' in patch: state['robot_vacuum']['mode'] = patch['configured_mode']
        if 'alarm_enabled' in patch: state['alarm']['alarms'][0]['enabled'] = patch['alarm_enabled']
    return state


def verify(initial, s, calls, final, kinds):
    oracle = s['oracle_draft']; effects = oracle['effects']; expected = deepcopy(initial)
    reasons = {'state':[],'trace':[],'grounding':[]}
    family = s['scenario_id'][4]
    if family == 'P':
        for identity,time in effects['shipment_times'].items():
            next(r for r in expected['package_tracking']['shipments'] if r['id'] == identity)['scheduled_time'] = time
        old = {r['id'] for r in initial['package_tracking']['pickups']}
        added = [r for r in final['package_tracking']['pickups'] if r['id'] not in old]
        if Counter(canonical({k:v for k,v in r.items() if k != 'id'}) for r in added) != Counter(map(canonical,effects['new_pickups'])):
            reasons['state'].append('pickup_payload_or_count')
        expected['package_tracking']['pickups'].extend(deepcopy(added))
    elif family == 'V':
        expected['robot_vacuum']['status'] = effects['status']
        expected['robot_vacuum']['current_job'] = deepcopy(effects['current_job'])
        actual_job = final['robot_vacuum']['current_job']; wanted = expected['robot_vacuum']['current_job']
        if actual_job is not None and wanted is not None:
            if Counter(actual_job['rooms']) == Counter(wanted['rooms']): wanted['rooms'] = deepcopy(actual_job['rooms'])
            if effects['current_job']['whole_house'] and Counter(actual_job['rooms']) == Counter(initial['robot_vacuum']['rooms']):
                wanted['whole_house'] = actual_job['whole_house']
    elif family == 'A':
        for identity,patch in effects['updates'].items():
            next(r for r in expected['alarm']['alarms'] if r['id'] == identity).update(patch)
    else:
        raise AssertionError(family)
    if final != expected: reasons['state'].append('goal_or_frame')
    seen = set(); writes = []; asks = []; observed_rooms = None
    def normalized(name,args):
        args = deepcopy(args)
        if name == 'package_tracking.reschedule_delivery':
            for ship in initial['package_tracking']['shipments']:
                if args.get('tracking_id') in [ship['id'],ship['tracking_id']]: args['tracking_id'] = ship['tracking_id']
        if name == 'robot_vacuum.start':
            args['rooms'] = sorted(args.get('rooms') or initial['robot_vacuum']['rooms'])
            args['mode'] = args.get('mode') or initial['robot_vacuum']['mode']
        if name == 'alarm.update':
            atoms = [canonical({'name':name,'id':args.get('alarm_id'),'field':k,'value':v}) for k,v in args.items() if k != 'alarm_id']
            return atoms or [canonical({'name':name,'empty_patch':args})]
        return [canonical({'name':name,'arguments':args})]
    for c in calls:
        name,args,result = c['name'],c['arguments'],c['result']
        if name not in s['agent_visible']['allowed_tools']: reasons['trace'].append('unpermitted_attempt')
        if (s['scenario_id'] == 'TR2_V_ALL' and name == 'robot_vacuum.get_status'
                and name in s['agent_visible']['allowed_tools'] and result.get('ok') is True
                and result.get('done') is not False
                and Counter(result.get('rooms',[])) == Counter(initial['robot_vacuum']['rooms'])):
            observed_rooms = result['rooms']
        if kinds.get(name) == 'read' and result.get('ok') is True:
            for i,n in enumerate(oracle['observations']):
                records = result.get(n['collection'],[]) if n.get('collection') else [result]
                if name == n['tool'] and any((not n.get('id') or r.get('id') == n['id']) and all(r.get(k) == v for k,v in n['fields'].items()) for r in records):
                    seen.add(i)
        if kinds.get(name,'write') == 'write':
            # Check original arguments: omission/[] delegates to the runtime,
            # whereas a concrete whole-house list needs a prior complete inventory.
            if s['scenario_id'] == 'TR2_V_ALL' and name == 'robot_vacuum.start' and args.get('rooms'):
                if observed_rooms is None or Counter(args['rooms']) != Counter(observed_rooms):
                    reasons['grounding'].append('whole_house_inventory_before_explicit_rooms')
            writes.extend(normalized(name,args))
            for i,n in enumerate(oracle['observations']):
                normalized_args = json.loads(normalized(name,args)[0]).get('arguments',args)
                uses = (n['argument'] in args and (args[n['argument']] == n['value'] or normalized_args.get(n['argument']) == n['value'])) or n.get('original_snapshot')
                if name == n['before_tool'] and uses and i not in seen:
                    reasons['grounding'].append('observation_before_consuming_write')
        if name == 'sys.ask_missing_info': asks.append(args)
    permitted = [token for a in oracle['writes'] for token in normalized(a['name'],a['arguments'])]
    if Counter(writes) != Counter(permitted): reasons['trace'].append('authorized_writes')
    if asks != ([oracle['ask']] if oracle['outcome'] == 'ask_missing' else []): reasons['trace'].append('clarification_target_or_necessity')
    reasons = {k:sorted(set(v)) for k,v in reasons.items()}
    return {'verdict':'reject' if any(reasons.values()) else 'pass', **reasons}


def run(archive, output):
    started = perf_counter()
    path = ROOT/'data/synthetic/design/train_wave_02.yaml'; original = path.read_bytes()
    design = yaml.load(original.decode('utf-8'),Loader=StrictLoader); inventory = validate(design)
    wm = {w['world_id']:w for w in design['worlds']}; sm = {s['scenario_id']:s for s in design['scenarios']}
    fixtures = {}
    for sid,s in sm.items():
        state = fixture(wm[s['world_id']],s); state['sys'] = {}
        state['notes'] = {'notes':[{'id':'tr2_guard_note','title':'Giữ riêng','content':'Không sửa.'}]}
        state['_meta'] = {'tools':s['agent_visible']['allowed_tools'],'current_time':s['agent_visible']['context']['current_time']}
        fixtures[sid] = state
        reversed_state = deepcopy(state)
        for app in wm[s['world_id']]['initial_state']:
            for values in reversed_state[app].values():
                if isinstance(values,list): values.reverse()
        fixtures[sid+'/reversed'] = reversed_state
    files = ['__init__.py','executor.py','validate.py','utils.py','apps/__init__.py','apps/base.py','apps/sys.py',
             'apps/package_tracking.py','apps/robot_vacuum.py','apps/alarm.py']
    p = design['provenance']; output.parent.mkdir(parents=True,exist_ok=True); rows = []
    with tempfile.TemporaryDirectory(prefix='wave02_runtime_',dir=output.parent) as temp:
        temp = Path(temp)
        with zipfile.ZipFile(archive) as z:
            for name in files:
                out = temp/'zaic_tools'/name; out.parent.mkdir(parents=True,exist_ok=True); out.write_bytes(z.read(p['runtime_root']+name))
            catalog_path = temp/'catalog.json'; catalog_path.write_bytes(z.read(p['catalog_member']))
        catalog = json.loads(catalog_path.read_text(encoding='utf-8')); assert catalog['schema_version'] == p['catalog_schema_version']
        tools = {t['name']:t for a in catalog['apps'] for t in a['tools']}; kinds = {n:t['kind'] for n,t in tools.items()}
        for s in sm.values():
            for a in s['oracle_draft']['writes']:
                assert a['name'] in s['agent_visible']['allowed_tools']
                assert set(tools[a['name']]['parameters']['required']) <= set(a['arguments'])
        assert tools['package_tracking.schedule_pickup']['parameters']['required'] == ['address','date']
        if 'zaic_tools' in sys.modules: raise RuntimeError('Fresh process required')
        sys.path.insert(0,str(temp))
        from zaic_tools.executor import Executor
        source = temp/'authored.json'; source.write_text(canonical(fixtures),encoding='utf-8')
        executor = Executor(str(source),str(catalog_path)); original_db = deepcopy(executor.db)

        def replay(sid,case='standard',reverse=False,expected='pass',reason=None):
            s = sm[sid]; key = sid+('/reversed' if reverse else '')
            session = executor.open(key); initial = session.get_state(); calls = []
            assert session.allowed == set(s['agent_visible']['allowed_tools']) | {'sys.ask_missing_info'}
            def call(tool,**args):
                before = session.get_state(); result = session.call(tool,args)
                if kinds[tool] != 'write': assert session.get_state() == before
                assert result.get('ok') is True and result.get('done') is not False,(sid,case,result)
                calls.append({'name':tool,'arguments':deepcopy(args),'result':deepcopy(result)})
                return result
            oracle = s['oracle_draft']; actions = deepcopy(oracle['writes']); obs = oracle['observations']
            family = sid[4]
            read_tool = {'P':'package_tracking.track','V':'robot_vacuum.get_status','A':'alarm.list'}[family]
            if (obs or case in ['extra_reads','filtered_track','enumerate_all','enumerate_reverse','observed_incomplete']) and case not in ['hidden_ID','late_read','pickup_before_read','direct_default']:
                result = call(read_tool)
                if family == 'P':
                    assert result == {'ok':True,'shipments':initial['package_tracking']['shipments']}
                    assert 'pickups' not in result and all('address' not in r for r in result['shipments'])
                elif family == 'A': assert result == {'ok':True,'alarms':initial['alarm']['alarms']}
                else:
                    assert result == {'ok':True,**{k:initial['robot_vacuum'][k] for k in ['battery','status','mode','rooms','current_job']}}
                found_records = {}
                for n in obs:
                    if not n.get('id'): continue
                    identity_field = 'name' if family == 'P' else 'label'
                    found = [r for r in result[n['collection']] if r[identity_field] == n['fields'][identity_field]]
                    assert len(found) == 1 and found[0]['id'] == n['id']
                    found_records[n['id']] = found[0]
                    for a in actions:
                        if a['name'] == n['before_tool'] and a['arguments'].get(n['argument']) == n['value']:
                            a['arguments'][n['argument']] = found[0]['tracking_id' if family == 'P' else 'id']
                if sid == 'TR2_A_SWAP':
                    actions[0]['arguments']['time'] = found_records['tr2_alarm_53']['time']
                    actions[1]['arguments']['time'] = found_records['tr2_alarm_17']['time']
                if case == 'explicit_mode': actions[0]['arguments']['mode'] = result['mode']
                if case == 'extra_reads': call(read_tool)
                if case == 'filtered_track': call('package_tracking.track',tracking_id=obs[0]['value'])
            if case == 'reverse_writes': actions.reverse()
            if case == 'premature_ask': actions = []
            if case == 'guess_address': actions = [{'name':'package_tracking.schedule_pickup','arguments':{'address':'18 ngõ Chồi, phường Vườn','date':'2026-12-22'}}]
            if case == 'wrong_direction': actions = [{'name':'package_tracking.reschedule_delivery','arguments':{'tracking_id':'LMTR82471','time':'2026-12-22T14:30:00+07:00'}}]
            if case == 'wrong_target': actions[0]['arguments']['tracking_id'] = 'LMTR82471'
            if case == 'omit_delivery': actions = actions[:1]
            if case == 'duplicate_pickup': actions.append(deepcopy(actions[0]))
            if case == 'state_ID_alias': actions[0]['arguments']['tracking_id'] = obs[0]['id']
            if case == 'whole_house': actions[0]['arguments'].pop('rooms',None)
            if case == 'omit_mode': actions[0]['arguments'].pop('mode',None)
            if case == 'active_job_mode': actions[0]['arguments']['mode'] = result['current_job']['mode']
            if case == 'wrong_mode': actions[0]['arguments']['mode'] = 'mop'
            if case == 'one_room': actions[0]['arguments']['rooms'] = ['phòng dệt']
            if case == 'room_order': actions[0]['arguments']['rooms'].reverse()
            if case in ['enumerate_all','enumerate_reverse','observed_incomplete']:
                actions[0]['arguments']['rooms'] = deepcopy(result['rooms'])
                if case == 'enumerate_reverse': actions[0]['arguments']['rooms'].reverse()
                if case == 'observed_incomplete': actions[0]['arguments']['rooms'].pop()
            if case in ['unobserved_enumeration','late_enumeration']:
                actions[0]['arguments']['rooms'] = deepcopy(initial['robot_vacuum']['rooms'])  # Private-value negative only.
            if case == 'empty_rooms': actions[0]['arguments']['rooms'] = []
            if case == 'stop_instead': actions = [{'name':'robot_vacuum.stop','arguments':{}}]
            if case == 'restart_after_stop': actions.append({'name':'robot_vacuum.start','arguments':{'rooms':['phòng dệt'],'mode':'vacuum'}})
            if case == 'delete_instead': actions = [{'name':'alarm.delete','arguments':{'alarm_id':'tr2_alarm_17'}}]
            if case == 'recreate': actions = [{'name':'alarm.delete','arguments':{'alarm_id':'tr2_alarm_17'}}, {'name':'alarm.create','arguments':{'time':'2026-12-23T06:45:00+07:00','label':'Mở sạp'}}]
            if case == 'reenable': actions[0]['arguments']['enabled'] = True
            if case == 'wrong_field': actions = [{'name':'alarm.update','arguments':{'alarm_id':'tr2_alarm_17','enabled':False}}]
            if case == 'label_only': actions[0]['arguments'].pop('time')
            if case == 'copy_updated_time':
                first = actions.pop(0); call(first['name'],**first['arguments'])
                updated = call('alarm.list')['alarms']
                actions[0]['arguments']['time'] = next(r['time'] for r in updated if r['id'] == first['arguments']['alarm_id'])
            if case == 'split_fields':
                a = actions[0]['arguments']; actions = [{'name':'alarm.update','arguments':{'alarm_id':a['alarm_id'],k:v}} for k,v in a.items() if k != 'alarm_id']
            if case == 'duplicate_field': actions.append(deepcopy(actions[-1]))
            if case == 'pickup_before_read':
                a = actions.pop(0); call(a['name'],**a['arguments'])
                result = call('package_tracking.track'); assert len(result['shipments']) == 2
            for a in actions: call(a['name'],**a['arguments'])
            if oracle['outcome'] == 'ask_missing' and case != 'guess_address' or case == 'premature_ask':
                ask = oracle.get('ask',{'tool_name':'package_tracking.schedule_pickup','params':['address']})
                if case == 'wrong_ask_parameter': ask = {'tool_name':'package_tracking.schedule_pickup','params':['date']}
                call('sys.ask_missing_info',**ask)
            if case == 'late_read': call(read_tool)
            if case == 'late_enumeration': call(read_tool)
            runtime_final = session.get_state(); final = deepcopy(runtime_final)
            if case == 'repeat_snapshot': next(r for r in final['alarm']['alarms'] if r['id']=='tr2_alarm_17')['repeat'] = 'once'
            if case == 'battery_snapshot': final['robot_vacuum']['battery'] = 12
            verdict = verify(initial,s,calls,final,kinds)
            assert verdict['verdict'] == expected,(sid,case,verdict)
            if reason: assert reason in verdict['trace']+verdict['state']+verdict['grounding'],(sid,case,verdict)
            if case in ['hidden_ID','late_read','unobserved_enumeration','late_enumeration']: assert not verdict['state']
            assert session.log == calls and session.get_tool_calls() == [{k:c[k] for k in ['name','arguments']} for c in calls]
            assert executor.db == original_db and executor.open(key).get_state() == initial
            rows.append({'scenario_id':sid,'lineage_id':s['lineage_id'],'trace_case':case,'ordering':'reversed' if reverse else 'original',
                         'initial_fixture_ref':key,'expected_verdict':expected,'required_reason':reason,'calls':calls,'final_state':final,
                         'verdict':verdict,'evidence_kind':'verifier_only_snapshot' if case.endswith('_snapshot') else 'actual_runtime_trace',
                         'construction':'hand_authored_positive' if expected == 'pass' else 'deliberate_counterexample'})
            if case.endswith('_snapshot'): rows[-1]['actual_runtime_final_state'] = runtime_final

        for sid in sm:
            replay(sid); replay(sid,'extra_reads'); replay(sid,reverse=True)
        replay('TR2_P_BOTH','reverse_writes'); replay('TR2_P_BOTH','pickup_before_read')
        for sid in ['TR2_P_DELIVERY','TR2_P_DELIVERY_OTHER']: replay(sid,'filtered_track')
        for sid in ['TR2_P_HISTORY','TR2_P_EXPLICIT']: replay(sid,'premature_ask',expected='reject',reason='clarification_target_or_necessity')
        replay('TR2_P_ASK','guess_address',expected='reject',reason='authorized_writes')
        replay('TR2_P_ASK','wrong_ask_parameter',expected='reject',reason='clarification_target_or_necessity')
        replay('TR2_P_HISTORY','wrong_direction',expected='reject',reason='authorized_writes')
        replay('TR2_P_DELIVERY_OTHER','wrong_target',expected='reject',reason='authorized_writes')
        replay('TR2_P_BOTH','omit_delivery',expected='reject',reason='authorized_writes')
        replay('TR2_P_HISTORY','duplicate_pickup',expected='reject',reason='authorized_writes')
        for sid in ['TR2_P_DELIVERY','TR2_P_DELIVERY_OTHER']:
            for case in ['hidden_ID','late_read']: replay(sid,case,expected='reject',reason='observation_before_consuming_write')
        replay('TR2_P_DELIVERY','state_ID_alias')
        if 'TR2_V_ROOM' in sm:
            for sid,case in [('TR2_V_ROOM','wrong_mode'),('TR2_V_ROOM','whole_house'),('TR2_V_MOP','omit_mode'),
                             ('TR2_V_TWO','one_room'),('TR2_V_ALL','one_room'),('TR2_V_STOP','restart_after_stop'),
                             ('TR2_V_ROOM','stop_instead'),('TR2_V_INHERIT','active_job_mode')]:
                replay(sid,case,expected='reject',reason='authorized_writes')
            for sid,case in [('TR2_V_TWO','room_order'),('TR2_V_ALL','enumerate_all'),('TR2_V_ALL','empty_rooms'),
                             ('TR2_V_INHERIT','direct_default'),('TR2_V_INHERIT','explicit_mode')]: replay(sid,case)
            replay('TR2_V_ALL','enumerate_reverse'); replay('TR2_V_ALL','enumerate_all',reverse=True)
            for case in ['unobserved_enumeration','late_enumeration']:
                replay('TR2_V_ALL',case,expected='reject',reason='whole_house_inventory_before_explicit_rooms')
            replay('TR2_V_ALL','observed_incomplete',expected='reject',reason='authorized_writes')
            replay('TR2_V_ROOM','battery_snapshot',expected='reject',reason='goal_or_frame')
        if 'TR2_A_TIME' in sm:
            for sid,case in [('TR2_A_DISABLE','delete_instead'),('TR2_A_TIME','recreate'),('TR2_A_TIME_DISABLED','reenable'),
                             ('TR2_A_LABEL','wrong_field'),('TR2_A_TIME_LABEL','label_only'),('TR2_A_SWAP','copy_updated_time'),
                             ('TR2_A_TIME','duplicate_field')]: replay(sid,case,expected='reject',reason='authorized_writes')
            for sid in ['TR2_A_DISABLE','TR2_A_TIME','TR2_A_TIME_DISABLED','TR2_A_LABEL','TR2_A_TIME_LABEL','TR2_A_SWAP']:
                replay(sid,'hidden_ID',expected='reject',reason='observation_before_consuming_write')
            replay('TR2_A_TIME_LABEL','split_fields'); replay('TR2_A_SWAP','reverse_writes')
            replay('TR2_A_TIME','repeat_snapshot',expected='reject',reason='goal_or_frame')
    assert path.read_bytes() == original
    status = {'unique_scenarios_replayed':len(sm),'outcomes':dict(Counter(s['oracle_draft']['outcome'] for s in sm.values())),
              'positive_runtime_paths':sum(r['expected_verdict']=='pass' for r in rows),
              'rejected_counterexamples':sum(r['expected_verdict']=='reject' and r['evidence_kind']=='actual_runtime_trace' for r in rows),
              'verifier_only_checks':sum(r['evidence_kind']!='actual_runtime_trace' for r in rows),
              'all_expectations_met':True,'spec_only':len(sm),'exportable':False,'execution_verified':0}
    result = {'created_utc':datetime.now(timezone.utc).isoformat(),'replay_wall_seconds':perf_counter()-started,
              'declared_volatile_fields':['created_utc','replay_wall_seconds'],'kind':'hand_authored_runtime_replay_not_model_evaluation',
              'status':status,'inventory':inventory,'provenance':{'design':str(path.relative_to(ROOT)),'archive':str(archive),
              'release_recorded':p['interface_release'],'catalog_schema':catalog['schema_version'],'runtime_modified':False,
              'allowlisted_members':[p['runtime_root']+n for n in files]+[p['catalog_member']],'python':sys.version},
              'fixtures':fixtures,'agent_visible':{sid:s['agent_visible'] for sid,s in sm.items()},'replays':rows,
              'limitations':['Reviewed gold; no model/history interpreter or official acceptance verification.','Intended train only; independent split/semantic review and team harness/template pending.']}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(status)); print('Replay seconds:',result['replay_wall_seconds']); print('Evidence:',output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/synthetic/train_wave_02_replay/replay.json')
    args = parser.parse_args(); run(args.archive,args.output)
