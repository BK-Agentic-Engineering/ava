"""Replay 26 historical/current factual decisions and authorized note effects."""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sys
import tempfile
from time import perf_counter
import zipfile
from zoneinfo import ZoneInfo

from audit_synthetic_coverage import components
from evaluate_factual_answer_pilot import grade,overall
from replay_train_wave_08 import ROOT,load_design,validate
from replay_train_wave_13 import execute_history
from replay_train_wave_15 import ARCHIVE
from replay_train_wave_19 import fact_value

DESIGN=ROOT/'data/synthetic/design/train_wave_20.yaml'
OUTPUT=ROOT/'artifacts/synthetic/train_wave_20_replay/replay.json'


def day_for(context,offset):
    local=datetime.fromisoformat(context['current_time']).astimezone(ZoneInfo(context['timezone']))
    return (local.date()+timedelta(days=offset)).isoformat()


def retrieval_dates(day,zone):
    # SDK filters inclusive raw ISO date prefixes. Python aware timestamps allow
    # offsets strictly between -24h and +24h; do not assume every source is +07.
    start=datetime.combine(day,datetime.min.time(),ZoneInfo(zone)).astimezone(timezone.utc)
    end=datetime.combine(day+timedelta(days=1),datetime.min.time(),ZoneInfo(zone)).astimezone(timezone.utc)
    tick=timedelta(microseconds=1)
    return ((start-timedelta(days=1)+tick).date().isoformat(),
            (end+timedelta(days=1)-tick).date().isoformat())


def observe_fact(spec,visible,calls):
    fact=deepcopy(spec)
    if fact['tool']=='contacts.search' and 'history_tag' not in fact:
        # The visible history already exposes contact IDs. A permitted get of
        # that record supplies the same current fields as a new search.
        calls=[{**c,'name':'contacts.search'} if c['name']=='contacts.get' else c for c in calls]
    if fact.get('account_name'):
        balances=[c['result'] for c in calls if c['name']=='banking.get_balance']
        for turn in visible['history']:
            if turn['role']=='assistant':
                balances.extend(result for call,result in zip(turn['tool_calls'],turn.get('tool_results',[]))
                                if call['name']=='banking.get_balance')
        identities={row['id'] for result in balances if isinstance(result,dict) and result.get('ok') is True
                    for row in result.get('accounts',[]) if row.get('name')==fact['account_name']}
        if len(identities)!=1:return 'missing',None
        identity=next(iter(identities))
        fact['match']={**fact['match'],'account_id':identity}
        if fact.get('complete'):
            eligible=[c for c in calls if c['name']==fact['tool'] and c['arguments'] in ({},{'account_id':identity})]
            if not eligible:return 'missing',None
            fact['scope']=eligible[-1]['arguments'];calls=eligible
    if 'history_tag' in fact:
        # The sidecar tag is private. Actual historical payloads are found by
        # visible turn/call position and compared to the named observable tool.
        index=fact['history_position']
        turns=[t for t in visible['history'] if t['role']=='assistant']
        if not turns or index>=len(turns[0].get('tool_results',[])):
            return 'missing',None
        turn=turns[0];result=turn['tool_results'][index]
        if not isinstance(result,dict) or turn['tool_calls'][index]['name']!=fact['tool']:
            return 'missing',None
        calls=[{**turn['tool_calls'][index],'result':result}]
    if 'relative_day' in fact:
        date=day_for(visible['context'],fact['relative_day'])
        local_day=datetime.fromisoformat(date).date()
        lower,upper=retrieval_dates(local_day,visible['context']['timezone'])
        eligible=[]
        for call in calls:
            args=call['arguments']
            if call['name']!=fact['tool'] or not set(args)<={'date_from','date_to'}:
                continue
            if args.get('date_from') and args['date_from']>lower:
                continue
            if args.get('date_to') and args['date_to']<upper:
                continue
            result=call['result']
            if result.get('ok') is not True or result.get('done') is False:
                continue
            events=result.get('events')
            if not isinstance(events,list) or any(not isinstance(e,dict) for e in events):
                continue
            selected=[]
            for event in events:
                try:
                    start=datetime.fromisoformat(event['start'])
                    if start.tzinfo is None:return 'missing',None
                    event_day=start.astimezone(ZoneInfo(visible['context']['timezone'])).date()
                except (KeyError,TypeError,ValueError):
                    return 'missing',None
                if event_day==local_day:selected.append(event)
            eligible.append({**call,'result':{**result,'events':selected}})
        if not eligible:return 'missing',None
        fact.pop('dates',None)
        if fact['operation']=='count':
            fact['scope']=eligible[-1]['arguments']
        calls=eligible
    return fact_value(fact,calls)


