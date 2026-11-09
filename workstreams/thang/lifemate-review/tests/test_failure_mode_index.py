"""Index reference/count regressions, not tests of authored semantic labels."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from check_failure_mode_index import INDEX, ROOT, accepted_runtime_reference, isolated_ids, read_rows, validate, selected, comparison_note


class FailureIndexTests(unittest.TestCase):
    def test_current_membership_includes_all_later_cases(self):
        rows=read_rows(INDEX)
        summary=validate(rows)
        self.assertEqual(summary['total_ids'],1063)
        self.assertEqual(summary['awaiting_mapping_review'],0)
        self.assertEqual(summary['reviewed_by_split'],{'dev':58,'train':1005})
        with self.assertRaises(AssertionError):validate(rows[:-1])

    def test_new_cases_cannot_use_wrong_source_snapshot(self):
        rows=read_rows(INDEX)
        row=next(r for r in rows if r['scenario_id']=='TR23_SMS_SENT')
        row['design_ref']['path']='data/synthetic/design/train_wave_07.yaml'
        with self.assertRaises(AssertionError):validate(rows)

    def test_repeated_upsert_is_not_the_rejected_constraint_record(self):
        row=next(r for r in read_rows(INDEX) if r['scenario_id']=='TR6_M_EXISTING')
        entry=next(e for e in row['failure_modes'] if e['tag']=='constraint_violation')
        negative=entry['evidence'][entry['comparison']['counterexample_evidence']]
        self.assertEqual(negative['trace_case'],'duplicate_saved_snapshot')
        self.assertEqual(negative['evidence_type'],'verifier_only_or_modified_evidence_probe')
        artifact=json.loads((ROOT/negative['path']).read_text(encoding='utf8'))
        self.assertEqual(artifact['replays'][98]['verdict']['verdict'],'pass')

    def test_new_answer_schema_retains_actual_text(self):
        row=next(r for r in read_rows(INDEX) if r['scenario_id']=='TR23_ORDER_DELIVERED')
        entry=next(e for e in row['failure_modes'] if e['tag']=='unsupported_answer')
        self.assertNotIn('None',entry['evidence_gap'])
        self.assertIn('authored answer changes',entry['evidence_gap'])

    def test_isolated_counts_union_runtime_and_answer_ids(self):
        rows=[{'scenario_id':'one','failure_modes':[
            {'tag':'wrong_target','evidence_status':'isolated_authored_counterexample'},
            {'tag':'wrong_target','evidence_status':'isolated_authored_answer_probe'}]},
            {'scenario_id':'two','failure_modes':[
            {'tag':'wrong_target','evidence_status':'isolated_authored_answer_probe'}]}]
        self.assertEqual(isolated_ids(rows,'wrong_target'),{'one','two'})
        self.assertEqual(len(isolated_ids(rows,'wrong_target')),2)

    def test_actual_accepted_recovery_alternative_is_not_standard(self):
        artifact=json.loads((ROOT/'artifacts/synthetic/train_wave_16_replay/replay.json').read_text(encoding='utf8'))
        row=artifact['replays'][6]
        self.assertEqual((row['scenario_id'],row['trace_case']),('TR16_PARCEL_DELIVERED','observed_noop'))
        self.assertEqual(row['verdict']['verdict'],'pass')
        self.assertFalse(accepted_runtime_reference({'selector':'/replays/6'},row,artifact,5))
        self.assertTrue(accepted_runtime_reference({'selector':'/replays/5'},artifact['replays'][5],artifact,5))

    def test_passing_modified_probe_cannot_be_runtime_alternative(self):
        row={'evidence_kind':'verifier_only_projection','verdict':{'verdict':'pass'}}
        with self.assertRaises(AssertionError):
            accepted_runtime_reference({'selector':'/replays/1'},row,{'kind':'runtime_replay'},0)
        with self.assertRaises(AssertionError):
            accepted_runtime_reference({'selector':'/answer_probes/1'},row,{},0)

    def test_runtime_selector_cannot_claim_another_scenario_identity(self):
        rows=read_rows(INDEX)
        ref=next(ref for ref in rows[0]['failure_modes'][0]['evidence']
                 if ref['evidence_type']=='accepted_authored_runtime_trace')
        ref['scenario_id']='unrelated'
        with self.assertRaises(AssertionError):validate(rows)

    def test_sidecar_expected_judgment_must_match_its_definition(self):
        rows=read_rows(INDEX)
        ref=next(ref for row in rows for entry in row['failure_modes'] for ref in entry['evidence']
                 if ref.get('support_kind')=='authored_answer_probe_definition')
        ref['specified_expected_judgment']=['pass','supported_facts']
        with self.assertRaises(AssertionError):validate(rows)

    def test_stale_comparison_description_is_rejected(self):
        rows=read_rows(INDEX)
        entry=next(e for r in rows if r['scenario_id']=='TR9_NEWS_LOOK'
                   for e in r['failure_modes'] if e['tag']=='unsupported_guessing')
        entry['evidence_gap']='wrong appends save to the correct lookup.'
        with self.assertRaisesRegex(AssertionError,'stale comparison'):validate(rows)

    def test_comparison_requires_a_negative_record(self):
        rows=read_rows(INDEX);entry=rows[0]['failure_modes'][0]
        entry['comparison']['counterexample_evidence']=entry['comparison']['accepted_evidence']
        with self.assertRaises(AssertionError):validate(rows)

    def test_modified_response_comparison_uses_verifier_input(self):
        rows=read_rows(INDEX)
        entry=next(e for r in rows if r['scenario_id']=='EX2_L_OR_FIRST'
                   for e in r['failure_modes'] if e['tag']=='unsupported_guessing')
        refs=[entry['evidence'][entry['comparison'][key]] for key in ['accepted_evidence','counterexample_evidence']]
        artifact=json.loads((ROOT/refs[0]['path']).read_text(encoding='utf8'))
        note=comparison_note(*refs,*[selected(artifact,ref['selector']) for ref in refs])
        self.assertIn('call names and arguments are unchanged',note)
        self.assertIn('result.devices[0].state.power',note)
        self.assertIn('verifier-only projection',note)


if __name__=='__main__':unittest.main()
