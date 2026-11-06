"""Explicit historical selection versus incidental mention: hand-authored replay only."""
from __future__ import annotations
import os

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import zipfile

import yaml
from replay_batch03 import ROOT, CODE_FILES, StrictLoader
from replay_expansion_pilot_v1 import verdict


def validate_design(design, docs=None):
    """Essential checks persist here so the reproduction command also checks the contrasts."""
    try:
        yaml.load('key: 1\nkey: 2', Loader=StrictLoader)
    except ValueError:
        pass
    else:
        raise AssertionError('Duplicate-key guard did not reject duplicate')
    if docs is None:
        docs = [yaml.load(p.read_text(encoding='utf-8'), Loader=StrictLoader) for p in (ROOT/'data/synthetic/design').glob('*.yaml')]
    worlds = [w for d in docs for w in d['worlds']]; all_scenarios = [s for d in docs for s in d['scenarios']]
    wm = {w['world_id']: w for w in worlds}; sm = {s['scenario_id']: s for s in all_scenarios}
    assert len(wm) == len(worlds) and len(sm) == len(all_scenarios), 'Duplicate WORLD/scenario ID'
    for s in all_scenarios:
        w = wm[s['world_id']]
        assert s['lineage_id'] == w['lineage_id']
        assert s['fixture_variant'] == 'base' or s['fixture_variant'] in w['variants']
        refs = s.get('contrast', {}).get('with', [])
        for ref in [refs] if isinstance(refs, str) else refs: assert ref in sm, 'Unknown contrast reference'
    assert len(design['worlds']) == 1 and not design['exportable']
    assert design['split'] == 'dev' and design['status'] == 'spec_only', 'Batch 04 must remain dev/spec_only'
    world = design['worlds'][0]; scenarios = {s['scenario_id'][-1]: s for s in design['scenarios']}
    assert world['split'] == 'dev', 'Batch 04 WORLD must remain dev'
    assert set(scenarios) == set('ABCD') and world['design_base'] in sm
    ancestry = world['ancestry']
    assert world['lineage_id'] == 'DEV_B03_HISTORY_EVENT_01' and world['lineage_id'] in ancestry['parent_lineage_ids']
    for wid in ancestry['parent_world_ids']: assert wm[wid]['split'] == 'dev' and wm[wid]['lineage_id'] in ancestry['parent_lineage_ids']
    for sid in ancestry['parent_scenario_ids']: assert sm[sid]['lineage_id'] in ancestry['parent_lineage_ids']
    events = world['initial_state']['calendar']['events']; aliases = world['event_aliases_private']
    assert len(events) == len({e['id'] for e in events}) == len({e['title'] for e in events}) == 3
    assert set(aliases.values()) == {e['id'] for e in events}
    for s in scenarios.values():
        assert s['status'] == 'spec_only', 'Batch 04 scenarios must remain spec_only'
        assert not s['exportable'], 'Batch 04 scenarios must remain non-exportable'
        assert s['fixture_variant'] == 'base'
        assert s['agent_visible']['context'] == scenarios['A']['agent_visible']['context']
        assert s['agent_visible']['allowed_tools'] == world['relevant_tools']
        history = s['agent_visible']['history']; assert len(history) == 4 and [r['role'] for r in history] == ['user','assistant','user','assistant']
        assert all(set(turn) == {'role','text'} for turn in history)
        target = s['oracle_draft']['reviewed_target']; span = s['oracle_draft']['supporting_history_span']
        assert span['turn_index'] == 0 and span['text'] == history[0]['text']
        assert target['title'] in span['text'] and 'để hủy, nhưng khoan thực hiện; đợi tôi yêu cầu.' in span['text']
        assert history[1]['text'] == 'Tôi đã ghi nhận lựa chọn của bạn và chưa hủy sự kiện nào.'
        assert s['agent_visible']['request'].startswith('Bây giờ hủy sự kiện ')
        assert any(e['id'] == target['event_id'] and e['title'] == target['title'] for e in events)
        assert target['event_id'] != aliases['C']
        expected_statuses = {e['id']: 'cancelled' if e['id'] == target['event_id'] else 'confirmed' for e in events}
        effects = s['oracle_draft']['required_effects']
        assert effects['statuses'] == expected_statuses and effects['event_count_after'] == 3
        assert effects['total_write_count'] == effects['cancel_count'] == 1 and effects['ask_count'] == 0
        for e in events:
            assert e['id'] not in json.dumps(s['agent_visible'], ensure_ascii=False)
            assert e['status'] == 'confirmed' and datetime.fromisoformat(s['agent_visible']['context']['current_time']) < datetime.fromisoformat(e['start']) < datetime.fromisoformat(e['end'])
    a, b = deepcopy(scenarios['A']['agent_visible']), scenarios['B']['agent_visible']
    title_a, title_b = (scenarios[x]['oracle_draft']['reviewed_target']['title'] for x in 'AB')
    assert a['history'][0]['text'].replace(title_a, title_b) == b['history'][0]['text']
    a['history'][0]['text'] = b['history'][0]['text']; assert a == b
    assert scenarios['A']['agent_visible']['request'] == 'Bây giờ hủy sự kiện tôi đã chọn để hủy giúp tôi.'
    for referential, control in [('A','C'),('B','D')]:
        a = deepcopy(scenarios[referential]['agent_visible']); b = scenarios[control]['agent_visible']
        assert a['request'] != b['request']; a['request'] = b['request']; assert a == b
        assert b['request'] == 'Bây giờ hủy sự kiện "' + scenarios[control]['oracle_draft']['reviewed_target']['title'] + '" giúp tôi.'
        assert scenarios[referential]['oracle_draft']['required_effects'] == scenarios[control]['oracle_draft']['required_effects']
    assert scenarios['A']['oracle_draft']['reviewed_target'] != scenarios['B']['oracle_draft']['reviewed_target']
    incidental = next(e['title'] for e in events if e['id'] == aliases['C'])
    assert all(s['agent_visible']['history'][2:] == scenarios['A']['agent_visible']['history'][2:] for s in scenarios.values())
    assert incidental in scenarios['A']['agent_visible']['history'][2]['text'] and incidental in scenarios['A']['agent_visible']['history'][3]['text']
    assert scenarios['A']['agent_visible']['history'][2]['text'].endswith('có nghĩa là kiểm tra bản in phải không?')
    return {'global_scenarios': len(all_scenarios), 'global_world_instances': len(worlds), 'named_lineage_ids': len({w['lineage_id'] for w in worlds}),
            'essential_contrast_ancestry_visibility_checks': 'passed', 'history_resolution': 'reviewed_specification_not_Executor_or_NLP'}