def verify(s,visible,initial,calls,final,text,kinds):
    o=s['oracle_draft'];reasons=set()
    permitted=visible['allowed_tools']
    if any(c['name'] not in permitted for c in calls):reasons.add('permission')
    if any(c['result'].get('ok') is not True or c['result'].get('done') is False for c in calls):reasons.add('call_failure')
    writes=[c for c in calls if kinds.get(c['name'])!='read']
    expected=o.get('note');content_review=False
    if expected:
        expected=deepcopy(expected)
        if len(writes)==1 and writes[0]['arguments'].get('content') in o.get('equivalent_note_contents',[]):
            expected['content']=writes[0]['arguments']['content']
        elif len(writes)==1 and writes[0]['name']=='notes.create':
            args=writes[0]['arguments']
            if (set(args)==set(expected) and args.get('title')==expected['title']
                    and isinstance(args.get('content'),str) and args['content'].strip()
                    and args['content']!=expected['content']):
                # These requests specify note meaning, not a literal template.
                # Check the frame exactly, but defer unrecognized prose instead
                # of treating a different string as automatically wrong/right.
                expected['content']=args['content'];content_review=True
    if expected:
        if len(writes)!=1 or writes[0]['name']!='notes.create' or writes[0]['arguments']!=expected:
            reasons.add('authorized_write')
    elif writes:reasons.add('unauthorized_write')
    required_initial=deepcopy(initial)
    if expected and len(writes)==1 and writes[0]['name']=='notes.create':
        payload={'id':writes[0]['result'].get('id'),'title':'',**expected}
        required_initial['notes']['notes'].append(payload)
    if required_initial!=final:reasons.add('state')
    # Required observations must precede the consuming write, when any.
    limit=next((i for i,c in enumerate(calls) if kinds.get(c['name'])!='read'),len(calls))
    reads=[c for c in calls[:limit] if c['name'] in permitted and kinds.get(c['name'])=='read']
    values=[observe_fact(f,visible,reads) for f in o['facts']]
    for status,_ in values:
        if status!='supported':reasons.add('evidence_'+status)
    trace='fail' if reasons else 'unresolved' if content_review else 'pass'
    if content_review:reasons.add('note_content_requires_review')
    if any(status!='supported' for status,_ in values):answer,reason='unresolved','missing_or_ambiguous_evidence'
    elif [v for _,v in values]!=[f['expected'] for f in o['facts']]:answer,reason='unresolved','source_mismatch'
    else:answer,reason=grade(o['answer_rules'],text)
    combined=overall(trace,answer)
    return {'trace_verdict':trace,'trace_reasons':sorted(reasons),'answer_verdict':answer,'answer_reason':reason,
            'observed_facts':values,'overall':combined,'verdict':'pass' if combined=='pass' else 'reject' if combined=='fail' else 'unresolved'}


