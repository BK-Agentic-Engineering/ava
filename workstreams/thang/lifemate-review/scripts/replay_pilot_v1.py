"""Hand-authored Pilot replay against allowlisted organizer code; no model evaluation."""
from __future__ import annotations
import os

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import zipfile

import yaml
from replay_batch03 import ROOT, CODE_FILES, StrictLoader

FILES = tuple(p for p in CODE_FILES if p != 'apps/calendar.py') + tuple('apps/' + name + '.py' for name in
                          ['smart_home', 'ride_hailing', 'food_delivery', 'contacts', 'sms', 'banking', 'reminders'])


def verify(initial, scenario, calls, final, kinds):
    sid, family = scenario['scenario_id'], scenario['scenario_id'][0]
    oracle = scenario['oracle_draft']
    effects, outcome = oracle['required_effects'], oracle['outcome']
    state, trace, ground, text_errors, review = [], [], [], [], []
    expected = deepcopy(initial)
    write_name = {'L': 'smart_home.light_set', 'R': 'ride_hailing.book', 'M': 'food_delivery.place_order',
                  'S': 'sms.send', 'T': 'banking.transfer', 'N': 'reminders.create', 'C': 'ride_hailing.cancel'}[family]
    collection = {'R': ('ride_hailing', 'rides'), 'M': ('food_delivery', 'orders'),
                  'S': ('sms', 'messages'), 'T': ('banking', 'transactions'), 'N': ('reminders', 'reminders')}.get(family)
    counts = {'L': 'light_write_count', 'R': 'new_ride_count', 'M': 'new_order_count', 'S': 'new_message_count',
              'T': 'new_transaction_count', 'N': 'new_reminder_count', 'C': 'latest_turn_cancel_count'}
    required_writes = effects[counts[family]]

    def text(actual, wanted, label, known_bad=()):
        if actual == wanted:
            return
        if actual in known_bad:
            text_errors.append(label + ':reviewed_meaning_error')
        else:
            review.append(label + ':human_review_required')

    if family == 'L':
        target_ids = set()
        for device in expected['smart_home']['devices']:
            power = effects['power_after'][device['id']]
            if device['state']['power'] != power:
                target_ids.add(device['id'])
            device['state']['power'] = power
    elif family == 'C':
        target_ids = set()
        for ride in expected['ride_hailing']['rides']:
            status = effects['statuses'][ride['id']]
            if ride['status'] != status:
                target_ids.add(ride['id'])
            ride['status'] = status
        if len(final['ride_hailing']['rides']) != effects['ride_count_after']:
            state.append('ride_count')
    else:
        target_ids = set()
    if family == 'T':
        for account in expected['banking']['accounts']:
            account['balance'] = effects['account_balance_after'][account['id']]
    writes = [c for c in calls if kinds.get(c['name'], 'write') == 'write']
    if len(writes) != required_writes:
        trace.append('write_count')
    if any(c['name'] != write_name for c in writes):
        trace.append('additional_write_attempt')
    asks = [c for c in calls if c['name'] == 'sys.ask_missing_info']
    if outcome == 'ask_missing':
        if len(asks) != effects['ask_count']:
            trace.append('ask_count')
        if any(c['arguments'] != effects['ask_arguments'] for c in asks):
            trace.append('ask_arguments')
    elif asks:
        trace.append('unexpected_ask')
    if outcome == 'out_of_scope' and calls:
        trace.append('OOS_nonempty_attempt_log')

    # Evidence is occurrence-specific: only earlier successful permitted observations count.
    devices, restaurants, menus, contacts, accounts, beneficiaries, rides = {}, {}, {}, {}, {}, {}, {}
    mother = next((r for r in initial.get('contacts', {}).get('contacts', []) if r['relation'] == 'mẹ'), None)
    for call in calls:
        name, args, result = call['name'], call['arguments'], call['result']
        allowed = name in scenario['agent_visible']['allowed_tools']
        if not allowed: trace.append('unpermitted_attempt')
        if result.get('ok') is not True: trace.append('failed_call')
        if result.get('done') is False: trace.append('noop_call')
        if name == 'food_delivery.get_menu' and args.get('restaurant_id') not in restaurants:
            ground.append('menu_read_with_unobserved_restaurant_ID')
        if name == write_name:
            if family == 'L':
                identity = args.get('device_id')
                if identity not in devices: ground.append('unobserved_device_ID')
                if identity not in target_ids: trace.append('excluded_light_attempt')
            elif family == 'M':
                rid = args.get('restaurant_id')
                if rid not in restaurants: ground.append('unobserved_restaurant_ID')
                for line in args.get('items', []):
                    if line.get('item_id') not in menus.get(rid, {}):
                        ground.append('unobserved_item_for_restaurant')
            elif family == 'S':
                cid, phone = args.get('contact_id'), args.get('phone_number')
                if cid and cid not in contacts: ground.append('unobserved_contact_ID')
                if sid == 'S2' and (mother['id'] not in contacts or
                                   (cid != mother['id'] if cid else phone != contacts[mother['id']]['phone'])):
                    ground.append('recipient_not_grounded_in_mother_record')
                if cid and phone and (cid not in contacts or contacts[cid].get('phone') != phone):
                    ground.append('inconsistent_observed_recipient_pair')
            elif family == 'T':
                if args.get('from_account_id') not in accounts: ground.append('unobserved_source_account')
                if args.get('beneficiary_id') not in beneficiaries: ground.append('unobserved_beneficiary')
            elif family == 'C':
                if args.get('ride_id') not in rides: ground.append('unobserved_ride_ID')
                if args.get('ride_id') not in target_ids: trace.append('wrong_ride_attempt')
        if allowed and result.get('ok') is True and result.get('done') is not False:
            for tool, key, destination in [('smart_home.get_status', 'devices', devices),
                                          ('food_delivery.list_restaurants', 'restaurants', restaurants),
                                          ('contacts.search', 'contacts', contacts),
                                          ('banking.get_balance', 'accounts', accounts),
                                          ('banking.list_beneficiaries', 'beneficiaries', beneficiaries)]:
                if name == tool:
                    destination.update({r['id']: r for r in result[key]})
            if name == 'food_delivery.get_menu' and args.get('restaurant_id') in restaurants:
                menus[args['restaurant_id']] = {r['id']: r for r in result['menu']}
            if name == 'ride_hailing.get_ride' and result.get('ride'):
                rides[result['ride']['id']] = result['ride']

    if collection:
        app, coll = collection
        old, after = initial[app][coll], final[app][coll]
        new = after[len(old):]
        if len(after) - len(old) != required_writes: state.append('new_record_count')
        if after[:len(old)] != old: state.append('existing_records_changed')
        expected[app][coll] += deepcopy(new)
        successful = [c for c in writes if c['name'] == write_name and c['result'].get('ok') is True and c['result'].get('done') is not False]
        if len(new) != len(successful): state.append('response_record_count')
        ids = [r.get('id') for r in new]
        if any(not isinstance(i, str) or not i or i in {r['id'] for r in old} for i in ids) or len(set(ids)) != len(ids):
            state.append('invalid_generated_ID')
        result_key = {'R': 'item', 'M': 'order', 'S': 'message', 'T': 'transaction', 'N': 'item'}[family]
        for record, call in zip(new, successful):
            result = call['result']
            if result.get(result_key) != record or ('id' in result and result['id'] != record.get('id')):
                state.append('response_record_mismatch')
            if family == 'R':
                e = effects if outcome == 'execute' else {'pickup': 'cổng Xưởng Gốm', 'vehicle': 'car4'}
                for field in ['pickup', 'dropoff']:
                    if field in e: text(record.get(field), e[field], field, ['Nhà Kính' if field == 'pickup' else 'cổng Xưởng Gốm'])
                if outcome != 'execute': state.append('forbidden_booking')
                for field in ['vehicle', 'status']:
                    if field in e and record.get(field) != e[field]: state.append('ride_' + field)
                if any(k in record for k in effects.get('new_ride_forbidden_keys', [])):
                    state.append('forbidden_schedule_time_key')
            elif family == 'M':
                for field in ['restaurant_id', 'total', 'payment', 'status']:
                    if record.get(field) != effects[field]: state.append('order_' + field)
                text(record.get('address'), effects['address'], 'address')
                if len(record.get('items', [])) != effects['item_line_count']: state.append('item_line_count')
                for line in record.get('items', []):
                    for field, value in effects['item_line_required_fields'].items():
                        if line.get(field) != value: state.append('item_' + field)
            elif family == 'S':
                if record.get('phone_number') != effects['recipient_phone']: state.append('recipient_phone')
                if record.get('contact_id') not in [None, effects['consistent_contact_id_if_stored']]:
                    state.append('recipient_consistency')
                if record.get('direction') != effects['direction']: state.append('message_direction')
                text(record.get('content'), scenario['agent_visible']['request'].split(': ', 1)[1], 'sms_content', ['Con chưa về nhà an toàn.'])
            elif family == 'T':
                for field, value in effects['transaction'].items():
                    if record.get(field) != value: state.append('transaction_' + field)
            elif family == 'N':
                for field in ['time', 'repeat', 'done']:
                    if record.get(field) != effects[field]: state.append('reminder_' + field)
                wanted = scenario['agent_visible']['request'].split('nhắc tôi ', 1)[1].removesuffix('.')
                opposite = wanted.removeprefix('không ') if wanted.startswith('không ') else 'không ' + wanted
                text(record.get('content'), wanted, 'reminder_content', [opposite, 'tắt máy hút bụi trong phòng làm việc'])
    if final != expected: state.append('state_or_frame_mismatch')
    if outcome != 'execute' and final != initial: state.append('forbidden_state_change')
    verdict = 'reject' if any([state, trace, ground, text_errors]) else ('human_review_required' if review else 'pass')
    return {'verdict': verdict, 'state_reasons': sorted(set(state)), 'trace_reasons': sorted(set(trace)),
            'grounding_reasons': sorted(set(ground)), 'text_errors': sorted(set(text_errors)), 'text_review': sorted(set(review))}


