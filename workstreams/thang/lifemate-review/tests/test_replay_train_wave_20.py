"""Wave 20 source, context, preservation and final-answer regressions."""
from copy import deepcopy
import json
import importlib
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from replay_train_wave_20 import ARCHIVE,DESIGN,OUTPUT,load_design,observe_fact,retrieval_dates,verify
from replay_train_wave_19 import fact_value


class Wave20Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design=load_design(DESIGN)
        cls.scenarios={s['scenario_id']:s for s in cls.design['scenarios']}
        cls.evidence=json.loads(OUTPUT.read_text(encoding='utf8'))
        cls.rows={(r['scenario_id'],r['trace_case']):r for r in cls.evidence['replays']}
        cls.kinds={name:'read' if name.endswith(('.search','.get','.list','.list_events','.get_balance','.list_transactions','.list_beneficiaries')) else 'write' for w in cls.design['worlds'] for name in w['relevant_tools']}

    def test_every_new_standard_passes_and_preserves_existing_records(self):
        self.assertEqual(len(self.scenarios),26)
        for sid,s in self.scenarios.items():
            row=self.rows[sid,'standard'];initial=self.evidence['scenarios'][sid]['post_history_state']
            self.assertEqual(row['verdict']['overall'],'pass')
            if s['oracle_draft'].get('note'):
                self.assertEqual(row['final_state']['notes']['notes'][:-1],initial['notes']['notes'])
                self.assertEqual({k:v for k,v in row['final_state'].items() if k!='notes'}, {k:v for k,v in initial.items() if k!='notes'})
            else:self.assertEqual(row['final_state'],initial)

    def test_visible_history_is_actual_paired_execution(self):
        for sid,r in self.evidence['scenarios'].items():
            calls=[{**c,'result':result} for t in r['agent_visible']['history'] if t['role']=='assistant'
                   for c,result in zip(t['tool_calls'],t['tool_results'],strict=True)]
            self.assertEqual(calls,r['historical_calls'])
            self.assertEqual(self.scenarios[sid]['agent_visible']['history'],[])
        self.assertEqual(sum(len(r['historical_calls']) for r in self.evidence['scenarios'].values()),68)

    def test_contact_old_and_current_use_different_moments(self):
        for suffix,value in [('OLD','tram.cu@lat.example.test'),('CURRENT','tram.moi@lat.example.test'),('OLD_CHANGED','tram.bantruoc@lat.example.test')]:
            self.assertEqual(self.rows['TR20_CONTACT_'+suffix,'standard']['verdict']['observed_facts'][0][1],value)
        sid='TR20_CONTACT_CURRENT';row=self.rows[sid,'standard'];r=self.evidence['scenarios'][sid]
        v=verify(self.scenarios[sid],r['agent_visible'],r['post_history_state'],[],row['final_state'],row['authored_final_text'],self.kinds)
        self.assertEqual(v['trace_verdict'],'fail')
        self.assertEqual(v['answer_verdict'],'unresolved')

    def test_declared_contact_source_contrast_changes_only_old_email(self):
        a,b=(self.evidence['scenarios']['TR20_CONTACT_'+suffix] for suffix in ['OLD','OLD_CHANGED'])
        left,right=deepcopy(a['pre_history_state']),deepcopy(b['pre_history_state'])
        first=next(r for r in left['contacts']['contacts'] if r['name']=='Nguyễn Diệp Trâm')
        second=next(r for r in right['contacts']['contacts'] if r['name']=='Nguyễn Diệp Trâm')
        self.assertNotEqual(first.pop('email'),second.pop('email'))
        self.assertEqual(left,right)
        self.assertEqual(a['post_history_state'],b['post_history_state'])
        self.assertEqual(self.scenarios['TR20_CONTACT_OLD']['agent_visible'],
                         self.scenarios['TR20_CONTACT_OLD_CHANGED']['agent_visible'])

    def test_calendar_context_only_changes_gold_and_not_history(self):
        a,b,c=(self.evidence['scenarios']['TR20_CAL_'+suffix] for suffix in ['TODAY_EVENING','TODAY_MORNING','TODAY_UTC'])
        for left,right,field in [(a,b,'current_time'),(b,c,'timezone')]:
            lv,rv=deepcopy(left['agent_visible']),deepcopy(right['agent_visible'])
            self.assertNotEqual(lv['context'].pop(field),rv['context'].pop(field))
            self.assertEqual(lv,rv)
            self.assertEqual(left['post_history_state'],right['post_history_state'])
        self.assertEqual([self.rows['TR20_CAL_'+suffix,'standard']['verdict']['observed_facts'][0][1] for suffix in ['TODAY_EVENING','TODAY_MORNING','TODAY_UTC']],['2028-02-10T20:00:00+07:00','2028-02-11T09:00:00+07:00','2028-02-10T20:00:00+07:00'])

    def test_ledger_needs_observed_account_identity_and_equivalent_note_passes(self):
        sid='TR20_BANK_LEDGER';row=self.rows[sid,'standard'];r=self.evidence['scenarios'][sid]
        visible=deepcopy(r['agent_visible']);visible['history'][1]['tool_results']=[]
        result=verify(self.scenarios[sid],visible,r['post_history_state'],row['calls'],row['final_state'],row['authored_final_text'],self.kinds)
        self.assertEqual(result['trace_verdict'],'fail')
        self.assertEqual(self.rows['TR20_BANK_NOTE_LEDGER','equivalent_note']['verdict']['overall'],'pass')

    def test_wrong_write_and_wrong_answer_are_independent(self):
        for sid in self.scenarios:
            wrong=self.rows[sid,'wrong_write']['verdict']
            self.assertEqual(wrong['trace_verdict'],'fail')
        p=self.evidence['answer_probes']
        self.assertEqual(sum(x['probe']=='wrong' and x['verdict']['answer_verdict']=='fail' for x in p),26)
        self.assertEqual(sum(x['provenance']=='modified_evidence_verifier_probe' for x in p),26)

    def test_all_note_cases_accept_reviewed_meaning_preserving_contents(self):
        for sid,s in self.scenarios.items():
            if not s['oracle_draft'].get('note'):continue
            row=self.rows[sid,'equivalent_note'];standard=self.rows[sid,'standard']
            self.assertEqual(row['verdict']['overall'],'pass')
            self.assertNotEqual(row['calls'][-1]['arguments']['content'],standard['calls'][-1]['arguments']['content'])
            self.assertEqual(row['final_state']['notes']['notes'][:-1],standard['final_state']['notes']['notes'][:-1])

    def test_unrecognized_note_prose_requires_review_without_weakening_state_checks(self):
        sid='TR20_CONTACT_NOTE_OLD';r=self.evidence['scenarios'][sid];row=self.rows[sid,'standard']
        calls=deepcopy(row['calls']);final=deepcopy(row['final_state'])
        content='Địa chỉ trước lần sửa: tram.cu@lat.example.test'
        calls[0]['arguments']['content']=content;calls[0]['result']['item']['content']=content
        final['notes']['notes'][-1]['content']=content
        v=verify(self.scenarios[sid],r['agent_visible'],r['post_history_state'],calls,final,row['authored_final_text'],self.kinds)
        self.assertEqual((v['trace_verdict'],v['overall']),('unresolved','unresolved'))
        self.assertEqual(v['trace_reasons'],['note_content_requires_review'])
        # This is a modified-state verifier probe, never an actual SDK trace.
        final['notes']['notes'][0]['content']='Damage'
        self.assertEqual(verify(self.scenarios[sid],r['agent_visible'],r['post_history_state'],calls,final,
            row['authored_final_text'],self.kinds)['trace_verdict'],'fail')

    def test_modified_response_ambiguity_and_changed_source_do_not_use_gold_selector(self):
        sid='TR20_CAL_TODAY_ROOM';row=self.rows[sid,'standard'];r=self.evidence['scenarios'][sid]
        calls=deepcopy(row['calls'])
        target=next(e for e in calls[0]['result']['events'] if e['title']=='Kiểm nan' and e['start'].startswith('2028-02-11'))
        calls[0]['result']['events'].append({**target,'id':'probe_other','location':'Phòng Khác'})
        v=verify(self.scenarios[sid],r['agent_visible'],r['post_history_state'],calls,row['final_state'],row['authored_final_text'],self.kinds)
        self.assertEqual(v['trace_reasons'],['evidence_ambiguous'])
        calls[0]['result']['events'].pop();target['location']='Phòng Khác'
        v=verify(self.scenarios[sid],r['agent_visible'],r['post_history_state'],calls,row['final_state'],row['authored_final_text'],self.kinds)
        self.assertEqual((v['trace_verdict'],v['answer_reason']),('pass','source_mismatch'))

    def test_no_observed_value_is_its_own_selector(self):
        for s in self.scenarios.values():
            for f in s['oracle_draft']['facts']:
                if f['operation']=='field':self.assertNotIn(f['path'][0],f['match'])

    def test_modified_response_calendar_day_uses_context_timezone(self):
        sid='TR20_CAL_TODAY_UTC';r=self.evidence['scenarios'][sid]
        spec={'tool':'calendar.list_events','collection':'events','operation':'count',
              'match':{'title':'Kiểm nan'},'relative_day':0,'complete':True,'scope':{}}
        event={'id':'boundary_probe','title':'Kiểm nan','start':'2028-02-11T01:00:00+07:00'}
        call={'name':'calendar.list_events','arguments':{},'result':{'ok':True,'events':[event]}}
        self.assertEqual(observe_fact(spec,r['agent_visible'],[call]),('supported',1))
        # A raw-prefix query for February 10 cannot establish the whole UTC day.
        call['arguments']={'date_from':'2028-02-10','date_to':'2028-02-10'}
        self.assertEqual(observe_fact(spec,r['agent_visible'],[call]),('missing',None))
        call['arguments']={'date_from':'2028-02-08','date_to':'2028-02-12'}
        self.assertEqual(observe_fact(spec,r['agent_visible'],[call]),('supported',1))
        call['result']['events'][0]['start']='2028-02-10T01:00:00+07:00'
        self.assertEqual(observe_fact(spec,r['agent_visible'],[call]),('supported',0))

    def test_modified_response_selection_does_not_convert_answer_value(self):
        sid='TR20_CAL_TODAY_UTC';r=self.evidence['scenarios'][sid]
        spec=deepcopy(self.scenarios[sid]['oracle_draft']['facts'][0])
        event={'id':'boundary_probe','title':'Kiểm nan','start':'2028-02-11T01:00:00+07:00'}
        call={'name':'calendar.list_events','arguments':{},'result':{'ok':True,'events':[event]}}
        self.assertEqual(observe_fact(spec,r['agent_visible'],[call]),('supported',event['start']))

    def test_modified_response_empty_collection_is_not_missing_collection(self):
        sid='TR20_CAL_TOMORROW';s=self.scenarios[sid];r=self.evidence['scenarios'][sid]
        row=self.rows[sid,'standard']
        for result in [{'ok':True}, {'ok':True,'events':None}, {'ok':True,'events':{}},
                       {'ok':True,'events':'[]'}, {'ok':True,'events':[None]}]:
            calls=[{'name':'calendar.list_events','arguments':{},'result':result}]
            v=verify(s,r['agent_visible'],r['post_history_state'],calls,row['final_state'],'0 buổi',self.kinds)
            self.assertEqual((v['trace_verdict'],v['answer_verdict']),('fail','unresolved'))
        calls=[{'name':'calendar.list_events','arguments':{},'result':{'ok':True,'events':[]}}]
        self.assertEqual(verify(s,r['agent_visible'],r['post_history_state'],calls,row['final_state'],
            '0 buổi',self.kinds)['overall'],'pass')

    def test_modified_response_utc_sufficient_bounds(self):
        from datetime import date
        self.assertEqual(retrieval_dates(date(2028,2,10),'UTC'),('2028-02-09','2028-02-11'))
        sid='TR20_CAL_TODAY_UTC';r=self.evidence['scenarios'][sid]
        spec=self.scenarios[sid]['oracle_draft']['facts'][0]
        event={'id':'boundary_probe','title':'Kiểm nan','start':'2028-02-11T01:00:00+07:00'}
        call={'name':'calendar.list_events','arguments':{'date_from':'2028-02-09','date_to':'2028-02-11'},
              'result':{'ok':True,'events':[event]}}
        self.assertEqual(observe_fact(spec,r['agent_visible'],[call]),('supported',event['start']))
        call['arguments']['date_to']='2028-02-10'
        self.assertEqual(observe_fact(spec,r['agent_visible'],[call]),('missing',None))

    def test_actual_sdk_date_scope_and_current_contact_get(self):
        provenance=self.design['provenance']
        with tempfile.TemporaryDirectory(dir=OUTPUT.parent) as directory:
            root=Path(directory)
            with zipfile.ZipFile(ARCHIVE) as archive:
                for member in ['__init__.py','executor.py','validate.py','utils.py',
                               'apps/__init__.py','apps/base.py','apps/sys.py','apps/calendar.py','apps/contacts.py']:
                    path=root/'zaic_tools'/member;path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_bytes(archive.read(provenance['runtime_root']+member))
                catalog=json.loads(archive.read(provenance['catalog_member']))
            self.assertNotIn('zaic_tools',sys.modules)
            sys.path.insert(0,directory)
            try:
                Session=importlib.import_module('zaic_tools.executor').Session
                sid='TR20_CAL_TODAY_UTC';r=self.evidence['scenarios'][sid]
                state=deepcopy(r['post_history_state'])
                state['calendar']['events']=[{'id':'boundary_probe','title':'Kiểm nan',
                    'start':'2028-02-11T01:00:00+07:00','end':'2028-02-11T02:00:00+07:00','status':'confirmed'}]
                session=Session('audit_boundary',{**state,'_meta':{'tools':['calendar.list_events'],
                    'current_time':r['agent_visible']['context']['current_time']}},catalog)
                narrow=session.call('calendar.list_events',{'date_from':'2028-02-10','date_to':'2028-02-10'})
                self.assertEqual(narrow['events'],[])
                broad=session.call('calendar.list_events',{})
                self.assertEqual(len(broad['events']),1)
                spec=self.scenarios[sid]['oracle_draft']['facts'][0]
                self.assertEqual(observe_fact(spec,r['agent_visible'],session.log),('supported',state['calendar']['events'][0]['start']))
                # Actual SDK diagnostic, not a modified-response probe: both
                # opposite-offset boundaries fall in February 10 UTC.
                state['calendar']['events'].append({'id':'early_boundary','title':'Other',
                    'start':'2028-02-09T23:30:00-01:00','end':'2028-02-10T00:30:00-01:00'})
                session=Session('audit_bounds',{**state,'_meta':{'tools':['calendar.list_events'],
                    'current_time':r['agent_visible']['context']['current_time']}},catalog)
                complete=session.call('calendar.list_events',{'date_from':'2028-02-09','date_to':'2028-02-11'})
                self.assertEqual({x['id'] for x in complete['events']},{'boundary_probe','early_boundary'})
                self.assertEqual(observe_fact(spec,r['agent_visible'],session.log),('supported',state['calendar']['events'][0]['start']))
                session.call('calendar.list_events',{'date_from':'2028-02-09','date_to':'2028-02-10'})
                self.assertEqual(observe_fact(spec,r['agent_visible'],session.log[-1:]),('missing',None))
                sid='TR20_CONTACT_CURRENT';r=self.evidence['scenarios'][sid]
                session=Session('audit_get',{**r['post_history_state'],'_meta':{'tools':r['agent_visible']['allowed_tools'],
                    'current_time':r['agent_visible']['context']['current_time']}},catalog)
                # This ID is present in the real visible historical search.
                result=session.call('contacts.get',{'contact_id':'w20_tram'})
                self.assertEqual(result['contacts'][0]['email'],'tram.moi@lat.example.test')
                # The former search-only path rejected this actual SDK response.
                self.assertEqual(fact_value(self.scenarios[sid]['oracle_draft']['facts'][0],session.log),('missing',None))
                row=self.rows[sid,'standard']
                self.assertEqual(verify(self.scenarios[sid],r['agent_visible'],r['post_history_state'],
                    session.log,session.get_state(),row['authored_final_text'],self.kinds)['overall'],'pass')
            finally:
                sys.path.remove(directory)
                for name in tuple(sys.modules):
                    if name=='zaic_tools' or name.startswith('zaic_tools.'):del sys.modules[name]


if __name__=='__main__':unittest.main()
