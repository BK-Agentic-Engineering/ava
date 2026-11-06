"""Concrete source, additive-count, default and idempotency risks; synthetic data only."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

import yaml

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from replay_train_wave_07 import ROOT, StrictLoader, fixture, validate, verify


class Wave07Tests(unittest.TestCase):
    def setUp(self):
        self.docs=[yaml.load(p.read_text(encoding='utf-8'),Loader=StrictLoader) for p in sorted((ROOT/'data/synthetic/design').glob('*.yaml'))]
        self.d=next(d for d in self.docs if d['version']=='train_wave_07');self.sm={s['scenario_id']:s for s in self.d['scenarios']};self.wm={w['world_id']:w for w in self.d['worlds']}
        reads=['flights.search','flights.my_bookings','chat_ott.list_chats','chat_ott.read_chat','medication.list']
        self.kinds={t:'read' if t in reads else 'meta' if t=='sys.ask_missing_info' else 'write' for w in self.wm.values() for t in w['relevant_tools']}

    def initial(self,sid):
        s=self.sm[sid];return fixture(self.wm[s['world_id']],s)

    def call(self,name,args,result=None):return {'name':name,'arguments':args,'result':result or {'ok':True}}

    def test_null_optional_alternatives_and_non_equivalent_requests(self):
        path=ROOT/'artifacts/synthetic/train_wave_07_replay/replay.json'
        evidence=json.loads(path.read_text(encoding='utf-8'))
        rows={(r['scenario_id'],r['trace_case'],r['ordering']):r for r in evidence['replays']}
        cases=[
            ('TR7_F_EARLY','null_seat_class','seat_class','TR7_F_BUSINESS'),
            ('TR7_C_VOICE','null_video','video','TR7_C_VIDEO'),
            ('TR7_D_DAILY','null_days','days','TR7_D_WEEKDAYS'),
            ('TR7_D_UNTIMED','null_time','time',None),
        ]
        for sid, trace, field, distinct in cases:
            with self.subTest(field=field):
                record=rows[sid,trace,'original']
                initial={k:v for k,v in evidence['fixtures'][record['initial_fixture_ref']].items() if k!='_meta'}
                calls=deepcopy(record['calls'])
                final=record['final_state']
                self.assertIn(field,calls[-1]['arguments'])
                self.assertIsNone(calls[-1]['arguments'][field])
                self.assertEqual(final,rows[sid,'standard','original']['final_state'])
                self.assertEqual(verify(initial,self.sm[sid],calls,final,self.kinds)['verdict'],'pass')
                if distinct:
                    rejected=verify(initial,self.sm[distinct],calls,final,self.kinds)
                else:
                    calls[-1]['arguments']['time']=self.sm[sid]['agent_visible']['context']['current_time']
                    rejected=verify(initial,self.sm[sid],calls,final,self.kinds)
                self.assertIn('authorized_action_or_count',rejected['authorization'])

    def test_optimum_needs_comparison_but_explicit_number_needs_identity(self):
        sid='TR7_F_EARLY';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        final['flights']['bookings'].append({'id':'unit','flight_id':'tr7_flight_21','passengers':2,'seat_class':'economy','status':'confirmed'})
        chosen=next(r for r in initial['flights']['flights'] if r['id']=='tr7_flight_21')
        # Verifier-only partial projection, not a claim of actual search filtering.
        partial=self.call('flights.search',{'origin':'SGN','destination':'DAD','date':'2027-01-20'},{'ok':True,'flights':[chosen]})
        write=self.call('flights.book',{'flight_id':'tr7_flight_21','passengers':2})
        self.assertIn('flight_selection_before_booking',verify(initial,s,[partial,write],final,self.kinds)['grounding'])
        self.assertEqual(verify(initial,self.sm['TR7_F_EXPLICIT'],[partial,write],final,self.kinds)['verdict'],'pass')
        full=self.call('flights.search',{}, {'ok':True,'flights':initial['flights']['flights'][:3]})
        self.assertEqual(verify(initial,s,[full,write],final,self.kinds)['verdict'],'pass')
        self.assertIn('flight_selection_before_booking',verify(initial,s,[write,full],final,self.kinds)['grounding'])

    def test_business_is_not_default_economy(self):
        sid='TR7_F_BUSINESS';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        final['flights']['bookings'].append({'id':'unit','flight_id':'tr7_flight_21','passengers':2,'seat_class':'economy','status':'confirmed'})
        read=self.call('flights.search',{}, {'ok':True,'flights':initial['flights']['flights'][:3]})
        write=self.call('flights.book',{'flight_id':'tr7_flight_21','passengers':2})
        self.assertIn('authorized_action_or_count',verify(initial,s,[read,write],final,self.kinds)['authorization'])

    def test_forward_content_needs_bound_source_read_before_send(self):
        sid='TR7_C_FORWARD';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        content=s['oracle_draft']['content'];final['chat_ott']['chats'][1]['messages'].append({'from':'me','content':content})
        metadata=[{k:v for k,v in r.items() if k!='messages'} for r in initial['chat_ott']['chats']]
        listing=self.call('chat_ott.list_chats',{}, {'ok':True,'chats':metadata})
        source=self.call('chat_ott.read_chat',{'chat_id':'tr7_chat_25','limit':1},{'ok':True,'messages':[initial['chat_ott']['chats'][0]['messages'][-1]]})
        write=self.call('chat_ott.send_message',{'chat_id':'tr7_chat_68','content':content})
        self.assertEqual(verify(initial,s,[listing,source,write],final,self.kinds)['verdict'],'pass')
        for calls in [[listing,write],[source,listing,write],[listing,write,source]]:
            result=verify(initial,s,calls,final,self.kinds);self.assertFalse(result['state']);self.assertIn('source_content_before_forward',result['grounding'])

    def test_voice_default_and_location_type(self):
        sid='TR7_C_VOICE';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        final['chat_ott']['calls'].append({'id':'unit','chat_id':'tr7_chat_68','video':False,'status':'dialing'})
        listing=self.call('chat_ott.list_chats',{}, {'ok':True,'chats':[{k:v for k,v in r.items() if k!='messages'} for r in initial['chat_ott']['chats']]})
        write=self.call('chat_ott.call',{'chat_id':'tr7_chat_68'})
        self.assertEqual(verify(initial,s,[listing,write],final,self.kinds)['verdict'],'pass')
        loc=self.sm['TR7_C_LOCATION'];final=deepcopy(initial);final['chat_ott']['chats'][1]['messages'].append({'from':'me','content':'Vị trí hiện tại'})
        text=self.call('chat_ott.send_message',{'chat_id':'tr7_chat_68','content':'Vị trí hiện tại'})
        self.assertIn('message_types_payload_or_count',verify(initial,loc,[listing,text],final,self.kinds)['state'])

    def test_medication_untimed_is_not_current_time_default(self):
        sid='TR7_D_UNTIMED';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        final['medication']['logs'].append({'schedule_id':'tr7_med_31','time':None})
        read=self.call('medication.list',{}, {'ok':True,'schedules':initial['medication']['schedules']})
        write=self.call('medication.log_taken',{'schedule_id':'tr7_med_31'})
        self.assertEqual(verify(initial,s,[read,write],final,self.kinds)['verdict'],'pass')
        write['arguments']['time']=s['agent_visible']['context']['current_time']
        self.assertIn('authorized_action_or_count',verify(initial,s,[read,write],final,self.kinds)['authorization'])

    def test_redundant_remove_semantics_separate_from_official_matching(self):
        sid='TR7_D_REMOVE';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        final['medication']['schedules']=final['medication']['schedules'][1:]
        read=self.call('medication.list',{}, {'ok':True,'schedules':initial['medication']['schedules']})
        first=self.call('medication.remove',{'schedule_id':'tr7_med_31'})
        repeat=self.call('medication.remove',{'schedule_id':'tr7_med_31'},{'ok':True,'done':False,'message':'already absent'})
        result=verify(initial,s,[read,first,repeat],final,self.kinds)
        self.assertEqual(result['verdict'],'pass');self.assertTrue(result['trace_policy_notes']);self.assertEqual(result['official_call_matching'],'not_evaluated')
        self.assertEqual(final['medication']['logs'],initial['medication']['logs'])

    def test_schedule_time_set_order_and_daily_default(self):
        sid='TR7_D_TWICE';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        final['medication']['schedules'].append({'id':'unit','name':'Viên Cam','times':['21:00','09:00'],'days':'daily'})
        write=self.call('medication.add',{'name':'Viên Cam','times':['21:00','09:00']})
        self.assertEqual(verify(initial,s,[write],final,self.kinds)['verdict'],'pass')

    def test_additive_duplicate_log_not_idempotent(self):
        sid='TR7_D_LOG';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        payload={'schedule_id':'tr7_med_31','time':s['oracle_draft']['log']};final['medication']['logs'].extend([payload,payload])
        read=self.call('medication.list',{}, {'ok':True,'schedules':initial['medication']['schedules']});write=self.call('medication.log_taken',payload)
        self.assertIn('authorized_action_or_count',verify(initial,s,[read,write,write],final,self.kinds)['authorization'])

    def test_train_derivatives_and_future_scope(self):
        validate(self.d,self.docs);w=self.d['worlds'][0];s=self.sm['TR7_F_EARLY']
        extra={'version':'unit_future','worlds':[{'world_id':'unit_future_w','lineage_id':w['lineage_id'],'split':'train','variants':{},'ancestry':{'parent_world_ids':[w['world_id']],'parent_scenario_ids':[s['scenario_id']],'parent_lineage_ids':[w['lineage_id']]}}],
               'scenarios':[{'scenario_id':'unit_future_s','world_id':'unit_future_w','lineage_id':w['lineage_id'],'fixture_variant':'base','status':'future','exportable':True,'agent_visible':deepcopy(s['agent_visible'])}]}
        validate(self.d,[*self.docs,extra])
        self.sm['TR7_F_EARLY']['exportable']=True
        with self.assertRaisesRegex(AssertionError,'Wave07 scenario status'):validate(self.d,self.docs)


if __name__=='__main__':unittest.main()
