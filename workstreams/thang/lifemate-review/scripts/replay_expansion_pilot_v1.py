"""Seven hand-authored expansion-pilot replays, not a generic harness or model eval."""
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
from replay_batch03 import ROOT, CODE_FILES, StrictLoader
from replay_batch04 import extract_time as extract_previous_line

FILES = tuple(p for p in CODE_FILES if p != 'apps/calendar.py') + ('apps/smart_home.py', 'apps/email.py', 'apps/reminders.py')


def extract_time(body):
    prefix = 'Thời điểm gửi bảng kê: '
    lines = [line for line in body.splitlines() if line.startswith(prefix)]
    if len(lines) != 1:
        return {'status': 'unresolved', 'time': None}
    # Adapt only the selected field, never unrelated labels elsewhere in the body.
    return extract_previous_line('Thời điểm nộp biên bản: ' + lines[0][len(prefix):])


def verdict(parts, calls):
    review = parts.get('text_review', [])
    errors = any(v for k, v in parts.items() if k != 'text_review')
    return {'verdict': 'reject' if errors else ('human_review_required' if review else 'pass'), **parts,
            'attempt_diagnostics': {'failed_call_indices': [i for i, c in enumerate(calls) if c['result'].get('ok') is not True],
                                    'noop_call_indices': [i for i, c in enumerate(calls) if c['result'].get('done') is False]}}


def verify_lights(initial, scenario, descriptions, calls, final, kinds):
    effects = scenario['oracle_draft']['required_effects']
    expected = deepcopy(initial)
    targets = [r for r in initial['smart_home']['devices'] if any(all(r.get(k) == v for k, v in d.items()) for d in descriptions)]
    target_ids = {r['id'] for r in targets}
    for r in expected['smart_home']['devices']: r['state']['power'] = effects['power_after'][r['id']]
    parts = {'state_reasons': [] if final == expected else ['state_or_frame_mismatch'],
             'trace_reasons': [], 'ID_grounding_reasons': [], 'condition_reasons': []}
    if len(final['smart_home']['devices']) != effects['device_count_after']: parts['state_reasons'].append('device_count')
    seen, on, off, writes, asks = set(), set(), set(), [], []
    gate = None
    for call in calls:
        name, args, result = call['name'], call['arguments'], call['result']
        allowed = name in scenario['agent_visible']['allowed_tools']
        if not allowed: parts['trace_reasons'].append('unpermitted_attempt')
        if name == 'smart_home.get_status' and allowed and result.get('ok') is True and result.get('done') is not False:
            for r in result['devices']:
                if r.get('id') in target_ids and any(all(r.get(k) == v for k, v in d.items()) for d in descriptions):
                    seen.add(r['id'])
                    if r.get('state', {}).get('power') == 'on': on.add(r['id'])
                    if r.get('state', {}).get('power') == 'off': off.add(r['id'])
        if kinds.get(name, 'write') == 'write':
            if gate is None: gate = target_ids <= on  # Freeze before first attempted group write.
            writes.append(call)
            if name != 'smart_home.light_set': parts['trace_reasons'].append('additional_write_attempt')
            if args.get('device_id') not in target_ids: parts['trace_reasons'].append('wrong_target_attempt')
            if args.get('device_id') not in seen: parts['ID_grounding_reasons'].append('unobserved_target_ID')
            if args.get('power') != 'off': parts['trace_reasons'].append('wrong_power')
            if scenario['scenario_id'] == 'EXP1_L_BOTH' and not gate:
                parts['condition_reasons'].append('both_true_not_observed_before_first_write')
        if name == 'sys.ask_missing_info': asks.append(call)
    if len(writes) != effects['total_write_count']: parts['trace_reasons'].append('total_write_count')
    if effects['total_write_count']:
        counts = Counter(c['arguments'].get('device_id') for c in writes)
        if counts != Counter({i: effects['writes_per_target'] for i in target_ids}): parts['trace_reasons'].append('writes_per_target')
    if asks: parts['trace_reasons'].append('unjustified_ask')
    if scenario['oracle_draft']['outcome'] == 'observe_no_write' and not off:
        parts['condition_reasons'].append('missing_named_false_observation')
    return verdict({k: sorted(set(v)) for k, v in parts.items()}, calls)


