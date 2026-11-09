"""Reconcile manual failure-mode mappings; never assign semantic tags."""
import argparse
import difflib
from collections import Counter
import json
from pathlib import Path

from replay_train_wave_08 import ROOT, load_design

INDEX = ROOT / 'artifacts/synthetic/failure_mode_index.jsonl'
GUIDE = ROOT / 'docs/implementation/FAILURE_MODE_INDEX.md'
TAGS = {
    'wrong_target': 'Wrong entity, recipient, device, event or source object.',
    'wrong_tool': 'Operation differs from the requested action, such as send instead of save draft.',
    'unsupported_guessing': 'ID, value or argument lacks sufficient visible or observed evidence.',
    'missed_context': 'Relevant current time, timezone, location, profile or other context is ignored.',
    'missed_history': 'Relevant earlier selection, correction, reference or fact is ignored.',
    'insufficient_information': 'Required information has not been resolved, including justified clarification.',
    'constraint_violation': 'Permissions, negation, scope, cardinality, order or preservation are violated.',
    'bad_recovery': 'Unjustified next step after error/no-op, or missing explicitly authorized recovery.',
    'unsupported_answer': 'Factual answer unsupported by the relevant evidence, including wrong subject or omitted facts.',
}
STATUSES = {'design_support_only', 'verifier_evidence_present_not_causally_isolated',
            'isolated_authored_counterexample','isolated_authored_answer_probe',
            'isolation_not_assessed'}


def isolated_ids(rows, tag):
    return {r['scenario_id'] for r in rows for e in r['failure_modes']
            if e['tag']==tag and e['evidence_status'] in
            {'isolated_authored_counterexample','isolated_authored_answer_probe'}}


def accepted_runtime_reference(ref, source, artifact, standard_index):
    assert ref['selector'].startswith('/replays/')
    assert not source.get('evidence_kind','').startswith('verifier')
    # Old dev records omit per-row provenance; their artifact and runner source
    # describe the actual authored runtime replay. Never accept an unlabeled
    # modified probe merely because its verdict passes.
    assert source.get('evidence_kind')=='actual_runtime_trace' or (
        'evidence_kind' not in source and any(word in artifact.get('kind','')
                                            for word in ['runtime','replay']))
    return ref['selector']==f'/replays/{standard_index}'


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf8').splitlines()]


def selected(data, pointer):
    assert pointer.startswith('/')
    for key in pointer.split('/')[1:]:
        key = key.replace('~1', '/').replace('~0', '~')
        data = data[int(key)] if isinstance(data, list) else data[key]
    return data


