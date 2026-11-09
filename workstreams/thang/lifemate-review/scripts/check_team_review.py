"""Read-only package bookkeeping and saved aggregate reconciliation; no scoring."""
import ast
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    from check_synthetic_quality_audit import check
    result = check()
    assert result['rows'] == result['direct_semantic_inspections'] == 1000
    assert result['dispositions'] == {'acceptable within scope':984,
        'pending semantic/policy adjudication':16}
    assert result['export_eligible'] == result['awaiting_direct_inspection'] == 0
    ledger = [json.loads(x) for x in (ROOT/'artifacts/synthetic/quality_audit_1000/per_sample_review.jsonl').read_text(encoding='utf8').splitlines()]
    holds = {r['scenario_id'] for r in ledger if r['content_disposition'] != 'acceptable within scope'}
    assert holds == {'B05_L_D','TR11_CHORE_PAIR','TR11_CHORE_EXPLICIT',
        'TR1_E_DRAFT','TR1_E_SEND','TR1_E_REPLY','TR1_E_REPLY_OTHER',
        'TR1_E_DRAFT_CC','TR1_E_SEND_CC','TR1_E_TWO_DRAFTS',
        'TR17_CAL_SHIFT','TR17_CAL_LONG','TR17_CAL_REPHRASE','TR17_CAL_EXTEND','TR17_CAL_EARLY','TR17_CAL_OTHER'}
    for dataset,n,words,chars,word_edits,char_edits in [
        ('vimd_20261101',2026,132471,436649,(9263,17393),(23714,45319)),
        ('vnslu_20261102',2401,32351,102236,(6566,5661),(18172,12788))]:
        metrics=json.loads((ROOT/f'artifacts/scoring/valsea_vs_gipformer_{dataset}/metrics.json').read_text(encoding='utf8'))
        models=({k:v['overall'] for k,v in metrics['models'].items()}
                if 'models' in metrics else metrics['overall'])
        for i,name in enumerate(['gipformer','valsea']):
            row=models[name]
            assert (row['n'],row['words'],row['chars'],row['word_errors'],row['char_errors']) == (n,words,chars,word_edits[i],char_edits[i])
            assert abs(row['wer_whitespace'] - row['word_errors']/words)<1e-14
            assert abs(row['cer'] - row['char_errors']/chars)<1e-14
    selection=json.loads((ROOT/'FILE_SELECTION.json').read_text(encoding='utf8'))
    assert all((ROOT/file).is_file() for file in selection['files'])
    for path in ROOT.rglob('*.py'):
        ast.parse(path.read_text(encoding='utf-8-sig'),filename=str(path))
    # Check packaged Markdown links; excluded source links are explicitly text.
    for path in ROOT.rglob('*.md'):
        for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)',path.read_text(encoding='utf8')):
            target=target.strip('<>');base=target.split('#')[0]
            if not base or '://' in target:continue
            assert (path.parent/base).exists(),(path.relative_to(ROOT),target)
    blind=(ROOT/'review/blind/reviewer_sheet_vi.md').read_text(encoding='utf8')
    assert len(re.findall(r'^## P\d+',blind,re.M))==6
    assert 'TR17_' not in blind and 'PRIVATE' not in blind
    assert not any(p.name == 'zaic_tools' for p in ROOT.rglob('*'))
    subprocess.run([sys.executable, str(ROOT/'dataset_v1_candidate/validate.py')], check=True)
    print('PASS: historical 1,000-ID snapshot and current candidate separately validated; aggregate totals, source map, syntax and links reconcile.')


if __name__=='__main__':
    main()
