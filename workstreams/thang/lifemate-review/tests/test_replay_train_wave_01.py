"""Focused verifier regressions with independently authored synthetic in-memory states."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

import yaml

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from replay_train_wave_01 import ROOT, StrictLoader, validate, verify


class WaveVerifierTests(unittest.TestCase):
    def setUp(self):
        self.design = yaml.load((ROOT/'data/synthetic/design/train_wave_01.yaml').read_text(encoding='utf-8'),Loader=StrictLoader)
        self.scenarios = {s['scenario_id']:s for s in self.design['scenarios']}
        self.worlds = {w['world_id']:w for w in self.design['worlds']}
        self.kinds = {n:'read' if n in ['email.list','email.read','notes.list','shopping_list.get'] else 'write'
                      for w in self.worlds.values() for n in w['relevant_tools']}

    def initial(self, sid):
        return deepcopy(self.worlds[self.scenarios[sid]['world_id']]['initial_state'])

    def call(self, name, args, result=None):
        return {'name':name,'arguments':args,'result':result or {'ok':True}}

    def test_future_descendant_can_retain_primary_lineage_but_independent_root_cannot(self):
        docs = [yaml.load(p.read_text(encoding='utf-8'),Loader=StrictLoader)
                for p in sorted((ROOT/'data/synthetic/design').glob('*.yaml'))]
        parent = self.worlds['W_TR1_NOTE_LIFECYCLE']
        child = deepcopy(parent)
        child['world_id'] = 'UNIT_FUTURE_DESCENDANT'
        child['ancestry'] = dict(parent_world_ids=[parent['world_id']],
                                 parent_scenario_ids=['TR1_N_COPY'],
                                 parent_lineage_ids=[parent['lineage_id']])
        docs.append(dict(version='unit_future',worlds=[child],scenarios=[]))
        validate(self.design,docs)
        child['ancestry'] = dict(parent_world_ids=[],parent_scenario_ids=[],parent_lineage_ids=[])
        with self.assertRaises(AssertionError):
            validate(self.design,docs)

    def test_primary_lineage_requires_referenced_ancestry(self):
        docs = [yaml.load(p.read_text(encoding='utf-8'),Loader=StrictLoader)
                for p in sorted((ROOT/'data/synthetic/design').glob('*.yaml'))]
        note = self.worlds['W_TR1_NOTE_LIFECYCLE']
        mail = self.worlds['W_TR1_MAIL_DISPOSITION']
        child = deepcopy(mail)
        child['world_id'] = 'UNIT_UNRELATED_PRIMARY'
        child['ancestry'] = dict(parent_world_ids=[note['world_id']],
                                 parent_scenario_ids=['TR1_N_COPY'],
                                 parent_lineage_ids=[note['lineage_id']])
        docs.append(dict(version='unit_bad_primary',worlds=[child],scenarios=[]))
        with self.assertRaisesRegex(AssertionError, 'primary lineage lacks an ancestry path'):
            validate(self.design,docs)
        child['ancestry']['parent_lineage_ids'].append(mail['lineage_id'])
        with self.assertRaisesRegex(AssertionError, 'parent lineage IDs disagree'):
            validate(self.design,docs)
        child['ancestry']['parent_scenario_ids'].append('TR1_E_DRAFT')
        validate(self.design,docs)

    def test_cyclic_descendants_cannot_certify_each_other(self):
        from replay_train_wave_01 import validate_ancestry
        root = self.worlds['W_TR1_NOTE_LIFECYCLE']
        lineage = root['lineage_id']
        worlds = {root['world_id']: root}
        for identity, parent in [('cycle_a','cycle_b'),('cycle_b','cycle_a')]:
            worlds[identity] = dict(
                split='train', lineage_id=lineage,
                ancestry=dict(parent_world_ids=[parent],parent_lineage_ids=[lineage]),
            )
        with self.assertRaisesRegex(AssertionError, 'cyclic ancestry'):
            validate_ancestry(worlds,{})

    def test_add_then_observe_then_check_old_row_allowed(self):
        sid = 'TR1_S_ADD_CHECK'; initial = self.initial(sid); final = deepcopy(initial)
        new = {'id':'unit_new','name':'mì gạo','quantity':2,'checked':False}
        final['shopping_list']['items'].append(new)
        observed = deepcopy(final['shopping_list']['items'])
        final['shopping_list']['items'][0]['checked'] = True
        calls = [self.call('shopping_list.add',{'name':'mì gạo','quantity':2}),
                 self.call('shopping_list.get',{}, {'ok':True,'items':observed}),
                 self.call('shopping_list.check',{'item_id':'tr1_item_35'})]
        self.assertEqual(verify(initial,self.scenarios[sid],calls,final,self.kinds)['verdict'],'pass')
        verdict = verify(initial,self.scenarios[sid],[calls[0],calls[2]],final,self.kinds)
        self.assertEqual(verdict['grounding'],['required_observation_before_write'])
        self.assertFalse(verdict['state'])

    def test_copy_requires_source_title_and_content_before_write(self):
        sid = 'TR1_N_COPY'; initial = self.initial(sid); final = deepcopy(initial)
        final['notes']['notes'][0]['content'] += '\nGiữ lại ba tấm lót.'
        observed = deepcopy(initial['notes']['notes'])
        write = self.call('notes.append',{'note_id':'tr1_note_26','content':'Giữ lại ba tấm lót.'})
        read = self.call('notes.list',{}, {'ok':True,'notes':observed})
        self.assertEqual(verify(initial,self.scenarios[sid],[read,write],final,self.kinds)['verdict'],'pass')
        observed[1]['title'] = 'Unrelated synthetic title'
        self.assertEqual(verify(initial,self.scenarios[sid],[read,write],final,self.kinds)['grounding'],['required_observation_before_write'])

    def test_append_cannot_overwrite_original_prefix(self):
        sid = 'TR1_N_APPEND'; initial = self.initial(sid); final = deepcopy(initial)
        final['notes']['notes'][0]['content'] = 'Chừa lối bên trái.'
        calls = [self.call('notes.list',{}, {'ok':True,'notes':initial['notes']['notes']}),
                 self.call('notes.append',{'note_id':'tr1_note_26','content':'Chừa lối bên trái.'})]
        self.assertIn('goal_or_unrelated_state',verify(initial,self.scenarios[sid],calls,final,self.kinds)['state'])

    def test_same_title_separate_note_is_valid(self):
        sid = 'TR1_N_CREATE'; initial = self.initial(sid); final = deepcopy(initial)
        final['notes']['notes'].append({'id':'unit_new','title':'Sổ đóng kiện','content':'Chừa lối bên trái.'})
        calls = [self.call('notes.create',{'title':'Sổ đóng kiện','content':'Chừa lối bên trái.'})]
        self.assertEqual(verify(initial,self.scenarios[sid],calls,final,self.kinds)['verdict'],'pass')
        final['notes']['notes'][1]['color'] = 'tampered'
        self.assertIn('goal_or_unrelated_state',verify(initial,self.scenarios[sid],calls,final,self.kinds)['state'])

    def test_duplicate_mark_rejected_despite_correct_state(self):
        sid = 'TR1_S_CHECK'; initial = self.initial(sid); final = deepcopy(initial)
        final['shopping_list']['items'][0]['checked'] = True
        read = self.call('shopping_list.get',{}, {'ok':True,'items':initial['shopping_list']['items']})
        write = self.call('shopping_list.check',{'item_id':'tr1_item_35'})
        verdict = verify(initial,self.scenarios[sid],[read,write,write],final,self.kinds)
        self.assertFalse(verdict['state'])
        self.assertEqual(verdict['trace'],['authorized_operation_arguments_or_count'])

    def test_omitted_empty_cc_allowed_but_draft_does_not_authorize_send(self):
        sid = 'TR1_E_DRAFT'; initial = self.initial(sid); final = deepcopy(initial)
        payload = {'to':['dieu@laco.example.test'],'subject':'Phiếu khay','body':'Tôi nhận bốn khay, không nhận thêm.'}
        final['email']['drafts'].append({'id':'unit_new',**payload,'cc':[]})
        write = self.call('email.create_draft',payload)
        self.assertEqual(verify(initial,self.scenarios[sid],[write],final,self.kinds)['verdict'],'pass')
        write['name'] = 'email.send'
        self.assertEqual(verify(initial,self.scenarios[sid],[write],final,self.kinds)['trace'],['authorized_operation_arguments_or_count'])


if __name__ == '__main__':
    unittest.main()