def comparison_note(accepted_ref, negative_ref, accepted, negative):
    """Render observed differences from the two linked records, without causal inference."""
    def label(ref):
        name=ref.get('trace_case',ref.get('probe','record'))
        return name+(f" [{ref['ordering']}]" if 'ordering' in ref else '')+f" ({ref['selector']})"
    lead=f"{label(accepted_ref)} versus {label(negative_ref)}: "
    if negative_ref['evidence_type']=='authored_answer_probe':
        text=accepted.get('text',accepted.get('authored_final_text'))
        return (lead+f"the authored answer changes from {text!r} to {negative['text']!r}, on the same standard trace. "
                +f"Recorded trace verdict: {negative['verdict']['trace_verdict']}; answer verdict: "
                +f"{negative['verdict']['answer_verdict']} ({negative['verdict']['answer_reason']}). "
                +'This is an authored answer probe, not model output.')
    projected='verifier_input_calls' in negative
    left=accepted['calls'];right=negative.get('verifier_input_calls',negative['calls'])
    key=lambda c:json.dumps([c['name'],c['arguments']],ensure_ascii=False,sort_keys=True)
    def changed_paths(a,b,path=''):
        if a==b:return []
        if isinstance(a,dict) and isinstance(b,dict):
            return [leaf for key in sorted(a.keys()|b.keys()) for leaf in
                    ([path+'.'+key] if key not in a or key not in b else changed_paths(a[key],b[key],path+'.'+key))]
        if isinstance(a,list) and isinstance(b,list) and len(a)==len(b):
            return [leaf for i,(x,y) in enumerate(zip(a,b)) for leaf in changed_paths(x,y,f'{path}[{i}]')]
        return [path]
    differences=[];response_changes=[]
    for op,i,j,k,l in difflib.SequenceMatcher(None,list(map(key,left)),list(map(key,right)),autojunk=False).get_opcodes():
        if op=='equal':
            for a,b in zip(range(i,j),range(k,l)):
                paths=changed_paths(left[a].get('result'),right[b].get('result'),'result')
                if paths:response_changes.append(left[a]['name']+' '+', '.join(paths[:3])+(f' (and {len(paths)-3} other changed paths)' if len(paths)>3 else ''))
        elif op=='delete':differences.append('remove '+', '.join(c['name'] for c in left[i:j]))
        elif op=='insert':differences.append('add '+', '.join(c['name'] for c in right[k:l]))
        elif j-i==l-k and all(x['name']==y['name'] for x,y in zip(left[i:j],right[k:l])):
            for x,y in zip(left[i:j],right[k:l]):
                a,b=x['arguments'],y['arguments']
                keys=sorted(key for key in a.keys()|b.keys() if (key in a)!=(key in b) or a.get(key)!=b.get(key))
                if keys:differences.append('change '+x['name']+' arguments: '+', '.join(keys))
        else:
            differences.append('replace '+', '.join(c['name'] for c in left[i:j])+' with '+', '.join(c['name'] for c in right[k:l]))
    note=lead+('; '.join(differences) if differences else 'call names and arguments are unchanged')+'. '
    if response_changes:note+='Aligned responses also differ: '+', '.join(dict.fromkeys(response_changes))+'. '
    if 'final_state' in accepted and 'final_state' in negative:
        note+='Recorded final state '+('matches' if accepted['final_state']==negative['final_state'] else 'differs from')+' the accepted record. '
    reasons=[]
    for key,value in negative['verdict'].items():
        if (key.endswith('reasons') or key in {'state','trace','grounding','authorization','text_errors'}) and isinstance(value,list):
            reasons.extend(str(v) for v in value)
    note+='Recorded rejection'+(' reasons: '+', '.join(dict.fromkeys(reasons)) if reasons else ' is retained verbatim in the evidence reference')+'. '
    if projected:note+='The changed response is a verifier-only projection, not a new SDK result. '
    return note+'Multiple rejection reasons are not counted as independent defects. Isolation status and scenario-wide limitations are recorded separately.'


