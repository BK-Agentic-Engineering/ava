"""Focused synthetic gold/scope regressions; no organizer data or runtime needed."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

import yaml

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from replay_train_wave_02 import ROOT, StrictLoader, fixture, validate, verify


class Wave02Tests(unittest.TestCase):
    def setUp(self):
        self.docs = [yaml.load(p.read_text(encoding='utf-8'),Loader=StrictLoader)
                     for p in sorted((ROOT/'data/synthetic/design').glob('*.yaml'))]
        self.design = next(d for d in self.docs if d['version']=='train_wave_02')
        self.sm = {s['scenario_id']:s for s in self.design['scenarios']}
        self.wm = {w['world_id']:w for w in self.design['worlds']}
        reads = ['package_tracking.track','robot_vacuum.get_status','alarm.list']
        self.kinds = {t:'meta' if t=='sys.ask_missing_info' else 'read' if t in reads else 'write'
                      for w in self.wm.values() for t in w['relevant_tools']}

    def initial(self,sid):
        s = self.sm[sid]
        return fixture(self.wm[s['world_id']],s)

    def call(self,name,args,result=None):
        return {'name':name,'arguments':deepcopy(args),'result':result or {'ok':True}}

    def test_execute_ask_contrast_is_one_history_fact(self):
        a,b = self.sm['TR2_P_HISTORY'],self.sm['TR2_P_ASK']
        visible = deepcopy(a['agent_visible']); visible['history'] = b['agent_visible']['history']
        self.assertEqual(visible,b['agent_visible'])
        self.assertEqual(self.initial(a['scenario_id']),self.initial(b['scenario_id']))
        self.assertNotEqual(a['agent_visible']['history'][0]['text'],b['agent_visible']['history'][0]['text'])
        ask = self.call('sys.ask_missing_info',b['oracle_draft']['ask'])
        initial = self.initial(b['scenario_id'])
        self.assertEqual(verify(initial,b,[ask],initial,self.kinds)['verdict'],'pass')
        self.assertIn('clarification_target_or_necessity',verify(initial,a,[ask],initial,self.kinds)['trace'])

    def test_valid_guessed_pickup_still_fails_missing_case(self):
        s = self.sm['TR2_P_ASK']; initial = self.initial(s['scenario_id']); final = deepcopy(initial)
        args = {'address':'18 ngõ Chồi, phường Vườn','date':'2026-12-22'}
        final['package_tracking']['pickups'].append({'id':'unit_pick',**args,'status':'scheduled'})
        result = verify(initial,s,[self.call('package_tracking.schedule_pickup',args)],final,self.kinds)
        self.assertIn('authorized_writes',result['trace'])
        self.assertIn('pickup_payload_or_count',result['state'])

    def test_wrong_missing_parameter_rejected(self):
        s = self.sm['TR2_P_ASK']; initial = self.initial(s['scenario_id'])
        call = self.call('sys.ask_missing_info',{'tool_name':'package_tracking.schedule_pickup','params':['date']})
        self.assertEqual(verify(initial,s,[call],initial,self.kinds)['trace'],['clarification_target_or_necessity'])

    def test_omitted_configured_mode_and_observed_explicit_mode(self):
        s = self.sm['TR2_V_INHERIT']; initial = self.initial(s['scenario_id']); final = deepcopy(initial)
        final['robot_vacuum']['status'] = 'cleaning'
        final['robot_vacuum']['current_job'] = {'rooms':['phòng dệt'],'whole_house':False,'mode':'mop'}
        write = self.call('robot_vacuum.start',{'rooms':['phòng dệt']})
        self.assertEqual(verify(initial,s,[write],final,self.kinds)['verdict'],'pass')
        write['arguments']['mode'] = 'mop'
        self.assertEqual(verify(initial,s,[write],final,self.kinds)['grounding'],['observation_before_consuming_write'])
        read = self.call('robot_vacuum.get_status',{}, {'ok':True,'mode':'mop','current_job':initial['robot_vacuum']['current_job']})
        self.assertEqual(verify(initial,s,[read,write],final,self.kinds)['verdict'],'pass')

    def test_split_alarm_fields_valid_repeat_changes_not_valid(self):
        s = self.sm['TR2_A_TIME_LABEL']; initial = self.initial(s['scenario_id']); final = deepcopy(initial)
        patch = s['oracle_draft']['effects']['updates']['tr2_alarm_17']
        final['alarm']['alarms'][0].update(patch)
        read = self.call('alarm.list',{}, {'ok':True,'alarms':initial['alarm']['alarms']})
        writes = [self.call('alarm.update',{'alarm_id':'tr2_alarm_17',k:v}) for k,v in patch.items()]
        self.assertEqual(verify(initial,s,[read,*writes],final,self.kinds)['verdict'],'pass')
        final['alarm']['alarms'][0]['repeat'] = 'once'
        self.assertEqual(verify(initial,s,[read,*writes],final,self.kinds)['state'],['goal_or_frame'])

    def test_disabled_alarm_not_silently_reenabled(self):
        s = self.sm['TR2_A_TIME_DISABLED']; initial = self.initial(s['scenario_id']); final = deepcopy(initial)
        final['alarm']['alarms'][0].update(time='2026-12-23T06:45:00+07:00',enabled=True)
        read = self.call('alarm.list',{}, {'ok':True,'alarms':initial['alarm']['alarms']})
        write = self.call('alarm.update',{'alarm_id':'tr2_alarm_17','time':'2026-12-23T06:45:00+07:00','enabled':True})
        result = verify(initial,s,[read,write],final,self.kinds)
        self.assertEqual(result['state'],['goal_or_frame'])
        self.assertEqual(result['trace'],['authorized_writes'])

    def test_hidden_alarm_ID_fails_with_correct_state(self):
        s = self.sm['TR2_A_DISABLE']; initial = self.initial(s['scenario_id']); final = deepcopy(initial)
        final['alarm']['alarms'][0]['enabled'] = False
        write = self.call('alarm.update',{'alarm_id':'tr2_alarm_17','enabled':False})
        result = verify(initial,s,[write],final,self.kinds)
        self.assertFalse(result['state'])
        self.assertEqual(result['grounding'],['observation_before_consuming_write'])

    def test_future_train_descendant_and_repeated_request_allowed(self):
        world = self.design['worlds'][0]; scenario = self.design['scenarios'][0]
        extra = {'version':'future_unit_only',
                 'worlds':[{'world_id':'UNIT_FUTURE_WORLD','lineage_id':world['lineage_id'],'split':'train','variants':{},
                            'ancestry':{'parent_world_ids':[world['world_id']],'parent_scenario_ids':[scenario['scenario_id']],'parent_lineage_ids':[world['lineage_id']]}}],
                 'scenarios':[{'scenario_id':'UNIT_FUTURE_SCENARIO','world_id':'UNIT_FUTURE_WORLD','lineage_id':world['lineage_id'],
                               'fixture_variant':'base','status':'other_status','exportable':True,'agent_visible':deepcopy(scenario['agent_visible']),
                               'contrast':{'with':scenario['scenario_id']}}]}
        result = validate(self.design,[*self.docs,extra])
        self.assertEqual(result['scenarios_by_split']['train'],sum(len(d['scenarios']) for d in self.docs if d.get('split')=='train')+1)

    def test_status_and_global_integrity_guards(self):
        self.design['scenarios'][0]['exportable'] = True
        with self.assertRaisesRegex(AssertionError,'Wave 02 scenario status'): validate(self.design,self.docs)
        self.design['scenarios'][0]['exportable'] = False
        self.design['worlds'][0]['ancestry']['parent_world_ids'] = ['W_RIDES']
        with self.assertRaisesRegex(AssertionError,'cross-split ancestry'): validate(self.design,self.docs)
        self.design['worlds'][0]['ancestry']['parent_world_ids'] = []
        unrelated = next(d for d in self.docs if d['version']=='train_wave_01')
        unrelated['scenarios'][0]['contrast']['with'] = 'NO_SUCH_SCENARIO'
        with self.assertRaisesRegex(AssertionError,'broken reference'): validate(self.design,self.docs)

    def test_duplicate_id_in_unrelated_design_still_rejected(self):
        unrelated = next(d for d in self.docs if d['version']=='train_wave_01')
        unrelated['scenarios'].append(deepcopy(unrelated['scenarios'][0]))
        with self.assertRaisesRegex(AssertionError,'duplicate ID'): validate(self.design,self.docs)

    def test_whole_house_defaults_and_explicit_inventory_grounding(self):
        s = self.sm['TR2_V_ALL']; initial = self.initial(s['scenario_id'])
        rooms = initial['robot_vacuum']['rooms']; final = deepcopy(initial)
        final['robot_vacuum']['current_job'] = {'rooms':rooms[:],'whole_house':True,'mode':'both'}
        for args in [{'mode':'both'},{'mode':'both','rooms':[]}]:
            self.assertEqual(verify(initial,s,[self.call('robot_vacuum.start',args)],final,self.kinds)['verdict'],'pass')
        final['robot_vacuum']['current_job']['whole_house'] = False
        read = self.call('robot_vacuum.get_status',{}, {'ok':True,'rooms':rooms[:]})
        for listed in [rooms[:],rooms[::-1]]:
            write = self.call('robot_vacuum.start',{'mode':'both','rooms':listed})
            self.assertEqual(verify(initial,s,[read,write],final,self.kinds)['verdict'],'pass')
            for calls in [[write],[write,read]]:
                result = verify(initial,s,calls,final,self.kinds)
                self.assertFalse(result['state'])
                self.assertEqual(result['grounding'],['whole_house_inventory_before_explicit_rooms'])
        write = self.call('robot_vacuum.start',{'mode':'both','rooms':rooms[:-1]})
        incomplete = deepcopy(final); incomplete['robot_vacuum']['current_job']['rooms'] = rooms[:-1]
        self.assertEqual(verify(initial,s,[read,write],incomplete,self.kinds)['verdict'],'reject')
        for result in [{'ok':False,'rooms':rooms},{'ok':True,'done':False,'rooms':rooms},{'ok':True,'rooms':rooms[:-1]}]:
            write = self.call('robot_vacuum.start',{'mode':'both','rooms':rooms[:]})
            self.assertEqual(verify(initial,s,[self.call('robot_vacuum.get_status',{},result),write],final,self.kinds)['verdict'],'reject')

    def test_user_named_room_can_start_directly(self):
        s = self.sm['TR2_V_ROOM']; initial = self.initial(s['scenario_id']); final = deepcopy(initial)
        final['robot_vacuum']['current_job'] = deepcopy(s['oracle_draft']['effects']['current_job'])
        write = self.call('robot_vacuum.start',{'rooms':['phòng dệt'],'mode':'vacuum'})
        self.assertEqual(verify(initial,s,[write],final,self.kinds)['verdict'],'pass')


if __name__ == '__main__':
    unittest.main()
