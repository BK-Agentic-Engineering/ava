"""Focused synthetic partial-authorization, source and ancestry regressions."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

import yaml

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from replay_train_wave_05 import ROOT, StrictLoader, fixture, validate, verify


class Wave05Tests(unittest.TestCase):
    def setUp(self):
        self.docs=[yaml.load(p.read_text(encoding='utf-8'),Loader=StrictLoader) for p in sorted((ROOT/'data/synthetic/design').glob('*.yaml'))]
        self.d=next(d for d in self.docs if d['version']=='train_wave_05');self.sm={s['scenario_id']:s for s in self.d['scenarios']};self.wm={w['world_id']:w for w in self.d['worlds']}
        reads=['appliances.list','bill_payment.list_bills','ewallet.get_balance','contacts.search','contacts.get']
        self.kinds={t:'read' if t in reads else 'meta' if t=='sys.ask_missing_info' else 'write' for w in self.wm.values() for t in w['relevant_tools']}

    def initial(self,sid):
        s=self.sm[sid];return fixture(self.wm[s['world_id']],s)

    def call(self,name,args,result=None):return {'name':name,'arguments':args,'result':result or {'ok':True}}

    def test_partial_write_required_but_all_or_none_forbids_it(self):
        sid='TR5_A_PARTIAL_BUSY';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        final['appliances']['appliances'][0]['state'].update(status='running',cycle='normal',delay_minutes=0)
        read=self.call('appliances.list',{}, {'ok':True,'appliances':initial['appliances']['appliances']})
        write=self.call('appliances.start_cycle',{'appliance_id':'tr5_app_26','cycle':'normal'})
        self.assertEqual(verify(initial,s,[read,write],final,self.kinds)['verdict'],'pass')
        self.assertIn('authorized_action_or_count',verify(initial,s,[read],initial,self.kinds)['trace'])
        all_s=self.sm['TR5_A_ALL_BUSY']
        self.assertIn('authorized_action_or_count',verify(initial,all_s,[read,write],final,self.kinds)['trace'])
        self.assertEqual(verify(initial,all_s,[read],initial,self.kinds)['verdict'],'pass')

    def test_idle_only_does_not_resolve_false_all_ready_branch(self):
        sid='TR5_A_ALL_BUSY';s=self.sm[sid];initial=self.initial(sid)
        read=self.call('appliances.list',{'type':'dryer'},{'ok':True,'appliances':initial['appliances']['appliances'][:1]})
        self.assertEqual(verify(initial,s,[read],initial,self.kinds)['grounding'],['decision_observation_missing'])

    def test_running_target_alone_resolves_false_all_ready_branch(self):
        sid='TR5_A_ALL_BUSY';s=self.sm[sid];initial=self.initial(sid)
        read=self.call('appliances.list',{'type':'washer'},{'ok':True,'appliances':[initial['appliances']['appliances'][1]]})
        self.assertEqual(verify(initial,s,[read],initial,self.kinds)['verdict'],'pass')
        self.assertEqual(verify(initial,s,[],initial,self.kinds)['grounding'],['decision_observation_missing'])
        for result in [{'ok':False,'appliances':[initial['appliances']['appliances'][1]]},{'ok':True,'done':False,'appliances':[initial['appliances']['appliances'][1]]}]:
            failed=self.call('appliances.list',{'type':'washer'},result)
            self.assertEqual(verify(initial,s,[failed],initial,self.kinds)['verdict'],'reject')

    def test_unrelated_running_projection_not_condition_evidence(self):
        # Verifier-only projection; no claim this fabricated response came from runtime.
        sid='TR5_A_ALL_BUSY';s=self.sm[sid];initial=self.initial(sid)
        unrelated=deepcopy(initial['appliances']['appliances'][2]);unrelated['state']['status']='running'
        read=self.call('appliances.list',{'type':'dishwasher'},{'ok':True,'appliances':[unrelated]})
        self.assertEqual(verify(initial,s,[read],initial,self.kinds)['grounding'],['decision_observation_missing'])

    def test_partial_sequential_reads_valid_all_or_none_preflight_required(self):
        sid='TR5_A_PARTIAL_READY';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial);calls=[]
        for r in initial['appliances']['appliances'][:2]:
            calls.extend([self.call('appliances.list',{'type':r['type']},{'ok':True,'appliances':[r]}),self.call('appliances.start_cycle',{'appliance_id':r['id'],'cycle':'normal'})])
            next(x for x in final['appliances']['appliances'] if x['id']==r['id'])['state'].update(status='running',cycle='normal')
        self.assertEqual(verify(initial,s,calls,final,self.kinds)['verdict'],'pass')
        self.assertIn('source_before_consuming_write',verify(initial,self.sm['TR5_A_ALL_READY'],calls,final,self.kinds)['grounding'])

    def test_correct_state_hidden_machine_ID_rejected(self):
        sid='TR5_A_PARTIAL_BUSY';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        final['appliances']['appliances'][0]['state'].update(status='running',cycle='normal')
        write=self.call('appliances.start_cycle',{'appliance_id':'tr5_app_26','cycle':'normal','delay_minutes':0})
        result=verify(initial,s,[write],final,self.kinds)
        self.assertFalse(result['state']);self.assertIn('source_before_consuming_write',result['grounding'])

    def test_autopay_alone_needs_no_bill_lookup_or_payment(self):
        sid='TR5_B_AUTO';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        final['bill_payment']['autopays'][0]['enabled']=True
        write=self.call('bill_payment.schedule_autopay',{'type':'electricity','enabled':True})
        self.assertEqual(verify(initial,s,[write],final,self.kinds)['verdict'],'pass')
        extra=self.call('bill_payment.pay',{'bill_id':'tr5_bill_24','source':'bank'})
        self.assertIn('authorized_action_or_count',verify(initial,s,[write,extra],final,self.kinds)['trace'])

    def test_contact_copy_requires_source_even_if_destination_state_correct(self):
        sid='TR5_C_COPY';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        final['contacts']['contacts'][0]['email']='vkhoi@cuonlua.example.test'
        read=self.call('contacts.search',{'query':'Đặng Hạ Mai'},{'ok':True,'contacts':initial['contacts']['contacts'][:1]})
        write=self.call('contacts.update',{'contact_id':'tr5_ct_32','email':'vkhoi@cuonlua.example.test'})
        result=verify(initial,s,[read,write],final,self.kinds)
        self.assertFalse(result['state']);self.assertIn('source_before_consuming_write',result['grounding'])

    def test_split_contact_fields_valid_preserve_relation(self):
        sid='TR5_C_BOTH';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        patch=s['oracle_draft']['updates']['tr5_ct_32'];final['contacts']['contacts'][0].update(patch)
        read=self.call('contacts.search',{}, {'ok':True,'contacts':initial['contacts']['contacts']})
        writes=[self.call('contacts.update',{'contact_id':'tr5_ct_32',k:v}) for k,v in patch.items()]
        self.assertEqual(verify(initial,s,[read,*writes],final,self.kinds)['verdict'],'pass')
        final['contacts']['contacts'][0]['relation']='changed'
        self.assertIn('goal_or_frame',verify(initial,s,[read,*writes],final,self.kinds)['state'])

    def test_train_derivative_ancestry_and_future_scope(self):
        validate(self.d,self.docs)
        w=self.d['worlds'][0];s=self.d['scenarios'][0]
        extra={'version':'unit_future','worlds':[{'world_id':'unit_future_w','lineage_id':w['lineage_id'],'split':'train','variants':{},'ancestry':{'parent_world_ids':[w['world_id']],'parent_scenario_ids':[s['scenario_id']],'parent_lineage_ids':[w['lineage_id']]}}],
               'scenarios':[{'scenario_id':'unit_future_s','world_id':'unit_future_w','lineage_id':w['lineage_id'],'fixture_variant':'base','status':'future','exportable':True,'agent_visible':deepcopy(s['agent_visible'])}]}
        validate(self.d,[*self.docs,extra])
        contacts=self.d['worlds'][2];contacts['ancestry']['parent_world_ids']=['W_SMS']
        with self.assertRaisesRegex(AssertionError,'cross-split ancestry'):validate(self.d,self.docs)


if __name__=='__main__':unittest.main()
