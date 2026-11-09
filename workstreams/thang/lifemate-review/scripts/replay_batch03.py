"""Hand-authored Batch 03 runtime replay; no model, history parser or official scorer."""
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

ROOT = Path(__file__).resolve().parents[1]
CODE_FILES = (
    '__init__.py', 'executor.py', 'validate.py', 'utils.py',
    'apps/__init__.py', 'apps/base.py', 'apps/calendar.py', 'apps/sys.py',
)


class StrictLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f'Duplicate YAML key: {key}')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def verify(initial, scenario, calls, final, kinds):
    """Separate complete state/frame checks from attempted-call and grounding checks.

    Intended target comes from reviewed oracle statuses, never NLP on the history.
    Only a successful permitted list observation of that exact initial record grounds ID.
    """
    effects = scenario['oracle_draft']['required_effects']
    expected = deepcopy(initial)
    for event in expected['calendar']['events']:
        event['status'] = effects['statuses'][event['id']]
    state_reasons = [] if final == expected else ['state_or_frame_mismatch']
    reasons, observed, cancels, asks = [], set(), [], []
    initial_records = {e['id']: e for e in initial['calendar']['events']}
    targets = {i for i, status in effects['statuses'].items()
               if status != initial_records[i]['status']}
    for call in calls:
        name, arguments, result = call['name'], call['arguments'], call['result']
        permitted = name in scenario['agent_visible']['allowed_tools']
        if not permitted:
            reasons.append('unpermitted_attempt')
        if result.get('ok') is not True:
            reasons.append('failed_call')
        if result.get('done') is False:
            reasons.append('noop_call')
        if name == 'calendar.list_events' and permitted and result.get('ok') is True:
            for record in result.get('events', []):
                if record == initial_records.get(record.get('id')):
                    observed.add(record['id'])
        elif name == 'calendar.cancel_event':
            event_id = arguments.get('event_id')
            cancels.append(event_id)
            if event_id not in observed:
                reasons.append('ungrounded_cancel')
            if event_id not in targets:
                reasons.append('wrong_target_attempt')
        elif name == 'sys.ask_missing_info':
            asks.append(arguments)
        elif kinds.get(name, 'write') != 'read':
            reasons.append('additional_write_attempt')
    if len(cancels) != effects['latest_turn_cancel_count']:
        reasons.append('cancel_count')
    if scenario['oracle_draft']['outcome'] == 'ask_missing':
        if len(asks) != effects['ask_count']:
            reasons.append('ask_count')
        if any(a != effects['ask_arguments'] for a in asks):
            reasons.append('ask_arguments')
    elif asks:
        reasons.append('unexpected_ask')
    return {'passed': not state_reasons and not reasons,
            'state_reasons': state_reasons, 'trace_reasons': sorted(set(reasons))}