def verify(initial, scenario, calls, final, kinds):
    target = scenario['oracle_draft']['reviewed_target']; effects = scenario['oracle_draft']['required_effects']
    expected = deepcopy(initial)
    for e in expected['calendar']['events']: e['status'] = effects['statuses'][e['id']]
    parts = {'state_reasons': [] if final == expected else ['state_or_effect_mismatch'], 'frame_reasons': [], 'trace_reasons': [], 'grounding_reasons': []}
    if len(final['calendar']['events']) != effects['event_count_after']: parts['state_reasons'].append('event_count')
    frame = deepcopy(final)
    for e in frame['calendar']['events']:
        if e['id'] == target['event_id']: e['status'] = next(r['status'] for r in initial['calendar']['events'] if r['id'] == e['id'])
    if frame != initial: parts['frame_reasons'].append('non_target_or_other_fields_changed')
    seen, cancels, writes, asks = {}, [], [], []
    for c in calls:
        name, args, result = c['name'], c['arguments'], c['result']
        permitted = name in scenario['agent_visible']['allowed_tools']
        if not permitted: parts['trace_reasons'].append('unpermitted_attempt')
        if name == 'calendar.list_events' and permitted and result.get('ok') is True and result.get('done') is not False:
            seen.update({e['id']:e for e in result['events']})
        if kinds.get(name, 'write') == 'write':
            writes.append(c)
            if name != 'calendar.cancel_event': parts['trace_reasons'].append('additional_write_attempt')
        if name == 'calendar.cancel_event':
            cancels.append(c); identity = args.get('event_id')
            if identity != target['event_id']: parts['trace_reasons'].append('wrong_target_attempt')
            if identity not in seen: parts['grounding_reasons'].append('ID_not_observed_before_cancel')
            elif identity == target['event_id'] and seen[identity].get('title') != target['title']: parts['grounding_reasons'].append('title_ID_mismatch')
        if name == 'sys.ask_missing_info': asks.append(c)
    if len(writes) != effects['total_write_count']: parts['trace_reasons'].append('write_count')
    if len(cancels) != effects['cancel_count']: parts['trace_reasons'].append('cancel_count')
    if len(asks) != effects['ask_count']: parts['trace_reasons'].append('unjustified_ask')
    return verdict({k:sorted(set(v)) for k,v in parts.items()}, calls)


