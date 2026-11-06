# LifeMate: Thắng’s team review handoff

Thắng benchmarked two ASR systems on the full released test splits and prepared 1,000 Vietnamese text scenarios for local tool-use tests. GIPFormer 1.5 FP16 remains the ASR baseline. Agent performance on these WORLDs is still unmeasured.

- **Tài:** use the [three integration cases](integration/three_cases/README.md) to check what Jaz renders, which tools it exposes and what it records after a call. These cases exercise the interface.
- **Tú:** inspect the [clarification input](integration/three_cases/B02_N_C.input.json) alongside its [reference output](integration/three_cases/B02_N_C.output.json) to review message serialization and loss masking. Training export awaits agreement on that format and case eligibility.
- **Team:** review the [16 pending decisions](#decisions-still-pending). For the independent Vietnamese reading, send the blind sheet before the reader opens any gold-bearing files.

## 1. Completed GIPFormer–VALSEA ASR benchmark

| Official test distribution | Records | GIPFormer WER / CER | VALSEA WER / CER |
| --- | ---: | ---: | ---: |
| ViMD | 2,026 | 6.992% / 5.431% | 13.130% / 10.379% |
| VN-SLU author-released test | 2,401 | 20.296% / 17.775% | 17.499% / 12.508% |

GIPFormer has better official-reference agreement on ViMD; VALSEA has better agreement on VN-SLU. Keep the datasets separate: no pooled score, universal winner, semantic-slot accuracy or LifeMate task-success claim follows. ViMD has paired speaker-cluster intervals; VN-SLU lacks speaker/region metadata, so those intervals are unavailable. Its released count of 2,401 differs from the paper’s 2,454.

Start at the [canonical ASR closeout](docs/implementation/ASR_BENCHMARK_CLOSEOUT.md) for additive totals, regional results, uncertainty, frozen scoring rules, provider-version limits and interpretation. Saved aggregate evidence: [ViMD](artifacts/scoring/valsea_vs_gipformer_vimd_20261101/) and [VN-SLU](artifacts/scoring/valsea_vs_gipformer_vnslu_20261102/). Frozen GIPFormer dependency/revision settings: [ViMD configuration](benchmarks/vimd_gipformer_frozen_configuration.json) and [VN-SLU configuration](benchmarks/vnslu_gipformer_frozen_configuration.json); their implementation source field is omitted.

GIPFormer uses **FP16 weights with mixed computation, greedy decoding and one T4 / cuda:0**, with disclosed FP32 preprocessing/internals. This is not pure-FP16 arithmetic or an end-to-end A30 compliance measurement. VALSEA’s submitted flags do not prove backend processing; its varying engine labels are not immutable revisions, and hosted precision is unverified. Remote API timing is separate from local compute.

Full benchmark reference/prediction text, provider raw responses and audio remain local. Redistribution rights remain unresolved for the recorded ViMD license, VN-SLU release and provider outputs. Aggregates do not replace the authorized original inputs needed for rescoring. Completed requests do not establish usage rights or exactly-once remote processing.

## 2. Synthetic WORLD scenarios and local evidence

| Checkpoint | Status |
| --- | --- |
| Scenarios | **1,000**: 942 intended train, 58 dev, zero test |
| WORLDs / named lineages / ancestry components | 108 / 31 / 15 (train: 5; dev: 10) |
| Outcomes | 715 execute, 239 observe-only, 31 ask_missing, 15 out_of_scope |
| Implementor inspection | 984 acceptable within scope; 16 inspected and awaiting adjudication; zero awaiting inspection |
| Eligibility | All **spec_only and non-exportable**; training-export eligibility is **zero** |

Entry points: [designs](data/synthetic/design/), [canonical authored replay](artifacts/synthetic/), [failure taxonomy and coverage](docs/implementation/WORLD_LOCAL_COVERAGE.md), [individual ledger](artifacts/synthetic/quality_audit_1000/per_sample_review.jsonl) and [completed implementor audit](docs/implementation/SYNTHETIC_1000_QUALITY_AUDIT.md).

Independently authored Vietnamese requests, fixtures and controls test permissions, entity/source selection, missing information, context/history, preservation, conditions, recovery and factual answers. Gold traces were authored and executed locally; they are not model-generated results or the only valid solutions. Designed failure cases remain **hypotheses until tested on a model**. Controls, rephrasings and negative traces are not additional independent mechanisms. Train/dev ancestry is preserved; exact request-repeat checks do not prove semantic independence. All 1,000 cases are text-only, with no generated scenario audio or established voice/ASR coverage.

### Decisions still pending

- **Seven mail-family holds:** connected-family split/overlap adjudication. Exact IDs and evidence are in the audit and ledger.
- **Six Wave 17 independent reviews:** responses remain pending. Give independent readers **only the [blind sheet](review/blind/reviewer_sheet_vi.md) before they see this gold-bearing package**. Keep the [private key](review/private/PRIVATE_comparison_key_vi.md) separate. Proposed administration changes remain unimplemented: one item at a time, explicit-duration control last; distinguish incomplete answers from reasoned ambiguity.
- **B05_L_D:** gold remains empty log / unchanged state. The open classification/policy question is whether an unavailable write permits a harmless condition read. That semantic alternative is not officially accepted or guaranteed full score.
- **TR11_CHORE_PAIR / TR11_CHORE_EXPLICIT:** gold still requires the authored assignments. Whether observation of an already-satisfied assignment permits no-op or partial writes remains open; PAIR still needs its genuinely changed assignment. No policy or gold change is made here.

## Evaluation and integration boundaries

Keep three concepts separate: **official contest score**, **local task/state/grounding correctness**, and **optional factual-answer/trace-efficiency diagnostics**. A semantically valid alternative may receive a different tool-call score against a fixed reference. Empty-gold contest scoring requires an empty submitted call list. Local acceptance, redundant-read notes and proposed no-op alternatives do not certify official full-score behavior. Older observe-only verifiers often do not grade final text; unfamiliar plausible language remains reviewable.

For example, in `TR16_PARCEL_DELIVERED`, the local verifier accepts two routes to the requested reminder. Tracking can confirm delivery, or a reschedule attempt can return an already-delivered no-op. Both supply evidence before the reminder is created. Creating the reminder first and checking delivery afterward fails the authorization check. The [Wave 16 replay](artifacts/synthetic/train_wave_16_replay/replay.json) records the calls, responses and verdicts for each route.

The [v0.1 harness proposal](docs/implementation/WORLD_HARNESS_CONTRACT_PROPOSAL.md) and [three-case integration README](integration/three_cases/README.md) provide TR15_PLANNING_TOMORROW, B02_N_C and TR16_APP_KEEP: visible inputs, private post-history WORLD, clock, permissions, reference calls/results/final state, oracle and verifier dependencies. Render **only agent_visible**. Never expose private state/gold or execute historical actions again. Prepared run IDs are examples, not actual model-run identities.

## Reproduction

Run from the package root with Python 3.10+ and PyYAML; Python 3.12+ is recommended for current tooling. Windows may need tzdata. These CPU tools are separate from the frozen ASR inference environment; no dependency upgrade is required by this documentation task.

Package-only checks:

```powershell
python -X utf8 scripts/check_team_review.py
python -X utf8 scripts/check_synthetic_quality_audit.py
python -X utf8 -m unittest discover -s tests -p "test_benchmark.py"
python -X utf8 -m unittest discover -s tests -p "test_compare_*.py"
```

SDK replay requires your **authorized release v3.2.0 archive, schema 2.7.0**:

```powershell
$env:LIFEMATE_SDK_ARCHIVE = 'X:/authorized/train+public_test.zip'
python -X utf8 integration/three_cases/verify.py --archive "$env:LIFEMATE_SDK_ARCHIVE"
```

The command temporarily materializes allowlisted SDK modules and nine exact schemas; none is distributed. No organizer sample/environment member is read. The [integration README](integration/three_cases/README.md) describes reference verification. The [validation record](VALIDATION.md) retains previously executed regression/replay checks; they are not newly executed results of this prose revision.

Complete ASR rescoring needs the withheld authorized manifests, predictions, configurations, ledgers and baseline scores at the paths documented in the saved reports. In particular, test_score_vnslu_test.py needs the completed run bundle. Do not invoke bundled inference/transport entry points; their source is present for frozen scoring validation. No model call or ASR scoring rerun is part of this task.

## Constraints and publication status

The [supplied contest description](docs/project/description.md) and [team assignment](docs/project/README.md) were checked locally on 2026-11-06, not reverified against a live organizer page. Their offline, model/context, hardware/time, deterministic decoding, precision and organizer-data restrictions remain applicable. [Validation qualifications](VALIDATION.md) separate recorded ASR/local replay evidence from **unverified full-system compliance**, licensing and training/deployment work outside this handoff. ASR-only T4 measurements establish no A30 end-to-end compliance.

[FILE_SELECTION.json](FILE_SELECTION.json) is the publication allowlist. Organizer SDK/data, transcript bundles, audio, weights, credentials, caches and delivery ZIPs are excluded from the extracted publication set. Retained plans and old setup instructions are historical. See [Draft PR text](DRAFT_PR.md) and [Vietnamese handoff note](HANDOFF_VI.md).

Team review is open in [Draft PR #5](https://github.com/BK-Agentic-Engineering/ava/pull/5).
