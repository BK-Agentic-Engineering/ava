"""Check audit-table identity and references; never assign semantic judgments."""
import json
from collections import Counter
from pathlib import Path

from replay_train_wave_08 import ROOT, load_design, validate

TABLE = ROOT / 'artifacts/synthetic/quality_audit_1000/per_sample_review.jsonl'


def check(table=TABLE):
    docs = [load_design(p) for p in sorted((ROOT/'data/synthetic/design').glob('*.yaml'))]
    inventory = validate(next(d for d in docs if d['version']=='train_wave_14'), docs)
    inventory.pop('near_duplicate_review',None)  # A Wave 14 note is not this audit's finding.
    scenarios = {s['scenario_id']:s for d in docs for s in d['scenarios']}
    rows = [json.loads(line) for line in table.read_text(encoding='utf8').splitlines()]
    ids = [r['scenario_id'] for r in rows]
    assert len(ids)==len(set(ids))==len(scenarios)==1000
    assert set(ids)==set(scenarios)
    designs, evidence = {}, {}
    for row in rows:
        path = row['design']
        if path not in designs:designs[path] = load_design(ROOT/path)
        s = designs[path]['scenarios'][row['scenario_index']]
        assert s==scenarios[row['scenario_id']]
        assert row['world_id']==s['world_id'] and row['lineage_id']==s['lineage_id']
        world = next(w for w in designs[path]['worlds'] if w['world_id']==s['world_id'])
        assert row['split']==world['split']
        path = row['evidence']
        if path not in evidence:evidence[path] = json.loads((ROOT/path).read_text(encoding='utf8'))
        trace = evidence[path]['replays'][row['reference_row_index']]
        assert (trace['scenario_id'],trace['trace_case'])==(row['scenario_id'],row['reference_trace_case'])
        assert row['design_status']==s['status']=='spec_only'
        assert row['exportable']==s.get('exportable',False)==False
        assert row['content_disposition'] in {'acceptable within scope','needs repair','pending semantic/policy adjudication'}
        if not row['direct_semantic_inspection']:
            assert row['content_disposition']=='pending semantic/policy adjudication'
            assert row['judgment'].startswith('NOT INSPECTED')
        else:
            assert row['judgment'] and not row['judgment'].startswith('NOT INSPECTED')
    return {'inventory':inventory,'rows':len(rows),
            'direct_semantic_inspections':sum(r['direct_semantic_inspection'] for r in rows),
            'dispositions':dict(Counter(r['content_disposition'] for r in rows)),
            'awaiting_direct_inspection':sum(not r['direct_semantic_inspection'] for r in rows),
            'inspected_awaiting_adjudication':sum(r['direct_semantic_inspection'] and
                r['content_disposition']=='pending semantic/policy adjudication' for r in rows),
            'oracle_statuses':dict(Counter(r['oracle_review_status'] for r in rows)),
            'harness_acceptance':dict(Counter(r['harness_acceptance'] for r in rows)),
            'export_eligible':sum(r['exportable'] for r in rows),
            'unreviewed_ids':[r['scenario_id'] for r in rows if not r['direct_semantic_inspection']]}


if __name__=='__main__':
    result=check()
    # The full exact unreviewed set remains in the table; keep terminal output short.
    result['unreviewed_count']=len(result.pop('unreviewed_ids'))
    print(json.dumps(result,ensure_ascii=False,indent=2))