def validate(rows):
    ledger = read_rows(ROOT/'artifacts/synthetic/quality_audit_1000/per_sample_review.jsonl')
    audit = {r['scenario_id']:r for r in ledger}
    assert len(rows) == len({r['scenario_id'] for r in rows}) == len(audit) == 1000
    assert {r['scenario_id'] for r in rows} == set(audit)
    docs, artifacts, rationales = {}, {}, set()
    for row in rows:
        sid = row['scenario_id']; old = audit[sid]
        for key in ['world_id','lineage_id','split','content_disposition','design_status','exportable','oracle_review_status']:
            assert row[key] == old[key], (sid,key)
        assert row['hold'] == (old['content_disposition'] != 'acceptable within scope')
        if row['hold']:assert row['hold_information'] == old['judgment']
        assert selected(ledger, '/'+str(row['audit_ref']['line']-1))['scenario_id'] == sid
        assert row['audit_ref']['path'] == 'artifacts/synthetic/quality_audit_1000/per_sample_review.jsonl'
        path = row['design_ref']['path']
        if path not in docs:docs[path] = load_design(ROOT/path)
        scenario = selected(docs[path],row['design_ref']['selector'])
        assert scenario['scenario_id'] == sid
        assert scenario['world_id'] == row['world_id'] and scenario['lineage_id'] == row['lineage_id']
        assert scenario['status'] == 'spec_only' and not scenario.get('exportable',False)
        assert row['expected_behavior'].strip()
        if not row['individually_reviewed']:
            assert row['failure_modes'] == [] and row['mapping_limitations']
            continue
        assert row['failure_modes'] or row['mapping_limitations']
        for entry in row['failure_modes']:
            assert entry['tag'] in TAGS
            assert entry['role'] in {'intended challenge','control','additional verifier check'}
            assert entry['evidence_status'] in STATUSES
            assert entry['rationale'].strip() and entry['rationale'] not in rationales, sid
            rationales.add(entry['rationale'])
            assert entry['evidence_gap'].strip()
            types=[]; isolated_answer=False
            for ref in entry['evidence']:
                path=ref['path'];target=(ROOT/path).resolve()
                assert target.is_relative_to(ROOT) and target.is_file()
                if ref['evidence_type']=='design_rationale':
                    if path==row['design_ref']['path']:
                        assert ref['selector']==row['design_ref']['selector']+'/oracle_draft'
                        selected(docs[path],ref['selector'])
                    else:
                        assert path=='data/synthetic/factual_answer_pilot.yaml'
                        if path not in docs:docs[path]=load_design(ROOT/path)
                        parts=ref['selector'].split('/')
                        assert len(parts)==5 and parts[1]=='cases' and parts[3]=='probes'
                        case=docs[path]['cases'][int(parts[2])]
                        probe=selected(docs[path],ref['selector'])
                        assert case['scenario_id']==sid and case['request']==scenario['agent_visible']['request']
                        assert ref['support_kind']=='authored_answer_probe_definition'
                        assert ref['probe_id']==probe['id'] and ref['specified_expected_judgment']==probe['expect']
                    types.append('design');continue
                if path not in artifacts:artifacts[path]=json.loads(target.read_text(encoding='utf8'))
                assert path==old['evidence'], (sid,path)
                source=selected(artifacts[path],ref['selector'])
                assert source['scenario_id']==ref['scenario_id']==sid
                for key in ['trace_case','ordering','probe','probe_kind','case','verdict']:
                    if key in source:assert ref[key]==source[key],(sid,key)
                verdict=source['verdict']
                passed=(verdict.get('verdict')=='pass' or verdict.get('passed') is True
                        or verdict.get('overall')=='pass')
                if ref['evidence_type']=='authored_answer_probe':
                    assert ref['selector'].startswith('/answer_probes/')
                    assert source['provenance']=='authored_answer_probe'
                    assert ref['trace_ref']==source['trace_ref']==sid+'/standard'
                    types.append('answer_positive' if passed else 'negative')
                    isolated_answer |= verdict.get('trace_verdict')=='pass' and verdict.get('answer_verdict')=='fail'
                elif ref['evidence_type']=='accepted_authored_runtime_trace':
                    assert passed
                    standard=accepted_runtime_reference(ref,source,artifacts[path],old['reference_row_index'])
                    types.append('reference' if standard else 'alternative')
                else:
                    assert not passed, (sid,ref['trace_case'])
                    modified=source.get('evidence_kind','').startswith('verifier')
                    assert ref['evidence_type']==('verifier_only_or_modified_evidence_probe' if modified
                                                else 'authored_runtime_counterexample')
                    assert verdict.get('verdict')=='reject' or verdict.get('passed') is False or verdict.get('overall')=='fail'
                    types.append('negative')
            assert 'design' in types and 'reference' in types
            if entry['evidence_status']=='isolated_authored_answer_probe':assert isolated_answer
            assert ('negative' not in types)==(entry['evidence_status']=='design_support_only')
            if 'negative' in types:
                pair=entry['comparison']
                a,n=(entry['evidence'][pair[key]] for key in ['accepted_evidence','counterexample_evidence'])
                assert a['evidence_type'] in {'accepted_authored_runtime_trace','authored_answer_probe'}
                assert n['evidence_type'] in {'authored_runtime_counterexample','verifier_only_or_modified_evidence_probe','authored_answer_probe'}
                left=selected(artifacts[a['path']],a['selector']);right=selected(artifacts[n['path']],n['selector'])
                assert left['verdict'].get('verdict')=='pass' or left['verdict'].get('passed') is True
                assert right['verdict'].get('verdict')=='reject' or right['verdict'].get('passed') is False
                assert entry['evidence_gap']==comparison_note(a,n,left,right),(sid,entry['tag'],'stale comparison')
        for ref in row.get('context_evidence',[]):
            path=ref['path']
            assert path==old['evidence']
            if path not in artifacts:artifacts[path]=json.loads((ROOT/path).read_text(encoding='utf8'))
            source=selected(artifacts[path],ref['selector'])
            assert ref['evidence_type']=='scenario_review_context'
            assert source['scenario_id']==ref['scenario_id']==sid
            for key in ['trace_case','ordering','probe','verdict']:assert ref.get(key)==source.get(key)
            kind=('verifier_only_or_modified_evidence_probe' if source.get('evidence_kind','').startswith('verifier') or source.get('provenance')=='modified_evidence_verifier_probe' else 'authored_answer_probe' if source.get('provenance')=='authored_answer_probe' else 'authored_runtime_trace')
            assert ref['source_kind']==kind
    assert sum(r['hold'] for r in rows)==16
    return {'total_ids':1000,'individually_reviewed':sum(r['individually_reviewed'] for r in rows),
            'awaiting_mapping_review':sum(not r['individually_reviewed'] for r in rows),
            'reviewed_but_unmapped':sum(r['individually_reviewed'] and not r['failure_modes'] for r in rows),
            'holds':16,'export_eligible':0,
            'reviewed_by_split':dict(Counter(r['split'] for r in rows if r['individually_reviewed'])),
            'pending_by_split':dict(Counter(r['split'] for r in rows if not r['individually_reviewed'])),
            'resume_at':next((r['scenario_id'] for r in rows if not r['individually_reviewed']),None),
            'unique_scenarios_per_tag':{tag:sum(any(e['tag']==tag for e in r['failure_modes']) for r in rows) for tag in TAGS},
            'unique_scenarios_per_evidence_status':{status:sum(any(e['evidence_status']==status for e in r['failure_modes']) for r in rows) for status in sorted(STATUSES)},
            'unique_scenarios_per_evidence_type':{kind:sum(any(ref['evidence_type']==kind for e in r['failure_modes'] for ref in e['evidence']) for r in rows)
                for kind in ['design_rationale','accepted_authored_runtime_trace','authored_runtime_counterexample',
                             'verifier_only_or_modified_evidence_probe','authored_answer_probe']},
            'actual_model_failure_records':0,
            'mapping_entries':sum(len(r['failure_modes']) for r in rows),
            'anchored_comparisons':sum('comparison' in e for r in rows for e in r['failure_modes']),
            'scenario_context_references':sum(len(r.get('context_evidence',[])) for r in rows)}


