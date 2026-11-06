"""Focused Batch 02 hand-authored replays; not a model or official evaluator."""
from __future__ import annotations
import os

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import tempfile
import zipfile

import yaml

from replay_batch03 import StrictLoader, CODE_FILES, ROOT

RUNTIME_FILES = CODE_FILES + ('apps/contacts.py', 'apps/email.py', 'apps/reminders.py')
# Explicit diagnostic examples, not an exhaustive semantic classifier.
KNOWN_WRONG_TEXT = {
    'Tôi chỉ nhận bảy thùng giấy, không nhận thêm.': 'changed_quantity',
    'Tôi chỉ nhận sáu thùng giấy, nhận thêm.': 'reversed_restriction',
    'Tôi nhận sáu thùng giấy.': 'removed_restriction',
    'Hủy phiếu giao hàng': 'changed_action',
    'Nộp phiếu thu': 'changed_object',
}


def text_judgment(actual, expected, field):
    if actual == expected:
        return None
    if actual in KNOWN_WRONG_TEXT:
        return f'{field}:{KNOWN_WRONG_TEXT[actual]}'
    return f'{field}:human_review_required'


def verify(initial, scenario, calls, final, kinds, intended_contact, intended_title, texts):
    effects = scenario['oracle_draft']['required_effects']
    outcome = scenario['oracle_draft']['outcome']
    email = '_E_' in scenario['scenario_id']
    condition = scenario['scenario_id'][-1]
    destination = 'email.send' if email else 'reminders.create'
    app, collection = ('email', 'sent') if email else ('reminders', 'reminders')
    state, trace, grounding, text_errors, unresolved = [], [], [], [], []
    before = initial[app][collection]
    after = final.get(app, {}).get(collection, [])
    expected_count = effects.get('new_sent_count', effects.get('new_reminder_count'))
    new = after[len(before):]
    if after[:len(before)] != before:
        state.append('existing_records_modified')
    if len(after) - len(before) != expected_count:
        state.append('new_record_count')
    frame = deepcopy(final)
    frame[app][collection] = deepcopy(before)
    if frame != initial:
        state.append('unrelated_state_changed')
    if outcome != 'execute' and final != initial:
        state.append('forbidden_state_change')
    observed_values, missing_observed, writes, asks = set(), False, [], []
    for call in calls:
        name, args, result = call['name'], call['arguments'], call['result']
        permitted = name in scenario['agent_visible']['allowed_tools']
        if not permitted:
            trace.append('unpermitted_attempt')
        if result.get('ok') is not True:
            trace.append('failed_call')
        if result.get('done') is False:
            trace.append('noop_call')
        if name == 'contacts.search' and permitted and result.get('ok') is True:
            matches = [r for r in result.get('contacts', []) if r.get('name') == intended_contact]
            if len(matches) == 1:
                if matches[0].get('email'):
                    observed_values.add(matches[0]['email'])
                else:
                    missing_observed = True
        if name == 'calendar.list_events' and permitted and result.get('ok') is True:
            events = result.get('events')
            if not isinstance(events, list) or any(not isinstance(r, dict) for r in events):
                grounding.append('malformed_calendar_collection')
                continue
            matches = [r for r in events if r.get('title') == intended_title]
            if len(matches) == 1 and matches[0].get('start'):
                observed_values.add(matches[0]['start'])
            if not matches and not args.get('date_from') and not args.get('date_to'):
                missing_observed = True
        if kinds.get(name, 'write') == 'write':
            writes.append(call)
            if name != destination:
                trace.append('additional_write_attempt')
            if name == destination and condition in ['B', 'C']:
                value = args.get('to') if email else args.get('time')
                grounded = (isinstance(value, list) and len(value) == 1 and value[0] in observed_values) if email else value in observed_values
                if not grounded:
                    grounding.append('write_without_matching_source_observation')
        if name == 'sys.ask_missing_info':
            asks.append(args)
            if condition == 'C' and not missing_observed:
                grounding.append('ask_without_required_absence_observation')
    if len(writes) != expected_count:
        trace.append('write_count')
    if condition == 'D' and calls:
        trace.append('D_nonempty_attempt_log')
    if outcome == 'ask_missing':
        if len(asks) != effects['ask_count']:
            trace.append('ask_count')
        if any(a != effects['ask_arguments'] for a in asks):
            trace.append('ask_arguments')
    elif asks:
        trace.append('unexpected_ask')
    successful_writes = [c for c in writes if c['name'] == destination and
                         c['result'].get('ok') is True and c['result'].get('done') is not False]
    old_ids = {r['id'] for r in before}
    new_ids = [r.get('id') for r in new]
    if any(not isinstance(i, str) or not i or i in old_ids for i in new_ids) or len(set(new_ids)) != len(new_ids):
        state.append('invalid_new_IDs')
    if len(successful_writes) != len(new):
        state.append('response_record_count')
    for record, call in zip(new, successful_writes):
        result = call['result']
        if result.get('id') != record.get('id') or result.get('email' if email else 'item') != record:
            state.append('response_record_mismatch')
        if email:
            if outcome == 'execute' and record.get('to') != effects['to']:
                state.append('recipient')
            if record.get('cc') != effects.get('cc', []):
                state.append('unintended_cc')
            fields = [('subject', texts[0]), ('body', texts[1])]
        else:
            for field in ['time', 'repeat', 'done'] if outcome == 'execute' else []:
                if record.get(field) != effects[field]:
                    state.append('reminder_' + field)
            fields = [('content', texts[0])]
        for field, expected in fields:
            judgment = text_judgment(record.get(field), expected, field)
            if judgment:
                (unresolved if judgment.endswith('human_review_required') else text_errors).append(judgment)
    rejected = any([state, trace, grounding, text_errors])
    return {'verdict': 'reject' if rejected else ('review_required' if unresolved else 'pass'),
            'state_reasons': sorted(set(state)), 'trace_reasons': sorted(set(trace)),
            'grounding_reasons': sorted(set(grounding)), 'text_errors': sorted(set(text_errors)),
            'text_review': sorted(set(unresolved)),
            'unnecessary_read_count': sum(kinds.get(c['name']) == 'read' for c in calls) if condition == 'A' else 0}


