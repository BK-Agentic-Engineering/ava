"""Bounded AND/OR and calendar-to-ride replays; no model or generic harness."""
from __future__ import annotations
import os

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import zipfile

import yaml
from replay_batch03 import ROOT, CODE_FILES, StrictLoader
from replay_expansion_pilot_v1 import verdict, extract_time

FILES = CODE_FILES + ('apps/smart_home.py', 'apps/ride_hailing.py')


def instant(value):
    try:
        result = datetime.fromisoformat(value)
        return result if result.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def verify(initial, scenario, world, calls, final, kinds):
    effects = scenario['oracle_draft']['required_effects']
    logic = 'operator' in scenario['oracle_draft']
    parts = {k: [] for k in ['state_reasons', 'frame_reasons', 'trace_reasons', 'grounding_reasons', 'condition_temporal_reasons', 'clarification_reasons', 'text_errors', 'text_review']}
    writes, asks, seen, bits, source_times = [], [], set(), {}, set()
    if logic:
        desc = world['action_description']; operands = world['operand_descriptions']
        action = next(r for r in initial['smart_home']['devices'] if all(r[k] == v for k, v in desc.items()))
    else:
        intended = instant(scenario['oracle_draft']['intended_pickup_time'])
        now = instant(scenario['agent_visible']['context']['current_time'])
    def truth():
        values = list(bits.values())
        if scenario['oracle_draft']['operator'] == 'AND':
            return False if False in values else (True if len(bits) == 2 else None)
        return True if True in values else (False if len(bits) == 2 else None)
    for call in calls:
        name, args, result = call['name'], call['arguments'], call['result']
        allowed = name in scenario['agent_visible']['allowed_tools']
        if not allowed: parts['trace_reasons'].append('unpermitted_attempt')
        if allowed and result.get('ok') is True and result.get('done') is not False:
            if logic and name == 'smart_home.get_status':
                for r in result['devices']:
                    if all(r.get(k) == v for k, v in desc.items()): seen.add(r['id'])
                    for i, operand in enumerate(operands):
                        if all(r.get(k) == v for k, v in operand.items()) and r.get('state', {}).get('power') in ['on', 'off']:
                            bits[i] = r['state']['power'] == 'on'
            elif not logic and name == 'calendar.list_events':
                matches = [r for r in result['events'] if all(r.get(k) == v for k, v in world['event_match'].items())]
                if len(matches) == 1 and instant(matches[0]['start']): source_times.add(instant(matches[0]['start']))
        if kinds.get(name, 'write') == 'write':
            writes.append(call)
            if logic:
                if name != 'smart_home.light_set': parts['trace_reasons'].append('additional_write')
                if args.get('device_id') != action['id']: parts['trace_reasons'].append('wrong_action_target')
                if args.get('device_id') not in seen: parts['grounding_reasons'].append('unobserved_action_ID')
                if truth() is not True: parts['condition_temporal_reasons'].append('predicate_not_true_before_action')
                if args.get('power') != 'off': parts['trace_reasons'].append('wrong_power')
            else:
                if name != 'ride_hailing.book': parts['trace_reasons'].append('additional_write')
                if scenario['oracle_draft']['time_source'] == 'event_start' and intended not in source_times:
                    parts['grounding_reasons'].append('missing_prior_target_start')
                supplied = args.get('schedule_time')
                if supplied is None:
                    if intended != now: parts['condition_temporal_reasons'].append('omitted_future_schedule')
                elif instant(supplied) != intended: parts['condition_temporal_reasons'].append('wrong_requested_instant')
        if name == 'sys.ask_missing_info': asks.append(call)
    if len(writes) != effects['total_write_count']: parts['trace_reasons'].append('write_count')
    if len(asks) != effects['ask_count']: parts['clarification_reasons'].append('unjustified_ask')
    if logic:
        if not effects['total_write_count'] and truth() is not False: parts['condition_temporal_reasons'].append('missing_false_predicate_evidence')
        records = final['smart_home']['devices']
        if {r['id']: r['state']['power'] for r in records} != effects['power_after']: parts['state_reasons'].append('power_goal')
        frame = deepcopy(final)
        if effects['total_write_count']:
            for r in frame['smart_home']['devices']:
                if r['id'] == action['id']: r['state']['power'] = action['state']['power']
        if frame != initial: parts['frame_reasons'].append('collateral_or_structure_changed')
    else:
        old, after = initial['ride_hailing']['rides'], final['ride_hailing']['rides']
        new = after[len(old):]
        if len(after) - len(old) != effects['new_ride_count']: parts['state_reasons'].append('new_ride_count')
        frame = deepcopy(final); frame['ride_hailing']['rides'] = deepcopy(old)
        if frame != initial or after[:len(old)] != old: parts['frame_reasons'].append('existing_ride_calendar_or_other_changed')
        successful = [c for c in writes if c['name'] == 'ride_hailing.book' and c['result'].get('ok') is True and c['result'].get('done') is not False]
        if len(successful) != len(new): parts['state_reasons'].append('response_count')
        ids = [r.get('id') for r in new]
        if len(set(ids)) != len(ids) or any(not isinstance(i, str) or not i or i in {r['id'] for r in old} for i in ids): parts['state_reasons'].append('invalid_generated_ID')
        for record, call in zip(new, successful):
            if call['result'].get('item') != record or call['result'].get('id') != record.get('id'): parts['state_reasons'].append('response_record_mismatch')
            for field in ['vehicle', 'status']:
                if record.get(field) != effects[field]: parts['state_reasons'].append('ride_' + field)
            for field, opposite in [('pickup', 'dropoff'), ('dropoff', 'pickup')]:
                if record.get(field) != effects[field]:
                    if record.get(field) == effects[opposite]: parts['text_errors'].append('reviewed_route_swap')
                    else: parts['text_review'].append('route_human_review_required')
            if ('schedule_time' in record) != effects['schedule_key_present']: parts['state_reasons'].append('schedule_key_presence')
            if effects['schedule_key_present'] and instant(record.get('schedule_time')) != intended: parts['state_reasons'].append('stored_schedule_instant')
    return verdict({k: sorted(set(v)) for k, v in parts.items()}, calls)


