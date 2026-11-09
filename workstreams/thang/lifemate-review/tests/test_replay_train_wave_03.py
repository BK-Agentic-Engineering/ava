"""Synthetic unit checks for Wave 03 source, guard and namespace risks."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

import yaml

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from replay_train_wave_03 import ROOT, StrictLoader, fixture, validate, verify


class Wave03Tests(unittest.TestCase):
    def setUp(self):
        self.docs=[yaml.load(p.read_text(encoding='utf-8'),Loader=StrictLoader) for p in sorted((ROOT/'data/synthetic/design').glob('*.yaml'))]
        self.d=next(d for d in self.docs if d['version']=='train_wave_03');self.sm={s['scenario_id']:s for s in self.d['scenarios']}
        self.wm={w['world_id']:w for w in self.d['worlds']}
        reads=['loyalty.get_points','library.search','music.list_tracks']
        self.kinds={t:'read' if t in reads else 'meta' if t=='sys.ask_missing_info' else 'write' for w in self.wm.values() for t in w['relevant_tools']}

    def initial(self,sid):
        s=self.sm[sid];return fixture(self.wm[s['world_id']],s)

    def call(self,name,args,result=None):
        return {'name':name,'arguments':args,'result':result or {'ok':True}}

    def test_no_write_requires_decisive_observation(self):
        sid='TR3_R_LOW';s=self.sm[sid];initial=self.initial(sid)
        self.assertIn('decision_observation_missing',verify(initial,s,[],initial,self.kinds)['grounding'])
        read=self.call('loyalty.get_points',{}, {'ok':True,'programs':initial['loyalty']['programs']})
        self.assertEqual(verify(initial,s,[read],initial,self.kinds)['verdict'],'pass')

    def test_affordable_but_reserve_guard_forbids_write(self):
        sid='TR3_R_RESERVE150';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        final['loyalty']['programs'][0]['points']=100
        final['loyalty']['vouchers'].append({'id':'unit_voucher',**self.sm['TR3_R_BASE']['oracle_draft']['voucher']})
        read=self.call('loyalty.get_points',{}, {'ok':True,'programs':initial['loyalty']['programs']})
        write=self.call('loyalty.redeem',{'program':'Vườn Sen','reward_id':'tr3_reward_tea'})
        self.assertIn('authorized_action_or_count',verify(initial,s,[read,write],final,self.kinds)['trace'])

    def test_correct_hidden_reward_does_not_pass_correct_state(self):
        sid='TR3_R_BASE';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        final['loyalty']['programs'][0]['points']=100
        final['loyalty']['vouchers'].append({'id':'unit_voucher',**s['oracle_draft']['voucher']})
        write=self.call('loyalty.redeem',{'program':'Vườn Sen','reward_id':'tr3_reward_tea'})
        result=verify(initial,s,[write],final,self.kinds)
        self.assertFalse(result['state']);self.assertIn('required_observation_before_write',result['grounding'])

    def test_library_sequential_reads_before_each_consuming_write(self):
        sid='TR3_L_TWO';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        final['library']['books'][0]['available']=False
        final['library']['reservations'].extend([{'id':'unit_a','book_id':'tr3_book_31','status':'ready'}, {'id':'unit_b','book_id':'tr3_book_64','status':'waiting'}])
        calls=[]
        for book in initial['library']['books'][:2]:
            calls.extend([self.call('library.search',{'query':book['title']},{'ok':True,'books':[book]}),self.call('library.reserve',{'book_id':book['id']})])
        self.assertEqual(verify(initial,s,calls,final,self.kinds)['verdict'],'pass')
        calls=[calls[1],calls[0],*calls[2:]]
        self.assertIn('required_observation_before_write',verify(initial,s,calls,final,self.kinds)['grounding'])

    def test_waiting_not_authorized_by_immediate_only_request(self):
        sid='TR3_L_NOWAIT';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        final['library']['reservations'].append({'id':'unit_wait','book_id':'tr3_book_31','status':'waiting'})
        read=self.call('library.search',{}, {'ok':True,'books':initial['library']['books']})
        write=self.call('library.reserve',{'book_id':'tr3_book_31'})
        self.assertIn('authorized_action_or_count',verify(initial,s,[read,write],final,self.kinds)['trace'])

    def test_music_redundant_namespace_ids_fail_even_correct_state(self):
        sid='TR3_M_PLAY';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        final['music']['now_playing']=deepcopy(s['oracle_draft']['playback_after'])
        read=self.call('music.list_tracks',{}, {'ok':True,'tracks':initial['music']['tracks'],'playlists':initial['music']['playlists']})
        write=self.call('music.play',{'track_id':'tr3_track_12','playlist_id':'tr3_list_44'})
        result=verify(initial,s,[read,write],final,self.kinds)
        self.assertFalse(result['state']);self.assertIn('authorized_action_or_count',result['trace'])

    def test_explicit_music_operation_order_is_preserved(self):
        sid='TR3_M_BOTH';s=self.sm[sid];initial=self.initial(sid);final=deepcopy(initial)
        final['music']['now_playing']=deepcopy(s['oracle_draft']['playback_after'])
        final['music']['playlists'][0]['track_ids'].append('tr3_track_12')
        read=self.call('music.list_tracks',{}, {'ok':True,'tracks':initial['music']['tracks'],'playlists':initial['music']['playlists']})
        add=self.call('music.add_to_playlist',{'track_id':'tr3_track_12','playlist_id':'tr3_list_44'})
        play=self.call('music.play',{'track_id':'tr3_track_12'})
        self.assertEqual(verify(initial,s,[read,add,play],final,self.kinds)['verdict'],'pass')
        self.assertIn('authorized_operation_order',verify(initial,s,[read,play,add],final,self.kinds)['trace'])

    def test_scoped_status_and_source_fact_guards(self):
        validate(self.d,self.docs)
        self.sm['TR3_R_BASE']['exportable']=True
        with self.assertRaises(AssertionError):validate(self.d,self.docs)
        self.sm['TR3_R_BASE']['exportable']=False
        self.sm['TR3_R_LOW']['agent_visible']['context']={'current_time':'different'}
        with self.assertRaises(AssertionError):validate(self.d,self.docs)


if __name__=='__main__':unittest.main()
