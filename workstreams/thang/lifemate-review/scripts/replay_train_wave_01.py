"""Bounded, hand-authored train-design replay; no model, generator or team harness."""
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


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def validate_ancestry(worlds, scenarios):
    parents = {}
    roots = {}
    for world_id, world in worlds.items():
        ancestry = world.get('ancestry', {})
        parent_ids = set(ancestry.get('parent_world_ids', []))
        parent_ids.update(scenarios[s]['world_id'] for s in ancestry.get('parent_scenario_ids', []))
        parents[world_id] = parent_ids
        referenced = [worlds[p] for p in parent_ids]
        assert all(p['split'] == world['split'] for p in referenced), 'cross-split ancestry'
        assert set(ancestry.get('parent_lineage_ids', [])) == {
            p['lineage_id'] for p in referenced
        }, 'parent lineage IDs disagree with referenced ancestry'
        if not parent_ids:
            lineage = world['lineage_id']
            assert lineage not in roots, 'independent root lineage collision'
            roots[lineage] = world_id

    def ancestors(world_id, path):
        assert world_id not in path, 'cyclic ancestry'
        found = set(parents[world_id])
        for parent_id in parents[world_id]:
            found.update(ancestors(parent_id, path | {world_id}))
        return found

    for world_id, world in worlds.items():
        if parents[world_id]:
            lineage = world['lineage_id']
            assert roots.get(lineage) in ancestors(world_id, set()), 'primary lineage lacks an ancestry path to its root'


def validate(design, docs=None):
    if docs is None:
        docs = [yaml.load(p.read_text(encoding='utf-8'), Loader=StrictLoader)
                for p in sorted((ROOT / 'data/synthetic/design').glob('*.yaml'))]
    worlds = [w for d in docs for w in d['worlds']]
    scenarios = [s for d in docs for s in d['scenarios']]
    wm = {w['world_id']: w for w in worlds}; sm = {s['scenario_id']: s for s in scenarios}
    assert len(wm) == len(worlds) and len(sm) == len(scenarios), 'duplicate ID'
    validate_ancestry(wm, sm)
    requests = {}
    for s in scenarios:
        w = wm[s['world_id']]
        assert s['lineage_id'] == w['lineage_id']
        assert s['fixture_variant'] == 'base' or s['fixture_variant'] in w['variants']
        refs = s.get('contrast', {}).get('with', [])
        for ref in [refs] if isinstance(refs, str) else refs: assert ref in sm
        requests.setdefault(s['agent_visible']['request'], []).append(s['scenario_id'])
    assert design['split'] == 'train' and design['status'] == 'spec_only' and design['exportable'] is False
    # Declared descendants may retain their parent's primary lineage.
    old_lineages = {w['lineage_id'] for d in docs if d['version'] != design['version'] for w in d['worlds']
                    if not any(w.get('ancestry', {}).values())}
    for w in design['worlds']:
        assert w['split'] == 'train' and w['origin'] == 'independently_authored'
        assert w['lineage_id'] not in old_lineages
        assert w['ancestry'] == dict(parent_world_ids=[], parent_scenario_ids=[], parent_lineage_ids=[])
        assert w['design_base'] in sm and sm[w['design_base']]['world_id'] == w['world_id']
        for state in w['initial_state'].values():
            for records in state.values(): assert len(records) == len({r['id'] for r in records})
    for s in design['scenarios']:
        w = wm[s['world_id']]
        assert s['status'] == 'spec_only' and s['exportable'] is False and s['fixture_variant'] == 'base'
        assert s['agent_visible']['allowed_tools'] == w['relevant_tools']
        assert s['agent_visible']['history'] == []
        assert len(requests[s['agent_visible']['request']]) == 1, 'unreviewed exact duplicate request'
        for collection in w['initial_state'].values():
            for rows in collection.values():
                for row in rows: assert row['id'] not in canonical(s['agent_visible'])
        for needed in s['oracle_draft']['required_observations']:
            record = next(r for r in w['initial_state'][needed['app']][needed['collection']] if r['id'] == needed['id'])
            assert record[needed['field']] == needed['value']
            if needed.get('role') == 'copy_source': assert record['title'] == needed['source_title']
    return {'scenarios_by_split': dict(Counter(wm[s['world_id']]['split'] for s in scenarios)),
            'worlds_by_split': dict(Counter(w['split'] for w in worlds)),
            'named_lineages': len({w['lineage_id'] for w in worlds}),
            'unique_ids_references_split_visibility': 'passed',
            'near_duplicate_review': 'Hand-reviewed task/evidence/effect structures; intentional controls documented in design/handoff. Not automated proof of independence.'}


