from copy import deepcopy

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