def guide(rows,summary):
    reviewed=summary['individually_reviewed'];pending=summary['awaiting_mapping_review']
    state='complete individual mapping' if not pending else 'incomplete mapping checkpoint'
    lines=[f'# Failure-mode index — {state}', '',
        f"**{reviewed:,}/1,000 individually reviewed; {pending} pending.** Reviewed-but-unmapped: {sum(r['individually_reviewed'] and not r['failure_modes'] for r in rows)}. All 1,000 IDs occur once. Prior quality-audit review and this mapping review are separate.", '',
        '[Index](../../artifacts/synthetic/failure_mode_index.jsonl) · [Audit](SYNTHETIC_1000_QUALITY_AUDIT.md)', '',
        'Counts use unique scenario IDs, with denominator 1,000. Tags and evidence statuses overlap; sums need not equal the collection size. These are designed cases, not independent statistical samples or model error rates. Unreviewed rows carry no inferred tags.', '',
        '| Tag | IDs | Train | Dev | Design-only | Isolation not assessed | Isolated authored negative |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for tag in TAGS:
        matched=[r for r in rows if any(e['tag']==tag for e in r['failure_modes'])]
        only={r['scenario_id'] for r in matched for e in r['failure_modes'] if e['tag']==tag and e['evidence_status']=='design_support_only'}
        unassessed={r['scenario_id'] for r in matched for e in r['failure_modes'] if e['tag']==tag and e['evidence_status'] in {'isolation_not_assessed','verifier_evidence_present_not_causally_isolated'}}
        lines.append(f"| {tag} | {len(matched)} | {sum(r['split']=='train' for r in matched)} | {sum(r['split']=='dev' for r in matched)} | {len(only)} | {len(unassessed)} | {len(isolated_ids(rows,tag))} |")
    lines += ['',f"Reviewed intended splits: {summary['reviewed_by_split'].get('train',0)} train, {summary['reviewed_by_split'].get('dev',0)} dev. Pending mapping reviews: {pending}. Resume: **{summary['resume_at'] or 'none'}**.", '',
              '| Evidence status | Unique IDs | Train | Dev |','| --- | ---: | ---: | ---: |']
    for status,count in summary['unique_scenarios_per_evidence_status'].items():
        matched=[r for r in rows if any(e['evidence_status']==status for e in r['failure_modes'])]
        lines.append(f"| {status} | {count} | {sum(r['split']=='train' for r in matched)} | {sum(r['split']=='dev' for r in matched)} |")
    lines += ['', '| Evidence type | Unique IDs |','| --- | ---: |']
    lines += [f'| {kind} | {count} |' for kind,count in summary['unique_scenarios_per_evidence_type'].items()]
    lines += ['| Actual model failure | 0 |', '',
        'The isolated-negative column is the union of runtime and answer-probe scenario IDs, never their sum. State changes and multiple verdict reasons can be consequences of one error, not independent defects. Isolation not assessed means no causal-isolation conclusion was reached. Per-entry comparisons name their accepted and negative records and are checked against source-derived differences. Scenario-wide limitations remain separate; context_evidence resolves other records mentioned there without adding tag coverage or isolated-negative counts.', '',
        f"The consistency review covers all {summary['mapping_entries']:,} entries: {summary['anchored_comparisons']:,} accepted/negative comparisons and {summary['mapping_entries']-summary['anchored_comparisons']:,} design-only entries. The {summary['scenario_context_references']} context references identify additional records discussed in scenario-level notes and do not increase tag coverage. The TR9_NEWS_LOOK and TR10_CLIMATE_FAN missing-read comparisons now describe their linked unobserved paths, separately from the wrong-write paths. No tag, hold, split, gold or evidence-status promotion follows from this cleanup.", '',
        '## Use and evidence boundaries', '',
        '```powershell','python -X utf8 scripts/check_failure_mode_index.py',
        'python -X utf8 scripts/check_failure_mode_index.py --tag wrong_target',
        'python -X utf8 scripts/check_failure_mode_index.py --scenario TR16_PARCEL_DELIVERED',
        'python -X utf8 scripts/check_failure_mode_index.py --pending-ids',
        'python -X utf8 scripts/check_failure_mode_index.py --require-complete','```', '',
        'The JSONL is the exhaustive mapping; this guide selects at most two examples per category. Runtime and executed-probe references retain file, exact selector, scenario_id, trace_case/probe, ordering where present, and actual verdict. The eight earlier factual-sidecar probe definitions retain their specified expected judgments as design support only; no standalone executed result is distributed for those definitions. Standard authored reference anchors remain mandatory; accepted runtime alternatives may additionally clarify a comparison. Modified/verifier-only probes, authored answer probes, design-only support and runtime counterexamples remain distinct. None is an actual model failure. Context references include passing repeats, negative paths or unresolved wording checks only to identify scenario-level notes; they are not automatically evidence for every tag. --write-guide renders only existing mappings and never assigns tags.', '',
        'Official contest score, local task/state/grounding correctness and optional factual-answer/efficiency diagnostics are separate. Semantic alternatives need not have equal fixed-reference tool-call scores. Empty-gold contest scoring requires empty submitted calls. A repeated-no-op rejection can be a local trace policy rather than a different final-state error.', '',
        '## Taxonomy and worked examples', '']
    for tag,definition in TAGS.items():
        lines += [f'### {tag}', '',definition,'']
        examples=[(i,r,e) for i,r in enumerate(rows,1) for e in r['failure_modes'] if e['tag']==tag]
        preferred={
            'wrong_target':['S1','TR18_WORK_A'],
            'wrong_tool':['TR1_E_DRAFT','TR1_E_SEND'],
            'unsupported_guessing':['B02_E_B','H1'],
            'missed_context':['EX2_R_FUTURE','TR20_CAL_TODAY_UTC'],
            'missed_history':['H1','TR20_CONTACT_OLD'],
            'insufficient_information':['B02_N_C','B02_E_C'],
            'constraint_violation':['N3','TR16_APP_KEEP'],
            'bad_recovery':['TR16_PARCEL_DELIVERED','TR13_APP_FAILED_RESTART'],
            'unsupported_answer':['TR19_DEVICE_FAN_POWER','TR19_TWO_CAL_REM'],
        }[tag]
        examples.sort(key=lambda item:preferred.index(item[1]['scenario_id']) if item[1]['scenario_id'] in preferred else len(preferred))
        chosen=[]
        for item in examples:
            if item[1]['scenario_id'] not in {x[1]['scenario_id'] for x in chosen}:chosen.append(item)
            if len(chosen)==2:break
        for line,row,entry in chosen:
            design=load_design(ROOT/row['design_ref']['path'])
            request=selected(design,row['design_ref']['selector'])['agent_visible']['request']
            lines.append(f"- [{row['scenario_id']}](../../artifacts/synthetic/failure_mode_index.jsonl#L{line}) — User: “{request}” {entry['rationale'].rstrip('.')}. ({entry['role']}; {entry['evidence_status']})")
            if 'comparison' in entry:
                pair=entry['comparison']
                refs=[entry['evidence'][pair[key]] for key in ['accepted_evidence','counterexample_evidence']]
                # Detailed payloads/verdict objects stay in the linked source, not Markdown prose.
                detail=entry['evidence_gap'].split('Recorded trace verdict')[0].split('Recorded rejection')[0].strip()
                lines.append('  Authored contrast: '+detail)
            else:
                refs=[ref for ref in entry['evidence'] if ref['evidence_type']=='accepted_authored_runtime_trace'][:1]
                lines.append('  Design support only: no counterexample is linked for this tag.')
            links=[]
            for ref in refs:
                name=ref.get('trace_case',ref.get('probe','record'))
                verdict=ref['verdict']
                status=verdict.get('verdict','pass' if verdict.get('passed') is True else 'reject' if verdict.get('passed') is False else 'unresolved')
                reasons=[str(reason) for key,value in verdict.items() if (key.endswith('reasons') or key in {'state','trace','grounding','text_errors'}) and isinstance(value,list) for reason in value]
                if verdict.get('answer_verdict')=='fail':reasons.append(verdict['answer_reason'])
                detail=': '+', '.join(dict.fromkeys(reasons)) if reasons else ''
                links.append(f"[{name}](../../{ref['path']}) `{ref['selector']}` ({ref['evidence_type']}; {status}{detail})")
            lines.append('  Evidence: '+'; '.join(links)+'.')
        if not chosen:lines.append('No reviewed mapping yet; this is not evidence of absent collection coverage.')
        lines.append('')
    lines += ['## Overlap and unresolved questions', '',
        '- Wrong recipient and unsupported recipient ID are different: S1 pairs two real inconsistent identities; B02_E_B guesses the correct address without reading it. Correct state does not cure missing source evidence.',
        '- N1/N2 use clock context; H1/H2 need historical event selection. C1/C2 have history but current get_ride resolves the target, so mere history presence is not a missed_history tag.',
        '- B02_N_C must inspect source absence and ask time; unrelated valid time is not evidence. In-utterance correction (T1 or EX3_T_B) is not conversation history.',
        '- An error/no-op trace alone does not establish bad_recovery; observe-only alone does not establish unsupported_answer. TR16 delivered recovery and TR19 fan wrong-subject probes provide specific mechanisms.',
        '- All 16 holds remain active: seven mail split holds, six Wave 17 independent reviews, B05_L_D and two Wave 11 chore policies. Mapping review never adjudicates these. All cases stay spec_only/non-exportable.',
        '- Source-witness limits for later review: TR9_NEWS_LOOK includes the queried publisher in its witness, and TR10_CLIMATE_FAN does not bind the requested room in its source witness. Their per-ID mappings describe the actual selected trace checks, not new defect reproductions. Inspect their design/oracle through --scenario before extending the fixture distribution.',
        '- Observation-necessity questions remain distinct from hidden-value guessing: TR10_REM_COPYONCE and TR10_ALARM_COPYSILENT retain their recorded rules; explicit text supplied by the user does not become hidden merely because a local verifier requires a read. See each mapping for the relevant scope rather than inferring a policy change.',
        '- Eight earlier factual-sidecar mappings use probe definitions/expected judgments as design support only. The 100 Wave 19 and 26 Wave 20 answer mappings link stored answer verdicts. An observe-only trace success alone is not factual-answer coverage.',
        '- Finite text rules, design-only entries and entries without examined isolation remain limitations. Unknown plausible answers are not invented model failures. No new taxonomy category is introduced.', '',
        'Exact pending IDs are individually_reviewed=false rows; --pending-ids prints them. Reviewed-but-unmapped rows must carry a case-specific reason. No gold, fixture, canonical replay, verifier, split or hold changes belong to this index.', '']
    return '\n'.join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-guide',action='store_true')
    parser.add_argument('--require-complete',action='store_true')
    parser.add_argument('--pending-ids',action='store_true')
    parser.add_argument('--reviewed-ids',action='store_true')
    parser.add_argument('--tag',choices=TAGS)
    parser.add_argument('--scenario')
    args=parser.parse_args();rows=read_rows(INDEX);summary=validate(rows)
    rendered=guide(rows,summary)
    if args.write_guide:GUIDE.write_text(rendered,encoding='utf8')
    else:assert GUIDE.read_text(encoding='utf8')==rendered,'Guide counts/mappings are stale'
    if args.scenario:
        print(json.dumps(next(r for r in rows if r['scenario_id']==args.scenario),ensure_ascii=False,indent=2))
    elif args.pending_ids or args.reviewed_ids or args.tag:
        ids=[r['scenario_id'] for r in rows if (args.pending_ids and not r['individually_reviewed'])
             or (args.reviewed_ids and r['individually_reviewed'])
             or (args.tag and any(e['tag']==args.tag for e in r['failure_modes']))]
        print('\n'.join(ids))
    else:print(json.dumps(summary,ensure_ascii=False,indent=2))
    if args.require_complete and summary['awaiting_mapping_review']:
        raise SystemExit('INCOMPLETE: individual mapping review remains outstanding.')


if __name__=='__main__':main()