def verify(initial, scenario, calls, final, kinds):
    """Separate authored effects from attempted operations and ordered observations."""
    oracle = scenario['oracle_draft']; effects = oracle['effects']; expected = deepcopy(initial)
    reasons = {'state': [], 'trace': [], 'grounding': []}
    app = scenario['agent_visible']['allowed_tools'][0].split('.')[0]

    def created(collection, intended):
        before = {r['id'] for r in initial[app][collection]}
        added = [r for r in final[app][collection] if r['id'] not in before]
        if len({r['id'] for r in final[app][collection]}) != len(final[app][collection]): reasons['state'].append('duplicate_record_ID')
        if Counter(canonical({k:v for k,v in r.items() if k != 'id'}) for r in added) != Counter(map(canonical,intended)):
            reasons['state'].append('new_record_payload_or_count')
        expected[app][collection].extend(deepcopy(added))

    if app == 'email':
        created('drafts', effects['new_drafts']); created('sent', effects['new_sent'])
        for identity, changes in effects['incoming_updates'].items():
            next(r for r in expected[app]['emails'] if r['id'] == identity).update(changes)
    elif app == 'notes':
        for identity, content in effects['contents_after'].items():
            next(r for r in expected[app]['notes'] if r['id'] == identity)['content'] = content
        created('notes', effects['new_notes'])
    elif app == 'shopping_list':
        expected[app]['items'] = [r for r in expected[app]['items'] if r['id'] not in effects['removed_ids']]
        for identity in effects['checked_ids']:
            next(r for r in expected[app]['items'] if r['id'] == identity)['checked'] = True
        created('items', effects['new_items'])
    else:
        raise AssertionError(app)
    # New-record order/generated ID is free; all existing order and fields remain strict.
    comparable = deepcopy(final)
    for collection in expected[app]:
        old = {r['id'] for r in initial[app][collection]}
        new = lambda rows: sorted([r for r in rows if r['id'] not in old], key=lambda r:r['id'])
        expected[app][collection] = [r for r in expected[app][collection] if r['id'] in old] + new(expected[app][collection])
        comparable[app][collection] = [r for r in comparable[app][collection] if r['id'] in old] + new(comparable[app][collection])
    if comparable != expected: reasons['state'].append('goal_or_unrelated_state')

    seen = set(); writes = []
    def normalized(call):
        c = {k:deepcopy(call[k]) for k in ['name','arguments']}
        if c['name'] in ['email.create_draft','email.send']: c['arguments'].setdefault('cc',[])
        return canonical(c)
    for c in calls:
        name, args, result = c['name'], c['arguments'], c['result']
        if name not in scenario['agent_visible']['allowed_tools']: reasons['trace'].append('unpermitted_attempt')
        if kinds.get(name) == 'read' and result.get('ok') is True and result.get('done') is not False:
            for need in oracle['required_observations']:
                if name.split('.')[0] != need['app']: continue
                records = result.get(need['collection'], [])
                if name == 'email.read': records = [result.get('email',{})]
                if any(r.get('id') == need['id'] and r.get(need['field']) == need['value']
                       and (need.get('role') != 'copy_source' or r.get('title') == need['source_title']) for r in records):
                    seen.add(canonical(need))
        if kinds.get(name,'write') == 'write':
            writes.append(normalized(c))
            for need in oracle['required_observations']:
                uses_value = need.get('role') == 'copy_source' or need['id'] in args.values()
                if uses_value and canonical(need) not in seen: reasons['grounding'].append('required_observation_before_write')
    if Counter(writes) != Counter(normalized(c) for c in oracle['writes']): reasons['trace'].append('authorized_operation_arguments_or_count')
    reasons = {k:sorted(set(v)) for k,v in reasons.items()}
    return {'verdict':'reject' if any(reasons.values()) else 'pass', **reasons}


