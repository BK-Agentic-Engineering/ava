"""Focused synthetic checks for fallback, credential permission and date grounding."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

import yaml

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from replay_train_wave_04 import ROOT, StrictLoader, fixture, validate, verify


class Wave04Tests(unittest.TestCase):
    def setUp(self):
        self.docs=[yaml.load(p.read_text(encoding='utf-8'),Loader=StrictLoader) for p in sorted((ROOT/'data/synthetic/design').glob('*.yaml'))]
        self.d=next(d for d in self.docs if d['version']=='train_wave_04');self.sm={s['scenario_id']:s for s in self.d['scenarios']};self.wm={w['world_id']:w for w in self.d['worlds']}
        reads=['bike_rental.find_bikes','door_lock.list_locks','fitness.get_activity']
        self.kinds={t:'read' if t in reads else 'meta' if t=='sys.ask_missing_info' else 'write' for w in self.wm.values() for t in w['relevant_tools']}

    def initial(self,sid):
        s=self.sm[sid];return fixture(self.wm[s['world_id']],s)

    def call(self,name,args,result=None):return {'name':name,'arguments':args,'result':result or {'ok':True}}

    def test_available_backup_does_not_override_preference_or_prohibition(self):
        for sid in ['TR4_B_PREFERRED','TR4_B_FORBID','TR4_B_LIMIT']:
            with self.subTest(sid=sid):
                s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
                final['bike_rental']['bikes'][1]['available']=False
                final['bike_rental']['reservations'].append({'id':'unit','bike_id':'tr4_bike_63','station':'Trạm Bờ Dâu','status':'reserved'})
                read=self.call('bike_rental.find_bikes',{}, {'ok':True,'bikes':initial['bike_rental']['bikes']})
                write=self.call('bike_rental.reserve',{'bike_id':'tr4_bike_63'})
                self.assertIn('authorized_action_or_count',verify(initial,s,[read,write],final,self.kinds)['trace'])

    def test_backup_observation_alone_does_not_prove_preferred_unavailable(self):
        sid='TR4_B_FALLBACK';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        final['bike_rental']['bikes'][1]['available']=False
        final['bike_rental']['reservations'].append({'id':'unit','bike_id':'tr4_bike_63','station':'Trạm Bờ Dâu','status':'reserved'})
        read=self.call('bike_rental.find_bikes',{'near':'Xe hoa lau'},{'ok':True,'bikes':[initial['bike_rental']['bikes'][1]]})
        write=self.call('bike_rental.reserve',{'bike_id':'tr4_bike_63'})
        result=verify(initial,s,[read,write],final,self.kinds)
        self.assertFalse(result['state']);self.assertIn('source_before_consuming_write',result['grounding'])

    def test_no_write_branch_still_needs_condition_observation(self):
        sid='TR4_B_FORBID';s=self.sm[sid];initial=self.initial(sid)
        self.assertIn('decision_observation_missing',verify(initial,s,[],initial,self.kinds)['grounding'])
        read=self.call('bike_rental.find_bikes',{}, {'ok':True,'bikes':[initial['bike_rental']['bikes'][0]]})
        self.assertEqual(verify(initial,s,[read],initial,self.kinds)['verdict'],'pass')

    def credential_case(self,sid,label=None):
        s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial);o=s['oracle_draft']
        lock=next(l for l in initial['door_lock']['locks'] if l['name']==o['lock'])
        payload={'lock_id':lock['id'],**o['credential']}
        if label is not None:payload['label']=label
        record={'id':'unit_guest','code':'123456',**payload};final['door_lock']['guest_codes'].append(record)
        read=self.call('door_lock.list_locks',{}, {'ok':True,'locks':initial['door_lock']['locks']})
        grant=self.call('door_lock.grant_guest_code',payload,{'ok':True,'guest_code':deepcopy(record)})
        return s,initial,final,read,grant

    def test_credential_does_not_authorize_unlock(self):
        s,initial,final,read,grant=self.credential_case('TR4_G_CODE')
        self.assertEqual(verify(initial,s,[read,grant],final,self.kinds)['verdict'],'pass')
        final['door_lock']['locks'][0]['locked']=False
        write=self.call('door_lock.set_lock',{'lock_id':'tr4_lock_31','locked':False})
        self.assertIn('authorized_action_or_count',verify(initial,s,[read,grant,write],final,self.kinds)['trace'])

    def test_hidden_lock_correct_state_and_late_read_fail(self):
        s,initial,final,read,grant=self.credential_case('TR4_G_CODE')
        for calls in [[grant],[grant,read]]:
            result=verify(initial,s,calls,final,self.kinds)
            self.assertFalse(result['state']);self.assertIn('source_before_consuming_write',result['grounding'])

    def test_empty_label_equivalent_and_code_bound_to_response(self):
        s,initial,final,read,grant=self.credential_case('TR4_G_UNLABELLED',label='')
        self.assertEqual(verify(initial,s,[read,grant],final,self.kinds)['verdict'],'pass')
        final['door_lock']['guest_codes'][-1]['code']='999999'
        self.assertIn('generated_code_response_binding',verify(initial,s,[read,grant],final,self.kinds)['state'])

    def test_correct_latest_date_guess_does_not_prove_latest(self):
        sid='TR4_F_LATEST';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial);final['fitness']['goal_steps']=7800
        response={'ok':True,'activity':{'date':'2026-12-27','steps':7800}}
        explicit=self.call('fitness.get_activity',{'date':'2026-12-27'},response)
        default=self.call('fitness.get_activity',{},response);write=self.call('fitness.set_goal',{'steps':7800})
        for calls in [[explicit,write],[explicit,write,default]]:
            result=verify(initial,s,calls,final,self.kinds)
            self.assertFalse(result['state']);self.assertIn('activity_source_before_goal',result['grounding'])
        self.assertEqual(verify(initial,s,[default,explicit,write],final,self.kinds)['verdict'],'pass')

    def test_today_zero_branch_cannot_be_justified_by_other_day(self):
        sid='TR4_F_TODAY';s=self.sm[sid];initial=self.initial(sid)
        wrong=self.call('fitness.get_activity',{}, {'ok':True,'activity':{'date':'2026-12-27','steps':7800}})
        self.assertIn('activity_decision_observation_missing',verify(initial,s,[wrong],initial,self.kinds)['grounding'])
        correct=self.call('fitness.get_activity',{'date':'2026-12-28'},{'ok':True,'activity':{'date':'2026-12-28','steps':0}})
        self.assertEqual(verify(initial,s,[correct],initial,self.kinds)['verdict'],'pass')

    def test_workout_now_default_and_explicit_visible_time_equivalent(self):
        sid='TR4_F_LOG_NOW';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        payload=s['oracle_draft']['workouts'][0];final['fitness']['workouts'].append({'id':'unit',**payload})
        for args in [{'type':'walking','minutes':25},payload]:
            self.assertEqual(verify(initial,s,[self.call('fitness.log_workout',args)],final,self.kinds)['verdict'],'pass')

    def test_scoped_validation_allows_future_train_descendant(self):
        w=self.d['worlds'][0];s=self.d['scenarios'][0]
        extra={'version':'future_unit_only','worlds':[{'world_id':'unit_future','lineage_id':w['lineage_id'],'split':'train','variants':{},
                'ancestry':{'parent_world_ids':[w['world_id']],'parent_scenario_ids':[s['scenario_id']],'parent_lineage_ids':[w['lineage_id']]}}],
               'scenarios':[{'scenario_id':'unit_future_s','world_id':'unit_future','lineage_id':w['lineage_id'],'fixture_variant':'base','status':'future','exportable':True,
                             'agent_visible':deepcopy(s['agent_visible']),'contrast':{'with':s['scenario_id']}}]}
        result=validate(self.d,[*self.docs,extra]);self.assertEqual(result['scenarios_by_split']['train'],sum(len(d['scenarios']) for d in self.docs if d.get('split')=='train')+1)
        self.sm['TR4_B_PREFERRED']['exportable']=True
        with self.assertRaisesRegex(AssertionError,'Wave 04 scenario status'):validate(self.d,self.docs)


if __name__=='__main__':unittest.main()
