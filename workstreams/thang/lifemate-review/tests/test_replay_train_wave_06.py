"""Focused synthetic source-transform, upsert and cumulative-progress regressions."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

import yaml

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from replay_train_wave_06 import ROOT, StrictLoader, fixture, validate, verify


class Wave06Tests(unittest.TestCase):
    def setUp(self):
        self.docs=[yaml.load(p.read_text(encoding='utf-8'),Loader=StrictLoader) for p in sorted((ROOT/'data/synthetic/design').glob('*.yaml'))]
        self.d=next(d for d in self.docs if d['version']=='train_wave_06');self.sm={s['scenario_id']:s for s in self.d['scenarios']};self.wm={w['world_id']:w for w in self.d['worlds']}
        reads=['home_energy.get_usage','calculator.calculate','maps.search_place','learning.list_courses']
        self.kinds={t:'read' if t in reads else 'meta' if t=='sys.ask_missing_info' else 'write' for w in self.wm.values() for t in w['relevant_tools']}

    def initial(self,sid):
        s=self.sm[sid];return fixture(self.wm[s['world_id']],s)

    def call(self,name,args,result=None):return {'name':name,'arguments':args,'result':result or {'ok':True}}

    def energy_read(self,initial,period):
        return self.call('home_energy.get_usage',{'period':period},{'ok':True,'period':period,'usage':initial['home_energy']['usage'][period],'alert_threshold_kwh':initial['home_energy']['alert_threshold_kwh']})

    def test_calculator_correct_result_not_source_evidence(self):
        sid='TR6_E_MONTH';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial);final['home_energy']['alert_threshold_kwh']=230
        calc=self.call('calculator.calculate',{'expression':'200+30'},{'ok':True,'value':230});write=self.call('home_energy.set_alert',{'threshold_kwh':230})
        for calls in [[write],[calc,write],[write,self.energy_read(initial,'month')],[self.energy_read(initial,'week'),write]]:
            result=verify(initial,s,calls,final,self.kinds);self.assertFalse(result['state']);self.assertIn('source_before_consuming_write',result['grounding'])
        self.assertEqual(verify(initial,s,[self.energy_read(initial,'month'),calc,write],final,self.kinds)['verdict'],'pass')

    def test_current_threshold_from_any_period_and_literal_direct(self):
        sid='TR6_E_CURRENT';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial);final['home_energy']['alert_threshold_kwh']=350
        write=self.call('home_energy.set_alert',{'threshold_kwh':350})
        for period in ['today','week','month']:self.assertEqual(verify(initial,s,[self.energy_read(initial,period),write],final,self.kinds)['verdict'],'pass')
        s=self.sm['TR6_E_LITERAL'];final['home_energy']['alert_threshold_kwh']=230
        self.assertEqual(verify(initial,s,[self.call('home_energy.set_alert',{'threshold_kwh':230})],final,self.kinds)['verdict'],'pass')

    def map_final(self,sid):
        s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        for i,save in enumerate(s['oracle_draft']['saves']):
            place=next(r for r in initial['maps']['places'] if r['name']==save['name'] and r['address']==save['address'])
            old=next((r for r in final['maps']['saved_places'] if r['place_id']==place['id']),None)
            if old:old['label']=save['label']
            else:final['maps']['saved_places'].append({'id':f'unit_{i}','place_id':place['id'],'label':save['label']})
        return s,initial,final

    def test_correct_hidden_place_rejected_and_exact_address_required(self):
        s,initial,final=self.map_final('TR6_M_SAVE');write=self.call('maps.save_place',{'place_id':'tr6_place_22','label':'Điểm nhận'})
        read=self.call('maps.search_place',{'query':'Xưởng Gấp'},{'ok':True,'places':initial['maps']['places']})
        self.assertEqual(verify(initial,s,[read,write],final,self.kinds)['verdict'],'pass')
        self.assertIn('source_before_consuming_write',verify(initial,s,[write,read],final,self.kinds)['grounding'])
        wrong=self.call('maps.save_place',{'place_id':'tr6_place_74','label':'Điểm nhận'})
        self.assertIn('authorized_action_or_count',verify(initial,s,[read,wrong],final,self.kinds)['trace'])

    def test_existing_bookmark_id_preserved_and_duplicate_rejected(self):
        s,initial,final=self.map_final('TR6_M_EXISTING');read=self.call('maps.search_place',{'query':'*'},{'ok':True,'places':initial['maps']['places']});write=self.call('maps.save_place',{'place_id':'tr6_place_22','label':'Điểm nhận'})
        self.assertEqual(verify(initial,s,[read,write],final,self.kinds)['verdict'],'pass')
        final['maps']['saved_places'][-1]['id']='replaced_old_id'
        self.assertEqual(verify(initial,s,[read,write],final,self.kinds)['verdict'],'reject')

    def test_each_place_may_be_observed_then_saved_independently(self):
        s,initial,final=self.map_final('TR6_M_TWO');calls=[]
        for save in s['oracle_draft']['saves']:
            place=next(r for r in initial['maps']['places'] if r['address']==save['address'])
            calls.extend([self.call('maps.search_place',{'query':save['name'],'near':save['address']},{'ok':True,'places':[place]}),self.call('maps.save_place',{'place_id':place['id'],'label':save['label']})])
        self.assertEqual(verify(initial,s,calls,final,self.kinds)['verdict'],'pass')

    def test_target_total_is_delta_and_hidden_progress_not_evidence(self):
        sid='TR6_L_TOTAL';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        final['learning']['courses'][0]['progress_minutes']=60;final['learning']['progress'].append({'id':'unit','course_id':'tr6_course_28','minutes':20})
        read=self.call('learning.list_courses',{}, {'ok':True,'courses':initial['learning']['courses']});write=self.call('learning.log_progress',{'course_id':'tr6_course_28','minutes':20})
        self.assertEqual(verify(initial,s,[read,write],final,self.kinds)['verdict'],'pass')
        self.assertIn('source_before_consuming_write',verify(initial,s,[write],final,self.kinds)['grounding'])
        write['arguments']['minutes']=60
        self.assertIn('authorized_action_or_count',verify(initial,s,[read,write],final,self.kinds)['trace'])

    def test_unenrolled_course_progress_does_not_authorize_enrollment(self):
        sid='TR6_L_OTHER';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        final['learning']['courses'][1]['progress_minutes']=35;final['learning']['progress'].append({'id':'unit','course_id':'tr6_course_67','minutes':25})
        read=self.call('learning.list_courses',{}, {'ok':True,'courses':initial['learning']['courses']});write=self.call('learning.log_progress',{'course_id':'tr6_course_67','minutes':25})
        self.assertEqual(verify(initial,s,[read,write],final,self.kinds)['verdict'],'pass')
        extra=self.call('learning.enroll',{'course_id':'tr6_course_67'});final['learning']['courses'][1]['enrolled']=True
        self.assertIn('goal_or_frame',verify(initial,s,[read,write,extra],final,self.kinds)['state'])

    def test_train_ancestry_and_future_status_scope(self):
        validate(self.d,self.docs);w=self.d['worlds'][1];s=self.sm['TR6_M_SAVE']
        extra={'version':'unit_future','worlds':[{'world_id':'unit_future_w','lineage_id':w['lineage_id'],'split':'train','variants':{},'ancestry':{'parent_world_ids':[w['world_id']],'parent_scenario_ids':[s['scenario_id']],'parent_lineage_ids':[w['lineage_id']]}}],
               'scenarios':[{'scenario_id':'unit_future_s','world_id':'unit_future_w','lineage_id':w['lineage_id'],'fixture_variant':'base','status':'future','exportable':True,'agent_visible':deepcopy(s['agent_visible'])}]}
        validate(self.d,[*self.docs,extra])
        self.sm['TR6_E_MONTH']['exportable']=True
        with self.assertRaisesRegex(AssertionError,'Wave06 scenario status'):validate(self.d,self.docs)
        self.sm['TR6_E_MONTH']['exportable']=False
        self.d['worlds'][0]['ancestry']['parent_world_ids']=['W_RIDES']
        with self.assertRaisesRegex(AssertionError,'cross-split ancestry'):validate(self.d,self.docs)


if __name__=='__main__':unittest.main()
