"""Run new factual questions with same-run evidence and separate answer probes."""
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

from audit_synthetic_coverage import components
from evaluate_factual_answer_pilot import at, grade, overall
from replay_train_wave_08 import ROOT, load_design, matches, validate
from replay_train_wave_15 import ARCHIVE

DESIGN=ROOT/'data/synthetic/design/train_wave_19.yaml'
OUTPUT=ROOT/'artifacts/synthetic/train_wave_19_replay/replay.json'


def scope_covers(fact, args):
    if args == fact['scope']:
        return True
    # These SDK filters retain every row of the requested equality scope.
    filters = {
        'bill_payment.list_bills': {'type': 'type'},
        'appliances.list': {'type': 'type'},
        'smart_home.get_status': {'room': 'room', 'floor': 'floor', 'type': 'type'},
        'tasks.list': {'status': 'done'},
    }.get(fact['tool'], {})
    if not args or not set(args) <= filters.keys():
        return False
    for key, value in args.items():
        if key == 'status':
            if value not in {'open', 'done'}:
                return False
            value = value == 'done'
        if fact['match'].get(filters[key]) != value:
            return False
    return True


def fact_matches(row, fact):
    return matches(row, fact['match']) and all(
        isinstance(row.get(key), str) and row[key][:10] == day
        for key, day in fact.get('dates', {}).items()
    ) and all(row.get(key) in values for key, values in fact.get('one_of', {}).items())


def fact_value(fact, calls):
    responses=[c for c in calls if c['name']==fact['tool'] and c['result'].get('ok') is True
               and c['result'].get('done') is not False]
    if fact.get('complete'):
        responses=[c for c in responses if scope_covers(fact,c['arguments'])]
    if not responses:
        return 'missing',None
    # Scalars and complete scopes use the last qualifying response. Entity fields
    # bind by semantic attributes and distinct ID, never response-array position.
    if fact['operation']=='scalar':
        try:return 'supported',at(responses[-1]['result'],fact['path'])
        except (KeyError,TypeError):return 'missing',None
    records={}
    for call in responses:
        for row in call['result'].get(fact['collection'],[]):
            if fact_matches(row,fact):records[row['id']]=row
    if fact['operation']=='field':
        if len(records)!=1:return ('ambiguous' if records else 'missing'),None
        try:return 'supported',at(next(iter(records.values())),fact['path'])
        except (KeyError,TypeError):return 'missing',None
    # A complete list replaces earlier lists instead of accumulating old records.
    records=[row for row in responses[-1]['result'][fact['collection']] if fact_matches(row,fact)]
    if fact['operation']=='count':return 'supported',len(records)
    if fact['operation']=='sum':return 'supported',sum(at(r,fact['path']) for r in records)
    raise AssertionError(fact['operation'])


def evaluate(scenario, initial, calls, final, text, kinds):
    reasons=set()
    if initial!=final:reasons.add('state_changed')
    for call in calls:
        if call['name'] not in scenario['agent_visible']['allowed_tools']:reasons.add('permission')
        if kinds[call['name']]!='read':reasons.add('write_attempt')
        if call['result'].get('ok') is not True or call['result'].get('done') is False:reasons.add('call_failure')
    observations=[c for c in calls if c['name'] in scenario['agent_visible']['allowed_tools']
                  and kinds.get(c['name'])=='read']
    facts=[fact_value(f,observations) for f in scenario['oracle_draft']['facts']]
    for status,_ in facts:
        if status!='supported':reasons.add('evidence_'+status)
    trace='fail' if reasons else 'pass'
    if any(status!='supported' for status,_ in facts):answer,why='unresolved','insufficient_run_evidence'
    elif [value for _,value in facts]!=[f['expected'] for f in scenario['oracle_draft']['facts']]:
        answer,why='unresolved','source_mismatch'
    else:answer,why=grade(scenario['oracle_draft']['answer_rules'],text)
    combined=overall(trace,answer)
    return {'trace_verdict':trace,'trace_reasons':sorted(reasons),'answer_verdict':answer,
            'answer_reason':why,'overall':combined,'observed_facts':facts,
            'verdict':'pass' if combined=='pass' else 'reject' if combined=='fail' else 'unresolved'}


def fixture(world, scenario):
    state=deepcopy(world['initial_state'])
    for app,collections in world['variants'].get(scenario['fixture_variant'],{}).items():
        for collection,value in collections.items():
            if isinstance(value,dict) and isinstance(state[app].get(collection),list):
                for identity,patch in value.items():
                    next(r for r in state[app][collection] if r['id']==identity).update(deepcopy(patch))
            else:state[app][collection]=deepcopy(value)
    return state


