"""Four hand-authored transfer-correction contrasts; no NLP correction parser."""
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

FILES = tuple(p for p in CODE_FILES if p != 'apps/calendar.py') + ('apps/banking.py',)


def verify(initial, scenario, calls, final, kinds):
    # Every expected target/value comes from this scenario's reviewed private specification.
    oracle = scenario['oracle_draft']; target = oracle['final_transfer']; effects = oracle['required_effects']
    parts = {k: [] for k in ['state_reasons', 'frame_reasons', 'trace_reasons', 'grounding_reasons']}
    observed_accounts, observed_beneficiaries, writes, asks = {}, {}, [], []
    for call in calls:
        name, args, result = call['name'], call['arguments'], call['result']
        permitted = name in scenario['agent_visible']['allowed_tools']
        if not permitted: parts['trace_reasons'].append('unpermitted_attempt')
        if permitted and result.get('ok') is True and result.get('done') is not False:
            if name == 'banking.get_balance': observed_accounts.update({a['id']: a for a in result['accounts']})
            if name == 'banking.list_beneficiaries': observed_beneficiaries.update({b['id']: b for b in result['beneficiaries']})
        if kinds.get(name, 'write') == 'write':
            writes.append(call)
            if name != 'banking.transfer':
                parts['trace_reasons'].append('additional_write_attempt')
                continue
            if args.get('from_account_id') not in observed_accounts: parts['grounding_reasons'].append('unobserved_source_ID')
            if args.get('beneficiary_id') not in observed_beneficiaries: parts['grounding_reasons'].append('unobserved_beneficiary_ID')
            if args.get('from_account_id') != target['from_account_id']: parts['trace_reasons'].append('wrong_source')
            if args.get('beneficiary_id') != target['beneficiary_id']: parts['trace_reasons'].append('wrong_beneficiary')
            if args.get('amount') != target['amount']: parts['trace_reasons'].append('wrong_amount')
            # Names/IDs must agree in the actual observation, not merely exist in one namespace.
            a = observed_accounts.get(args.get('from_account_id'), {})
            b = observed_beneficiaries.get(args.get('beneficiary_id'), {})
            if args.get('from_account_id') == target['from_account_id'] and a and a.get('name') != target['source_account_name']:
                parts['grounding_reasons'].append('source_name_ID_mismatch')
            if args.get('beneficiary_id') == target['beneficiary_id'] and b and b.get('name') != target['beneficiary_name']:
                parts['grounding_reasons'].append('beneficiary_name_ID_mismatch')
        if name == 'sys.ask_missing_info': asks.append(call)
    if len(writes) != effects['total_write_count']: parts['trace_reasons'].append('write_count')
    if len(asks) != effects['ask_count']: parts['trace_reasons'].append('unjustified_ask')
    bank, after = initial['banking'], final['banking']
    if {a['id']: a['balance'] for a in after['accounts']} != effects['account_balance_after']:
        parts['state_reasons'].append('account_balances')
    old = bank['transactions']; new = after['transactions'][len(old):]
    if after['transactions'][:len(old)] != old: parts['frame_reasons'].append('existing_transactions_changed')
    if len(after['transactions']) - len(old) != effects['new_transaction_count']: parts['state_reasons'].append('transaction_count')
    frame = deepcopy(final)
    for account in frame['banking']['accounts']:
        if account['id'] == target['from_account_id']:
            account['balance'] = next(a['balance'] for a in bank['accounts'] if a['id'] == account['id'])
    frame['banking']['transactions'] = deepcopy(old)
    if frame != initial: parts['frame_reasons'].append('unrelated_state_or_source_fields_changed')
    ids = [tx.get('id') for tx in new]
    if len(set(ids)) != len(ids) or any(not isinstance(i, str) or not i or i in {t['id'] for t in old} for i in ids):
        parts['state_reasons'].append('invalid_generated_ID')
    successful = [c for c in writes if c['name'] == 'banking.transfer' and c['result'].get('ok') is True and c['result'].get('done') is not False]
    if len(new) != len(successful): parts['state_reasons'].append('response_count')
    for tx, call in zip(new, successful):
        if call['result'].get('transaction') != tx: parts['state_reasons'].append('response_transaction_mismatch')
        for field, value in effects['transaction'].items():
            if tx.get(field) != value: parts['state_reasons'].append('transaction_' + field)
    return verdict({k: sorted(set(v)) for k, v in parts.items()}, calls)


