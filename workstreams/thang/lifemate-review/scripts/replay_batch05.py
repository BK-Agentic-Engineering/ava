"""Focused hand-authored Batch 05 replay, not a model or official policy evaluation."""
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

FILES = tuple(p for p in CODE_FILES if p != 'apps/calendar.py') + ('apps/smart_home.py',)


def verify(initial, scenario, description, calls, final, kinds):
    effects = scenario['oracle_draft']['required_effects']
    letter = scenario['scenario_id'][-1]
    target = next(r for r in initial['smart_home']['devices'] if all(r.get(k) == v for k, v in description.items()))
    expected = deepcopy(initial)
    for record in expected['smart_home']['devices']:
        record['state']['power'] = effects['power_after'][record['id']]
    state = [] if final == expected else ['state_or_frame_mismatch']
    if len(final['smart_home']['devices']) != effects['device_count_after']:
        state.append('device_count')
    trace, identity, condition, policy = [], [], [], []
    seen_target, seen_true, seen_false = False, False, False
    writes, light_writes, asks = [], [], []
    for call in calls:
        name, args, result = call['name'], call['arguments'], call['result']
        permitted = name in scenario['agent_visible']['allowed_tools']
        if not permitted: trace.append('unpermitted_attempt')
        if result.get('ok') is not True: trace.append('failed_call')
        if result.get('done') is False: trace.append('noop_call')
        if name == 'smart_home.get_status' and permitted and result.get('ok') is True and result.get('done') is not False:
            matches = [r for r in result.get('devices', []) if all(r.get(k) == v for k, v in description.items())]
            if len(matches) == 1 and matches[0].get('id') == target['id']:
                seen_target = True
                power = matches[0].get('state', {}).get('power')
                seen_true |= power == 'on'
                seen_false |= power == 'off'
        if kinds.get(name, 'write') == 'write':
            writes.append(call)
            if name != 'smart_home.light_set': trace.append('additional_write_attempt')
        if name == 'smart_home.light_set':
            light_writes.append(call)
            if args.get('device_id') != target['id']: trace.append('wrong_target_attempt')
            if args.get('power') != 'off': trace.append('wrong_power_argument')
            if not seen_target: identity.append('target_ID_not_observed_before_write')
            if letter == 'B' and not seen_true: condition.append('target_true_not_observed_before_write')
            if letter == 'C': condition.append('write_despite_false_condition')
        if name == 'sys.ask_missing_info': asks.append(call)
    if len(writes) != effects['total_write_count']: trace.append('total_write_count')
    if len(light_writes) != effects['light_write_count']: trace.append('light_write_count')
    if len(asks) != effects['ask_count']: policy.append('unjustified_ask')
    if letter == 'C' and not seen_false: condition.append('missing_target_false_observation')
    if letter == 'D' and calls: policy.append('D_nonempty_attempt_log')
    return {'verdict': 'reject' if any([state, trace, identity, condition, policy]) else 'pass',
            'state_reasons': state, 'trace_reasons': sorted(set(trace)),
            'ID_grounding_reasons': sorted(set(identity)), 'condition_reasons': sorted(set(condition)),
            'ask_capability_reasons': policy}


