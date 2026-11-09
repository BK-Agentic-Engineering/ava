"""Validate the portable candidate. Optional source reconciliation uses local originals."""
import argparse
import json
import importlib.util
from pathlib import Path

import sys

_previous_bytecode_setting=sys.dont_write_bytecode
sys.dont_write_bytecode=True
try:
    _grounding_spec=importlib.util.spec_from_file_location('candidate_trace_grounding',Path(__file__).with_name('trace_grounding.py'))
    _grounding=importlib.util.module_from_spec(_grounding_spec)
    _grounding_spec.loader.exec_module(_grounding)
    _answers_spec=importlib.util.spec_from_file_location('candidate_scoped_answers',Path(__file__).with_name('grade_final_wave_answers.py'))
    _answers=importlib.util.module_from_spec(_answers_spec)
    _answers_spec.loader.exec_module(_answers)
finally:
    sys.dont_write_bytecode=_previous_bytecode_setting



def rows(path):return [json.loads(x) for x in path.read_text(encoding='utf8').splitlines()]
def read(path):return json.loads(path.read_text(encoding='utf8'))


def validate(package,source_root=None):
    meta=read(package/'metadata.json');manifest=rows(package/'eligibility.jsonl')
    byid={r['scenario_id']:r for r in manifest};assert len(byid)==len(manifest)==meta['inventory']['scenarios'],'manifest IDs'
    assert len({r['world_id'] for r in manifest})==meta['inventory']['worlds']
    assert all(r['source_status']=='spec_only' and r['source_exportable'] is False for r in manifest)
    assert {r['scenario_id'] for r in manifest if r['original_hold']}==set(meta['original_holds'])
    assert all(r['eligibility']=='held' for r in manifest if r['original_hold'])
    assert set(r['eligibility'] for r in manifest)<={'ready_for_training_integration','needs_repair','held'}
    schemas=read(package/'tool_schemas.json');reviews={r['scenario_id']:r for r in rows(package/'private/answer_reviews.jsonl')}
    from collections import Counter
    assert Counter(r['eligibility'] for r in manifest)==Counter(meta['eligibility_counts'])
    assert Counter(r['intended_split'] for r in manifest)=={'train':meta['inventory']['train'],'dev':meta['inventory']['dev']}
    ids=set();group_splits={};evidence_cache={};required=0
    for file,split,count in [('training.jsonl','train',meta['training_rows']),('development.jsonl','dev',meta['development_rows'])]:
        demos=rows(package/file);assert len(demos)==count
        for d in demos:
            assert set(d)=={'scenario_id','agent_visible','tool_schema_names','assistant_target'},'private fields in demo'
            sid=d['scenario_id'];assert sid not in ids,'duplicate export';ids.add(sid);m=byid[sid]
            assert m['eligibility']=='ready_for_training_integration' and m['intended_split']==split
            assert m['demonstration']=={'file':file,'scenario_id':sid}
            group=m['proposed_content_group'];assert group_splits.setdefault(group,split)==split,'active content group crosses train/dev'
            v=d['agent_visible'];t=d['assistant_target']
            def no_private(value):
                if isinstance(value,dict):
                    assert not set(value)&{'oracle_draft','initial_state','final_state','fixture_variant','world_id','lineage_id','_meta','witnesses'},'private material in model input'
                    for child in value.values():no_private(child)
                elif isinstance(value,list):
                    for child in value:no_private(child)
            no_private(v)
            assert set(v)<={'request','context','history','allowed_tools'},'unexpected visible field needs inspection'
            assert set(t)=={'calls','final_text','final_text_origin','absence_reason','termination','outcome'}
            effective=set(v['allowed_tools'])|{'sys.ask_missing_info'}
            assert set(d['tool_schema_names'])==effective and effective<=schemas.keys()
            for turn in v.get('history',[]):
                assert len(turn.get('tool_calls',[]))==len(turn.get('tool_results',[])),'unpaired history'
            for c in t['calls']:
                assert set(c)=={'name','arguments','result'},'private field in call'
                assert c['name'] in effective and isinstance(c['arguments'],dict) and isinstance(c['result'],dict)
            assert not _grounding.unsupported_identifiers(v,t['calls']),'unsupported query/identifier source'
            text=t['final_text']
            if sid in _answers.RULES:assert _answers.grade(sid,v,t['calls'],text)['verdict']=='pass','scoped answer not supported'
            if m['answer_obligation']=='required':
                required+=1;assert isinstance(text,str) and text.strip(),'missing required answer'
                assert m['answer_review'] in {'existing_scoped_answer_verdict','bounded_author_review','bounded_author_review_and_existing_scoped_pilot_check'}
            if text is None:assert t['absence_reason'] and m['answer_obligation']!='required'
            if sid in reviews:
                r=reviews[sid];assert text==r['text'],'answer target differs from reviewed version'
                assert r['rationale'] and r['source']==m['validation_evidence'],'answer review/evidence binding'
            assert t['termination']==('waiting_for_user' if t['outcome']=='ask_missing' else 'completed')
            if source_root is not None:
                ref=m['validation_evidence'];ep=ref['path']
                if ep not in evidence_cache:evidence_cache[ep]=read(source_root/ep)
                e=evidence_cache[ep];row=e['replays'][ref['replay_row_index']]
                assert row['scenario_id']==sid and row['trace_case']==ref['trace_case'],'cross-case evidence'
                verdict=row['verdict'];assert verdict.get('verdict')=='pass' or verdict.get('passed') is True
                assert t['calls']==[{k:c[k] for k in ['name','arguments','result']} for c in row['calls']],'calls/results changed'
                views=e.get('agent_visible',{});refkey=row.get('initial_fixture_ref',sid)
                original=e.get('scenarios',{}).get(sid,{}).get('agent_visible',views.get(sid,views.get(refkey)))
                if original is None:
                    import yaml
                    original=yaml.safe_load((source_root/m['design']).read_text(encoding='utf8'))['scenarios'][m['scenario_index']]['agent_visible']
                assert v==original,'visible input changed or stale'
                init=m['private_initialization_ref'];snapshot=e
                for key in init['selector']:snapshot=snapshot[key]
                assert isinstance(snapshot,dict),'post-history selector'
                assert m['private_clock_permissions']['current_time']==v.get('context',{}).get('current_time')
                assert set(m['private_clock_permissions']['effective_tools'])==effective
                assert m['private_clock_permissions']['history_already_executed'] is True
                if sid in reviews:
                    originals={r['scenario_id']:r for r in rows(source_root/'data/synthetic/dataset_v1_answer_targets.jsonl')}
                    assert reviews[sid]==originals[sid],'reviewed answer source changed'
                if sid not in reviews:assert text==row.get('final_text',row.get('authored_final_text')),'unreviewed answer mutation'
    assert ids=={sid for sid,m in byid.items() if m['eligibility']=='ready_for_training_integration'},'eligible/export mismatch'
    assert len(reviews)==meta['answers_completed_in_demonstrations']
    if source_root is not None:
        # This optional check uses source's existing PyYAML, not a bundled dependency.
        import yaml
        from functools import cache
        @cache
        def design(path):return yaml.safe_load((source_root/path).read_text(encoding='utf8'))
        current={s['scenario_id'] for p in (source_root/'data/synthetic/design').glob('*.yaml') for s in design(str(p.relative_to(source_root)))['scenarios']}
        assert current==set(byid),'source collection changed'
        for m in manifest:
            s=design(m['design'])['scenarios'][m['scenario_index']];assert s['scenario_id']==m['scenario_id']
            ref=m['validation_evidence'];ep=ref['path']
            if ep not in evidence_cache:evidence_cache[ep]=read(source_root/ep)
            row=evidence_cache[ep]['replays'][ref['replay_row_index']]
            assert row['scenario_id']==m['scenario_id'] and row['trace_case']==ref['trace_case']
            assert row['verdict']==m['reference_verdict'],'saved verdict mismatch'
            for name in ['private_initialization_ref','private_final_state_ref']:
                loc=m[name];value=evidence_cache[ep]
                for key in loc['selector']:value=value[key]
                assert isinstance(value,dict)
            assert m['private_oracle_ref']['scenario_index']==m['scenario_index']
    return {'source_scenarios':len(manifest),'eligible_training':meta['training_rows'],'eligible_development':meta['development_rows'],
            'eligibility_counts':meta['eligibility_counts'],'required_export_answers':required,'source_reconciled':source_root is not None}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--package',type=Path,default=Path(__file__).resolve().parent);p.add_argument('--source-root',type=Path)
    a=p.parse_args();print(json.dumps(validate(a.package,a.source_root),ensure_ascii=False,sort_keys=True))