def run(archive, output):
    path = ROOT / 'data/synthetic/design/expansion_batch_02.yaml'; original = path.read_bytes()
    design = yaml.load(original.decode('utf-8'), Loader=StrictLoader)
    worlds = {w['world_id']: w for w in design['worlds']}; scenarios = {s['scenario_id']: s for s in design['scenarios']}
    pair = design['interface_pair']; fixtures, visible = {}, {}
    for sid, s in scenarios.items():
        base = deepcopy(worlds[s['world_id']]['initial_state'])
        if s['fixture_variant'] != 'base':
            v = worlds[s['world_id']]['variants'][s['fixture_variant']]
            if v['operation'] == 'replace_values':
                assert v['paths'] == ['smart_home.devices[0].state.power', 'smart_home.devices[1].state.power']
                for i, power in enumerate(v['values']): base['smart_home']['devices'][i]['state']['power'] = power
            elif v['path'] == 'smart_home.devices[0].state.power': base['smart_home']['devices'][0]['state']['power'] = v['value']
            else:
                assert v['path'] == 'calendar.events[0].start'
                base['calendar']['events'][0]['start'] = v['value']
        base['sys'] = {}; base['_meta'] = {'tools': s['agent_visible']['allowed_tools'][:], 'current_time': s['agent_visible']['context']['current_time']}
        for order in ['original', 'reversed']:
            entry = deepcopy(base)
            app, collection = ('smart_home', 'devices') if 'smart_home' in entry else ('calendar', 'events')
            if order == 'reversed': entry[app][collection].reverse()
            key = sid + '/' + order; fixtures[key] = entry
            agent = deepcopy(s['agent_visible']); agent['context']['installed_apps'] = {}
            for name in agent['allowed_tools']: agent['context']['installed_apps'].setdefault(name.split('.')[0], {'tools': []})['tools'].append(name)
            visible[key] = agent
    old_checks = json.loads((ROOT / 'artifacts/synthetic/expansion_pilot_v1_replay/replay.json').read_text(encoding='utf-8'))['source_extractor_checks']
    for check in old_checks: assert extract_time(check['input']) == check['expected']
    assert len(old_checks) == 12
    output.parent.mkdir(parents=True, exist_ok=True); evidence = []
    with tempfile.TemporaryDirectory(prefix='ex2_runtime_', dir=output.parent) as temp:
        temp = Path(temp); members = [pair['runtime_root'] + p for p in FILES] + [pair['catalog_member']]
        with zipfile.ZipFile(archive) as source:
            for relative in FILES:
                p = temp / 'zaic_tools' / relative; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(source.read(pair['runtime_root'] + relative))
            cp = temp / 'catalog.json'; cp.write_bytes(source.read(pair['catalog_member']))
        catalog = json.loads(cp.read_text(encoding='utf-8')); assert catalog['schema_version'] == pair['catalog_schema_version']
        tools = {t['name']: t for a in catalog['apps'] for t in a['tools']}; kinds = {n: t['kind'] for n, t in tools.items()}
        for name, contract in pair['capability_contracts'].items():
            assert tools[name]['parameters']['required'] == contract['required'] and set(contract['optional_used']) <= set(tools[name]['parameters']['properties'])
        if 'zaic_tools' in sys.modules: raise RuntimeError('Use a fresh Python process')
        sys.path.insert(0, str(temp))
        from zaic_tools.executor import Executor
        fp = temp / 'synthetic.json'; fp.write_text(json.dumps(fixtures, ensure_ascii=False), encoding='utf-8')
        executor = Executor(str(fp), str(cp)); snapshot = deepcopy(executor.db)

        def replay(sid, case='standard', order='original', expected='pass', reason=None, projection=None, mutation=None):
            s = scenarios[sid]; w = worlds[s['world_id']]; key = sid + '/' + order; session = executor.open(key); initial = session.get_state(); calls = []
            assert initial == {k: v for k, v in fixtures[key].items() if k != '_meta'}
            assert session.allowed == set(s['agent_visible']['allowed_tools']) and session.now == s['agent_visible']['context']['current_time']
            logic = 'operator' in s['oracle_draft']
            def call(name, **args):
                before = session.get_state(); result = session.call(name, args)
                if kinds[name] in ['read', 'meta']: assert session.get_state() == before
                if name == 'smart_home.get_status': assert result == {'ok': True, 'devices': [r for r in before['smart_home']['devices'] if all(r.get(k) == v for k, v in args.items())]}
                if name == 'calendar.list_events':
                    rs = [r for r in before['calendar']['events'] if (not args.get('date_from') or r['start'][:10] >= args['date_from']) and (not args.get('date_to') or r['start'][:10] <= args['date_to'])]
                    assert result == {'ok': True, 'events': rs}
                calls.append({'name': name, 'arguments': deepcopy(args), 'result': deepcopy(result)}); return result
            if logic:
                records = initial['smart_home']['devices'] if case in ['guess', 'empty_log', 'late_read'] else call('smart_home.get_status', **({'room': w['action_description']['room'], 'type': 'light'} if case == 'filtered' else {}))['devices']
                action = next(r for r in records if all(r.get(k) == v for k, v in w['action_description'].items()))
                if case == 'repeat_read': call('smart_home.get_status')
                write = s['oracle_draft']['outcome'] == 'execute' or case in ['false_action', 'wrong_operand', 'redundant_operand']
                if case in ['skip', 'empty_log', 'ask']: write = False
                if write:
                    target = action
                    if case in ['wrong_operand', 'redundant_operand']:
                        target = next(r for r in records if r['name'] == w['operand_descriptions'][0 if case == 'wrong_operand' else 1]['name'])
                    for _ in range(2 if case == 'duplicate' else 1): call('smart_home.light_set', device_id=target['id'], power='off')
                if case == 'late_read': call('smart_home.get_status')
                if case == 'ask': call('sys.ask_missing_info', tool_name='smart_home.light_set', params=['device_id'])
            else:
                e = s['oracle_draft']['required_effects']; source = s['oracle_draft']['time_source'] == 'event_start'
                schedule = s['oracle_draft']['intended_pickup_time'] if not source or case in ['guess', 'late_read'] else None
                if case not in ['guess', 'late_read'] and (source or case == 'optional_read'):
                    rs = call('calendar.list_events', **({'date_from': '2026-12-05', 'date_to': '2026-12-05'} if case == 'filtered' else {}))['events']
                    target = next(r for r in rs if all(r.get(k) == v for k, v in w['event_match'].items()))
                    schedule = target['start']
                    if case == 'wrong_source': schedule = next(r['start'] for r in rs if r['id'] != target['id'])
                args = {k: e[k] for k in ['pickup', 'dropoff', 'vehicle']}
                if case == 'ask': call('sys.ask_missing_info', tool_name='ride_hailing.book', params=['schedule_time'])
                else:
                    if case not in ['omit', 'drop_future']: args['schedule_time'] = schedule
                    if case == 'utc': args['schedule_time'] = instant(schedule).astimezone(timezone.utc).isoformat()
                    if case == 'past_argument': args['schedule_time'] = (instant(schedule) - timedelta(minutes=1)).isoformat()
                    if case == 'empty_schedule': args['schedule_time'] = ''
                    if case == 'swapped': args['pickup'], args['dropoff'] = args['dropoff'], args['pickup']
                    if case == 'paraphrase': args['pickup'] = 'lối vào Nhà Sợi'
                    for _ in range(2 if case == 'duplicate' else 1): call('ride_hailing.book', **args)
                if case == 'late_read': call('calendar.list_events')
            runtime_final = session.get_state(); final = deepcopy(runtime_final); projected = deepcopy(calls)
            if mutation: mutation(final)
            if projection:
                if logic:
                    records = projected[0]['result']['devices']; operand = w['operand_descriptions'][0]
                    selected = next(r for r in records if all(r.get(k) == v for k, v in operand.items()))
                    selected['state'].pop('power')
                else: projected[0]['result']['events'] = [r for r in projected[0]['result']['events'] if not all(r.get(k) == v for k, v in w['event_match'].items())]
            actual = verify(initial, s, w, projected, final, kinds)
            assert actual['verdict'] == expected, (sid, case, actual)
            if reason: assert reason in sum([v for k, v in actual.items() if k not in ['verdict', 'attempt_diagnostics']], []), (sid, case, actual)
            if case in ['guess', 'past_argument', 'redundant_operand', 'late_read'] or projection:
                assert not actual['state_reasons'] and not actual['frame_reasons'], actual
            assert session.get_tool_calls() == [{k: c[k] for k in ['name', 'arguments']} for c in calls] and session.log == calls
            assert executor.db == snapshot and executor.open(key).get_state() == initial
            row = {'scenario_id': sid, 'fixture_variant': s['fixture_variant'], 'ordering': order, 'trace_case': case,
                   'lineage_id': s['lineage_id'], 'initial_fixture_ref': key, 'expected_verdict': expected, 'required_reason': reason,
                   'calls': calls, 'final_state': final, 'verdict': actual, 'construction': 'deliberate_diagnostic_may_use_private_values' if expected != 'pass' else 'hand_authored_positive',
                   'evidence_kind': 'verifier_only_snapshot' if mutation else ('verifier_only_projection' if projection else 'actual_runtime_trace')}
            if mutation: row['actual_runtime_final_state'] = runtime_final
            if projection: row['verifier_input_calls'] = projected
            evidence.append(row)

        for sid in scenarios: replay(sid)
        for sid in scenarios:
            replay(sid, order='reversed')
            if sid != 'EX2_R_EXPLICIT': replay(sid, 'filtered')
        replay('EX2_R_NOW', 'omit'); replay('EX2_R_FUTURE', 'utc'); replay('EX2_R_NOW', 'utc'); replay('EX2_R_EXPLICIT', 'optional_read'); replay('EX2_L_OR_FALSE', 'repeat_read')
        for sid, case, reason in [
            ('EX2_L_AND', 'false_action', 'predicate_not_true_before_action'), ('EX2_L_OR_FIRST', 'skip', 'write_count'),
            ('EX2_L_OR_SECOND', 'skip', 'write_count'), ('EX2_L_OR_FALSE', 'false_action', 'predicate_not_true_before_action'),
            ('EX2_L_OR_FIRST', 'wrong_operand', 'wrong_action_target'), ('EX2_L_AND', 'redundant_operand', 'write_count'),
            ('EX2_L_OR_FALSE', 'empty_log', 'missing_false_predicate_evidence'), ('EX2_L_OR_FALSE', 'ask', 'unjustified_ask'),
            ('EX2_L_OR_FIRST', 'guess', 'unobserved_action_ID'), ('EX2_L_OR_FIRST', 'duplicate', 'write_count'),
            ('EX2_L_OR_FIRST', 'late_read', 'predicate_not_true_before_action'),
            ('EX2_R_NOW', 'guess', 'missing_prior_target_start'), ('EX2_R_FUTURE', 'guess', 'missing_prior_target_start'),
            ('EX2_R_FUTURE', 'late_read', 'missing_prior_target_start'),
            ('EX2_R_NOW', 'wrong_source', 'wrong_requested_instant'), ('EX2_R_FUTURE', 'wrong_source', 'wrong_requested_instant'),
            ('EX2_R_FUTURE', 'drop_future', 'omitted_future_schedule'), ('EX2_R_NOW', 'past_argument', 'wrong_requested_instant'),
            ('EX2_R_NOW', 'empty_schedule', 'schedule_key_presence'), ('EX2_R_FUTURE', 'duplicate', 'write_count'),
            ('EX2_R_EXPLICIT', 'ask', 'unjustified_ask'), ('EX2_R_FUTURE', 'swapped', 'reviewed_route_swap'),
        ]: replay(sid, case, expected='reject', reason=reason)
        replay('EX2_L_OR_FIRST', 'unknown_true_projection', expected='reject', reason='predicate_not_true_before_action', projection=True)
        replay('EX2_L_OR_FALSE', 'incomplete_false_projection', expected='reject', reason='missing_false_predicate_evidence', projection=True)
        replay('EX2_L_OR_SECOND', 'sufficient_one_true_projection', projection=True)
        replay('EX2_R_FUTURE', 'wrong_source_projection', expected='reject', reason='missing_prior_target_start', projection=True)
        replay('EX2_L_OR_FIRST', 'collateral_snapshot', expected='reject', reason='collateral_or_structure_changed', mutation=lambda st: st['smart_home']['devices'][0]['state'].update(brightness=55))
        replay('EX2_R_FUTURE', 'existing_ride_snapshot', expected='reject', reason='existing_ride_calendar_or_other_changed', mutation=lambda st: st['ride_hailing']['rides'][0].update(status='booked'))
        replay('EX2_R_FUTURE', 'paraphrase', expected='human_review_required', reason='route_human_review_required')
        for sid in scenarios:
            rows = [r for r in evidence if r['scenario_id'] == sid and r['trace_case'] == 'standard']
            def canonical(state):
                out = deepcopy(state)
                for app, coll in [('smart_home', 'devices'), ('calendar', 'events')]:
                    if app in out: out[app][coll] = sorted(out[app][coll], key=lambda r: r['id'])
                return out
            assert canonical(rows[0]['final_state']) == canonical(rows[1]['final_state'])
            assert visible[sid + '/original'] == visible[sid + '/reversed']
        assert path.read_bytes() == original
        runtime = [r for r in evidence if r['evidence_kind'] == 'actual_runtime_trace']
        status = {'unique_scenarios_replayed': 7, 'positive_runtime_paths': sum(r['expected_verdict']=='pass' for r in runtime), 'negative_runtime_traces': sum(r['expected_verdict']=='reject' for r in runtime),
                  'human_review_runtime_probes': sum(r['expected_verdict']=='human_review_required' for r in runtime), 'verifier_only_checks': len(evidence)-len(runtime), 'existing_extractor_regressions_passed': len(old_checks),
                  'all_expectations_met': True, 'spec_only': 7, 'execution_verified': 0, 'exportable': False}
        result = {'created_utc': datetime.now(timezone.utc).isoformat(), 'kind': 'hand_authored_runtime_replay_not_model_evaluation', 'status': status,
                  'provenance': {'archive': str(archive), 'design': str(path.relative_to(ROOT)), 'release_as_recorded_in_design': pair['release'], 'catalog_schema_version': catalog['schema_version'], 'allowlisted_members': members, 'runtime_modified': False, 'python': sys.version},
                  'world_ancestry': {wid:w['ancestry'] for wid,w in worlds.items()}, 'fixtures': fixtures, 'agent_visible': visible, 'replays': evidence,
                  'reproduction_command': 'python scripts/replay_expansion_batch_02.py', 'helper_checks': {'existing_label_regressions': 12, 'new_text_extractors': 0},
                  'limitations': ['No model evaluation, general semantics, training/harness integration or official policy acceptance.', 'Structured event.start and explicit request mapping only; unknown route paraphrases need human review.', 'Attempts remain diagnostic; authored goals/counts/evidence/frame determine verdict, not a universal failed-call rule.']}
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n',encoding='utf-8'); print(json.dumps(status)); print('Evidence:',output)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/synthetic/expansion_batch_02_replay/replay.json')
    args=parser.parse_args(); run(args.archive,args.output)