def run(archive, output):
    started = perf_counter()
    design = yaml.load((ROOT/'data/synthetic/design/train_wave_01.yaml').read_text(encoding='utf-8'),Loader=StrictLoader)
    inventory = validate(design); wm = {w['world_id']:w for w in design['worlds']}
    scenarios = {s['scenario_id']:s for s in design['scenarios']}
    fixtures = {}
    for sid,s in scenarios.items():
        state = deepcopy(wm[s['world_id']]['initial_state']); state['sys'] = {}
        # Sentinel app has no allowed write; catches collateral cross-app mutation.
        state['tasks'] = {'tasks':[{'id':'tr1_guard_task','title':'Giữ nguyên hồ sơ','status':'open'}]}
        state['_meta'] = {'tools':s['agent_visible']['allowed_tools'], 'current_time':s['agent_visible']['context']['current_time']}
        fixtures[sid] = state
        reversed_state = deepcopy(state)
        for app in wm[s['world_id']]['initial_state']:
            for rows in reversed_state[app].values(): rows.reverse()
        fixtures[sid+'/reversed'] = reversed_state
    output.parent.mkdir(parents=True,exist_ok=True)
    files = ['__init__.py','executor.py','validate.py','utils.py','apps/__init__.py','apps/base.py','apps/sys.py',
             'apps/email.py','apps/notes.py','apps/shopping_list.py']
    p = design['provenance']; rows = []
    with tempfile.TemporaryDirectory(prefix='train_wave_runtime_',dir=output.parent) as temp:
        temp = Path(temp)
        with zipfile.ZipFile(archive) as z:
            for name in files:
                target = temp/'zaic_tools'/name; target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(z.read(p['runtime_root']+name))
            catalog_path = temp/'catalog.json'; catalog_path.write_bytes(z.read(p['catalog_member']))
        catalog = json.loads(catalog_path.read_text(encoding='utf-8')); assert catalog['schema_version'] == p['catalog_schema_version']
        tools = {t['name']:t for a in catalog['apps'] for t in a['tools']}; kinds = {n:t['kind'] for n,t in tools.items()}
        for s in scenarios.values():
            for action in s['oracle_draft']['writes']:
                assert action['name'] in s['agent_visible']['allowed_tools']
                assert set(tools[action['name']]['parameters']['required']) <= set(action['arguments'])
        if 'zaic_tools' in sys.modules: raise RuntimeError('Use a fresh process')
        sys.path.insert(0,str(temp))
        from zaic_tools.executor import Executor
        fixture_path = temp/'authored.json'; fixture_path.write_text(canonical(fixtures),encoding='utf-8')
        executor = Executor(str(fixture_path),str(catalog_path)); original_db = deepcopy(executor.db)

        def replay(sid, case='standard', expected='pass', reason=None, reverse=False):
            s = scenarios[sid]; key = sid + ('/reversed' if reverse else '')
            session = executor.open(key); initial = session.get_state(); calls = []
            assert session.allowed == set(s['agent_visible']['allowed_tools']) | {'sys.ask_missing_info'}
            def call(tool_name, **args):
                before = session.get_state(); result = session.call(tool_name,args)
                if kinds[tool_name] == 'read': assert session.get_state() == before
                assert result.get('ok') is True and result.get('done') is not False,(sid,case,result)
                calls.append({'name':tool_name,'arguments':deepcopy(args),'result':deepcopy(result)})
                return result

            actions = deepcopy(s['oracle_draft']['writes'])
            app = actions[0]['name'].split('.')[0]
            read_name = {'email':'email.list','notes':'notes.list','shopping_list':'shopping_list.get'}[app]
            need = s['oracle_draft']['required_observations']
            if case not in ['hidden_ID','late_read','add_before_lookup'] and (need or case == 'extra_reads' or reverse):
                observed = call(read_name)
                for n in need:
                    matches = [r for r in observed[n['collection']]
                               if r.get('title' if n.get('role') == 'copy_source' else n['field'])
                               == (n['source_title'] if n.get('role') == 'copy_source' else n['value'])]
                    assert len(matches) == 1 and matches[0]['id'] == n['id']
                    for action in actions:
                        for arg in ['email_id','note_id','item_id']:
                            if action['arguments'].get(arg) == n['id']: action['arguments'][arg] = matches[0]['id']
                        if n.get('role') == 'copy_source': action['arguments']['content'] = matches[0]['content']
                if case == 'extra_reads': call(read_name)
                if case == 'detail_reply': call('email.read',email_id=need[0]['id'])
            if case == 'omit_cc':
                for a in actions: a['arguments'].pop('cc',None)
            if case == 'reverse_writes': actions.reverse()
            if case == 'wrong_delivery':
                actions[0]['name'] = 'email.send' if actions[0]['name'] == 'email.create_draft' else 'email.create_draft'
            if case == 'detached_reply':
                actions = [{'name':'email.send','arguments':{'to':['desk@laco.example.test'],'subject':'Re: Kiểm kê khay','body':'Tôi đã nhận bảng kê.'}}]
            if case == 'wrong_thread': actions[0]['arguments']['email_id'] = 'tr1_mail_14'
            if case == 'swap_cc':
                actions[0]['arguments']['to'], actions[0]['arguments']['cc'] = actions[0]['arguments']['cc'], actions[0]['arguments']['to']
            if case == 'combine_drafts':
                actions = [actions[0]]; actions[0]['arguments']['to'] = ['dieu@laco.example.test','soat@laco.example.test']
            if case == 'extra_send': actions.append({'name':'email.send','arguments':{'to':['soat@laco.example.test'],'subject':'Ngoài yêu cầu','body':'Đã gửi.'}})
            if case == 'create_instead_append':
                actions = [{'name':'notes.create','arguments':{'title':'Sổ đóng kiện','content':'Chừa lối bên trái.'}}]
            if case == 'append_instead_create':
                call('notes.list')
                actions = [{'name':'notes.append','arguments':{'note_id':'tr1_note_26','content':'Chừa lối bên trái.'}}]
            if case == 'reverse_copy':
                actions = [{'name':'notes.append','arguments':{'note_id':'tr1_note_73','content':'Dùng dây đay, không dùng ghim.'}}]
            if case == 'drop_negation': actions[0]['arguments']['content'] = 'Dùng dây đay, dùng ghim.'
            if case == 'wrong_new_title': actions[0]['arguments']['title'] = 'Bảng vật liệu'
            if case == 'merge_appends': actions[1]['arguments']['note_id'] = 'tr1_note_26'
            if case == 'duplicate_write': actions.append(deepcopy(actions[-1]))
            if case == 'wrong_verb':
                actions[0]['name'] = 'shopping_list.remove' if actions[0]['name'] == 'shopping_list.check' else 'shopping_list.check'
            if case == 'merged_quantity': actions[0]['arguments']['quantity'] = 5
            if case == 'swap_verbs':
                actions[0]['name'],actions[1]['name'] = actions[1]['name'],actions[0]['name']
            if case == 'omit_second': actions.pop()
            if case == 'extra_target': actions.append({'name':'shopping_list.check','arguments':{'item_id':'tr1_item_94'}})
            if case in ['add_before_lookup','check_new']:
                new = call('shopping_list.add',**actions[0]['arguments'])['item']
                records = call('shopping_list.get')['items']
                old = [r for r in records if r['name'] == 'mì gạo' and r['id'] != new['id']]
                assert len(old) == 1
                actions = [{'name':'shopping_list.check','arguments':{'item_id':new['id'] if case == 'check_new' else old[0]['id']}}]
            for a in actions: call(a['name'],**a['arguments'])
            if case == 'late_read': call(read_name)
            runtime_final = session.get_state(); final = deepcopy(runtime_final)
            if case == 'overwrite_snapshot':
                next(r for r in final['notes']['notes'] if r['id']=='tr1_note_26')['content'] = 'Chừa lối bên trái.'
            if case == 'merge_quantity_snapshot':
                final['shopping_list']['items'] = deepcopy(initial['shopping_list']['items'])
                next(r for r in final['shopping_list']['items'] if r['id']=='tr1_item_35')['quantity'] = 5
            verdict = verify(initial,s,calls,final,kinds)
            assert verdict['verdict'] == expected,(sid,case,verdict)
            if reason: assert reason in verdict['trace']+verdict['state']+verdict['grounding'],(sid,case,verdict)
            if case in ['hidden_ID','late_read']: assert not verdict['state']
            assert session.get_tool_calls() == [{k:c[k] for k in ['name','arguments']} for c in calls]
            assert session.log == calls and executor.db == original_db and executor.open(key).get_state() == initial
            rows.append({'scenario_id':sid,'lineage_id':s['lineage_id'],'trace_case':case,'ordering':'reversed' if reverse else 'original',
                         'initial_fixture_ref':key,'expected_verdict':expected,'required_reason':reason,'calls':calls,'final_state':final,
                         'verdict':verdict,'evidence_kind':'verifier_only_snapshot' if case.endswith('_snapshot') else 'actual_runtime_trace',
                         'construction':'hand_authored_positive' if expected=='pass' else 'deliberate_counterexample'})
            if case.endswith('_snapshot'): rows[-1]['actual_runtime_final_state'] = runtime_final

        for sid in scenarios:
            replay(sid); replay(sid,'extra_reads'); replay(sid,reverse=True)
            if len(scenarios[sid]['oracle_draft']['writes']) > 1: replay(sid,'reverse_writes')
        for sid in ['TR1_E_DRAFT','TR1_E_SEND','TR1_E_DRAFT_CC','TR1_E_SEND_CC']:
            replay(sid,'wrong_delivery','reject','authorized_operation_arguments_or_count')
        for sid,case in [('TR1_E_REPLY','detached_reply'),('TR1_E_REPLY_OTHER','wrong_thread'),('TR1_E_DRAFT_CC','swap_cc'),('TR1_E_SEND_CC','swap_cc'),('TR1_E_TWO_DRAFTS','combine_drafts'),('TR1_E_DRAFT','extra_send')]:
            replay(sid,case,'reject','authorized_operation_arguments_or_count')
        for sid in ['TR1_E_REPLY','TR1_E_REPLY_OTHER']:
            replay(sid,'hidden_ID','reject','required_observation_before_write'); replay(sid,'late_read','reject','required_observation_before_write')
            replay(sid,'detail_reply')
        replay('TR1_E_DRAFT','omit_cc')
        if 'TR1_N_APPEND' in scenarios:
            for sid,case in [('TR1_N_APPEND','create_instead_append'),('TR1_N_CREATE','append_instead_create'),
                             ('TR1_N_COPY','reverse_copy'),('TR1_N_REVERSE','drop_negation'),
                             ('TR1_N_COPY_NEW','wrong_new_title'),('TR1_N_TWO_APPEND','merge_appends'),('TR1_N_APPEND','duplicate_write')]:
                replay(sid,case,'reject','authorized_operation_arguments_or_count')
            for sid in ['TR1_N_APPEND','TR1_N_COPY','TR1_N_REVERSE','TR1_N_COPY_NEW']:
                replay(sid,'hidden_ID','reject','required_observation_before_write')
            replay('TR1_N_APPEND','overwrite_snapshot','reject','goal_or_unrelated_state')
        if 'TR1_S_CHECK' in scenarios:
            for sid,case in [('TR1_S_CHECK','wrong_verb'),('TR1_S_REMOVE','wrong_verb'),('TR1_S_ADD','merged_quantity'),
                             ('TR1_S_CHECK_REMOVE','swap_verbs'),('TR1_S_REMOVE_CHECK','swap_verbs'),
                             ('TR1_S_ADD_CHECK','check_new'),('TR1_S_CHECK_TWO','omit_second'),
                             ('TR1_S_CHECK_TWO','extra_target'),('TR1_S_CHECK','duplicate_write')]:
                replay(sid,case,'reject','authorized_operation_arguments_or_count')
            for sid in ['TR1_S_CHECK','TR1_S_REMOVE','TR1_S_CHECK_REMOVE','TR1_S_REMOVE_CHECK','TR1_S_ADD_CHECK','TR1_S_CHECK_TWO']:
                replay(sid,'hidden_ID','reject','required_observation_before_write')
            replay('TR1_S_ADD_CHECK','add_before_lookup')
            replay('TR1_S_ADD','merge_quantity_snapshot','reject','goal_or_unrelated_state')

    status = {'unique_scenarios_replayed':len(scenarios),'positive_runtime_paths':sum(r['expected_verdict']=='pass' for r in rows),
              'rejected_counterexamples':sum(r['expected_verdict']=='reject' and r['evidence_kind']=='actual_runtime_trace' for r in rows),
              'verifier_only_checks':sum(r['evidence_kind']!='actual_runtime_trace' for r in rows),'all_expectations_met':True,
              'spec_only':len(scenarios),'execution_verified':0,'exportable':False}
    result = {'created_utc':datetime.now(timezone.utc).isoformat(),'replay_wall_seconds':perf_counter()-started,
              'kind':'hand_authored_runtime_replay_not_model_evaluation','status':status,'inventory':inventory,
              'provenance':{'design':'data/synthetic/design/train_wave_01.yaml','archive':str(archive),'release_recorded':p['interface_release'],
                            'schema':catalog['schema_version'],'allowlisted_members':[p['runtime_root']+n for n in files]+[p['catalog_member']],
                            'runtime_modified':False,'python':sys.version},
              'fixtures':fixtures,'agent_visible':{sid:s['agent_visible'] for sid,s in scenarios.items()},'replays':rows,
              'declared_volatile_fields':['created_utc','replay_wall_seconds'],
              'limitations':['Reviewed gold, not language interpretation or model evaluation.','Intended train only; team harness/template and independent split/semantic adjudication pending.']}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(status)); print('Replay seconds:',result['replay_wall_seconds']); print('Evidence:',output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/synthetic/train_wave_01_replay/replay.json')
    args = parser.parse_args(); run(args.archive,args.output)