def run(archive, output):
    path = ROOT/'data/synthetic/design/expansion_batch_04.yaml'; original = path.read_bytes()
    design = yaml.load(original.decode('utf-8'), Loader=StrictLoader); static = validate_design(design)
    world, pair = design['worlds'][0], design['interface_pair']; scenarios = {s['scenario_id'][-1]:s for s in design['scenarios']}
    fixtures, visible = {}, {}
    for letter, s in scenarios.items():
        for order in ['original','reversed']:
            entry = deepcopy(world['initial_state']); entry['sys'] = {}
            if order == 'reversed': entry['calendar']['events'].reverse()
            entry['_meta'] = {'tools':s['agent_visible']['allowed_tools'][:], 'current_time':s['agent_visible']['context']['current_time']}
            key = letter+'/'+order; fixtures[key] = entry
            agent = deepcopy(s['agent_visible']); agent['context']['installed_apps'] = {}
            for name in agent['allowed_tools']: agent['context']['installed_apps'].setdefault(name.split('.')[0],{'tools':[]})['tools'].append(name)
            visible[key] = agent
    assert all(fixtures[x+'/original'] == fixtures['A/original'] for x in 'ABCD')
    output.parent.mkdir(parents=True,exist_ok=True); evidence = []
    with tempfile.TemporaryDirectory(prefix='ex4_runtime_',dir=output.parent) as temp:
        temp = Path(temp); members = [pair['runtime_root']+p for p in CODE_FILES]+[pair['catalog_member']]
        with zipfile.ZipFile(archive) as source:
            for relative in CODE_FILES:
                p=temp/'zaic_tools'/relative; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(source.read(pair['runtime_root']+relative))
            cp=temp/'catalog.json'; cp.write_bytes(source.read(pair['catalog_member']))
        catalog=json.loads(cp.read_text(encoding='utf-8')); assert catalog['schema_version']==pair['catalog_schema_version']
        tools={t['name']:t for app in catalog['apps'] for t in app['tools']}; kinds={n:t['kind'] for n,t in tools.items()}
        for name,contract in pair['capability_contracts'].items():
            assert tools[name]['parameters']['required']==contract['required'] and set(contract['optional_used'])<=set(tools[name]['parameters']['properties'])
        if 'zaic_tools' in sys.modules: raise RuntimeError('Use a fresh Python process')
        sys.path.insert(0,str(temp))
        from zaic_tools.executor import Executor
        fp=temp/'synthetic.json'; fp.write_text(json.dumps(fixtures,ensure_ascii=False),encoding='utf-8')
        executor=Executor(str(fp),str(cp)); snapshot=deepcopy(executor.db)

        def replay(letter,case='standard',order='original',expected='pass',reason=None,expected_for=None,mutation=None):
            s=scenarios[letter]; key=letter+'/'+order; session=executor.open(key); initial=session.get_state(); calls=[]
            assert initial=={k:v for k,v in fixtures[key].items() if k!='_meta'}
            assert session.allowed==set(s['agent_visible']['allowed_tools']) and session.now==s['agent_visible']['context']['current_time']
            def call(name,**args):
                before=session.get_state(); result=session.call(name,args); after=session.get_state()
                if kinds[name] in ['read','meta']: assert after==before
                if name=='calendar.list_events':
                    rows=[e for e in before['calendar']['events'] if not args.get('date_from') or e['start'][:10]>=args['date_from']]
                    assert result=={'ok':True,'events':rows}
                if name=='calendar.cancel_event' and result.get('item'):
                    expected_after=deepcopy(before)
                    next(e for e in expected_after['calendar']['events'] if e['id']==args['event_id'])['status']='cancelled'
                    assert after==expected_after and result['item']==next(e for e in after['calendar']['events'] if e['id']==args['event_id'])
                calls.append({'name':name,'arguments':deepcopy(args),'result':deepcopy(result)}); return result
            title=s['oracle_draft']['reviewed_target']['title']
            if case in ['hidden_ID','late_read']:
                selected_id=s['oracle_draft']['reviewed_target']['event_id']  # Deliberate private-ID negative only.
                records=[]
            else:
                args={'date_from':s['agent_visible']['context']['current_time'][:10]} if case=='filtered' else {}
                records=call('calendar.list_events',**args)['events']
                matches=[e for e in records if e['title']==title]; assert len(matches)==1
                selected_id=matches[0]['id']
                if case=='repeated_reads': call('calendar.list_events')
            aliases=world['event_aliases_private']; ids=[selected_id]
            if case=='other_candidate': ids=[next(e['id'] for e in records if e['id'] in [aliases['A'],aliases['B']] and e['id']!=selected_id)]
            if case=='incidental_C': ids=[next(e['id'] for e in records if e['id']==aliases['C'])]
            if case=='both_candidates': ids=[next(e['id'] for e in records if e['id']==i) for i in [aliases['A'],aliases['B']]]
            if case=='target_then_C': ids=[selected_id,next(e['id'] for e in records if e['id']==aliases['C'])]
            if case=='duplicate': ids=[selected_id,selected_id]
            for i,identity in enumerate(ids):
                before=session.get_state(); result=call('calendar.cancel_event',event_id=identity)
                assert result['ok'] is True and result.get('done') is not False
                if case=='duplicate' and i==1: assert session.get_state()==before
                else: assert next(e for e in before['calendar']['events'] if e['id']==identity)['status']=='confirmed'
            if case=='late_read': call('calendar.list_events')
            runtime_final=session.get_state(); final=deepcopy(runtime_final)
            if mutation: mutation(final)
            verifier_scenario=scenarios[expected_for] if expected_for else s
            actual=verify(initial,verifier_scenario,calls,final,kinds)
            assert actual['verdict']==expected,(letter,case,actual)
            if reason: assert reason in sum([v for k,v in actual.items() if k not in ['verdict','attempt_diagnostics']],[]),(case,actual)
            if case in ['hidden_ID','late_read','duplicate']: assert not actual['state_reasons'] and not actual['frame_reasons']
            assert session.get_tool_calls()==[{k:c[k] for k in ['name','arguments']} for c in calls] and session.log==calls
            assert executor.db==snapshot and executor.open(key).get_state()==initial
            kind='verifier_only_snapshot' if mutation else ('verifier_only_cross_contrast' if expected_for else 'actual_runtime_trace')
            row={'scenario_id':s['scenario_id'],'lineage_id':s['lineage_id'],'fixture_variant':s['fixture_variant'],'ordering':order,'trace_case':case,
                 'initial_fixture_ref':key,'expected_verdict':expected,'required_reason':reason,'calls':calls,'final_state':final,'verdict':actual,'evidence_kind':kind,
                 'construction':'hand_authored_positive' if expected=='pass' else 'deliberate_diagnostic_may_use_private_IDs'}
            if mutation: row['actual_runtime_final_state']=runtime_final
            if expected_for: row['verifier_expected_scenario_id']=verifier_scenario['scenario_id']
            evidence.append(row)

        for letter in 'ABCD':
            replay(letter); replay(letter,order='reversed'); replay(letter,'filtered')
        replay('A','repeated_reads')
        for letter in 'AB':
            for case,reason in [('other_candidate','wrong_target_attempt'),('incidental_C','wrong_target_attempt'),('both_candidates','cancel_count'),
                                ('target_then_C','cancel_count'),('hidden_ID','ID_not_observed_before_cancel'),('late_read','ID_not_observed_before_cancel'),('duplicate','cancel_count')]:
                replay(letter,case,expected='reject',reason=reason)
        replay('A','cross_against_B',expected='reject',reason='wrong_target_attempt',expected_for='B')
        replay('B','cross_against_A',expected='reject',reason='wrong_target_attempt',expected_for='A')
        replay('A','incidental_field_snapshot',expected='reject',reason='non_target_or_other_fields_changed',
               mutation=lambda st: next(e for e in st['calendar']['events'] if e['id']==world['event_aliases_private']['C']).update(location='Verifier-only tampering'))
        for letter in 'ABCD':
            rows=[r for r in evidence if r['scenario_id']==scenarios[letter]['scenario_id'] and r['trace_case']=='standard']
            assert len(rows)==2 and visible[letter+'/original']==visible[letter+'/reversed']
            assert {e['id']:e for e in rows[0]['final_state']['calendar']['events']}=={e['id']:e for e in rows[1]['final_state']['calendar']['events']}
        for origin,control in [('A','C'),('B','D')]:
            standard=lambda x: next(r for r in evidence if r['scenario_id']==scenarios[x]['scenario_id'] and r['trace_case']=='standard' and r['ordering']=='original')
            assert standard(origin)['final_state']==standard(control)['final_state']
        for origin,other in [('A','B'),('B','A')]:
            cross=next(r for r in evidence if r['trace_case']=='cross_against_'+other)
            original_row=next(r for r in evidence if r['scenario_id']==scenarios[origin]['scenario_id'] and r['trace_case']=='standard' and r['ordering']=='original')
            assert cross['calls']==original_row['calls'] and cross['final_state']==original_row['final_state']
        assert path.read_bytes()==original
        runtime=[r for r in evidence if r['evidence_kind']=='actual_runtime_trace']
        status={'unique_scenarios_replayed':4,'positive_runtime_paths':sum(r['expected_verdict']=='pass' for r in runtime),
                'negative_runtime_traces':sum(r['expected_verdict']=='reject' for r in runtime),'verifier_only_checks':len(evidence)-len(runtime),
                'all_expectations_met':True,'spec_only':4,'execution_verified':0,'exportable':False}
        result={'created_utc':datetime.now(timezone.utc).isoformat(),'kind':'hand_authored_runtime_replay_not_model_evaluation','status':status,'static_validation':static,
                'provenance':{'archive':str(archive),'design':str(path.relative_to(ROOT)),'release_as_recorded_in_design':pair['release'],'catalog_schema_version':catalog['schema_version'],
                              'allowlisted_members':members,'runtime_modified':False,'python':sys.version},'world_ancestry':world['ancestry'],'fixtures':fixtures,'agent_visible':visible,'replays':evidence,
                'reproduction_command':'python scripts/replay_expansion_batch_04.py',
                'limitations':['Executor does not consume history; reviewed oracle supplies intended target, not an NLP resolver.',
                               'No model comprehension, official semantic acceptance, team harness or training/export validation.',
                               'Attempts remain diagnostic; authored target/count/evidence/frame requirements decide verdict.']}
        output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(status)); print('Evidence:',output)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/synthetic/expansion_batch_04_replay/replay.json')
    args=parser.parse_args(); run(args.archive,args.output)