def run(archive, output):
    design_path = ROOT / 'data/synthetic/design/batch_02.yaml'
    design_bytes = design_path.read_bytes()
    design = yaml.load(design_bytes.decode('utf-8'), Loader=StrictLoader)
    scenarios = {s['scenario_id']: s for s in design['scenarios']}
    worlds = {w['world_id']: w for w in design['worlds']}
    pair = design['interface_pair']
    fixtures, visible, materialized = {}, {}, {}
    for sid, scenario in scenarios.items():
        world = worlds[scenario['world_id']]
        entry = deepcopy(world['initial_state'])
        variant = scenario['fixture_variant']
        if variant != 'base':
            change = world['variants'][variant]
            # Only the two authored variant operations/paths, not a scenario DSL.
            if change['operation'] == 'remove_key' and change['path'] == 'contacts.contacts[0].email':
                del entry['contacts']['contacts'][0]['email']
            elif change['operation'] == 'replace_value' and change['path'] == 'calendar.events[0].title':
                entry['calendar']['events'][0]['title'] = change['value']
            else:
                raise ValueError(change)
        materialized[sid] = deepcopy(entry)
        entry['sys'] = {}
        entry['_meta'] = {'current_time': scenario['agent_visible']['context']['current_time'],
                          'tools': scenario['agent_visible']['allowed_tools'][:]}
        fixtures[sid] = entry
        agent = deepcopy(scenario['agent_visible'])
        agent['context']['installed_apps'] = {}
        for tool in agent['allowed_tools']:
            agent['context']['installed_apps'].setdefault(tool.split('.')[0], {'tools': []})['tools'].append(tool)
        visible[sid] = agent
    for family in ['E', 'N']:
        base, missing = (deepcopy(materialized[f'B02_{family}_{c}']) for c in ['B', 'C'])
        if family == 'E':
            del base['contacts']['contacts'][0]['email']
        else:
            base['calendar']['events'][0]['title'] = missing['calendar']['events'][0]['title']
        assert base == missing
        assert scenarios[f'B02_{family}_B']['agent_visible'] == scenarios[f'B02_{family}_C']['agent_visible']
        assert materialized[f'B02_{family}_A'] == materialized[f'B02_{family}_D']
        a, d = (deepcopy(scenarios[f'B02_{family}_{c}']['agent_visible']) for c in ['A', 'D'])
        write = 'email.send' if family == 'E' else 'reminders.create'
        a['allowed_tools'].remove(write)
        assert a == d
        assert scenarios[f'B02_{family}_A']['oracle_draft']['required_effects'] == scenarios[f'B02_{family}_B']['oracle_draft']['required_effects']
    evidence = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='batch02_runtime_', dir=output.parent) as temp:
        temp = Path(temp)
        members = [pair['runtime_root'] + f for f in RUNTIME_FILES] + [pair['catalog_member']]
        with zipfile.ZipFile(archive) as source:
            for relative in RUNTIME_FILES:
                p = temp / 'zaic_tools' / relative
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(source.read(pair['runtime_root'] + relative))
            catalog_path = temp / 'catalog.json'
            catalog_path.write_bytes(source.read(pair['catalog_member']))
        catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
        assert catalog['schema_version'] == pair['catalog_schema_version']
        tools = {t['name']: t for a in catalog['apps'] for t in a['tools']}
        for name, contract in pair['capability_contracts'].items():
            assert tools[name]['parameters']['required'] == contract['required']
        kinds = {name: t['kind'] for name, t in tools.items()}
        if 'zaic_tools' in sys.modules:
            raise RuntimeError('Use a fresh Python process')
        sys.path.insert(0, str(temp))
        from zaic_tools.executor import Executor
        fixture_path = temp / 'synthetic.json'
        fixture_path.write_text(json.dumps(fixtures, ensure_ascii=False), encoding='utf-8')
        executor = Executor(str(fixture_path), str(catalog_path))
        snapshot = deepcopy(executor.db)

        def replay(family, condition, case, reason=None, expected='pass'):
            sid = f'B02_{family}_{condition}'
            scenario = scenarios[sid]
            world = worlds[scenario['world_id']]
            email = family == 'E'
            base = scenarios[f'B02_{family}_B']
            effects = base['oracle_draft']['required_effects']
            quoted = re.findall(r'"([^"]*)"', scenario['agent_visible']['request'])
            texts = quoted[-2:] if email else quoted[:1]
            intended_contact = world['initial_state']['contacts']['contacts'][0]['name'] if email else None
            intended_title = world['initial_state']['calendar']['events'][0]['title'] if not email else None
            session = executor.open(sid)
            initial = session.get_state()
            assert initial == {k: v for k, v in fixtures[sid].items() if k != '_meta'}
            assert session.allowed == set(scenario['agent_visible']['allowed_tools'])
            assert session.now == scenario['agent_visible']['context']['current_time']
            calls = []

            def call(name, **args):
                result = session.call(name, args)
                calls.append({'name': name, 'arguments': deepcopy(args), 'result': deepcopy(result)})
                return result

            read = 'contacts.search' if email else 'calendar.list_events'
            write = 'email.send' if email else 'reminders.create'
            args = {'to': deepcopy(effects['to']), 'subject': texts[0], 'body': texts[1]} if email else {'content': texts[0], 'time': effects['time']}
            ask = {'tool_name': write, 'params': ['to' if email else 'time']}
            lookup_cases = {'read_write', 'full_listing', 'date_range', 'empty_then_unfiltered', 'wrong_value', 'cc', 'guess_C', 'unrelated_time', 'wrong_tool', 'wrong_parameter', 'duplicate', 'wrong_repeat', 'quantity', 'restriction', 'removed_restriction', 'action', 'object', 'paraphrase', 'snapshot', 'noop', 'extra_write', 'failed_call'}
            if case == 'empty_then_unfiltered' or case == 'filtered_only':
                result = call(read, date_from='2027-01-01', date_to='2027-01-02')
                assert result == {'ok': True, 'events': []}
            if case == 'read_only' or case in lookup_cases or (case == 'standard' and condition in ['B', 'C']):
                read_args = {'query': intended_contact} if email and case != 'full_listing' else {}
                if case == 'date_range':
                    read_args = {'date_from': effects['time'][:10], 'date_to': effects['time'][:10]}
                result = call(read, **read_args)
                collection = 'contacts' if email else 'events'
                source_app = 'contacts' if email else 'calendar'
                assert result == {'ok': True, collection: initial[source_app][collection]}
                matches = [r for r in result[collection] if r.get('name' if email else 'title') == (intended_contact if email else intended_title)]
                if condition in ['A', 'B']:
                    assert len(matches) == 1
                    if email:
                        args['to'] = [matches[0]['email']]
                    else:
                        args['time'] = matches[0]['start']
                if case == 'unrelated_time':
                    args['time'] = result['events'][0]['start']
                    assert args['time'] == effects['time'] and not matches
            should_ask = (condition == 'C' and case not in ['guess_C', 'unrelated_time']) or case == 'ask_in_A'
            if case in ['wrong_tool', 'wrong_parameter']:
                ask['tool_name' if case == 'wrong_tool' else 'params'] = 'calendar.create_event' if case == 'wrong_tool' else ['subject' if email else 'start']
            if should_ask:
                assert call('sys.ask_missing_info', **ask) == {'ok': True, 'waiting_for_user': True}
            elif case not in ['no_calls', 'read_only']:
                if case == 'wrong_value':
                    args['to' if email else 'time'] = ['other@example.test'] if email else '2026-11-14T16:40:00+07:00'
                if case == 'cc': args['cc'] = ['extra@example.test']
                if case == 'wrong_repeat': args['repeat'] = 'daily'
                if case == 'quantity': args['body'] = 'Tôi chỉ nhận bảy thùng giấy, không nhận thêm.'
                if case == 'restriction': args['body'] = 'Tôi chỉ nhận sáu thùng giấy, nhận thêm.'
                if case == 'removed_restriction': args['body'] = 'Tôi nhận sáu thùng giấy.'
                if case == 'action': args['content'] = 'Hủy phiếu giao hàng'
                if case == 'object': args['content'] = 'Nộp phiếu thu'
                if case == 'paraphrase': args['content'] = 'Nhắc mình nộp phiếu giao hàng nhé'
                if case == 'noop': args['to'] = ['invalid-address']
                if case == 'failed_call':
                    assert call(write)['ok'] is False
                result = call(write, **args)
                if condition == 'D': assert result['ok'] is False
                if case == 'noop': assert result['ok'] is True and result['done'] is False
                if case == 'duplicate': call(write, **args)
                if case == 'extra_write':
                    assert call('email.create_draft', **args)['ok'] is False
            runtime_final = session.get_state()
            final = deepcopy(runtime_final)
            if case == 'snapshot':
                final['contacts']['contacts'][0]['relation'] = 'Tampered verifier snapshot'
            assert session.get_tool_calls() == [{k: c[k] for k in ['name', 'arguments']} for c in calls]
            assert session.log == calls
            verdict = verify(initial, scenario, calls, final, kinds, intended_contact, intended_title, texts)
            assert verdict['verdict'] == expected, (sid, case, verdict)
            if reason:
                assert reason in sum([verdict[k] for k in ['state_reasons', 'trace_reasons', 'grounding_reasons', 'text_errors', 'text_review']], []), (sid, case, verdict)
            assert executor.db == snapshot and executor.open(sid).get_state() == initial
            row = {'scenario_id': sid, 'fixture_variant': scenario['fixture_variant'], 'trace_case': case,
                   'initial_fixture_ref': sid, 'expected_verdict': expected, 'required_reason': reason,
                   'construction': 'hand_authored_positive' if expected == 'pass' else ('verifier_only_snapshot_mutation' if case == 'snapshot' else 'deliberate_diagnostic_may_use_private_values'),
                   'calls': calls, 'final_state': final, 'verdict': verdict}
            if case == 'snapshot': row['actual_runtime_final_state'] = runtime_final
            evidence.append(row)

        for family in ['E', 'N']:
            for condition in ['A', 'B', 'C', 'D']:
                replay(family, condition, 'no_calls' if condition == 'D' else 'standard')
            replay(family, 'A', 'read_write')
        replay('E', 'B', 'full_listing')
        replay('N', 'B', 'date_range')
        replay('N', 'C', 'empty_then_unfiltered')
        for family in ['E', 'N']:
            for condition, case, reason in [
                ('B', 'guess_B', 'write_without_matching_source_observation'),
                ('C', 'ask_no_lookup', 'ask_without_required_absence_observation'),
                ('C', 'wrong_tool', 'ask_arguments'), ('C', 'wrong_parameter', 'ask_arguments'),
                ('A', 'ask_in_A', 'unexpected_ask'), ('D', 'read_only', 'D_nonempty_attempt_log'),
                ('D', 'attempt_write', 'unpermitted_attempt'), ('B', 'duplicate', 'write_count'),
                ('B', 'wrong_value', 'recipient' if family == 'E' else 'reminder_time'),
            ]:
                replay(family, condition, case, reason, 'reject')
        for family, condition, case, reason in [
            ('E', 'B', 'cc', 'unintended_cc'),
            ('E', 'C', 'guess_C', 'write_without_matching_source_observation'),
            ('N', 'C', 'unrelated_time', 'write_without_matching_source_observation'),
            ('N', 'C', 'filtered_only', 'ask_without_required_absence_observation'),
            ('N', 'B', 'wrong_repeat', 'reminder_repeat'),
            ('E', 'B', 'quantity', 'body:changed_quantity'),
            ('E', 'B', 'restriction', 'body:reversed_restriction'),
            ('E', 'B', 'removed_restriction', 'body:removed_restriction'),
            ('N', 'B', 'action', 'content:changed_action'),
            ('N', 'B', 'object', 'content:changed_object'),
            ('E', 'B', 'noop', 'noop_call'),
            ('E', 'B', 'extra_write', 'additional_write_attempt'),
            ('E', 'B', 'failed_call', 'failed_call'),
            ('E', 'B', 'snapshot', 'unrelated_state_changed'),
        ]:
            replay(family, condition, case, reason, 'reject')
        replay('N', 'B', 'paraphrase', 'content:human_review_required', 'review_required')
        assert design_path.read_bytes() == design_bytes
        result = {'created_utc': datetime.now(timezone.utc).isoformat(),
                  'kind': 'hand_authored_runtime_replay_not_model_evaluation',
                  'status': {'positive_replays': sum(r['expected_verdict'] == 'pass' for r in evidence),
                             'negative_checks': sum(r['expected_verdict'] == 'reject' for r in evidence),
                             'text_review_checks': sum(r['expected_verdict'] == 'review_required' for r in evidence),
                             'all_expectations_met': True, 'spec_only': 8, 'execution_verified': 0, 'exportable': False},
                  'provenance': {'design': str(design_path.relative_to(ROOT)), 'archive': str(archive),
                                 'release_as_recorded_in_design': pair['release'], 'catalog_schema_version': catalog['schema_version'],
                                 'allowlisted_members': members, 'runtime_modified': False, 'python': sys.version},
                  'reproduction_command': 'python scripts/replay_batch02.py',
                  'text_scope': {'exact_requested_text': 'accepted for these hand-authored traces',
                                 'reviewed_wrong_examples': KNOWN_WRONG_TEXT, 'other_paraphrases': 'human_review_required'},
                  'limitations': ['No model evaluation, team conversation harness or official semantic-policy acceptance.',
                                  'Intended source identity is supplied by reviewed specification, not an NLP interpreter.',
                                  'Exact text plus explicit diagnostic errors is not a complete semantic oracle.'],
                  'fixtures': fixtures, 'agent_visible': visible, 'replays': evidence}
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result['status']))
        print('Replay evidence:', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/synthetic/batch_02_replay/replay.json')
    args = parser.parse_args()
    run(args.archive, args.output)
