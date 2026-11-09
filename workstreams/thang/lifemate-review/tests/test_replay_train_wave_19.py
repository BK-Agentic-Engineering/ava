"""Focused tests for same-run factual evidence, selection and answer boundaries."""
from copy import deepcopy
import json
import importlib
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from replay_train_wave_19 import ARCHIVE,DESIGN,OUTPUT,evaluate,load_design


class Wave19Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design=load_design(DESIGN)
        cls.scenarios={s['scenario_id']:s for s in cls.design['scenarios']}
        cls.evidence=json.loads(OUTPUT.read_text(encoding='utf8'))
        cls.rows={(r['scenario_id'],r['trace_case']):r for r in cls.evidence['replays']}
        cls.probes={(p['scenario_id'],p['probe']):p for p in cls.evidence['answer_probes']}
        cls.kinds={t:'read' for w in cls.design['worlds'] for t in w['relevant_tools']}
        cls.kinds['tasks.complete']='write'

    def test_all_new_standards_and_state_preservation(self):
        self.assertEqual(len(self.scenarios),100)
        self.assertEqual({sid for sid,case in self.rows if case=='standard'},set(self.scenarios))
        for sid,s in self.scenarios.items():
            row=self.rows[sid,'standard']
            self.assertEqual(row['verdict']['overall'],'pass')
            self.assertEqual(row['final_state'],self.evidence['scenarios'][sid]['post_history_state'])
            self.assertEqual(s['status'],'spec_only')
            self.assertFalse(s['exportable'])

    def test_parcel_pilot_changes_only_the_declared_status(self):
        ids=['TR19_PARCEL_'+s for s in ['TRANSIT','DELIVERED','DISTRACTOR']]
        self.assertEqual([self.scenarios[sid]['agent_visible'] for sid in ids],[self.scenarios[ids[0]]['agent_visible']]*3)
        base=deepcopy(self.evidence['scenarios'][ids[0]]['post_history_state'])
        delivered=deepcopy(self.evidence['scenarios'][ids[1]]['post_history_state'])
        distractor=deepcopy(self.evidence['scenarios'][ids[2]]['post_history_state'])
        next(r for r in delivered['package_tracking']['shipments'] if r['id']=='w19_parcel_a')['status']='in_transit'
        next(r for r in distractor['package_tracking']['shipments'] if r['id']=='w19_parcel_b')['status']='delivered'
        self.assertEqual(base,delivered)
        self.assertEqual(base,distractor)
        self.assertEqual([self.rows[sid,'standard']['verdict']['observed_facts'][0][1] for sid in ids],['in_transit','delivered','in_transit'])

    def test_wrong_entity_and_wrong_answer_fail_independently(self):
        for sid in ['TR19_PARCEL_TRANSIT','TR19_PARCEL_DELIVERED','TR19_PARCEL_DISTRACTOR']:
            v=self.rows[sid,'insufficient']['verdict']
            self.assertEqual((v['trace_verdict'],v['answer_verdict'],v['overall']),('fail','unresolved','fail'))
            v=self.probes[sid,'wrong']['verdict']
            self.assertEqual((v['trace_verdict'],v['answer_verdict'],v['overall']),('pass','fail','fail'))

    def test_two_facts_can_come_from_one_response(self):
        for sid in ['TR19_TWO_ACCOUNT_PAIR','TR19_TWO_START_END','TR19_TWO_CYCLE_STATE','TR19_TWO_PARCEL_PAIR']:
            row=self.rows[sid,'standard']
            self.assertEqual(len(row['calls']),1)
            self.assertEqual(len(row['verdict']['observed_facts']),2)
            self.assertEqual(row['verdict']['overall'],'pass')

    def test_missing_second_observation_cannot_be_repaired_with_correct_text(self):
        sid='TR19_TWO_WALLET_BILL'
        self.assertEqual(self.rows[sid,'insufficient']['verdict']['overall'],'fail')
        self.assertEqual(self.probes[sid,'incomplete']['verdict']['answer_verdict'],'fail')
        self.assertEqual(self.rows[sid,'alternative_lookup']['verdict']['overall'],'pass')

    def test_exhaustive_scope_and_duplicate_line_counts(self):
        for sid,n in [('TR19_LIST_ROWS',3),('TR19_LIST_ALL_TOTAL',9),('TR19_LIST_OPEN_TOTAL',7)]:
            self.assertEqual(self.rows[sid,'standard']['verdict']['observed_facts'][0][1],n)
        self.assertEqual(self.rows['TR19_MONEY_UNPAID_COUNT','insufficient']['verdict']['trace_verdict'],'fail')

    def test_correct_answer_does_not_override_an_actual_write(self):
        v=self.rows['TR19_TWO_TASK_ALARM','unauthorized_write']['verdict']
        self.assertEqual(v['trace_reasons'],['state_changed','write_attempt'])
        self.assertEqual((v['answer_verdict'],v['overall']),('pass','fail'))

    def test_adapter_probes_reordered_rows_and_changed_source(self):
        sid='TR19_PARCEL_TRANSIT';s=self.scenarios[sid]
        row=self.rows[sid,'standard'];calls=deepcopy(row['calls'])
        calls[0]['result']['shipments'].reverse()
        initial=self.evidence['scenarios'][sid]['post_history_state']
        self.assertEqual(evaluate(s,initial,calls,row['final_state'],s['oracle_draft']['answers'][0],self.kinds)['overall'],'pass')
        target=next(r for r in calls[0]['result']['shipments'] if r['carrier']=='Bưu Cói' and r['name']=='Thùng dây cói')
        target['status']='delivered'
        v=evaluate(s,initial,calls,row['final_state'],s['oracle_draft']['answers'][0],self.kinds)
        self.assertEqual((v['trace_verdict'],v['answer_verdict'],v['answer_reason']),('pass','unresolved','source_mismatch'))

    def test_unfamiliar_wording_stays_unresolved_and_equivalents_pass(self):
        for sid in self.scenarios:
            probe=self.scenarios[sid]['oracle_draft']['review_probe']
            self.assertEqual(self.probes[sid,probe['label']]['verdict']['answer_verdict'],probe['expected'])
            self.assertEqual(self.probes[sid,'alternative']['verdict']['answer_verdict'],'pass')

    def run_probe(self, sid, mutate):
        # Modified-response probe, separate from actual SDK replay.
        row=self.rows[sid,'standard']
        calls=deepcopy(row['calls'])
        mutate(calls)
        return evaluate(self.scenarios[sid],self.evidence['scenarios'][sid]['post_history_state'],
                        calls,row['final_state'],self.scenarios[sid]['oracle_draft']['answers'][0],self.kinds)

    def test_location_question_cannot_select_by_its_expected_answer(self):
        def duplicate(calls):
            rows=calls[0]['result']['events']
            target=next(r for r in rows if r['location']=='Phòng Lan' and r['start'].startswith('2028-01-06'))
            rows.append({**target,'id':'probe_second_location','location':'Phòng Khác'})
        verdict=self.run_probe('TR19_CAL_WHERE',duplicate)
        self.assertEqual(verdict['trace_reasons'],['evidence_ambiguous'])
        self.assertEqual(verdict['answer_verdict'],'unresolved')

    def test_start_question_extracts_changed_time_and_rejects_ambiguous_time(self):
        def change(calls):
            next(r for r in calls[0]['result']['events'] if r['location']=='Phòng Lan')['start']='2028-01-06T10:20:00+07:00'
        verdict=self.run_probe('TR19_CAL_START',change)
        self.assertEqual(verdict['trace_verdict'],'pass')
        self.assertEqual(verdict['answer_reason'],'source_mismatch')
        def duplicate(calls):
            rows=calls[0]['result']['events']
            target=next(r for r in rows if r['location']=='Phòng Lan')
            rows.append({**target,'id':'probe_second_time','start':'2028-01-06T10:20:00+07:00'})
        self.assertEqual(self.run_probe('TR19_CAL_START',duplicate)['trace_reasons'],['evidence_ambiguous'])

    def test_fan_room_is_a_required_identity_condition(self):
        def other_room(calls):
            fan=next(r for r in calls[0]['result']['devices'] if r['name']=='Quạt góc')
            calls[0]['result']['devices']=[{**fan,'id':'probe_other_room','room':'Phòng Kho'}]
        self.assertEqual(self.run_probe('TR19_DEVICE_FAN_POWER',other_room)['trace_reasons'],['evidence_missing'])

    def test_time_selectors_use_spoken_day_and_reminder_name(self):
        for sid in ['TR19_CAL_START','TR19_CAL_REM_TIME','TR19_TWO_START_END','TR19_TASK_PRIORITY']:
            for fact in self.scenarios[sid]['oracle_draft']['facts']:
                self.assertIn('dates',fact)
                self.assertNotIn(fact['path'][0],fact['match'])
        for sid in ['TR19_CAL_REM_REPEAT','TR19_CAL_REM_DONE','TR19_CAL_REM_PENDING']:
            fact=self.scenarios[sid]['oracle_draft']['facts'][0]
            self.assertEqual(fact['match'],{'content':'Gom bìa'})

    def test_no_requested_field_is_used_as_its_own_entity_selector(self):
        for sid,scenario in self.scenarios.items():
            for fact in scenario['oracle_draft']['facts']:
                if fact['operation']!='field':
                    continue
                value=fact['match']
                for key in fact['path']:
                    if not isinstance(value,dict) or key not in value:
                        break
                    value=value[key]
                else:
                    self.fail((sid,'queried field used as selector',fact['path']))

    def test_explicit_wrong_subject_fails_and_concise_parcel_answer_passes(self):
        for sid in ['TR19_DEVICE_FAN_POWER','TR19_TASK_WEEKDAY','TR19_TASK_WEEKEND',
                    'TR19_TASK_WEEKEND_CHANGED','TR19_TASK_WEEKEND_DISTRACTOR']:
            self.assertEqual(self.probes[sid,'wrong_subject']['verdict']['answer_verdict'],'fail')
            self.assertNotIn('Đèn',self.scenarios[sid]['oracle_draft']['answers'][1])
        for sid in ['TR19_PARCEL_TRANSIT','TR19_PARCEL_DISTRACTOR']:
            self.assertEqual(self.probes[sid,'concise_not_delivered']['verdict']['answer_verdict'],'pass')

    def test_scope_from_real_sdk_electricity_filter(self):
        sid='TR19_MONEY_ELECTRIC_COUNT';s=self.scenarios[sid]
        entry={**self.evidence['scenarios'][sid]['post_history_state'],
               '_meta':{'tools':s['agent_visible']['allowed_tools'],'current_time':s['agent_visible']['context']['current_time']}}
        provenance=self.design['provenance']
        with tempfile.TemporaryDirectory(dir=OUTPUT.parent) as directory:
            root=Path(directory)
            with zipfile.ZipFile(ARCHIVE) as archive:
                for member in ['__init__.py','executor.py','validate.py','utils.py',
                               'apps/__init__.py','apps/base.py','apps/sys.py','apps/bill_payment.py']:
                    path=root/'zaic_tools'/member;path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_bytes(archive.read(provenance['runtime_root']+member))
                catalog=json.loads(archive.read(provenance['catalog_member']))
            self.assertNotIn('zaic_tools',sys.modules)
            sys.path.insert(0,directory)
            try:
                Session=importlib.import_module('zaic_tools.executor').Session
                session=Session(sid,entry,catalog)
                result=session.call('bill_payment.list_bills',{'type':'electricity'})
                self.assertEqual(len(result['bills']),1)
                verdict=evaluate(s,session.get_state(),session.log,session.get_state(),'1 hóa đơn',self.kinds)
                self.assertEqual(verdict['overall'],'pass')
                total=self.scenarios['TR19_MONEY_UNPAID_COUNT']
                verdict=evaluate(total,session.get_state(),session.log,session.get_state(),'2 hóa đơn',self.kinds)
                self.assertEqual(verdict['trace_reasons'],['evidence_missing'])
            finally:
                sys.path.remove(directory)
                for name in tuple(sys.modules):
                    if name=='zaic_tools' or name.startswith('zaic_tools.'):del sys.modules[name]

    def test_lookup_alternatives_are_distinct_and_repeats_are_labeled(self):
        for sid,s in self.scenarios.items():
            o=s['oracle_draft']
            case='alternative_lookup' if o['reads']!=o['broad_reads'] else 'reproducibility_repeat'
            row=self.rows[sid,case]
            standard=self.rows[sid,'standard']
            self.assertEqual(row['calls']==standard['calls'],case=='reproducibility_repeat')


if __name__=='__main__':unittest.main()