def run(archive, output):
    path = ROOT / 'data/synthetic/design/expansion_batch_03.yaml'; original = path.read_bytes()
    design = yaml.load(original.decode('utf-8'), Loader=StrictLoader)
    world = design['worlds'][0]; pair = design['interface_pair']; scenarios = {s['scenario_id'][-1]: s for s in design['scenarios']}
    assert set(scenarios) == set('ABCD')
    fixtures, visible = {}, {}
    for letter, scenario in scenarios.items():
        assert scenario['fixture_variant'] == 'base'
        for order in ['original', 'beneficiaries_reversed']:
            entry = deepcopy(world['initial_state']); entry['sys'] = {}
            if order != 'original': entry['banking']['beneficiaries'].reverse()
            entry['_meta'] = {'tools': scenario['agent_visible']['allowed_tools'][:], 'current_time': scenario['agent_visible']['context']['current_time']}
            key = letter + '/' + order; fixtures[key] = entry
            agent = deepcopy(scenario['agent_visible']); agent['context']['installed_apps'] = {}
            for name in agent['allowed_tools']: agent['context']['installed_apps'].setdefault(name.split('.')[0], {'tools': []})['tools'].append(name)
            visible[key] = agent
    assert all(fixtures[c + '/original'] == fixtures['A/original'] for c in 'ABCD')
    output.parent.mkdir(parents=True, exist_ok=True); evidence = []
    with tempfile.TemporaryDirectory(prefix='ex3_runtime_', dir=output.parent) as temp:
        temp = Path(temp); members = [pair['runtime_root'] + p for p in FILES] + [pair['catalog_member']]
        with zipfile.ZipFile(archive) as source:
            for relative in FILES:
                p = temp / 'zaic_tools' / relative; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(source.read(pair['runtime_root'] + relative))
            cp = temp / 'catalog.json'; cp.write_bytes(source.read(pair['catalog_member']))
        catalog = json.loads(cp.read_text(encoding='utf-8')); assert catalog['schema_version'] == pair['catalog_schema_version']
        tools = {t['name']: t for app in catalog['apps'] for t in app['tools']}; kinds = {n: t['kind'] for n, t in tools.items()}
        for name, contract in pair['capability_contracts'].items(): assert tools[name]['parameters']['required'] == contract['required']
        assert tools['banking.transfer']['parameters']['properties']['amount']['exclusiveMinimum'] == 0
        assert 'currency' not in tools['banking.transfer']['parameters']['properties']
        if 'zaic_tools' in sys.modules: raise RuntimeError('Use a fresh Python process')
        sys.path.insert(0, str(temp))
        from zaic_tools.executor import Executor
        fp = temp / 'synthetic.json'; fp.write_text(json.dumps(fixtures, ensure_ascii=False), encoding='utf-8')
        executor = Executor(str(fp), str(cp)); snapshot = deepcopy(executor.db)

        def replay(letter, case='standard', order='original', expected='pass', reason=None):
            scenario = scenarios[letter]; target = scenario['oracle_draft']['final_transfer']; superseded = scenario['oracle_draft']['superseded']
            key = letter + '/' + order; session = executor.open(key); initial = session.get_state(); calls = []
            assert initial == {k: v for k, v in fixtures[key].items() if k != '_meta'}
            assert session.allowed == set(scenario['agent_visible']['allowed_tools']) and session.now == scenario['agent_visible']['context']['current_time']
            def call(name, **args):
                before = session.get_state(); result = session.call(name, args); after = session.get_state()
                if kinds[name] in ['read', 'meta']: assert after == before
                if name == 'banking.get_balance': assert result == {'ok': True, 'accounts': before['banking']['accounts']}
                if name == 'banking.list_beneficiaries': assert result == {'ok': True, 'beneficiaries': before['banking']['beneficiaries']}
                if name == 'banking.transfer' and result.get('transaction'):
                    account = next(a for a in after['banking']['accounts'] if a['id'] == args['from_account_id'])
                    assert result['balance'] == account['balance']
                    assert result['transaction'] == after['banking']['transactions'][-1]
                    assert result['transaction']['amount'] == -args['amount']
                calls.append({'name': name, 'arguments': deepcopy(args), 'result': deepcopy(result)}); return result
            if case == 'guess_IDs':
                source_id, beneficiary_id = target['from_account_id'], target['beneficiary_id']  # Deliberate private-ID diagnostic.
                accounts, beneficiaries = [], []
            else:
                if case == 'reverse_reads':
                    beneficiaries = call('banking.list_beneficiaries')['beneficiaries']; accounts = call('banking.get_balance')['accounts']
                else:
                    accounts = call('banking.get_balance')['accounts']
                    beneficiaries = [] if case == 'unobserved_beneficiary' else call('banking.list_beneficiaries')['beneficiaries']
                source_id = next(a['id'] for a in accounts if a['name'] == target['source_account_name'])
                beneficiary_id = target['beneficiary_id'] if case == 'unobserved_beneficiary' else next(b['id'] for b in beneficiaries if b['name'] == target['beneficiary_name'])
                if case == 'repeated_reads': call('banking.get_balance'); call('banking.list_beneficiaries')
            amount = target['amount']
            if case in ['old_beneficiary', 'old_both', 'obsolete_then_final']:
                beneficiary_id = next(b['id'] for b in beneficiaries if b['name'] == superseded['beneficiary_name'])
            if case in ['old_amount', 'old_both', 'obsolete_then_final']: amount = superseded['amount']
            if case == 'wrong_source': source_id = next(a['id'] for a in accounts if a['id'] != source_id)
            call('banking.transfer', from_account_id=source_id, beneficiary_id=beneficiary_id, amount=amount)
            if case == 'obsolete_then_final':
                source_id = next(a['id'] for a in accounts if a['name'] == target['source_account_name'])
                beneficiary_id = next(b['id'] for b in beneficiaries if b['name'] == target['beneficiary_name'])
                call('banking.transfer', from_account_id=source_id, beneficiary_id=beneficiary_id, amount=target['amount'])
                transfers = [c for c in calls if c['name'] == 'banking.transfer']
                assert len(transfers) == 2 and all(c['result'].get('transaction') and c['result'].get('done') is not False for c in transfers)
                assert len(session.get_state()['banking']['transactions']) == len(initial['banking']['transactions']) + 2
                remaining = next(a['balance'] for a in session.get_state()['banking']['accounts'] if a['id'] == source_id)
                assert remaining == next(a['balance'] for a in accounts if a['id'] == source_id) - superseded['amount'] - target['amount']
            if case == 'extra_mutation':
                other_account = next(a for a in accounts if a['id'] != source_id)
                other_beneficiary = next(b for b in beneficiaries if b['id'] != beneficiary_id)
                extra_amount = abs(initial['banking']['transactions'][0]['amount'])
                result = call('banking.transfer', from_account_id=other_account['id'], beneficiary_id=other_beneficiary['id'], amount=extra_amount)
                assert result.get('transaction') and result.get('done') is not False
            if case == 'unpermitted_mutation':
                assert call('banking.open_savings', from_account_id=source_id, amount=amount, term_months=3)['ok'] is False
            if case == 'duplicate': call('banking.transfer', from_account_id=source_id, beneficiary_id=beneficiary_id, amount=amount)
            runtime_final = session.get_state(); final = deepcopy(runtime_final); reviewed = deepcopy(scenario)
            if case == 'prior_transaction_snapshot': final['banking']['transactions'][0]['note'] = 'Verifier-only tampering'
            if case == 'changed_expected_beneficiary':
                other = next(b for b in beneficiaries if b['id'] != target['beneficiary_id'])
                reviewed['oracle_draft']['final_transfer'].update(beneficiary_name=other['name'], beneficiary_id=other['id'])
                reviewed['oracle_draft']['required_effects']['transaction']['beneficiary_id'] = other['id']
            actual = verify(initial, reviewed, calls, final, kinds)
            assert actual['verdict'] == expected, (letter, case, actual)
            if reason: assert reason in sum([v for k, v in actual.items() if k not in ['verdict', 'attempt_diagnostics']], []), (case, actual)
            if case in ['guess_IDs', 'unobserved_beneficiary', 'unpermitted_mutation']:
                assert not actual['state_reasons'] and not actual['frame_reasons'], actual
            assert session.get_tool_calls() == [{k: c[k] for k in ['name', 'arguments']} for c in calls] and session.log == calls
            assert executor.db == snapshot and executor.open(key).get_state() == initial
            kind = 'verifier_only_snapshot' if case == 'prior_transaction_snapshot' else ('verifier_only_expectation' if case == 'changed_expected_beneficiary' else 'actual_runtime_trace')
            row = {'scenario_id': scenario['scenario_id'], 'lineage_id': scenario['lineage_id'], 'fixture_variant': scenario['fixture_variant'], 'ordering': order,
                   'trace_case': case, 'initial_fixture_ref': key, 'expected_verdict': expected, 'required_reason': reason, 'calls': calls, 'final_state': final, 'verdict': actual,
                   'evidence_kind': kind, 'construction': 'hand_authored_positive' if expected == 'pass' else 'deliberate_diagnostic_may_use_private_IDs'}
            if kind == 'verifier_only_snapshot': row['actual_runtime_final_state'] = runtime_final
            if kind == 'verifier_only_expectation': row['verifier_expected_oracle'] = reviewed['oracle_draft']
            evidence.append(row)

        for letter in 'ABCD':
            replay(letter); replay(letter, order='beneficiaries_reversed'); replay(letter, 'reverse_reads')
        replay('D', 'repeated_reads')
        for letter, case, reason in [
            ('B', 'old_beneficiary', 'wrong_beneficiary'), ('C', 'old_amount', 'wrong_amount'),
            ('D', 'old_beneficiary', 'wrong_beneficiary'), ('D', 'old_amount', 'wrong_amount'), ('D', 'old_both', 'wrong_beneficiary'),
            ('D', 'obsolete_then_final', 'write_count'), ('A', 'wrong_source', 'wrong_source'),
            ('A', 'guess_IDs', 'unobserved_source_ID'), ('A', 'unobserved_beneficiary', 'unobserved_beneficiary_ID'),
            ('A', 'extra_mutation', 'write_count'), ('A', 'unpermitted_mutation', 'additional_write_attempt'), ('A', 'duplicate', 'write_count'),
        ]: replay(letter, case, expected='reject', reason=reason)
        replay('A', 'prior_transaction_snapshot', expected='reject', reason='existing_transactions_changed')
        replay('A', 'changed_expected_beneficiary', expected='reject', reason='wrong_beneficiary')
        positives = [r for r in evidence if r['expected_verdict'] == 'pass']
        def equivalent_state(state):
            normalized = deepcopy(state)
            normalized['banking']['beneficiaries'].sort(key=lambda b: b['id'])
            old_count = len(world['initial_state']['banking']['transactions'])
            # Generated IDs/optional note are verified locally, not cross-session semantic gold.
            normalized['banking']['transactions'][old_count:] = [
                {k: tx[k] for k in ['account_id', 'beneficiary_id', 'amount']}
                for tx in normalized['banking']['transactions'][old_count:]]
            return normalized
        assert all(equivalent_state(r['final_state']) == equivalent_state(positives[0]['final_state']) for r in positives)
        probe = next(r for r in evidence if r['trace_case'] == 'changed_expected_beneficiary')
        standard = next(r for r in positives if r['scenario_id'] == scenarios['A']['scenario_id'] and r['trace_case'] == 'standard' and r['ordering'] == 'original')
        assert probe['calls'] == standard['calls'] and probe['final_state'] == standard['final_state']
        assert all(visible[c + '/original'] == visible[c + '/beneficiaries_reversed'] for c in 'ABCD')
        assert path.read_bytes() == original
        runtime = [r for r in evidence if r['evidence_kind'] == 'actual_runtime_trace']
        status = {'unique_scenarios_replayed': 4, 'positive_runtime_paths': sum(r['expected_verdict']=='pass' for r in runtime),
                  'negative_runtime_traces': sum(r['expected_verdict']=='reject' for r in runtime), 'verifier_only_checks': len(evidence)-len(runtime),
                  'all_expectations_met': True, 'spec_only': 4, 'execution_verified': 0, 'exportable': False}
        result = {'created_utc': datetime.now(timezone.utc).isoformat(), 'kind': 'hand_authored_runtime_replay_not_model_evaluation', 'status': status,
                  'provenance': {'archive': str(archive), 'design': str(path.relative_to(ROOT)), 'release_as_recorded_in_design': pair['release'], 'catalog_schema_version': catalog['schema_version'], 'allowlisted_members': members, 'runtime_modified': False, 'python': sys.version},
                  'world_ancestry': world['ancestry'], 'fixtures': fixtures, 'agent_visible': visible, 'replays': evidence,
                  'reproduction_command': 'python scripts/replay_expansion_batch_03.py',
                  'limitations': ['No NLP correction parser or model evaluation; request meanings come from authored specification, not runtime success.', 'Independent semantic review, team harness/serialization, official acceptance and training export remain unverified.', 'Failed/no-op attempts are retained; authored effect/trace/frame rules decide verdicts.']}
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8'); print(json.dumps(status)); print('Evidence:', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=Path(os.environ.get("LIFEMATE_SDK_ARCHIVE", "external/train+public_test.zip")))
    parser.add_argument('--output', type=Path, default=ROOT/'artifacts/synthetic/expansion_batch_03_replay/replay.json')
    args = parser.parse_args(); run(args.archive, args.output)