def verify_email(initial, scenario, calls, final, kinds):
    effects, match = scenario['oracle_draft']['required_effects'], scenario['oracle_draft']['source_match']
    execute = scenario['oracle_draft']['outcome'] == 'execute'
    parts = {k: [] for k in ['state_reasons', 'trace_reasons', 'ID_grounding_reasons', 'body_grounding_reasons', 'clarification_reasons', 'text_errors', 'text_review']}
    listed, times, unavailable, writes, asks = {}, set(), False, [], []
    for call in calls:
        name, args, result = call['name'], call['arguments'], call['result']
        allowed = name in scenario['agent_visible']['allowed_tools']
        success = allowed and result.get('ok') is True and result.get('done') is not False
        if not allowed: parts['trace_reasons'].append('unpermitted_attempt')
        if name == 'email.list' and success: listed.update({r['id']: r for r in result['emails']})
        if name == 'email.read':
            identity = args.get('email_id')
            if identity not in listed: parts['ID_grounding_reasons'].append('read_ID_not_previously_listed')
            record = result.get('email', {})
            if success and identity in listed and record.get('id') == identity and {k: v for k, v in record.items() if k != 'body'} == listed[identity] and all(record.get(k) == v for k, v in match.items()):
                parsed = extract_time(record['body'])
                if parsed['status'] == 'available': times.add(parsed['time'])
                elif parsed['status'] == 'unavailable': unavailable = True
                else: parts['text_review'].append('source_wording_unresolved')
        if kinds.get(name, 'write') == 'write':
            writes.append(call)
            if name != 'reminders.create': parts['trace_reasons'].append('additional_write_attempt')
            elif args.get('time') not in times: parts['body_grounding_reasons'].append('time_without_prior_requested_body_evidence')
        if name == 'sys.ask_missing_info':
            asks.append(args)
            if not execute and not unavailable: parts['clarification_reasons'].append('ask_before_target_unavailable_observation')
    if len(writes) != effects['total_write_count']: parts['trace_reasons'].append('total_write_count')
    if len(asks) != effects['ask_count']: parts['clarification_reasons'].append('ask_count')
    if not execute and any(a != effects['ask_arguments'] for a in asks): parts['clarification_reasons'].append('ask_arguments')
    old, after = initial['reminders']['reminders'], final['reminders']['reminders']
    new = after[len(old):]
    if after[:len(old)] != old: parts['state_reasons'].append('existing_reminder_changed')
    if len(after) - len(old) != effects['new_reminder_count']: parts['state_reasons'].append('new_reminder_count')
    frame = deepcopy(final); frame['reminders']['reminders'] = deepcopy(old)
    if frame != initial: parts['state_reasons'].append('unrelated_state_changed')
    if not execute and final != initial: parts['state_reasons'].append('forbidden_state_change')
    successful = [c for c in writes if c['name'] == 'reminders.create' and c['result'].get('ok') is True and c['result'].get('done') is not False]
    if len(new) != len(successful): parts['state_reasons'].append('response_record_count')
    ids = [r.get('id') for r in new]
    if len(set(ids)) != len(ids) or any(not isinstance(i, str) or not i or i in {r['id'] for r in old} for i in ids): parts['state_reasons'].append('invalid_generated_ID')
    content = re.findall(r'"([^"]+)"', scenario['agent_visible']['request'])[0]
    for record, call in zip(new, successful):
        if call['result'].get('item') != record or call['result'].get('id') != record.get('id'): parts['state_reasons'].append('response_record_mismatch')
        if execute:
            for field in ['time', 'repeat', 'done']:
                if record.get(field) != effects[field]: parts['state_reasons'].append('reminder_' + field)
        if record.get('content') != content:
            if record.get('content') == 'Hủy bảng kê vật liệu': parts['text_errors'].append('reviewed_changed_action')
            else: parts['text_review'].append('content_human_review_required')
    return verdict({k: sorted(set(v)) for k, v in parts.items()}, calls)