def run(archive, output):
    design_path = ROOT / 'data/synthetic/design/batch_03.yaml'
    design_bytes = design_path.read_bytes()
    design = yaml.load(design_bytes.decode('utf-8'), Loader=StrictLoader)
    world = design['worlds'][0]
    scenarios = {s['scenario_id']: s for s in design['scenarios']}
    assert set(scenarios) == {'H1', 'H2', 'H3', 'H4'}
    pair = design['interface_pair']
    source_root = pair['runtime_root']
    members = [source_root + name for name in CODE_FILES] + [pair['catalog_member']]
    evidence = []
    # Only exact allowlisted members are read; no whole-archive extraction/discovery.
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='batch03_runtime_', dir=output.parent) as temp:
        temp = Path(temp)
        with zipfile.ZipFile(archive) as source:
            for relative in CODE_FILES:
                destination = temp / 'zaic_tools' / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read(source_root + relative))
            catalog_path = temp / 'catalog.json'
            catalog_path.write_bytes(source.read(pair['catalog_member']))
        catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
        assert catalog['schema_version'] == pair['catalog_schema_version']
        tools = {t['name']: t for a in catalog['apps'] for t in a['tools']}
        kinds = {name: t['kind'] for name, t in tools.items()}
        for name, contract in pair['capability_contracts'].items():
            assert tools[name]['parameters']['required'] == contract['required']
        if 'zaic_tools' in sys.modules:
            raise RuntimeError('Run in a fresh Python process to avoid runtime import reuse')
        sys.path.insert(0, str(temp))
        from zaic_tools.executor import Executor

        fixtures, visible = {}, {}
        for order in ['original', 'reversed']:
            for sid, scenario in scenarios.items():
                entry = deepcopy(world['initial_state'])
                # Session materializes an empty state for the installed sys app.
                entry.setdefault('sys', {})
                if order == 'reversed':
                    entry['calendar']['events'].reverse()
                agent = deepcopy(scenario['agent_visible'])
                installed = {}
                for name in agent['allowed_tools']:
                    installed.setdefault(name.split('.')[0], {'tools': []})['tools'].append(name)
                agent['context']['installed_apps'] = installed
                entry['_meta'] = {'current_time': agent['context']['current_time'],
                                  'tools': agent['allowed_tools'][:]}
                key = sid + '_' + order
                fixtures[key], visible[key] = entry, agent
                assert all(e['id'] not in json.dumps(agent) for e in entry['calendar']['events'])
        fixture_path = temp / 'synthetic_fixtures.json'
        fixture_path.write_text(json.dumps(fixtures, ensure_ascii=False), encoding='utf-8')
        executor = Executor(str(fixture_path), str(catalog_path))
        fixture_snapshot = deepcopy(executor.db)

        def replay(sid, case, order='original', required_reason=None, snapshot_mutation=False):
            key = sid + '_' + order
            scenario = scenarios[sid]
            session = executor.open(key)
            initial = session.get_state()
            expected_initial = {app: deepcopy(state) for app, state in fixtures[key].items() if app != '_meta'}
            assert initial == expected_initial
            assert session.allowed == set(scenario['agent_visible']['allowed_tools'])
            assert session.now == scenario['agent_visible']['context']['current_time']
            calls = []

            def call(name, **arguments):
                result = session.call(name, arguments)
                calls.append({'name': name, 'arguments': deepcopy(arguments), 'result': deepcopy(result)})
                return result

            statuses = scenario['oracle_draft']['required_effects']['statuses']
            records = world['initial_state']['calendar']['events']
            target = next((e for e in records if statuses[e['id']] == 'cancelled'), records[0])
            other = next(e for e in records if e['id'] != target['id'])
            if case not in ['direct_ask', 'no_ask', 'unobserved_cancel']:
                arguments = {'date_from': records[0]['start'][:10]} if case == 'filtered_cancel' else {}
                result = call('calendar.list_events', **arguments)
                assert result['ok'] is True
                assert {e['id']: e for e in result['events']} == {e['id']: e for e in records}
                observed_target = next(e['id'] for e in result['events'] if e['title'] == target['title'])
            if case in ['cancel', 'filtered_cancel', 'snapshot_field']:
                call('calendar.cancel_event', event_id=observed_target)
            elif case == 'wrong_target':
                call('calendar.cancel_event', event_id=other['id'])
            elif case == 'both_targets':
                for record in records:
                    call('calendar.cancel_event', event_id=record['id'])
            elif case == 'twice':
                for _ in range(2):
                    call('calendar.cancel_event', event_id=observed_target)
            elif case == 'unobserved_cancel':
                call('calendar.cancel_event', event_id=target['id'])
            elif case in ['guess_A', 'guess_B']:
                call('calendar.cancel_event', event_id=records[case == 'guess_B']['id'])
            elif case == 'nonexistent':
                result = call('calendar.cancel_event', event_id='b03_nonexistent')
                assert result['ok'] is True and result['done'] is False
            elif case == 'extra_write':
                call('calendar.cancel_event', event_id=observed_target)
                result = call('calendar.update_event', event_id=observed_target, location='Unpermitted')
                assert result['ok'] is False
            elif case == 'failed_call':
                assert call('calendar.cancel_event')['ok'] is False
                call('calendar.cancel_event', event_id=observed_target)
            elif case in ['direct_ask', 'read_ask', 'wrong_tool', 'wrong_parameter']:
                arguments = deepcopy(scenario['oracle_draft']['required_effects']['ask_arguments'])
                if case == 'wrong_tool':
                    arguments['tool_name'] = 'reminders.create'
                if case == 'wrong_parameter':
                    arguments['params'] = ['title']
                assert call('sys.ask_missing_info', **arguments) == {'ok': True, 'waiting_for_user': True}
            elif case != 'no_ask':
                raise ValueError(case)
            final = session.get_state()
            runtime_final = deepcopy(final)
            if snapshot_mutation:
                # Verifier-only tampering, deliberately not attributed to tool execution.
                next(e for e in final['calendar']['events'] if e['id'] == other['id'])['location'] = 'Tampered'
            assert session.get_tool_calls() == [{k: c[k] for k in ['name', 'arguments']} for c in calls]
            assert session.log == calls
            verdict = verify(initial, scenario, calls, final, kinds)
            expected_pass = required_reason is None
            assert verdict['passed'] == expected_pass, (sid, case, verdict)
            if required_reason:
                assert required_reason in verdict['state_reasons'] + verdict['trace_reasons'], (case, verdict)
            assert executor.db == fixture_snapshot, 'State leaked into shared fixture'
            assert executor.open(key).get_state() == initial, 'Fresh session was not isolated'
            evidence.append({'scenario_id': sid, 'trace_case': case, 'event_order': order,
                             'construction': 'verifier_only_snapshot_mutation' if snapshot_mutation else
                             ('hand_authored_positive_observed_IDs' if expected_pass else 'deliberate_negative_may_use_private_fixture_IDs'),
                             'expected_pass': expected_pass, 'required_rejection_reason': required_reason,
                             'initial_fixture_ref': key, 'calls': calls, 'final_state': final, 'verdict': verdict})
            if snapshot_mutation:
                evidence[-1]['actual_runtime_final_state'] = runtime_final

        for order in ['original', 'reversed']:
            for sid in ['H1', 'H2', 'H3']:
                replay(sid, 'cancel', order)
            for case in ['direct_ask', 'read_ask']:
                replay('H4', case, order)
        replay('H1', 'filtered_cancel')  # A different permitted read sequence also passes.
        for sid, case, reason in [
            ('H1', 'wrong_target', 'wrong_target_attempt'),
            ('H1', 'both_targets', 'cancel_count'),
            ('H1', 'twice', 'cancel_count'),
            ('H1', 'unobserved_cancel', 'ungrounded_cancel'),
            ('H4', 'guess_A', 'wrong_target_attempt'),
            ('H4', 'guess_B', 'wrong_target_attempt'),
            ('H4', 'no_ask', 'ask_count'),
            ('H4', 'wrong_tool', 'ask_arguments'),
            ('H4', 'wrong_parameter', 'ask_arguments'),
            ('H1', 'nonexistent', 'noop_call'),
            ('H1', 'extra_write', 'additional_write_attempt'),
            ('H1', 'failed_call', 'failed_call'),
        ]:
            replay(sid, case, required_reason=reason)
        replay('H1', 'snapshot_field', required_reason='state_or_frame_mismatch', snapshot_mutation=True)
        assert design_path.read_bytes() == design_bytes
        for sid in ['H1', 'H2', 'H3', 'H4']:
            assert visible[sid + '_original'] == visible[sid + '_reversed']
        for original in [e for e in evidence if e['expected_pass'] and e['event_order'] == 'original' and e['trace_case'] != 'filtered_cancel']:
            reversed_case = next(e for e in evidence if e['scenario_id'] == original['scenario_id'] and
                                 e['trace_case'] == original['trace_case'] and e['event_order'] == 'reversed')
            def by_id(state):
                return {e['id']: e for e in state['calendar']['events']}
            assert by_id(original['final_state']) == by_id(reversed_case['final_state'])
        result = {
            'created_utc': datetime.now(timezone.utc).isoformat(),
            'kind': 'hand_authored_runtime_replay_not_model_evaluation',
            'design': str(design_path.relative_to(ROOT)),
            'status': {'spec_only': 4, 'exportable': False, 'execution_verified': 0,
                       'positive_replays': sum(e['expected_pass'] for e in evidence),
                       'negative_checks': sum(not e['expected_pass'] for e in evidence), 'all_expectations_met': True},
            'provenance': {'archive': str(archive), 'release_as_recorded_in_design': pair['release'],
                           'catalog_schema_version': catalog['schema_version'], 'allowlisted_members': members,
                           'runtime_modified': False, 'python': sys.version},
            'reproduction_command': 'python scripts/replay_batch03.py',
            'limitations': ['Executor does not consume history; agent_visible is separate authoring evidence.',
                            'Targets come from reviewed oracle, not a history interpreter or model.',
                            'H4 policy is draft; runtime acceptance is not official semantic acceptance.',
                            'No team conversation harness integration or training export validated.'],
            'fixtures': fixtures, 'agent_visible': visible, 'replays': evidence,
        }
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result['status']))
        print('Replay evidence:', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/synthetic/batch_03_replay/replay.json')
    args = parser.parse_args()
    run(args.archive, args.output)
