"""Altered-response absence probes, separate from SDK replay evidence."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from replay_batch02 import verify
from replay_train_wave_08 import ROOT,load_design


class CalendarAbsenceTests(unittest.TestCase):
    def test_batch02_absence_requires_an_actual_collection(self):
        s=next(s for s in load_design(ROOT/'data/synthetic/design/batch_02.yaml')['scenarios']
               if s['scenario_id']=='B02_N_C')
        evidence=json.loads((ROOT/'artifacts/synthetic/batch_02_replay/replay.json').read_text(encoding='utf8'))
        row=next(r for r in evidence['replays'] if r['scenario_id']==s['scenario_id'] and r['trace_case']=='standard')
        for result,passed in [({'ok':True},False),({'ok':True,'events':None},False),
                              ({'ok':True,'events':{}},False),({'ok':True,'events':[]},True)]:
            calls=deepcopy(row['calls']);calls[0]['result']=result
            v=verify(row['final_state'],s,calls,row['final_state'],
                {'calendar.list_events':'read','sys.ask_missing_info':'meta'},
                'Đỗ Bảo Yến','Trao đổi mẫu gốm',['Nộp phiếu giao hàng'])
            self.assertEqual(v['verdict']=='pass',passed)


if __name__=='__main__':unittest.main()