def run(archive, output):
    started = perf_counter()
    path = ROOT / 'data/synthetic/design/expansion_pilot_v1.yaml'
    original = path.read_bytes()
    design = yaml.load(original.decode('utf-8'), Loader=StrictLoader)
    worlds = {w['world_id']: w for w in design['worlds']}
    scenarios = {s['scenario_id']: s for s in design['scenarios']}
    pair = design['interface_pair']; fixtures, visible = {}, {}
    for sid, s in scenarios.items():
        state = deepcopy(worlds[s['world_id']]['initial_state'])
        if s['fixture_variant'] != 'base':
            change = worlds[s['world_id']]['variants'][s['fixture_variant']]
            assert change['operation'] == 'replace_value'
            if change['path'].startswith('smart_home.devices['): state['smart_home']['devices'][int(change['path'].split('[')[1][0])]['state']['power'] = change['value']
            else:
                assert change['path'] == 'email.emails[0].body'
                state['email']['emails'][0]['body'] = change['value']
        state['sys'] = {}; state['_meta'] = {'tools': s['agent_visible']['allowed_tools'][:], 'current_time': s['agent_visible']['context']['current_time']}
        orders = {'original': None, 'reversed': [2, 1, 0]} if '_L_' in sid else {'original': None, 'same_subject_first': [1, 0, 2], 'same_sender_first': [2, 0, 1]}
        for order, indices in orders.items():
            entry = deepcopy(state)
            if indices:
                app, collection = ('smart_home', 'devices') if '_L_' in sid else ('email', 'emails')
                entry[app][collection] = [entry[app][collection][i] for i in indices]
            key = sid + '/' + order; fixtures[key] = entry
            agent = deepcopy(s['agent_visible']); agent['context']['installed_apps'] = {}
            for name in agent['allowed_tools']: agent['context']['installed_apps'].setdefault(name.split('.')[0], {'tools': []})['tools'].append(name)
            visible[key] = agent
    def entry(sid): return deepcopy(fixtures[sid + '/original'])
    assert entry('EXP1_L_U') == entry('EXP1_L_BOTH')
    for sid, index in [('EXP1_L_FIRST_OFF', 0), ('EXP1_L_SECOND_OFF', 1)]:
        expected_entry = entry('EXP1_L_BOTH'); expected_entry['smart_home']['devices'][index]['state']['power'] = 'off'
        assert entry(sid) == expected_entry
        assert visible[sid + '/original'] == visible['EXP1_L_BOTH/original']
    expected_entry = entry('EXP1_E_A')
    expected_entry['email']['emails'][0]['body'] = expected_entry['email']['emails'][0]['body'].replace(scenarios['EXP1_E_A']['oracle_draft']['required_effects']['time'], 'chưa được chốt')
    assert entry('EXP1_E_C') == expected_entry and visible['EXP1_E_A/original'] == visible['EXP1_E_C/original']
    assert entry('EXP1_E_A') == entry('EXP1_E_B')
    # Confirm derivation and source interpretation without strengthening the fixture.
    mail = worlds['W_EXP1_MAIL_COLLISIONS']['initial_state']['email']['emails']
    source_findings = {}
    for sid in ['EXP1_E_A', 'EXP1_E_B']:
        match = scenarios[sid]['oracle_draft']['source_match']
        source_findings[sid] = {k + '_matches': sum(r[k] == v for r in mail) for k, v in match.items()}
        assert sum(all(r[k] == v for k, v in match.items()) for r in mail) == 1
    assert source_findings['EXP1_E_A'] == {'subject_matches': 2, 'from_matches': 2}
    assert source_findings['EXP1_E_B']['from_matches'] == 1
    correct = 'Thời điểm gửi bảng kê: 2026-12-03T10:15:00+07:00.'
    old = 'Thời điểm nộp biên bản: 2026-12-03T17:45:00+07:00.'
    missing = 'Thời điểm gửi bảng kê: chưa được chốt.'
    available = {'status': 'available', 'time': '2026-12-03T10:15:00+07:00'}
    unavailable = {'status': 'unavailable', 'time': None}
    unresolved = {'status': 'unresolved', 'time': None}
    source_checks = []
    for label, text, expected in [
        ('correct_timestamp', correct, available),
        ('correct_unavailable', missing, unavailable),
        ('old_label_only', old, unresolved),
        ('both_labels', correct + '\n' + old, available),
        ('both_labels_reversed', old + '\n' + correct, available),
        ('correct_unavailable_old_timestamp', missing + '\n' + old, unavailable),
        ('conflicting_correct_lines', correct + '\nThời điểm gửi bảng kê: 2026-12-03T14:35:00+07:00.', unresolved),
        ('duplicate_correct_lines', correct + '\n' + correct, unresolved),
        ('invalid_date', 'Thời điểm gửi bảng kê: 2026-02-30T10:15:00+07:00.', unresolved),
        ('unknown_expression', 'Thời điểm gửi bảng kê: khi thuận tiện.', unresolved),
        ('old_unavailable_only', 'Thời điểm nộp biên bản: chưa được chốt.', unresolved),
        ('correct_timestamp_old_unavailable', correct + '\nThời điểm nộp biên bản: chưa được chốt.', available),
    ]:
        parsed = extract_time(text)
        assert parsed == expected, (label, parsed, expected)
        source_checks.append({'case': label, 'input': text, 'expected': expected, 'result': parsed})
    output.parent.mkdir(parents=True, exist_ok=True); evidence = []
    with tempfile.TemporaryDirectory(prefix='expansion_runtime_', dir=output.parent) as temp:
        temp = Path(temp)
        members = [pair['runtime_root'] + p for p in FILES] + [pair['catalog_member']]
        with zipfile.ZipFile(archive) as source:
            for relative in FILES:
                target = temp / 'zaic_tools' / relative; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read(pair['runtime_root'] + relative))
            cp = temp / 'catalog.json'; cp.write_bytes(source.read(pair['catalog_member']))
        catalog = json.loads(cp.read_text(encoding='utf-8')); assert catalog['schema_version'] == pair['catalog_schema_version']
        tools = {t['name']: t for app in catalog['apps'] for t in app['tools']}; kinds = {n: t['kind'] for n, t in tools.items()}
        for name, contract in pair['capability_contracts'].items():
            assert tools[name]['parameters']['required'] == contract['required']
            assert set(contract['optional_used']) <= set(tools[name]['parameters']['properties'])
        if 'zaic_tools' in sys.modules: raise RuntimeError('Use a fresh Python process')
        sys.path.insert(0, str(temp))
        from zaic_tools.executor import Executor
        fp = temp / 'synthetic.json'; fp.write_text(json.dumps(fixtures, ensure_ascii=False), encoding='utf-8')
        executor = Executor(str(fp), str(cp)); snapshot = deepcopy(executor.db)

        def replay(sid, case='standard', order='original', expected='pass', reason=None, projection=None, mutation=None):
            s = scenarios[sid]; w = worlds[s['world_id']]; key = sid + '/' + order
            session = executor.open(key); initial = session.get_state(); calls = []
            assert initial == {k: v for k, v in fixtures[key].items() if k != '_meta'}
            assert session.allowed == set(s['agent_visible']['allowed_tools']) and session.now == s['agent_visible']['context']['current_time']
            def call(name, **args):
                before = session.get_state(); result = session.call(name, args)
                if kinds[name] in ['read', 'meta']: assert session.get_state() == before
                if name == 'smart_home.get_status': assert result == {'ok': True, 'devices': [r for r in before['smart_home']['devices'] if all(r.get(k) == v for k, v in args.items())]}
                if name == 'email.list': assert result == {'ok': True, 'emails': [{k: v for k, v in r.items() if k != 'body'} for r in before['email']['emails'] if not args.get('unread_only') or r['unread']]}
                if name == 'email.read' and result.get('email'): assert result['email'] == next(r for r in before['email']['emails'] if r['id'] == args['email_id'])
                if name == 'sys.ask_missing_info': assert result == {'ok': True, 'waiting_for_user': True}
                calls.append({'name': name, 'arguments': deepcopy(args), 'result': deepcopy(result)}); return result
            if '_L_' in sid:
                descriptions = [{k: r[k] for k in ['name', 'room', 'type']} for r in w['initial_state']['smart_home']['devices'][:2]]
                records = initial['smart_home']['devices'] if case in ['guess_IDs', 'empty_log'] else call('smart_home.get_status', **({'room': descriptions[0]['room'], 'type': 'light'} if case == 'filtered' else {}))['devices']
                targets = [next(r for r in records if all(r.get(k) == v for k, v in d.items())) for d in descriptions]
                if case == 'repeated_reads': call('smart_home.get_status')
                action = s['oracle_draft']['outcome'] == 'execute' or case in ['write_on_target', 'redundant']
                if action:
                    selected = targets[:]
                    if case == 'reverse_writes': selected.reverse()
                    if case in ['missing_write', 'skip_after_read']: selected = selected[:1]
                    if case == 'duplicate_first': selected = [targets[0], targets[0]]
                    if case == 'wrong_device': selected = [targets[0], next(r for r in records if r['id'] not in {t['id'] for t in targets})]
                    if case in ['write_on_target', 'redundant']: selected = [next(r for r in targets if r['state']['power'] == ('on' if case == 'write_on_target' else 'off'))]
                    if case == 'nonexistent': selected[0] = {'id': 'exp1_nonexistent'}
                    for i, r in enumerate(selected):
                        call('smart_home.light_set', device_id=r['id'], power='off')
                        if i == 0 and case in ['between_reads', 'skip_after_read']: call('smart_home.get_status')
                if case == 'ask': call('sys.ask_missing_info', tool_name='smart_home.light_set', params=['device_id'])
            else:
                content = re.findall(r'"([^"]+)"', s['agent_visible']['request'])[0]; match = s['oracle_draft']['source_match']; time = None
                if case == 'early_ask': listed = []
                elif case == 'hidden_read': listed = initial['email']['emails']  # Deliberate private-ID negative.
                else: listed = call('email.list', **({'unread_only': True} if case == 'unread_filter' else {}))['emails']
                target = next((r for r in listed if all(r[k] == v for k, v in match.items())), None)
                wrong_subject = next((r for r in listed if r['subject'] == match['subject'] and r['from'] != match['from']), None)
                wrong_sender = next((r for r in listed if r['from'] == match['from'] and r['subject'] != match['subject']), None)
                wrong = wrong_sender if case in ['same_sender', 'borrow_sender'] else wrong_subject
                if case == 'around_reads':
                    for r in listed:
                        if r['id'] != target['id']: call('email.read', email_id=r['id'])
                if case not in ['list_create', 'late_read', 'early_ask', 'nonexistent_read']:
                    chosen = wrong if case in ['same_subject', 'same_sender', 'wrong_body_correct_time'] else target
                    response = call('email.read', email_id=chosen['id'])
                    parsed = extract_time(response['email']['body'])
                    if parsed['status'] == 'available': time = parsed['time']
                    elif case == 'same_sender': time = re.search(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}', response['email']['body'])[0]
                    else: assert sid == 'EXP1_E_C' and parsed['status'] == 'unavailable'
                if case == 'around_reads':
                    for r in listed:
                        if r['id'] != target['id']: call('email.read', email_id=r['id'])
                if case == 'nonexistent_read':
                    result = call('email.read', email_id='exp1_nonexistent'); assert result['ok'] and result['done'] is False
                if case in ['borrow_subject', 'borrow_sender']:
                    response = call('email.read', email_id=wrong['id'])
                    time = re.search(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}', response['email']['body'])[0]
                if sid == 'EXP1_E_C' and case not in ['borrow_subject', 'borrow_sender']:
                    call('sys.ask_missing_info', tool_name='reminders.create', params=['content' if case == 'wrong_parameter' else 'time'])
                else:
                    if case in ['list_create', 'late_read', 'wrong_body_correct_time', 'nonexistent_read']: time = s['oracle_draft']['required_effects']['time']  # Deliberate hidden-value negatives.
                    if case == 'copy_A_time': time = scenarios['EXP1_E_A']['oracle_draft']['required_effects']['time']
                    if case == 'wrong_content': content = 'Hủy bảng kê vật liệu'
                    if case == 'paraphrase': content = 'Nhắc tôi gửi bảng kê vật liệu nhé'
                    for _ in range(2 if case == 'duplicate' else 1): call('reminders.create', content=content, time=time)
                if case == 'late_read': call('email.read', email_id=target['id'])
            runtime_final = session.get_state(); final = deepcopy(runtime_final); verifier_calls = deepcopy(calls)
            if mutation: mutation(final)
            if projection:
                if projection == 'old_label_only':
                    record = next(c['result']['email'] for c in verifier_calls if c['name'] == 'email.read' and all(c['result']['email'].get(k) == v for k, v in s['oracle_draft']['source_match'].items()))
                    observed_time = extract_time(record['body'])['time']
                    assert observed_time == s['oracle_draft']['required_effects']['time']
                    record['body'] = 'Thời điểm nộp biên bản: ' + observed_time + '.'
                else:
                    rows = verifier_calls[0]['result']['devices']
                    if projection == 'one_true': next(r for r in rows if r['id'] == targets[1]['id'])['state'].pop('power')
                    elif projection == 'identity_only':
                        for r in rows: r['state'].pop('power')
                    else:
                        assert projection == 'falsifying_only'
                        verifier_calls[0]['result']['devices'] = [r for r in rows if r['id'] in {t['id'] for t in targets} and r['state']['power'] == 'off']
            actual = verify_lights(initial, s, descriptions, verifier_calls, final, kinds) if '_L_' in sid else verify_email(initial, s, verifier_calls, final, kinds)
            assert actual['verdict'] == expected, (sid, case, actual)
            if reason: assert reason in sum([v for k, v in actual.items() if k not in ['verdict', 'attempt_diagnostics']], []), (sid, case, actual)
            if case in ['list_create', 'hidden_read', 'wrong_body_correct_time', 'late_read', 'guess_IDs', 'redundant']:
                assert not actual['state_reasons'], actual
            if case == 'one_true_projection': assert not actual['state_reasons'] and not actual['trace_reasons'] and not actual['ID_grounding_reasons']
            if projection == 'old_label_only':
                assert not actual['state_reasons'] and not actual['trace_reasons'] and not actual['ID_grounding_reasons'] and not actual['clarification_reasons']
                assert actual['text_review'] == ['source_wording_unresolved']
            assert session.get_tool_calls() == [{k: c[k] for k in ['name', 'arguments']} for c in calls] and session.log == calls
            assert executor.db == snapshot and executor.open(key).get_state() == initial
            row = {'scenario_id': sid, 'lineage_id': s['lineage_id'], 'fixture_variant': s['fixture_variant'], 'ordering': order,
                   'trace_case': case, 'initial_fixture_ref': key, 'expected_verdict': expected, 'required_reason': reason,
                   'calls': calls, 'final_state': final, 'verdict': actual,
                   'construction': 'deliberate_diagnostic_may_use_private_values' if expected != 'pass' else 'hand_authored_positive',
                   'evidence_kind': 'verifier_only_snapshot' if mutation else ('verifier_only_projection' if projection else 'actual_runtime_trace')}
            if mutation: row['actual_runtime_final_state'] = runtime_final
            if projection: row['verifier_input_calls'] = verifier_calls
            evidence.append(row)

        for sid in scenarios: replay(sid)
        lights = [sid for sid in scenarios if '_L_' in sid]
        for sid in lights:
            replay(sid, order='reversed'); replay(sid, 'filtered')
        for sid in ['EXP1_L_U', 'EXP1_L_BOTH']: replay(sid, 'reverse_writes')
        replay('EXP1_L_BOTH', 'between_reads'); replay('EXP1_L_FIRST_OFF', 'repeated_reads')
        for order in ['same_subject_first', 'same_sender_first']: replay('EXP1_E_A', order=order)
        for sid in ['EXP1_E_A', 'EXP1_E_B', 'EXP1_E_C']: replay(sid, 'around_reads')
        replay('EXP1_E_A', 'unread_filter')
        for sid, case, reason in [
            ('EXP1_L_U', 'missing_write', 'writes_per_target'), ('EXP1_L_U', 'wrong_device', 'wrong_target_attempt'),
            ('EXP1_L_BOTH', 'duplicate_first', 'writes_per_target'), ('EXP1_L_BOTH', 'guess_IDs', 'unobserved_target_ID'),
            ('EXP1_L_BOTH', 'skip_after_read', 'writes_per_target'),
            ('EXP1_L_FIRST_OFF', 'write_on_target', 'total_write_count'), ('EXP1_L_SECOND_OFF', 'write_on_target', 'total_write_count'),
            ('EXP1_L_FIRST_OFF', 'redundant', 'total_write_count'), ('EXP1_L_FIRST_OFF', 'empty_log', 'missing_named_false_observation'),
            ('EXP1_L_FIRST_OFF', 'ask', 'unjustified_ask'), ('EXP1_L_BOTH', 'nonexistent', 'wrong_target_attempt'),
            ('EXP1_E_A', 'same_subject', 'time_without_prior_requested_body_evidence'), ('EXP1_E_A', 'same_sender', 'time_without_prior_requested_body_evidence'),
            ('EXP1_E_B', 'copy_A_time', 'reminder_time'), ('EXP1_E_A', 'hidden_read', 'read_ID_not_previously_listed'),
            ('EXP1_E_A', 'list_create', 'time_without_prior_requested_body_evidence'), ('EXP1_E_A', 'wrong_body_correct_time', 'time_without_prior_requested_body_evidence'),
            ('EXP1_E_A', 'late_read', 'time_without_prior_requested_body_evidence'), ('EXP1_E_C', 'early_ask', 'ask_before_target_unavailable_observation'),
            ('EXP1_E_C', 'wrong_parameter', 'ask_arguments'), ('EXP1_E_C', 'borrow_subject', 'time_without_prior_requested_body_evidence'),
            ('EXP1_E_C', 'borrow_sender', 'time_without_prior_requested_body_evidence'), ('EXP1_E_A', 'duplicate', 'total_write_count'),
            ('EXP1_E_A', 'wrong_content', 'reviewed_changed_action'), ('EXP1_E_A', 'nonexistent_read', 'time_without_prior_requested_body_evidence'),
        ]: replay(sid, case, expected='reject', reason=reason)
        replay('EXP1_L_BOTH', 'collateral_snapshot', expected='reject', reason='state_or_frame_mismatch', mutation=lambda st: st['smart_home']['devices'][2]['state'].update(power='off'))
        replay('EXP1_E_A', 'existing_record_snapshot', expected='reject', reason='existing_reminder_changed', mutation=lambda st: st['reminders']['reminders'][0].update(done=True))
        replay('EXP1_L_BOTH', 'one_true_projection', expected='reject', reason='both_true_not_observed_before_first_write', projection='one_true')
        for sid in ['EXP1_L_FIRST_OFF', 'EXP1_L_SECOND_OFF']: replay(sid, 'falsifying_only_projection', projection='falsifying_only')
        replay('EXP1_L_U', 'identity_only_projection', projection='identity_only')
        replay('EXP1_E_A', 'old_label_only_projection', expected='reject', reason='time_without_prior_requested_body_evidence', projection='old_label_only')
        replay('EXP1_E_A', 'paraphrase', expected='human_review_required', reason='content_human_review_required')
        for sid in lights + ['EXP1_E_A']:
            rows = [r for r in evidence if r['scenario_id'] == sid and r['trace_case'] == 'standard']
            def canonical(st):
                out = deepcopy(st)
                if 'smart_home' in out: out['smart_home']['devices'] = sorted(out['smart_home']['devices'], key=lambda r: r['id'])
                if 'email' in out: out['email']['emails'] = sorted(out['email']['emails'], key=lambda r: r['id'])
                return out
            assert all(canonical(r['final_state']) == canonical(rows[0]['final_state']) for r in rows)
            for r in rows:
                app, col = ('smart_home', 'devices') if '_L_' in sid else ('email', 'emails')
                assert [x['id'] for x in r['final_state'][app][col]] == [x['id'] for x in fixtures[r['initial_fixture_ref']][app][col]]
                assert visible[r['initial_fixture_ref']] == visible[sid + '/original']
        assert path.read_bytes() == original
        runtime = [r for r in evidence if r['evidence_kind'] == 'actual_runtime_trace']
        status = {'unique_scenarios_replayed': 7, 'positive_runtime_paths': sum(r['expected_verdict'] == 'pass' for r in runtime),
                  'negative_runtime_traces': sum(r['expected_verdict'] == 'reject' for r in runtime),
                  'human_review_runtime_probes': sum(r['expected_verdict'] == 'human_review_required' for r in runtime),
                  'verifier_only_checks': len(evidence) - len(runtime), 'all_expectations_met': True,
                  'pure_extractor_checks': len(source_checks),
                  'spec_only': 7, 'execution_verified': 0, 'exportable': False}
        result = {'created_utc': datetime.now(timezone.utc).isoformat(), 'check_wall_seconds': perf_counter() - started,
                  'kind': 'hand_authored_runtime_replay_not_model_evaluation', 'status': status,
                  'provenance': {'archive': str(archive), 'design': str(path.relative_to(ROOT)), 'release_as_recorded_in_design': pair['release'],
                                 'catalog_schema_version': catalog['schema_version'], 'allowlisted_members': members, 'runtime_modified': False, 'python': sys.version},
                  'reproduction_command': 'python scripts/replay_expansion_pilot_v1.py',
                  'volatile_comparison_fields': ['created_utc', 'check_wall_seconds'], 'source_identity_findings': source_findings,
                  'world_ancestry': {wid: w['ancestry'] for wid, w in worlds.items()}, 'fixtures': fixtures, 'agent_visible': visible,
                  'source_extractor_checks': source_checks, 'replays': evidence,
                  'limitations': ['No model evaluation or official semantic-policy acceptance; no team training/harness integration.',
                  'Failed/no-op calls are diagnostic evidence, not a universal task-failure rule. Authored write/evidence/frame restrictions decide verdicts.',
                  'Bounded authored-line extractor and text checks; unfamiliar wording remains unresolved.']}
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(status)); print('Evidence:', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/synthetic/expansion_pilot_v1_replay/replay.json')
    args = parser.parse_args(); run(args.archive, args.output)