def run(archive,output,pilot=False):
    start=perf_counter();design=load_design(DESIGN)
    docs=[load_design(p) for p in sorted(DESIGN.parent.glob('*.yaml'))]
    inventory=validate(next(d for d in docs if d['version']=='train_wave_14'),docs)
    inventory.pop('near_duplicate_review',None)
    inventory['components']=components({w['world_id']:w for d in docs for w in d['worlds']},
                                       {s['scenario_id']:s for d in docs for s in d['scenarios']})
    assert (design['split'],design['status'],design['exportable'])==('train','spec_only',False)
    worlds={w['world_id']:w for w in design['worlds']};provenance=design['provenance']
    apps=sorted({t.split('.')[0] for w in worlds.values() for t in w['relevant_tools']}-{'sys'})
    files=['__init__.py','executor.py','validate.py','utils.py','apps/__init__.py','apps/base.py','apps/sys.py']+[f'apps/{a}.py' for a in apps]
    records,rows,probes={},{},[]
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        root=Path(directory)
        with zipfile.ZipFile(archive) as source:
            for member in files:
                path=root/'zaic_tools'/member;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(source.read(provenance['runtime_root']+member))
            catalog=json.loads(source.read(provenance['catalog_member']))
        assert catalog['schema_version']==provenance['schema']
        kinds={t['name']:t['kind'] for app in catalog['apps'] for t in app['tools']}
        assert 'zaic_tools' not in sys.modules
        sys.path.insert(0,directory)
        from zaic_tools.executor import Session
        for s in design['scenarios']:
            if pilot and not s.get('pilot'):continue
            sid=s['scenario_id'];w=worlds[s['world_id']];o=s['oracle_draft']
            assert s['status']=='spec_only' and s['exportable'] is False and w['split']=='train'
            assert s['agent_visible']['allowed_tools']==w['relevant_tools']
            state=fixture(w,s)
            entry={**state,'sys':{},'_meta':{'tools':s['agent_visible']['allowed_tools'],
                                          'current_time':s['agent_visible']['context']['current_time']}}
            records[sid]={'agent_visible':s['agent_visible'],'post_history_state':{**state,'sys':{}}}
            distinct = o['broad_reads'] != o['reads']
            alternative_case = 'alternative_lookup' if distinct else 'reproducibility_repeat'
            plans={'standard':o['reads'],alternative_case:o['broad_reads'],'insufficient':o['insufficient_reads']}
            if o.get('unauthorized_write'):
                plans['unauthorized_write']=o['reads']+[o['unauthorized_write']]
            for case,plan in plans.items():
                session=Session(sid,entry,catalog)
                assert session.log==[] and session.allowed==set(w['relevant_tools'])|{'sys.ask_missing_info'}
                for name,args in plan:
                    result=session.call(name,args)
                    assert result.get('ok') is True and result.get('done') is not False
                calls=deepcopy(session.log);final=session.get_state()
                verdict=evaluate(s,records[sid]['post_history_state'],calls,final,o['answers'][0],kinds)
                assert verdict['trace_verdict']==('fail' if case in {'insufficient','unauthorized_write'} else 'pass'),(sid,case,verdict)
                assert verdict['answer_verdict']==('unresolved' if case=='insufficient' else 'pass'),(sid,case,verdict)
                rows[sid+'/'+case]={'scenario_id':sid,'run_id':sid+'/'+case,'trace_case':case,'evidence_kind':'actual_runtime_trace',
                                   'calls':calls,'final_state':final,'authored_final_text':o['answers'][0],
                                   'text_provenance':'authored_answer_probe','verdict':verdict}
                if case=='standard':
                    review = o['review_probe']
                    for label,text,expected in [('correct',o['answers'][0],'pass'),('alternative',o['answers'][1],'pass'),
                                                ('wrong',o['wrong_answer'],'fail'),
                                                (review['label'],review['text'],review['expected'])]:
                        v=evaluate(s,records[sid]['post_history_state'],calls,final,text,kinds)
                        assert v['answer_verdict']==expected,(sid,label,v)
                        probes.append({'scenario_id':sid,'probe':label,'expected_judgment':expected,'trace_ref':sid+'/standard',
                                       'provenance':'authored_answer_probe','text':text,'verdict':v})
                    for probe in o.get('extra_probes', []):
                        v=evaluate(s,records[sid]['post_history_state'],calls,final,probe['text'],kinds)
                        assert v['answer_verdict']==probe['expected'],(sid,probe,v)
                        probes.append({'scenario_id':sid,'probe':probe['label'],'expected_judgment':probe['expected'],
                                       'trace_ref':sid+'/standard','provenance':'authored_answer_probe',
                                       'text':probe['text'],'verdict':v})
                    if o.get('incomplete_answer'):
                        v=evaluate(s,records[sid]['post_history_state'],calls,final,o['incomplete_answer'],kinds)
                        assert v['answer_verdict']=='fail'
                        probes.append({'scenario_id':sid,'probe':'incomplete','trace_ref':sid+'/standard',
                                       'provenance':'authored_answer_probe','text':o['incomplete_answer'],'verdict':v})
                assert Session(sid,entry,catalog).get_state()==records[sid]['post_history_state']
    replay_rows=list(rows.values())
    result={'created_utc':datetime.now(timezone.utc).isoformat(),'replay_wall_seconds':perf_counter()-start,
            'declared_volatile_fields':['created_utc','replay_wall_seconds'],'inventory':inventory,
            'provenance':{**provenance,'archive':str(archive),'allowlisted_members':[provenance['runtime_root']+f for f in files]+[provenance['catalog_member']]},
            'scenarios':records,'replays':replay_rows,'answer_probes':probes,
            'status':{'new_scenarios':len(records),'upgraded_existing':0,'trace_verdicts':dict(Counter(r['verdict']['trace_verdict'] for r in replay_rows)),
                      'lookup_coverage':dict(Counter(r['trace_case'] for r in replay_rows)),
                      'answer_probe_verdicts':dict(Counter(p['verdict']['answer_verdict'] for p in probes)),
                      'exportable':False,'execution_verified':0}}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(result['status'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,default=ARCHIVE)
    parser.add_argument('--output',type=Path,default=OUTPUT)
    parser.add_argument('--pilot',action='store_true')
    args=parser.parse_args();run(args.archive,args.output,args.pilot)