def run(archive, output):
    path = ROOT / 'data/synthetic/design/batch_05.yaml'
    design_bytes = path.read_bytes()
    design = yaml.load(design_bytes.decode('utf-8'), Loader=StrictLoader)
    world, pair = design['worlds'][0], design['interface_pair']
    scenarios = {s['scenario_id'][-1]: s for s in design['scenarios']}
    assert set(scenarios) == set('ABCD')
    fixtures, visible = {}, {}
    for letter, scenario in scenarios.items():
        base = deepcopy(world['initial_state'])
        if scenario['fixture_variant'] != 'base':
            variant = world['variants'][scenario['fixture_variant']]
            assert variant['operation'] == 'replace_value' and variant['path'] == 'smart_home.devices[0].state.power'
            base['smart_home']['devices'][0]['state']['power'] = variant['value']
        base['sys'] = {}
        base['_meta'] = {'tools': scenario['agent_visible']['allowed_tools'][:], 'current_time': scenario['agent_visible']['context']['current_time']}
        agent = deepcopy(scenario['agent_visible'])
        agent['context']['installed_apps'] = {}
        for name in agent['allowed_tools']:
            agent['context']['installed_apps'].setdefault(name.split('.')[0], {'tools': []})['tools'].append(name)
        for order in ['original', 'reversed']:
            key = letter + '_' + order
            fixtures[key] = deepcopy(base)
            if order == 'reversed': fixtures[key]['smart_home']['devices'].reverse()
            visible[key] = deepcopy(agent)
    b, c = deepcopy(fixtures['B_original']), fixtures['C_original']
    b['smart_home']['devices'][0]['state']['power'] = 'off'
    assert b == c and scenarios['B']['agent_visible'] == scenarios['C']['agent_visible']
    b, d = deepcopy(fixtures['B_original']), fixtures['D_original']
    b['_meta']['tools'].remove('smart_home.light_set')
    assert b == d
    b, d = deepcopy(scenarios['B']['agent_visible']), scenarios['D']['agent_visible']
    b['allowed_tools'].remove('smart_home.light_set')
    assert b == d
    output.parent.mkdir(parents=True, exist_ok=True)
    evidence = []
    with tempfile.TemporaryDirectory(prefix='batch05_runtime_', dir=output.parent) as temp:
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
            parameters = tools[name]['parameters']
            assert parameters['required'] == contract['required']
            assert set(contract['optional_used']) <= set(parameters['properties'])
        assert tools['smart_home.light_set']['parameters']['properties']['power']['enum'] == ['on', 'off']
        kinds = {name: spec['kind'] for name, spec in tools.items()}
        if 'zaic_tools' in sys.modules: raise RuntimeError('Run in a fresh Python process')
        sys.path.insert(0, str(temp))
        from zaic_tools.executor import Executor
        fp = temp / 'synthetic.json'
        fp.write_text(json.dumps(fixtures, ensure_ascii=False), encoding='utf-8')
        executor = Executor(str(fp), str(cp))
        snapshot = deepcopy(executor.db)

        def replay(letter, case='standard', order='original', expected='pass', reason=None, mutation=None, projection=None):
            scenario = scenarios[letter]
            key = letter + '_' + order
            session = executor.open(key)
            initial = session.get_state()
            assert initial == {k: v for k, v in fixtures[key].items() if k != '_meta'}
            assert session.allowed == set(scenario['agent_visible']['allowed_tools'])
            assert session.now == scenario['agent_visible']['context']['current_time']
            description = world['target_description']
            target = next(r for r in initial['smart_home']['devices'] if all(r.get(k) == v for k, v in description.items()))
            calls = []

            def call(name, **args):
                before = session.get_state()
                result = session.call(name, args)
                after = session.get_state()
                if name == 'smart_home.get_status':
                    assert after == before
                    matching = [r for r in before['smart_home']['devices'] if all(r.get(k) == v for k, v in args.items())]
                    assert result == {'ok': True, 'devices': matching}
                if name == 'sys.ask_missing_info':
                    assert result == {'ok': True, 'waiting_for_user': True} and after == before
                if name == 'smart_home.light_set' and result.get('item'):
                    record = next(r for r in after['smart_home']['devices'] if r['id'] == args['device_id'])
                    assert result['item'] == record
                    expected_after = deepcopy(before)
                    changed = next(r for r in expected_after['smart_home']['devices'] if r['id'] == args['device_id'])
                    changed['state'].update({k: v for k, v in args.items() if k != 'device_id' and v is not None})
                    assert after == expected_after
                calls.append({'name': name, 'arguments': deepcopy(args), 'result': deepcopy(result)})
                return result

            no_read = case in ['hidden_ID', 'late_read', 'empty_log'] or (letter == 'D' and case in ['standard', 'ask', 'unavailable_write'])
            observed = None
            if not no_read:
                args = {'room': description['room'], 'type': description['type']} if case == 'filtered' else {}
                if case == 'empty_filter': args = {'type': 'fan'}
                result = call('smart_home.get_status', **args)
                matches = [r for r in result['devices'] if all(r.get(k) == v for k, v in description.items())]
                observed = matches[0] if matches else None
                if case == 'repeated_reads': call('smart_home.get_status', room=description['room'], type='light')
            do_write = letter in ['A', 'B'] and case != 'no_write'
            do_write |= case in ['redundant', 'distractor_condition', 'unavailable_write']
            if do_write:
                identity = observed['id'] if observed else target['id']  # Private value only in deliberately ungrounded negatives.
                if case == 'wrong_device':
                    identity = next(r['id'] for r in result['devices'] if r['id'] != observed['id'])
                if case == 'distractor_condition':
                    assert observed['state']['power'] == 'off'
                    assert any(r['state']['power'] == 'on' and r['id'] != observed['id'] for r in result['devices'])
                if case == 'failed_call': assert call('smart_home.light_set', power='off')['ok'] is False
                if case == 'nonexistent': identity = 'b05_nonexistent'
                before_write = session.get_state()
                for _ in range(2 if case == 'duplicate' else 1): result = call('smart_home.light_set', device_id=identity, power='off')
                if case in ['redundant', 'distractor_condition']:
                    assert session.get_state() == before_write and result['ok'] is True
                if case == 'unavailable_write': assert result['ok'] is False and session.get_state() == before_write
                if case == 'nonexistent': assert result['ok'] is True and result['done'] is False
            if case in ['ask_device', 'ask_power', 'ask']:
                call('sys.ask_missing_info', tool_name='smart_home.light_set', params=['power' if case == 'ask_power' else 'device_id'])
            if case == 'late_read': call('smart_home.get_status')
            runtime_final = session.get_state()
            final = deepcopy(runtime_final)
            if mutation: mutation(final)
            verifier_calls = deepcopy(calls)
            if projection:
                # Intentionally altered verifier input, never presented as a runtime response.
                records = verifier_calls[0]['result']['devices']
                if projection == 'identity_only':
                    next(r for r in records if r['id'] == target['id'])['state'].pop('power')
                else:
                    assert projection == 'distractor_only'
                    verifier_calls[0]['result']['devices'] = [r for r in records if r['id'] != target['id']]
            assert session.get_tool_calls() == [{k: c[k] for k in ['name', 'arguments']} for c in calls]
            assert session.log == calls
            verdict = verify(initial, scenario, description, verifier_calls, final, kinds)
            assert verdict['verdict'] == expected, (letter, case, verdict)
            if reason: assert reason in sum([v for k, v in verdict.items() if k != 'verdict'], []), (case, verdict)
            if case in ['redundant', 'late_read', 'harmless_read', 'empty_log', 'distractor_condition']:
                assert not verdict['state_reasons'], verdict
            if projection == 'identity_only':
                assert not verdict['state_reasons'] and not verdict['trace_reasons'] and not verdict['ID_grounding_reasons'], verdict
            assert executor.db == snapshot and executor.open(key).get_state() == initial
            row = {'scenario_id': scenario['scenario_id'], 'fixture_variant': scenario['fixture_variant'],
                   'device_order': order, 'trace_case': case, 'initial_fixture_ref': key,
                   'expected_verdict': expected, 'required_reason': reason, 'calls': calls,
                   'final_state': final, 'verdict': verdict,
                   'evidence_kind': 'verifier_only_snapshot' if mutation else ('verifier_only_partial_observation' if projection else 'actual_runtime_trace'),
                   'construction': 'deliberate_negative_may_use_private_IDs' if expected == 'reject' else 'hand_authored_positive'}
            if mutation: row['actual_runtime_final_state'] = runtime_final
            if projection: row['verifier_input_calls'] = verifier_calls
            evidence.append(row)

        for order in ['original', 'reversed']:
            for letter in 'ABCD': replay(letter, order=order)
        for letter in 'ABC': replay(letter, 'filtered')
        replay('C', 'repeated_reads')
        for letter, case, reason in [
            ('A', 'hidden_ID', 'target_ID_not_observed_before_write'),
            ('B', 'late_read', 'target_true_not_observed_before_write'),
            ('A', 'wrong_device', 'wrong_target_attempt'), ('B', 'wrong_device', 'wrong_target_attempt'),
            ('B', 'no_write', 'total_write_count'), ('C', 'empty_log', 'missing_target_false_observation'),
            ('C', 'redundant', 'total_write_count'), ('C', 'distractor_condition', 'write_despite_false_condition'),
            ('C', 'ask_device', 'unjustified_ask'), ('C', 'ask_power', 'unjustified_ask'),
            ('C', 'empty_filter', 'missing_target_false_observation'), ('B', 'duplicate', 'total_write_count'),
            ('D', 'harmless_read', 'D_nonempty_attempt_log'), ('D', 'ask', 'D_nonempty_attempt_log'),
            ('D', 'unavailable_write', 'unpermitted_attempt'),
            ('B', 'failed_call', 'failed_call'), ('B', 'nonexistent', 'noop_call'),
        ]: replay(letter, case, expected='reject', reason=reason)
        replay('B', 'unrelated_field_snapshot', expected='reject', reason='state_or_frame_mismatch',
               mutation=lambda st: st['smart_home']['devices'][1].update(name='Verifier-only tampering'))
        replay('B', 'target_field_snapshot', expected='reject', reason='state_or_frame_mismatch',
               mutation=lambda st: st['smart_home']['devices'][0]['state'].update(brightness=30))
        replay('B', 'device_deleted_snapshot', expected='reject', reason='device_count',
               mutation=lambda st: st['smart_home']['devices'].pop())
        replay('B', 'list_order_snapshot', expected='reject', reason='state_or_frame_mismatch',
               mutation=lambda st: st['smart_home']['devices'].reverse())
        replay('A', 'identity_only_projection', projection='identity_only')
        replay('B', 'identity_only_projection', expected='reject', reason='target_true_not_observed_before_write', projection='identity_only')
        replay('C', 'distractor_only_projection', expected='reject', reason='missing_target_false_observation', projection='distractor_only')
        for letter in 'ABCD':
            rows = [r for r in evidence if r['scenario_id'].endswith('_' + letter) and r['trace_case'] == 'standard']
            assert len(rows) == 2
            assert visible[letter + '_original'] == visible[letter + '_reversed']
            def by_identity(state): return {r['id']: r for r in state['smart_home']['devices']}
            assert by_identity(rows[0]['final_state']) == by_identity(rows[1]['final_state'])
            for row in rows:
                assert [r['id'] for r in row['final_state']['smart_home']['devices']] == [r['id'] for r in fixtures[row['initial_fixture_ref']]['smart_home']['devices']]
        assert path.read_bytes() == design_bytes
        runtime = [r for r in evidence if r['evidence_kind'] == 'actual_runtime_trace']
        status = {'unique_scenarios_replayed': 4, 'positive_runtime_paths': sum(r['expected_verdict'] == 'pass' for r in runtime),
                  'negative_runtime_traces': sum(r['expected_verdict'] == 'reject' for r in runtime),
                  'snapshot_checks': 4, 'partial_observation_checks': 3,
                  'total_pass_verdicts': sum(r['expected_verdict'] == 'pass' for r in evidence),
                  'total_reject_verdicts': sum(r['expected_verdict'] == 'reject' for r in evidence),
                  'all_expectations_met': True, 'spec_only': 4, 'execution_verified': 0, 'exportable': False}
        result = {'created_utc': datetime.now(timezone.utc).isoformat(), 'kind': 'hand_authored_runtime_replay_not_model_evaluation',
                  'status': status, 'provenance': {'archive': str(archive), 'design': str(path.relative_to(ROOT)),
                  'release_as_recorded_in_design': pair['release'], 'catalog_schema_version': catalog['schema_version'],
                  'allowlisted_members': members, 'runtime_modified': False, 'python': sys.version},
                  'reproduction_command': 'python scripts/replay_batch05.py', 'fixtures': fixtures, 'agent_visible': visible,
                  'replays': evidence, 'limitations': ['No model evaluation, general condition interpreter or team harness validation.',
                  'D conditional-OOS empty-log behavior is a project draft, not official semantic acceptance.',
                  'No natural-language final explanation is evaluated; target identity comes from reviewed specification.']}
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(status))
        print('Evidence:', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/synthetic/batch_05_replay/replay.json')
    args = parser.parse_args()
    run(args.archive, args.output)