def run(archive, output):
    path = ROOT / 'data/synthetic/design/pilot_v1.yaml'
    design_bytes = path.read_bytes()
    design = yaml.load(design_bytes.decode('utf-8'), Loader=StrictLoader)
    scenarios = {s['scenario_id']: s for s in design['scenarios']}
    worlds = {w['world_id']: w for w in design['worlds']}
    assert len(scenarios) == 16 and len(worlds) == 7
    pair = design['interface_pair']
    fixtures, visible = {}, {}
    for sid, scenario in scenarios.items():
        entry = deepcopy(worlds[scenario['world_id']]['initial_state'])
        if scenario['fixture_variant'] != 'base':
            change = worlds[scenario['world_id']]['variants'][scenario['fixture_variant']]
            if sid == 'M2' and change['replace_only'] == 'food_delivery.restaurants[id=r4].menu[0].id':
                next(r for r in entry['food_delivery']['restaurants'] if r['id'] == 'r4')['menu'][0]['id'] = change['value']
            elif sid == 'C2' and change['replace_only'] == 'ride_hailing.rides[1]':
                entry['ride_hailing']['rides'][1] = deepcopy(change['value'])
            else: raise ValueError(change)
        entry['sys'] = {}
        entry['_meta'] = {'tools': scenario['agent_visible']['allowed_tools'][:], 'current_time': scenario['agent_visible']['context']['current_time']}
        fixtures[sid] = entry
        agent = deepcopy(scenario['agent_visible'])
        agent['context']['installed_apps'] = {}
        for name in agent['allowed_tools']:
            agent['context']['installed_apps'].setdefault(name.split('.')[0], {'tools': []})['tools'].append(name)
        visible[sid] = agent
    fixtures['S2_reversed'] = deepcopy(fixtures['S2'])
    fixtures['S2_reversed']['contacts']['contacts'].reverse()
    visible['S2_reversed'] = deepcopy(visible['S2'])
    output.parent.mkdir(parents=True, exist_ok=True)
    evidence = []
    with tempfile.TemporaryDirectory(prefix='pilot_runtime_', dir=output.parent) as temp:
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
        tools = {t['name']: t for a in catalog['apps'] for t in a['tools']}
        for name, contract in pair['capability_contracts'].items():
            parameters = tools[name]['parameters']
            assert parameters['required'] == contract['required']
            assert set(contract.get('optional_used', [])) <= set(parameters['properties'])
            if 'target_groups' in contract:
                assert parameters['x-one-of'] == contract['target_groups']
            if 'item_required' in contract:
                assert parameters['properties']['items']['items']['required'] == contract['item_required']
        kinds = {name: tool['kind'] for name, tool in tools.items()}
        if 'zaic_tools' in sys.modules: raise RuntimeError('Use a fresh Python process')
        sys.path.insert(0, str(temp))
        from zaic_tools.executor import Executor
        fp = temp / 'synthetic.json'
        fp.write_text(json.dumps(fixtures, ensure_ascii=False), encoding='utf-8')
        executor = Executor(str(fp), str(cp))
        snapshot = deepcopy(executor.db)

        def replay(sid, case='standard', expected='pass', reason=None, reverse=False, mutation=None):
            scenario = scenarios[sid]
            effects = scenario['oracle_draft']['required_effects']
            family = sid[0]
            key = sid + ('_reversed' if reverse else '')
            session = executor.open(key)
            initial = session.get_state()
            assert initial == {k: v for k, v in fixtures[key].items() if k != '_meta'}
            assert session.allowed == set(scenario['agent_visible']['allowed_tools'])
            assert session.now == scenario['agent_visible']['context']['current_time']
            calls = []

            def call(name, **args):
                result = session.call(name, args)
                calls.append({'name': name, 'arguments': deepcopy(args), 'result': deepcopy(result)})
                return result

            if family == 'L':
                devices = initial['smart_home']['devices'] if case == 'guess_ID' else call('smart_home.get_status', **({'floor': 2, 'type': 'light'} if case == 'filtered_read' else {}))['devices']
                targets = [d for d in devices if effects['power_after'][d['id']] != d['state']['power']]
                if case == 'reverse_writes': targets.reverse()
                if case == 'wrong_light': targets = [d for d in devices if d['id'] == 'd5']
                if case == 'excluded_light': targets += [d for d in devices if d['id'] == 'd2']
                for device in targets: call('smart_home.light_set', device_id=device['id'], power='off')
                if case == 'extra_field': call('smart_home.light_set', device_id=targets[0]['id'], brightness=10)
            elif family == 'R':
                base = scenarios['R1']['oracle_draft']['required_effects']
                args = {f: base[f] for f in ['pickup', 'dropoff', 'vehicle']}
                if sid == 'R2' and case != 'guess_dropoff':
                    if case != 'empty_log': call('sys.ask_missing_info', **effects['ask_arguments'])
                elif sid == 'R3' and case == 'standard': pass
                elif case == 'OOS_read': call('ride_hailing.get_ride')
                elif case == 'OOS_ask': call('sys.ask_missing_info', tool_name='ride_hailing.book', params=['dropoff'])
                else:
                    if case == 'swapped_route': args['pickup'], args['dropoff'] = args['dropoff'], args['pickup']
                    if case in ['schedule_null', 'schedule_empty', 'schedule_absent']:
                        args['schedule_time'] = {'schedule_null': None, 'schedule_empty': '', 'schedule_absent': 'absent'}[case]
                    call('ride_hailing.book', **args)
            elif family == 'M':
                if case == 'guess_ID':
                    rid, item = effects['restaurant_id'], effects['item_line_required_fields']['item_id']
                else:
                    found = call('food_delivery.list_restaurants')['restaurants']
                    assert all('menu' not in r for r in found)
                    restaurant = next(r for r in found if r['name'] == 'Nếp Mộc')
                    rid = restaurant['id']
                    menu = call('food_delivery.get_menu', restaurant_id=rid)['menu']
                    item = next(m['id'] for m in menu if m['name'] == 'bánh bí')
                    if case == 'other_restaurant':
                        rid = next(r['id'] for r in found if r['name'] == 'Tán Lá')
                        item = call('food_delivery.get_menu', restaurant_id=rid)['menu'][0]['id']
                    if case == 'wrong_association':
                        other = next(r['id'] for r in found if r['name'] == 'Tán Lá')
                        item = call('food_delivery.get_menu', restaurant_id=other)['menu'][0]['id']
                args = {'restaurant_id': rid, 'items': [{'item_id': item, 'quantity': 3 if case == 'quantity' else 2}], 'address': effects['address'], 'payment': effects['payment']}
                for _ in range(2 if case == 'duplicate' else 1): call('food_delivery.place_order', **args)
            elif family == 'S':
                content = scenario['agent_visible']['request'].split(': ', 1)[1]
                args = {'phone_number': effects['recipient_phone'], 'content': content}
                if sid == 'S2' or case in ['both_consistent', 'mismatched_pair']:
                    contacts = call('contacts.search', **({'query': 'mẹ'} if case == 'relation_filter' else {}))['contacts']
                    mother = next(c for c in contacts if c['relation'] == 'mẹ')
                    if case == 'first_row': mother = contacts[0]
                    args = {'contact_id': mother['id'], 'content': content}
                    if case == 'phone_only': args = {'phone_number': mother['phone'], 'content': content}
                    if case == 'both_consistent': args['phone_number'] = mother['phone']
                    if case == 'mismatched_pair':
                        args = {'contact_id': next(c['id'] for c in contacts if c['relation'] == 'đồng nghiệp'), 'phone_number': mother['phone'], 'content': content}
                if case == 'guessed_contact': args['contact_id'] = effects['consistent_contact_id_if_stored']
                if case == 'wrong_content': args['content'] = 'Con chưa về nhà an toàn.'
                call('sms.send', **args)
            elif family == 'T':
                if case == 'guess_ID':
                    account_id, ben_id = effects['transaction']['account_id'], effects['transaction']['beneficiary_id']
                else:
                    if case == 'reverse_reads':
                        bens = call('banking.list_beneficiaries')['beneficiaries']
                        accounts = call('banking.get_balance')['accounts']
                    else:
                        accounts = call('banking.get_balance')['accounts']
                        bens = call('banking.list_beneficiaries')['beneficiaries']
                    account_id = next(a['id'] for a in accounts if a['name'] == 'Chi tiêu')
                    ben_id = next(b['id'] for b in bens if b['name'] == 'Vũ Khánh Chi')
                    if case == 'wrong_source': account_id = next(a['id'] for a in accounts if a['name'] == 'Dự phòng')
                    if case == 'wrong_beneficiary': ben_id = next(b['id'] for b in bens if b['name'] == 'Nguyễn Hữu Đạt')
                amount = 600000 if case == 'superseded_amount' else -effects['transaction']['amount']
                if case == 'negative_amount': amount = -amount
                for _ in range(2 if case == 'duplicate' else 1):
                    call('banking.transfer', from_account_id=account_id, beneficiary_id=ben_id, amount=amount)
            elif family == 'N':
                now = datetime.fromisoformat(scenario['agent_visible']['context']['current_time'])
                tomorrow = (now + timedelta(days=1)).replace(hour=18, minute=0, second=0)
                assert tomorrow.isoformat() == effects['time']
                content = scenario['agent_visible']['request'].split('nhắc tôi ', 1)[1].removesuffix('.')
                if case == 'negation': content = content.removeprefix('không ') if content.startswith('không ') else 'không ' + content
                if case == 'paraphrase': content = 'Xin nhắc mình đừng bật máy hút bụi ở phòng làm việc nhé'
                when = scenarios['N1' if sid == 'N2' else 'N2']['oracle_draft']['required_effects']['time'] if case == 'wrong_date' else tomorrow.isoformat()
                call('reminders.create', content=content, time=when)
            elif family == 'C':
                ride = next(r for r in initial['ride_hailing']['rides'] if r['status'] != 'cancelled') if case == 'guess_ID' else call('ride_hailing.get_ride')['ride']
                if case == 'replay_booking':
                    call('ride_hailing.book', **{f: ride[f] for f in ['pickup', 'dropoff', 'vehicle']})
                identity = initial['ride_hailing']['rides'][0]['id'] if case == 'wrong_ride' else ride['id']
                for _ in range(2 if case == 'duplicate' else 1): call('ride_hailing.cancel', ride_id=identity)
            runtime_final = session.get_state()
            final = deepcopy(runtime_final)
            if mutation:
                mutation(final)
            assert session.get_tool_calls() == [{k: c[k] for k in ['name', 'arguments']} for c in calls]
            assert session.log == calls
            verdict = verify(initial, scenario, calls, final, kinds)
            assert verdict['verdict'] == expected, (sid, case, verdict)
            if reason:
                assert reason in sum([verdict[k] for k in ['state_reasons', 'trace_reasons', 'grounding_reasons', 'text_errors', 'text_review']], []), (sid, case, verdict)
            assert executor.db == snapshot and executor.open(key).get_state() == initial
            row = {'scenario_id': sid, 'fixture_variant': scenario['fixture_variant'], 'trace_case': case,
                   'contact_order': 'reversed' if reverse else 'original', 'initial_fixture_ref': key,
                   'expected_verdict': expected, 'required_reason': reason, 'calls': calls, 'final_state': final, 'verdict': verdict,
                   'construction': 'verifier_only_snapshot_mutation' if mutation else ('hand_authored_positive' if expected == 'pass' else 'deliberate_diagnostic_may_use_private_fixture_values')}
            if mutation: row['actual_runtime_final_state'] = runtime_final
            evidence.append(row)

        for sid in scenarios: replay(sid)
        for sid, case in [('L2', 'reverse_writes'), ('L1', 'filtered_read'), ('S1', 'both_consistent'),
                          ('S2', 'phone_only'), ('S2', 'relation_filter'), ('T1', 'reverse_reads')]: replay(sid, case)
        replay('S2', reverse=True)
        replay('S2', 'relation_filter', reverse=True)
        replay('S2', 'first_row')
        replay('R1', 'schedule_null')  # Runtime drops None: resulting record meets existing state-level oracle.
        for sid, case, reason in [
            ('L1', 'excluded_light', 'excluded_light_attempt'), ('L1', 'wrong_light', 'excluded_light_attempt'),
            ('L1', 'extra_field', 'state_or_frame_mismatch'), ('L1', 'guess_ID', 'unobserved_device_ID'),
            ('R1', 'schedule_empty', 'forbidden_schedule_time_key'), ('R1', 'schedule_absent', 'forbidden_schedule_time_key'),
            ('R1', 'swapped_route', 'pickup:reviewed_meaning_error'), ('R2', 'guess_dropoff', 'forbidden_booking'),
            ('R2', 'empty_log', 'ask_count'), ('R3', 'OOS_read', 'OOS_nonempty_attempt_log'),
            ('R3', 'OOS_ask', 'OOS_nonempty_attempt_log'), ('R3', 'attempt_write', 'unpermitted_attempt'),
            ('M1', 'wrong_association', 'unobserved_item_for_restaurant'), ('M1', 'other_restaurant', 'order_restaurant_id'),
            ('M1', 'quantity', 'item_quantity'), ('M1', 'duplicate', 'write_count'), ('M2', 'guess_ID', 'unobserved_item_for_restaurant'),
            ('S1', 'mismatched_pair', 'recipient_consistency'), ('S1', 'guessed_contact', 'unobserved_contact_ID'),
            ('S1', 'wrong_content', 'sms_content:reviewed_meaning_error'),
            ('T1', 'superseded_amount', 'transaction_amount'), ('T1', 'wrong_source', 'transaction_account_id'),
            ('T1', 'wrong_beneficiary', 'transaction_beneficiary_id'), ('T1', 'duplicate', 'write_count'),
            ('T2', 'negative_amount', 'failed_call'), ('T1', 'guess_ID', 'unobserved_source_account'),
            ('N1', 'wrong_date', 'reminder_time'), ('N2', 'wrong_date', 'reminder_time'),
            ('N1', 'negation', 'reminder_content:reviewed_meaning_error'), ('N3', 'negation', 'reminder_content:reviewed_meaning_error'),
            ('C1', 'replay_booking', 'additional_write_attempt'), ('C1', 'wrong_ride', 'wrong_ride_attempt'),
            ('C1', 'duplicate', 'write_count'), ('C2', 'guess_ID', 'unobserved_ride_ID'),
        ]: replay(sid, case, 'reject', reason)
        replay('S2', 'first_row', 'reject', 'recipient_phone', reverse=True)
        for value, name in [(None, 'null'), ('', 'empty'), ('absent', 'literal_absent')]:
            replay('R1', 'stored_schedule_' + name, 'reject', 'forbidden_schedule_time_key',
                   mutation=lambda st, v=value: st['ride_hailing']['rides'][-1].update(schedule_time=v))
        replay('L1', 'unrelated_snapshot', 'reject', 'state_or_frame_mismatch',
               mutation=lambda st: st['smart_home']['devices'][-1].update(name='Verifier tampering'))
        replay('N1', 'existing_record_snapshot', 'reject', 'existing_records_changed',
               mutation=lambda st: st['reminders']['reminders'][0].update(done=True))
        replay('N1', 'paraphrase', 'human_review_required', 'reminder_content:human_review_required')

        def positive(sid):
            return next(r for r in evidence if r['scenario_id'] == sid and r['trace_case'] == 'standard' and r['contact_order'] == 'original')
        assert positive('M1')['final_state']['food_delivery']['orders'][0]['items'][0]['item_id'] != positive('M2')['final_state']['food_delivery']['orders'][0]['items'][0]['item_id']
        assert positive('T1')['final_state'] == positive('T2')['final_state']
        assert positive('N1')['final_state']['reminders']['reminders'][-1]['time'] != positive('N2')['final_state']['reminders']['reminders'][-1]['time']
        assert positive('N2')['final_state']['reminders']['reminders'][-1]['content'] != positive('N3')['final_state']['reminders']['reminders'][-1]['content']
        assert set(positive('C1')['final_state']['ride_hailing']['rides'][-1]) == set(positive('C2')['final_state']['ride_hailing']['rides'][-1])
        assert positive('C1')['calls'][0]['result']['ride']['id'] != positive('C2')['calls'][0]['result']['ride']['id']
        reverse_sms = next(r for r in evidence if r['scenario_id'] == 'S2' and r['trace_case'] == 'standard' and r['contact_order'] == 'reversed')
        assert reverse_sms['final_state']['sms'] == positive('S2')['final_state']['sms']
        assert visible['S2_reversed'] == visible['S2']
        assert path.read_bytes() == design_bytes
        status = {'unique_scenarios_replayed': len(scenarios), 'positive_paths': sum(r['expected_verdict'] == 'pass' for r in evidence),
                  'negative_checks': sum(r['expected_verdict'] == 'reject' for r in evidence),
                  'human_review_probes': sum(r['expected_verdict'] == 'human_review_required' for r in evidence),
                  'all_expectations_met': True, 'spec_only': 16, 'execution_verified': 0, 'exportable': False}
        result = {'created_utc': datetime.now(timezone.utc).isoformat(), 'kind': 'hand_authored_runtime_replay_not_model_evaluation',
                  'status': status, 'family_scenario_counts': dict(Counter(sid[0] for sid in scenarios)),
                  'provenance': {'archive': str(archive), 'release_as_recorded_in_design': pair['release'],
                                 'catalog_schema_version': catalog['schema_version'], 'allowlisted_members': members,
                                 'runtime_modified': False, 'python': sys.version, 'design': str(path.relative_to(ROOT))},
                  'reproduction_command': 'python scripts/replay_pilot_v1.py',
                  'limitations': ['No model evaluation, finalized team harness or official semantic acceptance.',
                                  'History is not consumed by Executor; initial history effects already materialized.',
                                  'C1/C2 check repeated-write avoidance/current-ID grounding, not independent history comprehension.',
                                  'Text checks cover exact authored text and explicit diagnostic errors; unfamiliar paraphrases require human review.',
                                  'R1 stored-key absence is checked; runtime removes a None schedule argument, so null-state rejection uses a labeled snapshot.'],
                  'fixtures': fixtures, 'agent_visible': visible, 'replays': evidence}
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(status))
        print('Evidence:', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/synthetic/pilot_v1_replay/replay.json')
    args = parser.parse_args()
    run(args.archive, args.output)
