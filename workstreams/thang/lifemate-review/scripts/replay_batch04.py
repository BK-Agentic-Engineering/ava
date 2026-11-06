"""Batch 04 hand-authored local replay; bounded source/text interpretation, no model."""
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
from replay_batch03 import ROOT, CODE_FILES, StrictLoader

FILES = tuple(p for p in CODE_FILES if p != 'apps/calendar.py') + ('apps/email.py', 'apps/reminders.py')


def extract_time(body):
    """Only the authored line; unknown/ambiguous wording is not evidence of missingness."""
    lines = [line for line in body.splitlines() if line.startswith('Thời điểm nộp biên bản: ')]
    if len(lines) != 1:
        return {'status': 'unresolved', 'time': None}
    expression = lines[0].removeprefix('Thời điểm nộp biên bản: ')
    if expression == 'chưa được chốt.':
        return {'status': 'unavailable', 'time': None}
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}\.', expression):
        try:
            value = expression[:-1]
            datetime.fromisoformat(value)
            return {'status': 'available', 'time': value}
        except ValueError:
            pass
    return {'status': 'unresolved', 'time': None}


def verify(initial, scenario, target_metadata, calls, final, kinds):
    effects = scenario['oracle_draft']['required_effects']
    explicit = scenario['scenario_id'].endswith('_A')
    execute = scenario['oracle_draft']['outcome'] == 'execute'
    state, trace, ids, values, clarification, text_errors, review = [], [], [], [], [], [], []
    listed, target_values, target_missing = {}, set(), False
    writes, asks = [], []
    for call in calls:
        name, args, result = call['name'], call['arguments'], call['result']
        permitted = name in scenario['agent_visible']['allowed_tools']
        success = permitted and result.get('ok') is True and result.get('done') is not False
        if not permitted: trace.append('unpermitted_attempt')
        if result.get('ok') is not True: trace.append('failed_call')
        if result.get('done') is False: trace.append('noop_call')
        if name == 'email.list' and success:
            listed.update({r['id']: r for r in result['emails']})
        if name == 'email.read':
            identity = args.get('email_id')
            grounded_id = identity in listed
            if not grounded_id: ids.append('read_ID_not_previously_listed')
            if success and result.get('email'):
                record = result['email']
                if record.get('id') != identity:
                    ids.append('read_response_ID_mismatch')
                metadata = {k: v for k, v in record.items() if k != 'body'}
                target = grounded_id and metadata == listed[identity] and record.get('id') == identity and all(record.get(k) == v for k, v in target_metadata.items())
                if target:
                    parsed = extract_time(record.get('body', ''))
                    if parsed['status'] == 'available': target_values.add(parsed['time'])
                    elif parsed['status'] == 'unavailable': target_missing = True
                    else: review.append('target_source_wording_unresolved')
        if kinds.get(name, 'write') == 'write':
            writes.append(call)
            if name != 'reminders.create': trace.append('additional_write_attempt')
            elif not explicit and args.get('time') not in target_values:
                values.append('create_without_prior_matching_target_body_time')
        if name == 'sys.ask_missing_info':
            asks.append(args)
            if not execute and not target_missing:
                clarification.append('ask_without_prior_target_unavailable_observation')
    if len(writes) != effects['new_reminder_count']: trace.append('write_count')
    if execute:
        if asks: clarification.append('unjustified_ask')
    else:
        if len(asks) != effects['ask_count']: clarification.append('ask_count')
        if any(a != effects['ask_arguments'] for a in asks): clarification.append('ask_arguments')
    old, after = initial['reminders']['reminders'], final['reminders']['reminders']
    new = after[len(old):]
    if after[:len(old)] != old: state.append('existing_reminder_changed')
    if len(after) - len(old) != effects['new_reminder_count']: state.append('new_reminder_count')
    frame = deepcopy(final)
    frame['reminders']['reminders'] = deepcopy(old)
    if frame != initial: state.append('unrelated_state_changed')
    if not execute and final != initial: state.append('forbidden_state_change')
    new_ids = [r.get('id') for r in new]
    if any(not isinstance(i, str) or not i or i in {r['id'] for r in old} for i in new_ids) or len(set(new_ids)) != len(new_ids):
        state.append('invalid_generated_ID')
    successful = [c for c in writes if c['name'] == 'reminders.create' and c['result'].get('ok') is True and c['result'].get('done') is not False]
    if len(successful) != len(new): state.append('response_record_count')
    content = re.findall(r'"([^"]+)"', scenario['agent_visible']['request'])[0]
    for record, call in zip(new, successful):
        if call['result'].get('id') != record.get('id') or call['result'].get('item') != record:
            state.append('response_record_mismatch')
        if execute:
            for field in ['time', 'repeat', 'done']:
                if record.get(field) != effects[field]: state.append('reminder_' + field)
        actual = record.get('content')
        if actual != content:
            if actual in ['Hủy biên bản bàn giao kệ trưng bày', 'Nộp phiếu bảo trì giá đỡ']:
                text_errors.append('reviewed_content_meaning_error')
            else: review.append('content_human_review_required')
    errors = any([state, trace, ids, values, clarification, text_errors])
    return {'verdict': 'reject' if errors else ('human_review_required' if review else 'pass'),
            'state_reasons': sorted(set(state)), 'trace_reasons': sorted(set(trace)),
            'ID_grounding_reasons': sorted(set(ids)), 'body_value_grounding_reasons': sorted(set(values)),
            'clarification_reasons': sorted(set(clarification)), 'text_errors': sorted(set(text_errors)),
            'text_review': sorted(set(review))}