def run(archive,output):
    start=perf_counter();design=load_design(DESIGN)
    assert (design['split'],design['status'],design['exportable'])==('train','spec_only',False)
    docs=[load_design(p) for p in sorted(DESIGN.parent.glob('*.yaml'))]
    inventory=validate(next(d for d in docs if d['version']=='train_wave_14'),docs);inventory.pop('near_duplicate_review',None)
    inventory['components']=components({w['world_id']:w for d in docs for w in d['worlds']},{s['scenario_id']:s for d in docs for s in d['scenarios']})
    worlds={w['world_id']:w for w in design['worlds']};provenance=design['provenance']
    apps=sorted({t.split('.')[0] for w in worlds.values() for t in w['relevant_tools']}-{'sys'})
    files=['__init__.py','executor.py','validate.py','utils.py','apps/__init__.py','apps/base.py','apps/sys.py']+[f'apps/{app}.py' for app in apps]
    output.parent.mkdir(parents=True,exist_ok=True)
    records,rows,probes={},[],[]
    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        root=Path(directory)
        with zipfile.ZipFile(archive) as source:
            for member in files:
                path=root/'zaic_tools'/member;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(source.read(provenance['runtime_root']+member))
            catalog=json.loads(source.read(provenance['catalog_member']))
        assert catalog['schema_version']==provenance['schema']
        kinds={t['name']:t['kind'] for a in catalog['apps'] for t in a['tools']}
        assert 'zaic_tools' not in sys.modules;sys.path.insert(0,directory)
        from zaic_tools.executor import Session
        for s in design['scenarios']:
            sid=s['scenario_id'];w=worlds[s['world_id']];v=deepcopy(s['agent_visible']);o=s['oracle_draft']
            assert s['status']=='spec_only' and s['exportable'] is False and w['split']=='train'
            assert v['allowed_tools']==w['relevant_tools'] and v['history']==[]
            assert s['fixture_variant']=='base' or s['fixture_variant'] in w['variants']
            state=deepcopy(w['initial_state'])
            for app,fields in w['variants'].get(s['fixture_variant'],{}).items():
                for collection,patches in fields.items():
                    for identity,patch in patches.items():next(r for r in state[app][collection] if r['id']==identity).update(deepcopy(patch))
            hist_session=Session(sid,{**state,'_meta':{'tools':v['allowed_tools'],'current_time':s['history_time']}},catalog)
            assert datetime.fromisoformat(s['history_time'])<datetime.fromisoformat(v['context']['current_time'])
            turns,events,historical=execute_history(hist_session,s['historical_turns'])
            v['history']=turns;post=hist_session.get_state()
            for f in o['facts']:
                if 'history_tag' in f:
                    event=events[f['history_tag']]
                    assert event['position']==f['history_position'] and event['name']==f['tool']
            records[sid]={'agent_visible':v,'pre_history_state':state,'post_history_state':post,'historical_calls':historical,
                          'historical_current_time':s['history_time']}
            alternate='alternative_lookup' if o['reads']!=o['alternative_reads'] else 'reproducibility_repeat'
            plans={'standard':o['reads'],alternate:o['alternative_reads'],'wrong_write':o['reads']+[o['wrong_write']]}
            if o.get('equivalent_note_contents'):
                plans['equivalent_note']=o['reads']+[['notes.create',{**o['note'],'content':o['equivalent_note_contents'][0]}]]
            for case,plan in plans.items():
                session=Session(sid,{**post,'_meta':{'tools':v['allowed_tools'],'current_time':v['context']['current_time']}},catalog)
                assert session.log==[] and session.get_state()==post
                assert session.allowed==set(v['allowed_tools'])|{'sys.ask_missing_info'}
                for name,args in plan+([['notes.create',o['note']]] if o.get('note') and case not in {'wrong_write','equivalent_note'} else []):
                    result=session.call(name,args)
                    assert result.get('ok') is True and result.get('done') is not False,(sid,case,result)
                calls=deepcopy(session.log);final=session.get_state()
                verdict=verify(s,v,post,calls,final,o['answers'][0],kinds)
                assert verdict['trace_verdict']==('fail' if case=='wrong_write' else 'pass'),(sid,case,verdict)
                run_id=sid+'/'+case
                rows.append({'scenario_id':sid,'run_id':run_id,'trace_case':case,'calls':calls,'final_state':final,
                             'evidence_kind':'actual_runtime_trace','authored_final_text':o['answers'][0],
                             'text_provenance':'authored_answer_probe','verdict':verdict})
                if case=='standard':
                    for label,text,expected in [('correct',o['answers'][0],'pass'),('alternative',o['answers'][1],'pass'),
                                                ('wrong',o['wrong_answer'],'fail'),('manual_review',o['manual_answer'],'unresolved')]:
                        result=verify(s,v,post,calls,final,text,kinds)
                        assert result['answer_verdict']==expected,(sid,label,result)
                        probes.append({'scenario_id':sid,'trace_ref':run_id,'probe':label,'text':text,
                                       'provenance':'authored_answer_probe','verdict':result})
                    # Deliberate in-memory evidence ablation, never an SDK trace.
                    hidden=deepcopy(v)
                    for turn in hidden['history']:
                        if turn['role']=='assistant':turn['tool_results']=[]
                    ablated_calls=[c for c in calls if kinds[c['name']]!='read']
                    missing=verify(s,hidden,post,ablated_calls,final,o['answers'][0],kinds)
                    assert missing['trace_verdict']=='fail' and missing['answer_verdict']=='unresolved'
                    probes.append({'scenario_id':sid,'trace_ref':run_id,'probe':'remove_observations',
                                   'provenance':'modified_evidence_verifier_probe','verdict':missing})
    result={'created_utc':datetime.now(timezone.utc).isoformat(),'replay_wall_seconds':perf_counter()-start,
            'declared_volatile_fields':['created_utc','replay_wall_seconds'],'inventory':inventory,
            'provenance':{**provenance,'archive':str(archive),'allowlisted_members':[provenance['runtime_root']+f for f in files]+[provenance['catalog_member']]},
            'scenarios':records,'replays':rows,'answer_probes':probes,
            'status':{'scenarios':len(records),'historical_calls':sum(len(r['historical_calls']) for r in records.values()),
                      'outcomes':dict(Counter(s['oracle_draft']['outcome'] for s in design['scenarios'])),
                      'trace_verdicts':dict(Counter(r['verdict']['trace_verdict'] for r in rows)),
                      'probe_verdicts':dict(Counter(p['verdict']['overall'] for p in probes)),
                      'exportable':False,'execution_verified':0}}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(result['status'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--archive',type=Path,default=ARCHIVE)
    parser.add_argument('--output',type=Path,default=OUTPUT);args=parser.parse_args();run(args.archive,args.output)