def run(archive, output):
    design_path = ROOT / 'data/synthetic/design/batch_04.yaml'
    design_bytes = design_path.read_bytes()
    design = yaml.load(design_bytes.decode('utf-8'), Loader=StrictLoader)
    world, pair = design['worlds'][0], design['interface_pair']
    scenarios = {s['scenario_id'][-1]: s for s in design['scenarios']}
    assert set(scenarios) == set('ABCD')
    fixtures, visible = {}, {}
    for letter, scenario in scenarios.items():
        entry = deepcopy(world['initial_state'])
        if scenario['fixture_variant'] != 'base':
            change = world['variants'][scenario['fixture_variant']]
            assert change['operation'] == 'replace_value' and change['path'] == 'email.emails[0].body'
            entry['email']['emails'][0]['body'] = change['value']
        entry['sys'] = {}
        entry['_meta'] = {'current_time': scenario['agent_visible']['context']['current_time'], 'tools': scenario['agent_visible']['allowed_tools'][:]}
        fixtures[letter] = entry
        agent = deepcopy(scenario['agent_visible'])
        agent['context']['installed_apps'] = {}
        for name in agent['allowed_tools']:
            agent['context']['installed_apps'].setdefault(name.split('.')[0], {'tools': []})['tools'].append(name)
        visible[letter] = agent
    for letter in ['C', 'D']:
        expected = deepcopy(fixtures['B'])
        expected['email']['emails'][0]['body'] = fixtures[letter]['email']['emails'][0]['body']
        assert fixtures[letter] == expected and visible[letter] == visible['B']
    base_body = fixtures['B']['email']['emails'][0]['body']
    base_time = scenarios['B']['oracle_draft']['required_effects']['time']
    assert base_body.replace(base_time, scenarios['C']['oracle_draft']['required_effects']['time']) == fixtures['C']['email']['emails'][0]['body']
    assert base_body.replace(base_time, 'chưa được chốt') == fixtures['D']['email']['emails'][0]['body']
    # Pure extractor inputs, not fabricated runtime observations or extra scenarios.
    source_checks = []
    for label, body, expected in [
        ('authored_time', base_body, 'available'),
        ('authored_unavailable', fixtures['D']['email']['emails'][0]['body'], 'unavailable'),
        ('unfamiliar', 'Thời điểm nộp biên bản: khi thuận tiện.', 'unresolved'),
        ('ambiguous', base_body + base_body, 'unresolved'),
        ('invalid_date', 'Thời điểm nộp biên bản: 2026-02-30T14:20:00+07:00.', 'unresolved'),
    ]:
        parsed = extract_time(body)
        assert parsed['status'] == expected
        source_checks.append({'case': label, 'authored_text_input': body, 'expected_status': expected, 'actual': parsed})
    output.parent.mkdir(parents=True, exist_ok=True)
    evidence = []
    with tempfile.TemporaryDirectory(prefix='batch04_runtime_', dir=output.parent) as temp:
        temp = Path(temp)
        members = [pair['runtime_root'] + p for p in FILES] + [pair['catalog_member']]
        with zipfile.ZipFile(archive) as source:
            for relative in FILES:
                destination = temp / 'zaic_tools' / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read(pair['runtime_root'] + relative))
            cp = temp / 'catalog.json'
            cp.write_bytes(source.read(pair['catalog_member']))
        catalog = json.loads(cp.read_text(encoding='utf-8'))
        assert catalog['schema_version'] == pair['catalog_schema_version']
        tools = {t['name']: t for app in catalog['apps'] for t in app['tools']}
        for name, contract in pair['capability_contracts'].items():
            assert tools[name]['parameters']['required'] == contract['required']
            assert set(contract['optional_used']) <= set(tools[name]['parameters']['properties'])
        kinds = {name: tool['kind'] for name, tool in tools.items()}
        if 'zaic_tools' in sys.modules: raise RuntimeError('Use a fresh Python process')
        sys.path.insert(0, str(temp))
        from zaic_tools.executor import Executor
        fp = temp / 'synthetic.json'
        fp.write_text(json.dumps(fixtures, ensure_ascii=False), encoding='utf-8')
        executor = Executor(str(fp), str(cp))
        snapshot = deepcopy(executor.db)

        def replay(letter, case='standard', expected='pass', reason=None, mutation=None):
            scenario = scenarios[letter]
            session = executor.open(letter)
            initial = session.get_state()
            assert initial == {k: v for k, v in fixtures[letter].items() if k != '_meta'}
            assert session.allowed == set(scenario['agent_visible']['allowed_tools'])
            assert session.now == scenario['agent_visible']['context']['current_time']
            calls = []

            def call(name, **args):
                before = session.get_state()
                result = session.call(name, args)
                if kinds.get(name) in ['read', 'meta']:
                    assert session.get_state() == before, 'Read/meta side effect'
                if name == 'email.list':
                    assert result == {'ok': True, 'emails': [{k: v for k, v in r.items() if k != 'body'} for r in before['email']['emails'] if not args.get('unread_only') or r['unread']]}
                if name == 'email.read' and result.get('email'):
                    assert result['email'] == next(r for r in before['email']['emails'] if r['id'] == args['email_id'])
                calls.append({'name': name, 'arguments': deepcopy(args), 'result': deepcopy(result)})
                return result

            content = re.findall(r'"([^"]+)"', scenario['agent_visible']['request'])[0]
            wanted = scenario['oracle_draft']['required_effects']
            time = scenarios['A']['oracle_draft']['required_effects']['time'] if letter == 'A' else None
            target_id = initial['email']['emails'][0]['id']  # Deliberate hidden-ID diagnostics only.
            skip_list = case in ['hidden_ID', 'A_hidden_ID', 'early_ask'] or (letter == 'A' and case in ['standard', 'A_ask'])
            if not skip_list:
                listed = call('email.list', **({'unread_only': True} if case == 'unread_filter' else {}))['emails']
                matches = [r for r in listed if all(r.get(k) == v for k, v in world['target_metadata'].items())]
                assert len(matches) == 1
                target = matches[0]
                target_id = target['id']
                distractor_id = next(r['id'] for r in listed if r['id'] != target_id)
            if case in ['both_reads', 'distractor_only']:
                call('email.read', email_id=distractor_id)
            skip_target = case in ['list_only_create', 'distractor_only', 'late_read', 'early_ask', 'nonexistent_read'] or (letter == 'A' and case in ['standard', 'A_ask'])
            if case == 'nonexistent_read':
                result = call('email.read', email_id='b04_nonexistent')
                assert result['ok'] is True and result['done'] is False and 'email' not in result
            if not skip_target:
                result = call('email.read', email_id=target_id)
                parsed = extract_time(result['email']['body'])
                if parsed['status'] == 'available': time = parsed['time']
                else: assert letter == 'D' and parsed['status'] == 'unavailable'
            if case == 'target_then_distractor':
                result = call('email.read', email_id=distractor_id)
                # Deliberate wrong-source diagnostic: timestamp extraction here is not target evidence.
                time = re.search(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}', result['email']['body'])[0]
            if case == 'target_then_distractor_keep_target':
                call('email.read', email_id=distractor_id)  # Keep the previously extracted target time.
            should_ask = (letter == 'D' and case != 'guess_create') or case == 'A_ask'
            if should_ask:
                args = {'tool_name': 'reminders.create', 'params': ['time']}
                if case == 'wrong_tool': args['tool_name'] = 'email.read'
                if case == 'wrong_parameter': args['params'] = ['content']
                assert call('sys.ask_missing_info', **args) == {'ok': True, 'waiting_for_user': True}
            else:
                if case in ['old_time', 'guess_create', 'list_only_create', 'distractor_only', 'late_read', 'nonexistent_read']:
                    time = base_time  # Deliberate negative construction using a private value.
                if case == 'wrong_content': content = 'Hủy biên bản bàn giao kệ trưng bày'
                if case == 'paraphrase': content = 'Nhắc mình nộp biên bản bàn giao kệ trưng bày nhé'
                args = {'content': content, 'time': time}
                if case == 'wrong_repeat': args['repeat'] = 'daily'
                if case == 'failed_call': assert call('reminders.create', content=content)['ok'] is False
                for _ in range(2 if case == 'duplicate' else 1): call('reminders.create', **args)
                if case == 'extra_write':
                    assert call('email.archive', email_id=target_id, action='archive')['ok'] is False
            if case == 'late_read': call('email.read', email_id=target_id)
            runtime_final = session.get_state()
            final = deepcopy(runtime_final)
            if mutation: mutation(final)
            assert session.get_tool_calls() == [{k: c[k] for k in ['name', 'arguments']} for c in calls]
            assert session.log == calls
            verdict = verify(initial, scenario, world['target_metadata'], calls, final, kinds)
            assert verdict['verdict'] == expected, (letter, case, verdict)
            if reason:
                assert reason in sum([v for k, v in verdict.items() if k != 'verdict'], []), (letter, case, verdict)
            if case in ['list_only_create', 'hidden_ID', 'distractor_only', 'late_read'] and letter == 'B':
                assert not verdict['state_reasons'] and not verdict['trace_reasons'], verdict
            if case in ['nonexistent_read', 'old_time']:
                assert 'create_without_prior_matching_target_body_time' in verdict['body_value_grounding_reasons']
            assert executor.db == snapshot and executor.open(letter).get_state() == initial
            row = {'scenario_id': scenario['scenario_id'], 'fixture_variant': scenario['fixture_variant'],
                   'trace_case': case, 'initial_fixture_ref': letter, 'expected_verdict': expected,
                   'required_reason': reason, 'calls': calls, 'final_state': final, 'verdict': verdict,
                   'construction': 'verifier_only_snapshot_mutation' if mutation else ('hand_authored_positive' if expected == 'pass' else 'deliberate_diagnostic_may_use_private_values')}
            if mutation: row['actual_runtime_final_state'] = runtime_final
            evidence.append(row)

        for letter in 'ABCD': replay(letter)
        for letter, case in [('A', 'optional_reads'), ('B', 'unread_filter'), ('B', 'both_reads'), ('C', 'both_reads'), ('D', 'both_reads')]: replay(letter, case)
        replay('C', 'target_then_distractor_keep_target')
        for letter, case, reason in [
            ('B', 'list_only_create', 'create_without_prior_matching_target_body_time'),
            ('B', 'hidden_ID', 'read_ID_not_previously_listed'),
            ('B', 'distractor_only', 'create_without_prior_matching_target_body_time'),
            ('B', 'late_read', 'create_without_prior_matching_target_body_time'),
            ('C', 'old_time', 'reminder_time'), ('C', 'target_then_distractor', 'create_without_prior_matching_target_body_time'),
            ('D', 'early_ask', 'ask_without_prior_target_unavailable_observation'),
            ('D', 'distractor_only', 'ask_without_prior_target_unavailable_observation'),
            ('D', 'guess_create', 'create_without_prior_matching_target_body_time'),
            ('D', 'wrong_tool', 'ask_arguments'), ('D', 'wrong_parameter', 'ask_arguments'),
            ('A', 'A_ask', 'unjustified_ask'), ('A', 'A_hidden_ID', 'read_ID_not_previously_listed'),
            ('B', 'duplicate', 'write_count'), ('B', 'wrong_repeat', 'reminder_repeat'),
            ('B', 'wrong_content', 'reviewed_content_meaning_error'), ('B', 'nonexistent_read', 'noop_call'),
            ('B', 'failed_call', 'failed_call'), ('B', 'extra_write', 'additional_write_attempt'),
        ]: replay(letter, case, 'reject', reason)
        replay('B', 'existing_reminder_snapshot', 'reject', 'existing_reminder_changed', mutation=lambda st: st['reminders']['reminders'][0].update(done=True))
        for field, value in [('unread', False), ('folder', 'archive'), ('body', 'Verifier-only changed body')]:
            replay('B', 'email_' + field + '_snapshot', 'reject', 'unrelated_state_changed',
                   mutation=lambda st, k=field, v=value: st['email']['emails'][0].update({k: v}))
        replay('B', 'paraphrase', 'human_review_required', 'content_human_review_required')
        assert design_path.read_bytes() == design_bytes
        status = {'unique_scenarios_replayed': 4, 'positive_paths': sum(r['expected_verdict'] == 'pass' for r in evidence),
                  'negative_checks': sum(r['expected_verdict'] == 'reject' for r in evidence),
                  'human_review_probes': sum(r['expected_verdict'] == 'human_review_required' for r in evidence),
                  'source_extractor_checks': len(source_checks), 'all_expectations_met': True,
                  'spec_only': 4, 'execution_verified': 0, 'exportable': False}
        result = {'created_utc': datetime.now(timezone.utc).isoformat(), 'kind': 'hand_authored_runtime_replay_not_model_evaluation',
                  'status': status, 'provenance': {'design': str(design_path.relative_to(ROOT)), 'archive': str(archive),
                  'release_as_recorded_in_design': pair['release'], 'catalog_schema_version': catalog['schema_version'],
                  'allowlisted_members': members, 'runtime_modified': False, 'python': sys.version},
                  'reproduction_command': 'python scripts/replay_batch04.py', 'fixtures': fixtures, 'agent_visible': visible,
                  'source_extractor_checks': source_checks, 'replays': evidence,
                  'limitations': ['No model evaluation, team conversation harness or official semantic-policy acceptance.',
                                  'Extractor understands only the authored timestamp/unavailable expression; other source wording is unresolved.',
                                  'Exact content and explicit errors are bounded checks, not a general semantic oracle.']}
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(status))
        print('Evidence:', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/synthetic/batch_04_replay/replay.json')
    args = parser.parse_args()
    run(args.archive, args.output)
